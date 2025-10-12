"""
Streaming store - bridges API layer with ReactAgent for MVP transparency.

Handles:
- Event emitter setup
- Agent invocation with streaming
- Event persistence
- Status updates
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any

from api.store import ApiStore
from api.streaming.emitter import StreamingEventEmitter, set_current_emitter
from api.streaming.events import StreamEvent
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
        
        # Start agent invocation in background
        agent_task = asyncio.create_task(
            agent.chat_sync(
                user_query=user_content,
                thread_id=thread_id,
                tender_id=metadata.get("tender_id"),
                user_id=metadata.get("user_id")
            )
        )
        
        # Stream events as they arrive
        heartbeat_interval = 15  # seconds
        last_heartbeat = datetime.now(timezone.utc)
        last_event_time = datetime.now(timezone.utc)
        
        while True:
            # Check for new events from emitter
            event = await emitter.get_next(timeout=1.0)
            
            if event:
                last_event_time = datetime.now(timezone.utc)
                yield event
                
                # Track tool calls for final summary
                if event.type == "tool_end":
                    tool_call_count += 1
            
            # Check if agent finished
            if agent_task.done():
                # Get final result
                result = await agent_task
                
                # Extract final response
                final_response = result.get("response", "")
                if final_response:
                    full_response = final_response
                    
                    # Stream content in chunks (for progressive rendering)
                    words = final_response.split()
                    chunk_size = 10
                    for i in range(0, len(words), chunk_size):
                        chunk = " ".join(words[i:i+chunk_size])
                        await emitter.emit_content(chunk)
                        yield emitter._event_buffer[-1]
                        await asyncio.sleep(0.02)  # Small delay for smoothness
                
                # Emit END event
                await emitter.emit_end("completed", tool_call_count)
                yield emitter._event_buffer[-1]
                
                break
            
            # Send heartbeat if quiet for too long
            now = datetime.now(timezone.utc)
            time_since_last_event = (now - last_event_time).total_seconds()
            time_since_last_heartbeat = (now - last_heartbeat).total_seconds()
            
            if time_since_last_event > 5 and time_since_last_heartbeat > heartbeat_interval:
                # Send status update
                elapsed_str = f"{int(time_since_last_event)}s"
                await emitter.emit_status(f"Processing... ({elapsed_str} elapsed)")
                yield emitter._event_buffer[-1]
                last_heartbeat = now
            
            # Small delay to avoid busy waiting
            await asyncio.sleep(0.1)
        
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

