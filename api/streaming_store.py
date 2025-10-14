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
from typing import AsyncGenerator, Dict, Any, Optional

from langchain_core.messages import AIMessage
from langgraph.types import Command

from api.store import ApiStore
from api.streaming.emitter import StreamingEventEmitter, set_current_emitter
from api.streaming.events import StreamEvent, create_status_event, create_end_event
from api.streaming.persistence import EventPersistence
from api.utils import generate_thread_id
from api.background_agent_registry import get_agent_registry

logger = logging.getLogger(__name__)


class RobustEventWriter:
    """
    Event writer with retry logic that never raises exceptions.
    
    Ensures events are persisted even during transient failures.
    """
    
    def __init__(self, event_persistence: EventPersistence, message_id: str, chat_id: str):
        self.event_persistence = event_persistence
        self.message_id = message_id
        self.chat_id = chat_id
        self.failed_events = []
    
    async def write_event(self, event: StreamEvent, max_retries: int = 3) -> bool:
        """
        Write event with retries. Never raises exceptions.
        
        Args:
            event: Event to write
            max_retries: Maximum retry attempts
            
        Returns:
            True if successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                self.event_persistence.append_event(self.message_id, self.chat_id, event)
                return True
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to persist event after {max_retries} attempts "
                        f"for message {self.message_id}: {e}"
                    )
                    # Store in fallback queue
                    self.failed_events.append(event)
                    return False
                await asyncio.sleep(0.1 * (attempt + 1))  # Exponential backoff
        return False
    
    async def flush_failed_events(self) -> int:
        """
        Retry writing failed events.
        
        Returns:
            Number of events successfully written
        """
        if not self.failed_events:
            return 0
        
        written = 0
        remaining = []
        
        for event in self.failed_events:
            try:
                self.event_persistence.append_event(self.message_id, self.chat_id, event)
                written += 1
            except Exception:
                remaining.append(event)
        
        self.failed_events = remaining
        
        if written > 0:
            logger.info(f"Flushed {written} failed events for message {self.message_id}")
        
        return written


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
        try:
            yield emitter._event_buffer[-1]  # Get last emitted event
        except (asyncio.CancelledError, GeneratorExit):
            client_connected = False
            logger.info(f"Client disconnected immediately after START for message {message_id}")
        
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
        
        # Track seen messages to avoid duplicate THINKING events
        seen_message_ids = set()
        
        # Track if client is still connected
        client_connected = True
        
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
                
                # Capture AI messages as THINKING events
                if "messages" in chunk and chunk["messages"]:
                    last_message = chunk["messages"][-1]
                    
                    # Check if it's an AIMessage with content
                    if isinstance(last_message, AIMessage):
                        msg_id = getattr(last_message, 'id', None)
                        content = last_message.content
                        
                        # Emit THINKING if:
                        # 1. Has content (string or list with text)
                        # 2. Haven't seen this message yet
                        # 3. Not the final response (we'll handle that separately)
                        if content and msg_id not in seen_message_ids:
                            # Extract text from content (handle both string and list)
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict):
                                        if block.get("type") == "text":
                                            text_parts.append(block.get("text", ""))
                                    elif hasattr(block, 'text'):
                                        text_parts.append(block.text)
                                    else:
                                        text_parts.append(str(block))
                                thinking_text = " ".join(text_parts).strip()
                            else:
                                thinking_text = str(content).strip()
                            
                            # Only emit if there's actual text content
                            if thinking_text:
                                # Check if this is just tool calls without reasoning
                                has_tool_calls = hasattr(last_message, 'tool_calls') and last_message.tool_calls
                                
                                # Emit THINKING event for AI reasoning
                                # Don't emit if it's ONLY tool calls with no text
                                if not has_tool_calls or thinking_text:
                                    await emitter.emit_thinking(thinking_text)
                                    
                                    if msg_id:
                                        seen_message_ids.add(msg_id)
                
                # Drain emitter between agent chunks
                while True:
                    evt = await emitter.get_next(timeout=0.01)
                    if not evt:
                        break
                    
                    # Always persist events (even if client disconnected)
                    if evt.type != EventType.STATUS:
                        try:
                            event_persistence.append_event(message_id, chat_id, evt)
                        except Exception as persist_err:
                            logger.warning(f"Failed to persist event: {persist_err}")
                    
                    # Only yield if client is connected
                    if client_connected:
                        try:
                            yield evt
                            last_emit_time = datetime.now(timezone.utc)
                        except (asyncio.CancelledError, GeneratorExit):
                            # Client disconnected mid-yield
                            client_connected = False
                            logger.info(f"Client disconnected during event yield for message {message_id}")
                            # Continue processing but stop yielding
                    
                    # Track tool calls
                    if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                        tool_call_count += 1
                
                # Send heartbeat if needed (and client still connected)
                if client_connected:
                    now = datetime.now(timezone.utc)
                    if (now - last_heartbeat_check).total_seconds() > 5:
                        time_since_last_emit = (now - last_emit_time).total_seconds()
                        if time_since_last_emit > heartbeat_interval:
                            await emitter.emit_status(f"Processing... ({int(time_since_last_emit)}s elapsed)")
                            try:
                                yield emitter._event_buffer[-1]
                                last_emit_time = now
                            except (asyncio.CancelledError, GeneratorExit):
                                client_connected = False
                                logger.info(f"Client disconnected during heartbeat for message {message_id}")
                        last_heartbeat_check = now
        
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected - LET AGENT CONTINUE RUNNING
            # The agent should complete and persist all events even if no one is watching
            client_connected = False
            logger.info(f"Stream cancelled for message {message_id} (client disconnected)")
            logger.info(f"Agent will continue running in background. All events will be persisted.")
            logger.info(f"Client can reconnect with Last-Event-ID to resume watching.")
            
            # Don't re-raise - this keeps the agent running
            # Continue to process agent_stream to completion silently
        
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
            if client_connected:
                try:
                    yield emitter._event_buffer[-1]
                except (asyncio.CancelledError, GeneratorExit):
                    client_connected = False
            
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
                
                # Emit CONTENT_START to signal final response begins
                await emitter.emit_content_start()
                if client_connected:
                    try:
                        yield emitter._event_buffer[-1]
                    except (asyncio.CancelledError, GeneratorExit):
                        client_connected = False
                
                # Stream content in chunks (for progressive rendering)
                words = final_response.split()
                chunk_size = 10
                for i in range(0, len(words), chunk_size):
                    chunk_text = " ".join(words[i:i+chunk_size])
                    await emitter.emit_content(chunk_text)
                    if client_connected:
                        try:
                            yield emitter._event_buffer[-1]
                            await asyncio.sleep(0.02)  # Small delay for smoothness
                        except (asyncio.CancelledError, GeneratorExit):
                            client_connected = False
                            # Continue persisting but stop yielding
                
                # Emit CONTENT_END to signal final response complete
                await emitter.emit_content_end()
                if client_connected:
                    try:
                        yield emitter._event_buffer[-1]
                    except (asyncio.CancelledError, GeneratorExit):
                        client_connected = False
            
            # Emit END event
            await emitter.emit_end("completed", tool_call_count)
            if client_connected:
                try:
                    yield emitter._event_buffer[-1]
                except (asyncio.CancelledError, GeneratorExit):
                    client_connected = False
                    logger.info(f"Client disconnected before END event for message {message_id}")
        
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
        try:
            yield emitter._event_buffer[-1]
        except (asyncio.CancelledError, GeneratorExit):
            logger.info(f"Client disconnected during error handling for message {message_id}")
        
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


async def execute_agent_pure(
    store: ApiStore,
    event_persistence: EventPersistence,
    chat_id: str,
    message_id: str,
    user_content: str,
    metadata: Dict[str, Any]
) -> None:
    """
    Execute agent as a pure async function - NO generators, NO yields.
    
    This is immune to client cancellation because:
    - No generator/yield statements
    - Events written directly to DB
    - Completely decoupled from SSE streaming
    
    Args:
        store: API store
        event_persistence: Event persistence layer
        chat_id: Chat ID
        message_id: Assistant message ID
        user_content: User query content
        metadata: Message metadata
    """
    # Create robust event writer
    event_writer = RobustEventWriter(event_persistence, message_id, chat_id)
    
    start_time = datetime.now(timezone.utc)
    full_response = ""
    tool_call_count = 0
    
    # Emitter reference for background capture
    emitter: Optional[StreamingEventEmitter] = None

    try:
        # Update message status to PROCESSING
        from api.models import MessageStatus
        store.update_message_status(message_id, MessageStatus.PROCESSING)
        
        # Create START event
        from api.streaming.events import create_start_event
        start_event = create_start_event(f"start_{message_id}", message_id, chat_id)
        await event_writer.write_event(start_event)
        
        logger.info(f"Pure agent execution started for message {message_id}")
        
        # Get agent instance
        agent = store._get_agent()
        thread_id = generate_thread_id(chat_id)
        
        # Build initial state (same as stream_agent_response)
        config = {"configurable": {"thread_id": thread_id}}
        
        # Enforce single-tender scope
        tender_id = (metadata or {}).get("tender_id")
        
        try:
            if tender_id:
                agent._ensure_single_tender_scope(thread_id, tender_id)
        except Exception as guard_err:
            # Emit error and stop
            from api.streaming.events import create_error_event
            error_event = create_error_event(f"error_{message_id}", str(guard_err))
            await event_writer.write_event(error_event)
            store.update_message_status(message_id, MessageStatus.FAILED, error=str(guard_err))
            return
        
        # Build context files
        context_files = agent._build_context_files(tender_id) if tender_id else {}
        
        # Enhance query with context
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
        
        # Build initial state
        initial_state: Dict[str, Any] = {
            "messages": messages,
            "files": context_files,
        }
        if tender_id and context_files:
            initial_state["cluster_id"] = context_files.get(
                agent.CONTEXT_CLUSTER_ID_PATH, 
                "68c99b8a10844521ad051543"
            )
        
        # Track seen message IDs to avoid duplicate events
        seen_message_ids = set()
        interrupt_detected = False
        interrupt_data = None
        last_chunk = None
        
        # Create an event emitter so tool_start/tool_end and other events are captured by middleware
        emitter = StreamingEventEmitter(message_id, chat_id)
        set_current_emitter(emitter)
        emitter.start()

        # Heartbeat tracking
        last_heartbeat_check = datetime.now(timezone.utc)

        # Run agent and drain emitter (no client coupling)
        agent_stream = agent.agent.astream(
            initial_state,
            config=config,
            stream_mode="values"
        )
        
        # Process agent stream - NO yields, just persist events
        async for chunk in agent_stream:
            last_chunk = chunk
            
            # Check for interrupts
            if "__interrupt__" in chunk:
                interrupt_detected = True
                interrupt_info = chunk["__interrupt__"]
                interrupt_data = interrupt_info[0] if interrupt_info else None
                logger.info(f"HITL interrupt detected for message {message_id}")
                break
            
            # Capture AI messages as THINKING events (emit via emitter for consistency)
            if "messages" in chunk and chunk["messages"]:
                last_message = chunk["messages"][-1]
                
                if isinstance(last_message, AIMessage):
                    msg_id = getattr(last_message, 'id', None)
                    content = last_message.content
                    
                    if content and msg_id not in seen_message_ids:
                        # Extract text from content
                        if isinstance(content, list):
                            text_parts = []
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                elif hasattr(block, 'text'):
                                    text_parts.append(block.text)
                                else:
                                    text_parts.append(str(block))
                            thinking_text = " ".join(text_parts).strip()
                        else:
                            thinking_text = str(content).strip()
                        
                        if thinking_text:
                            has_tool_calls = hasattr(last_message, 'tool_calls') and last_message.tool_calls
                            if not has_tool_calls or thinking_text:
                                try:
                                    await emitter.emit_thinking(thinking_text)
                                except Exception:
                                    # Fallback to direct persistence if emitter fails
                                    from api.streaming.events import create_thinking_event
                                    await event_writer.write_event(
                                        create_thinking_event(
                                            f"think_{message_id}_{len(seen_message_ids)}",
                                            thinking_text
                                        )
                                    )
                                if msg_id:
                                    seen_message_ids.add(msg_id)

            # Drain emitter queue and persist events
            while True:
                evt = await emitter.get_next(timeout=0.01)
                if not evt:
                    break
                await event_writer.write_event(evt)
                # Count tool_end to track total tool calls
                try:
                    from api.streaming.events import EventType
                    if evt.type == EventType.TOOL_END or getattr(evt.type, "value", None) == "tool_end":
                        tool_call_count += 1
                except Exception:
                    pass

            # Emit periodic heartbeat to indicate liveness
            now = datetime.now(timezone.utc)
            if (now - last_heartbeat_check).total_seconds() >= 15:
                try:
                    elapsed = int((now - start_time).total_seconds())
                    await event_writer.write_event(create_status_event(f"Processing... ({elapsed}s elapsed)"))
                except Exception:
                    pass
                last_heartbeat_check = now
        
        # Handle interrupt
        if interrupt_detected:
            tool_call = {}
            tool_name = "request_human_input"
            tool_args = {}
            
            if interrupt_data and hasattr(interrupt_data, 'value'):
                tool_call = interrupt_data.value if isinstance(interrupt_data.value, dict) else {}
                tool_name = tool_call.get("name", "request_human_input")
                tool_args = tool_call.get("args", {})
            
            question = tool_args.get("question", "Agent needs clarification")
            
            from api.streaming.events import StreamEvent
            status_event = StreamEvent(
                type="status",
                id=f"status_{message_id}_interrupt",
                ts=datetime.now(timezone.utc).isoformat(),
                text="⏸️ Agent needs human input",
                md=json.dumps({
                    "interrupt": True,
                    "tool": tool_name,
                    "question": question,
                    "thread_id": thread_id
                })
            )
            await event_writer.write_event(status_event)
            
            # Update message status
            store.update_message_status(
                message_id,
                MessageStatus.PROCESSING,
                metadata={
                    "interrupted": True,
                    "interrupt_question": question,
                    "thread_id": thread_id
                }
            )
            
            # Drain any remaining events from emitter before ending
            if emitter:
                while True:
                    evt = await emitter.get_next(timeout=0.05)
                    if not evt:
                        break
                    await event_writer.write_event(evt)

            # Emit END event
            processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            end_event = create_end_event(
                f"end_{message_id}",
                "interrupted",
                processing_time_ms,
                tool_call_count
            )
            await event_writer.write_event(end_event)
            
            return
        
        # Process final response
        if not interrupt_detected and last_chunk:
            if "messages" in last_chunk and last_chunk["messages"]:
                last_message = last_chunk["messages"][-1]
                if isinstance(last_message, AIMessage):
                    content = last_message.content
                    if isinstance(content, list):
                        final_response = " ".join([
                            block.get("text", "") if isinstance(block, dict) else str(block)
                            for block in content
                        ])
                    else:
                        final_response = str(content)
                    
                    if final_response:
                        full_response = final_response
                        
                        # Emit CONTENT events
                        from api.streaming.events import create_content_start_event, create_content_event, create_content_end_event
                        
                        await event_writer.write_event(
                            create_content_start_event(f"content_start_{message_id}")
                        )
                        
                        # Stream content in chunks
                        words = final_response.split()
                        chunk_size = 10
                        for i in range(0, len(words), chunk_size):
                            chunk_text = " ".join(words[i:i+chunk_size])
                            content_event = create_content_event(
                                f"content_{message_id}_{i}",
                                chunk_text  # md parameter
                            )
                            await event_writer.write_event(content_event)
                        
                        await event_writer.write_event(
                            create_content_end_event(f"content_end_{message_id}")
                        )
            
            # Drain any remaining events from emitter before END
            if emitter:
                while True:
                    evt = await emitter.get_next(timeout=0.05)
                    if not evt:
                        break
                    await event_writer.write_event(evt)

            # Emit END event
            processing_time_ms_final = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            end_event = create_end_event(
                f"end_{message_id}",
                "completed",
                processing_time_ms_final,
                tool_call_count
            )
            await event_writer.write_event(end_event)
        
        # Calculate processing time
        processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        # Update message in DB
        store.update_message_status(
            message_id,
            MessageStatus.COMPLETED,
            content=full_response,
            processing_time_ms=processing_time_ms
        )
        
        # Flush any failed events
        await event_writer.flush_failed_events()
        
        logger.info(
            f"Pure agent execution completed for message {message_id}: "
            f"{processing_time_ms}ms, {tool_call_count} tool calls"
        )
    
    except Exception as e:
        logger.error(f"Error in execute_agent_pure for message {message_id}: {e}", exc_info=True)
        
        # Emit error event
        from api.streaming.events import create_error_event
        error_event = create_error_event(f"error_{message_id}", str(e))
        await event_writer.write_event(error_event)
        
        # Update message status to FAILED
        from api.models import MessageStatus
        store.update_message_status(
            message_id,
            MessageStatus.FAILED,
            error=str(e)
        )
        
        # Try to flush failed events even on error
        try:
            await event_writer.flush_failed_events()
        except Exception:
            pass
    
    finally:
        # Clean up emitter
        try:
            if emitter:
                emitter.stop()
        except Exception:
            pass
        try:
            set_current_emitter(None)
        except Exception:
            pass
async def run_agent_background(
    store: ApiStore,
    event_persistence: EventPersistence,
    chat_id: str,
    message_id: str,
    user_content: str,
    metadata: Dict[str, Any]
) -> None:
    """
    Run agent as a true background task - no streaming to client.
    
    This enables:
    - Multiple agents running simultaneously
    - User can switch between chats
    - Streams connect/disconnect without affecting execution
    
    All events are persisted to DB. Streams read from persistence.
    
    Args:
        store: API store
        event_persistence: Event persistence layer
        chat_id: Chat ID
        message_id: Assistant message ID
        user_content: User query content
        metadata: Message metadata
    """
    # Use pure execution (no generators/yields)
    # This is immune to client cancellation
    try:
        await execute_agent_pure(
            store=store,
            event_persistence=event_persistence,
            chat_id=chat_id,
            message_id=message_id,
            user_content=user_content,
            metadata=metadata
        )
        
        logger.info(f"Background agent completed for message {message_id}")
    
    except Exception as e:
        logger.error(f"Background agent error for message {message_id}: {e}", exc_info=True)


async def watch_agent_stream(
    event_persistence: EventPersistence,
    chat_id: str,
    message_id: str,
    since_id: Optional[str] = None,
    poll_interval: float = 0.5,
    max_wait: float = 3600.0  # 1 hour max
) -> AsyncGenerator[StreamEvent, None]:
    """
    Watch an agent execution by reading from persistence.
    
    This function:
    - Replays historical events
    - Polls for new events while agent is running  
    - Stops when agent completes
    - Multiple clients can watch same agent
    
    Args:
        event_persistence: Event persistence layer
        chat_id: Chat ID
        message_id: Message ID to watch
        since_id: Event ID to start from (for reconnect)
        poll_interval: How often to poll for new events (seconds)
        max_wait: Maximum time to wait (seconds)
        
    Yields:
        StreamEvent: Events as they're found in persistence
    """
    from api.streaming.events import EventType
    
    registry = get_agent_registry()
    start_time = datetime.now(timezone.utc)
    last_event_id = since_id
    seen_event_ids = set()
    agent_completed = False
    
    logger.info(f"Watcher started for message {message_id}, since_id={since_id}")
    
    try:
        while True:
            # Check if agent is still running
            is_running = await registry.is_running(message_id)
            
            # Get new events from persistence
            events = event_persistence.get_events(
                message_id=message_id,
                since_id=last_event_id,
                limit=100
            )
            
            # Yield new events
            for event_dict in events:
                event_id = event_dict.get("id")
                
                # Skip if already seen
                if event_id in seen_event_ids:
                    continue
                
                seen_event_ids.add(event_id)
                last_event_id = event_id
                
                # Convert datetime back to ISO string if needed
                if "ts" in event_dict and hasattr(event_dict["ts"], "isoformat"):
                    event_dict["ts"] = event_dict["ts"].isoformat()
                
                # Remove MongoDB _id field
                event_dict.pop("_id", None)
                event_dict.pop("message_id", None)
                event_dict.pop("chat_id", None)
                event_dict.pop("seq", None)
                
                # Convert dict to StreamEvent
                event = StreamEvent(**event_dict)
                yield event
                
                # Check if this is the END event
                if event.type == EventType.END or event.type == "end":
                    agent_completed = True
                    logger.info(f"Agent {message_id} completed (END event received)")
                    return
            
            # If agent not running and we got the END event, we're done
            if agent_completed or (not is_running and last_event_id):
                # Wait a bit more to catch any final events
                await asyncio.sleep(poll_interval)
                
                # One more check for events
                final_events = event_persistence.get_events(
                    message_id=message_id,
                    since_id=last_event_id,
                    limit=100
                )
                
                for event_dict in final_events:
                    event_id = event_dict.get("id")
                    if event_id not in seen_event_ids:
                        seen_event_ids.add(event_id)
                        
                        # Convert datetime back to ISO string if needed
                        if "ts" in event_dict and hasattr(event_dict["ts"], "isoformat"):
                            event_dict["ts"] = event_dict["ts"].isoformat()
                        
                        # Remove MongoDB fields
                        event_dict.pop("_id", None)
                        event_dict.pop("message_id", None)
                        event_dict.pop("chat_id", None)
                        event_dict.pop("seq", None)
                        
                        event = StreamEvent(**event_dict)
                        yield event
                
                logger.info(f"Agent {message_id} completed, watcher stopping")
                return
            
            # Check timeout
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > max_wait:
                logger.warning(f"Watcher timeout for message {message_id} after {elapsed}s")
                return
            
            # Wait before next poll
            await asyncio.sleep(poll_interval)
    
    except Exception as e:
        logger.error(f"Error in watcher for message {message_id}: {e}", exc_info=True)
        raise

