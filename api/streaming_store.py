"""
Streaming store - bridges API layer with ReactAgent for MVP transparency.

Handles:
- Event emitter setup
- Agent invocation with streaming
- Event persistence
- Status updates
- Human-in-the-loop interrupts
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any

from langchain_core.messages import AIMessage
from langgraph.types import Command

from api.store import ApiStore
from api.streaming.emitter import StreamingEventEmitter, set_current_emitter
from api.streaming.events import StreamEvent, create_status_event, create_end_event
from api.streaming.persistence import EventPersistence
from api.utils import generate_thread_id

logger = logging.getLogger(__name__)


async def stream_agent_response(
    store: ApiStore,
    event_persistence: EventPersistence,
    chat_id: str,
    message_id: str,
    user_content: str,
    metadata: Dict[str, Any]
) -> AsyncGenerator[StreamEvent, None]:
    """
    Stream agent response with MVP event transparency.
    
    This function:
    1. Creates event emitter
    2. Invokes agent in background
    3. Streams events as they arrive
    4. Batch writes events to DB at the end
    5. Updates message in DB
    
    Args:
        store: API store
        event_persistence: Event persistence layer
        chat_id: Chat ID
        message_id: Assistant message ID
        user_content: User query content
        metadata: Message metadata (tender_id, etc.)
        
    Yields:
        StreamEvent: Events as they occur
    """
    # Create event emitter for this request
    emitter = StreamingEventEmitter(message_id, chat_id)
    set_current_emitter(emitter)
    emitter.start()
    
    start_time = datetime.now(timezone.utc)
    full_response = ""
    tool_call_count = 0
    
    try:
        # Update message status to PROCESSING
        from api.models import MessageStatus
        store.update_message_status(message_id, MessageStatus.PROCESSING)
        
        # Emit START event
        await emitter.emit_start()
        yield emitter._event_buffer[-1]  # Get last emitted event
        
        # Get agent instance
        agent = store._get_agent()
        thread_id = generate_thread_id(chat_id)
        
        # Start agent invocation using streaming (to detect interrupts)
        config = {"configurable": {"thread_id": thread_id}}
        agent_stream = agent.agent.stream(
            {"messages": [{"role": "user", "content": user_content}]},
            config=config,
            stream_mode="values"
        )
        
        # Decouple emitter draining from agent chunk cadence
        # Run agent in background while continuously draining emitter
        heartbeat_interval = 15  # seconds
        interrupt_detected = False
        interrupt_data = None
        agent_done = asyncio.Event()
        last_chunk = None
        
        async def _run_agent():
            """Background task that runs the agent stream."""
            nonlocal last_chunk, interrupt_detected, interrupt_data
            try:
                # LangGraph's stream() returns a sync generator, iterate with regular for
                # but yield control to event loop between iterations
                for chunk in agent_stream:
                    last_chunk = chunk
                    
                    # Check for interrupts (HITL requests)
                    if "__interrupt__" in chunk:
                        interrupt_detected = True
                        interrupt_info = chunk["__interrupt__"]
                        interrupt_data = interrupt_info[0] if interrupt_info else None
                        logger.info(f"HITL interrupt detected for message {message_id}")
                        break
                    
                    # Yield control to event loop
                    await asyncio.sleep(0)
            except Exception as e:
                logger.error(f"Agent stream error: {e}")
            finally:
                agent_done.set()
        
        # Start agent in background
        asyncio.create_task(_run_agent())
        
        # Continuously drain emitter while agent runs
        from api.streaming.events import EventType
        last_emit_time = datetime.now(timezone.utc)
        
        while not agent_done.is_set():
            # Try to get next event from emitter
            evt = await emitter.get_next(timeout=0.2)
            
            if evt:
                # Yield event immediately
                yield evt
                last_emit_time = datetime.now(timezone.utc)
                
                # Track tool calls for final summary (fix enum comparison)
                if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                    tool_call_count += 1
                
                # Persist non-status events for resumability
                if evt.type != EventType.STATUS:
                    try:
                        event_persistence.append_event(message_id, chat_id, evt)
                    except Exception as persist_err:
                        logger.warning(f"Failed to persist event during stream: {persist_err}")
            else:
                # No events available - check if we should send heartbeat
                now = datetime.now(timezone.utc)
                time_since_last_emit = (now - last_emit_time).total_seconds()
                
                if time_since_last_emit > heartbeat_interval:
                    await emitter.emit_status(f"Processing... ({int(time_since_last_emit)}s elapsed)")
                    yield emitter._event_buffer[-1]
                    last_emit_time = now
        
        # Agent finished - drain any remaining events in queue
        while True:
            evt = await emitter.get_next(timeout=0.05)
            if not evt:
                break
            yield evt
            
            # Track tool calls (fix enum comparison)
            if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                tool_call_count += 1
            
            # Persist non-status events
            if evt.type != EventType.STATUS:
                try:
                    event_persistence.append_event(message_id, chat_id, evt)
                except Exception as persist_err:
                    logger.warning(f"Failed to persist tail event: {persist_err}")
        
        # Handle interrupt if detected
        if interrupt_detected:
            # interrupt_data is a LangGraph Interrupt object, not a dict
            # Access its value attribute to get the tool call
            tool_call = {}
            tool_name = "request_human_input"
            tool_args = {}
            
            if interrupt_data and hasattr(interrupt_data, 'value'):
                tool_call = interrupt_data.value if isinstance(interrupt_data.value, dict) else {}
                tool_name = tool_call.get("name", "request_human_input")
                tool_args = tool_call.get("args", {})
            
            question = tool_args.get("question", "Agent needs clarification")
            context = tool_args.get("context", "")
            
            # Emit status event with HITL request
            status_event = StreamEvent(
                type="status",
                id=emitter._generate_event_id(),
                ts=datetime.now(timezone.utc).isoformat(),
                text="⏸️ Agent needs human input",
                md=json.dumps({
                    "interrupt": True,
                    "tool": tool_name,
                    "question": question,
                    "context": context,
                    "thread_id": thread_id,
                    "instructions": "Human input required. Use resume endpoint to continue."
                })
            )
            emitter._event_buffer.append(status_event)
            yield status_event
            
            # Update message status to INTERRUPTED
            from api.models import MessageStatus
            store.update_message_status(
                message_id,
                MessageStatus.PROCESSING,
                metadata={
                    "interrupted": True,
                    "interrupt_question": question,
                    "interrupt_context": context,
                    "thread_id": thread_id
                }
            )
            
            # Emit END event for this stream
            await emitter.emit_end("interrupted", tool_call_count)
            yield emitter._event_buffer[-1]
            
            # Persist interrupt events
            try:
                event_persistence.append_event(message_id, chat_id, status_event)
                event_persistence.append_event(message_id, chat_id, emitter._event_buffer[-1])
            except Exception:
                pass
            
            # Return early - don't process final response
            return
        
        # If no interrupt, process final response
        if not interrupt_detected and last_chunk:
            # Extract final response from last chunk
            final_response = ""
            if "messages" in last_chunk and last_chunk["messages"]:
                last_message = last_chunk["messages"][-1]
                if isinstance(last_message, AIMessage):
                    final_response = last_message.content
            
            if final_response:
                full_response = final_response
                
                # Stream content in chunks (for progressive rendering)
                words = final_response.split()
                chunk_size = 10
                for i in range(0, len(words), chunk_size):
                    chunk_text = " ".join(words[i:i+chunk_size])
                    await emitter.emit_content(chunk_text)
                    yield emitter._event_buffer[-1]
                    await asyncio.sleep(0.02)  # Small delay for smoothness
            
            # Emit END event
            await emitter.emit_end("completed", tool_call_count)
            yield emitter._event_buffer[-1]
        
        # Calculate total processing time
        processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        # Update message in DB with final response
        store.update_message_status(
            message_id,
            MessageStatus.COMPLETED,
            content=full_response,
            processing_time_ms=processing_time_ms
        )
        
        # Batch write all events to DB
        events = emitter.get_buffered_events()
        event_persistence.batch_write_events(
            message_id=message_id,
            chat_id=chat_id,
            events=events
        )
        
        logger.info(
            f"Streaming completed for message {message_id}: "
            f"{processing_time_ms}ms, {len(events)} events, {tool_call_count} tool calls"
        )
        
    except Exception as e:
        logger.error(f"Error in stream_agent_response for message {message_id}: {e}")
        
        # Emit error event
        await emitter.emit_error(str(e))
        yield emitter._event_buffer[-1]
        
        # Update message status to FAILED
        from api.models import MessageStatus
        store.update_message_status(
            message_id,
            MessageStatus.FAILED,
            error=str(e)
        )
        
        # Still try to save events
        try:
            events = emitter.get_buffered_events()
            event_persistence.batch_write_events(
                message_id=message_id,
                chat_id=chat_id,
                events=events
            )
        except Exception as persist_error:
            logger.error(f"Failed to persist events after error: {persist_error}")
    
    finally:
        # Clean up
        emitter.stop()
        set_current_emitter(None)

