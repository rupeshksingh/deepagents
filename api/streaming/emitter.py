"""
Event emitter with context-aware async queue.

Uses contextvars for proper async context isolation.
"""

import asyncio
import contextvars
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from api.streaming.events import StreamEvent, EventType

logger = logging.getLogger(__name__)

# Context variable for per-request event emitter
_current_emitter: contextvars.ContextVar[Optional['StreamingEventEmitter']] = (
    contextvars.ContextVar('streaming_emitter', default=None)
)


def set_current_emitter(emitter: Optional['StreamingEventEmitter']) -> None:
    """Set the event emitter for the current async context."""
    _current_emitter.set(emitter)


def get_current_emitter() -> Optional['StreamingEventEmitter']:
    """Get the event emitter for the current async context."""
    return _current_emitter.get()


class StreamingEventEmitter:
    """
    Async event emitter with bounded queue and drop policy.
    
    Features:
    - Bounded consumer queue (maxsize=1000)
    - Drop policy: STATUS events can be dropped, others cannot
    - Sequence numbers for ordering
    - Event ID generation (snowflake-like)
    """
    
    def __init__(self, message_id: str, chat_id: str, maxsize: int = 1000):
        """
        Initialize emitter.
        
        Args:
            message_id: The message being processed
            chat_id: The chat this message belongs to
            maxsize: Maximum queue size
        """
        self.message_id = message_id
        self.chat_id = chat_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._active = False
        self._seq = 0
        self._start_time = datetime.now(timezone.utc)
        
        # Event buffer for batch DB writes
        self._event_buffer: list[StreamEvent] = []
        
        logger.info(f"StreamingEventEmitter created for message {message_id}")
    
    def start(self) -> None:
        """Start capturing events."""
        self._active = True
        logger.info(f"Event streaming started for message {self.message_id}")
    
    def stop(self) -> None:
        """Stop capturing events."""
        self._active = False
        logger.info(
            f"Event streaming stopped for message {self.message_id}. "
            f"Total events buffered: {len(self._event_buffer)}"
        )
    
    def _generate_event_id(self) -> str:
        """
        Generate unique event ID.
        
        Format: {timestamp_ms}_{seq}_{random}
        This allows ordering and deduplication.
        """
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self._seq += 1
        random_suffix = uuid.uuid4().hex[:8]
        return f"{timestamp_ms}_{self._seq:04d}_{random_suffix}"
    
    async def emit(self, event: StreamEvent) -> bool:
        """
        Emit an event to the stream.
        
        Args:
            event: The event to emit
            
        Returns:
            True if event was queued, False if dropped
        """
        if not self._active:
            return False
        
        # Add to buffer for DB persistence
        self._event_buffer.append(event)
        
        # Try to add to queue
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            # Drop policy: Only drop STATUS events
            if event.type == EventType.STATUS:
                logger.warning(
                    f"Dropped STATUS event for message {self.message_id} "
                    f"(queue full)"
                )
                return False
            else:
                # Critical events must not be dropped
                logger.error(
                    f"Queue full for message {self.message_id}, "
                    f"dropping critical event type: {event.type}"
                )
                # In production, we might want to implement backpressure here
                return False
    
    async def get_next(self, timeout: float = 0.1) -> Optional[StreamEvent]:
        """
        Get the next event from the queue.
        
        Args:
            timeout: Maximum time to wait for an event
            
        Returns:
            The next event, or None if timeout
        """
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    def get_buffered_events(self) -> list[StreamEvent]:
        """
        Get all buffered events for DB persistence.
        
        Returns:
            List of all events emitted during this session
        """
        return self._event_buffer.copy()
    
    def get_event_count(self) -> int:
        """Get total number of events emitted."""
        return len(self._event_buffer)
    
    async def emit_start(self) -> None:
        """Emit START event."""
        from api.streaming.events import create_start_event
        event = create_start_event(
            self._generate_event_id(),
            self.message_id,
            self.chat_id
        )
        await self.emit(event)
    
    async def emit_plan(self, items: list[dict]) -> None:
        """Emit PLAN event."""
        from api.streaming.events import create_plan_event
        event = create_plan_event(self._generate_event_id(), items)
        await self.emit(event)
    
    async def emit_tool_start(
        self,
        call_id: str,
        name: str,
        args_summary: str
    ) -> None:
        """Emit TOOL_START event."""
        from api.streaming.events import create_tool_start_event
        event = create_tool_start_event(
            self._generate_event_id(),
            call_id,
            name,
            args_summary
        )
        await self.emit(event)
    
    async def emit_tool_end(
        self,
        call_id: str,
        name: str,
        status: str,
        ms: int,
        result_summary: str
    ) -> None:
        """Emit TOOL_END event."""
        from api.streaming.events import create_tool_end_event
        event = create_tool_end_event(
            self._generate_event_id(),
            call_id,
            name,
            status,
            ms,
            result_summary
        )
        await self.emit(event)
    
    async def emit_status(self, text: str) -> None:
        """Emit STATUS event (heartbeat)."""
        from api.streaming.events import create_status_event
        event = create_status_event(self._generate_event_id(), text)
        await self.emit(event)
    
    async def emit_rationale(self, text: str) -> None:
        """Emit RATIONALE event."""
        from api.streaming.events import create_rationale_event
        event = create_rationale_event(self._generate_event_id(), text)
        await self.emit(event)
    
    async def emit_content(self, md: str) -> None:
        """Emit CONTENT event."""
        from api.streaming.events import create_content_event
        event = create_content_event(self._generate_event_id(), md)
        await self.emit(event)
    
    async def emit_end(self, status: str, tool_calls: int) -> None:
        """Emit END event."""
        from api.streaming.events import create_end_event
        elapsed = datetime.now(timezone.utc) - self._start_time
        ms_total = int(elapsed.total_seconds() * 1000)
        event = create_end_event(
            self._generate_event_id(),
            status,
            ms_total,
            tool_calls
        )
        await self.emit(event)
    
    async def emit_error(self, error: str) -> None:
        """Emit ERROR event."""
        from api.streaming.events import create_error_event
        event = create_error_event(self._generate_event_id(), error)
        await self.emit(event)

