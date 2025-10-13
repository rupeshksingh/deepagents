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

        # Mirror ReactAgent workflow: enforce single-tender scope, build context files,
        # and enhance the initial user message with tender summary + file index.
        tender_id = (metadata or {}).get("tender_id")
        logger.warning(f"STREAMING_METADATA_DEBUG: metadata={metadata}, tender_id={tender_id}")

        # Enforce single-tender-per-thread guard (same as ReactAgent)
        try:
            if tender_id:
                agent._ensure_single_tender_scope(thread_id, tender_id)
        except Exception as guard_err:
            # Emit an immediate error event and stop
            await emitter.emit_error(str(guard_err))
            yield emitter._event_buffer[-1]
            return

        # Build context files first - they'll be available in state
        # (Match ReactAgent implementation exactly)
        context_files = agent._build_context_files(tender_id) if tender_id else {}
        logger.info(f"STREAMING_DEBUG: tender_id={tender_id}, context_files_count={len(context_files)}, files_keys={list(context_files.keys())[:3]}")
        
        # Pre-load summary & file index for main agent to answer generic questions quickly
        # Subagents won't get this - they only get files in state (via middleware filtering)
        if tender_id and context_files:
            tender_summary = context_files.get(agent.CONTEXT_SUMMARY_PATH, "")
            file_index = context_files.get(agent.CONTEXT_FILE_INDEX_PATH, "")
            
            enhanced_query = f"""<tender_context>
<tender_summary>
{tender_summary}
</tender_summary>

<file_index>
{file_index}
</file_index>
</tender_context>

User Query: {user_content}"""
            messages = [{"role": "user", "content": enhanced_query}]
        else:
            messages = [{"role": "user", "content": user_content}]

        # Bootstrap /context files into virtual filesystem state
        # IMPORTANT: files must be set unconditionally so checkpointer doesn't drop them
        initial_state: Dict[str, Any] = {
            "messages": messages,
            "files": context_files,  # Always set, even if empty dict
        }
        if tender_id and context_files:
            # Also store cluster_id at top-level for tools to access without file read
            initial_state["cluster_id"] = context_files.get(agent.CONTEXT_CLUSTER_ID_PATH, "68c99b8a10844521ad051543")
        
        logger.info(f"STREAMING_INITIAL_STATE: keys={list(initial_state.keys())}, files_in_state={len(initial_state.get('files', {}))}")

        agent_stream = agent.agent.astream(
            initial_state,
            config=config,
            stream_mode="values"
        )
        
        # Stream agent chunks and simultaneously drain emitter queue
        # Process in same async context so StreamingMiddleware can access emitter
        heartbeat_interval = 15  # seconds
        interrupt_detected = False
        interrupt_data = None
        last_chunk = None
        
        from api.streaming.events import EventType
        last_emit_time = datetime.now(timezone.utc)
        last_heartbeat_check = datetime.now(timezone.utc)
        
        # Process agent stream and emitter concurrently
        try:
            async for chunk in agent_stream:
                last_chunk = chunk
                
                # Check for interrupts (HITL requests)
                if "__interrupt__" in chunk:
                    interrupt_detected = True
                    interrupt_info = chunk["__interrupt__"]
                    interrupt_data = interrupt_info[0] if interrupt_info else None
                    logger.info(f"HITL interrupt detected for message {message_id}")
                    break
                
                # Drain emitter between agent chunks
                while True:
                    evt = await emitter.get_next(timeout=0.01)
                    if not evt:
                        break
                    yield evt
                    last_emit_time = datetime.now(timezone.utc)
                    
                    if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                        tool_call_count += 1
                    
                    if evt.type != EventType.STATUS:
                        try:
                            event_persistence.append_event(message_id, chat_id, evt)
                        except Exception as persist_err:
                            logger.warning(f"Failed to persist event: {persist_err}")
                
                # Send heartbeat if needed
                now = datetime.now(timezone.utc)
                if (now - last_heartbeat_check).total_seconds() > 5:
                    time_since_last_emit = (now - last_emit_time).total_seconds()
                    if time_since_last_emit > heartbeat_interval:
                        await emitter.emit_status(f"Processing... ({int(time_since_last_emit)}s elapsed)")
                        yield emitter._event_buffer[-1]
                        last_emit_time = now
                    last_heartbeat_check = now
        
        except Exception as e:
            logger.error(f"Agent stream error: {e}")
        
        # Drain any remaining events after agent finishes
        while True:
            evt = await emitter.get_next(timeout=0.05)
            if not evt:
                break
            yield evt
            
            if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                tool_call_count += 1
            
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
                    # Handle both string and list content
                    content = last_message.content
                    if isinstance(content, list):
                        # Multiple content blocks - join text blocks
                        final_response = " ".join([
                            block.get("text", "") if isinstance(block, dict) else str(block)
                            for block in content
                        ])
                    else:
                        final_response = str(content)
            
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
        
        # Note: Events already persisted in real-time via append_event()
        # No need for batch write which would cause duplicate key errors
        
        logger.info(
            f"Streaming completed for message {message_id}: "
            f"{processing_time_ms}ms, {tool_call_count} tool calls"
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
        
        # Note: Events already persisted in real-time via append_event()
        # during successful parts of the stream
    
    finally:
        # Clean up
        emitter.stop()
        set_current_emitter(None)

