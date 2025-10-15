"""
Event schema and types for streaming.

Defines the MVP event model based on senior engineer review.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of streaming events (Enhanced for agentic UX)."""
    START = "start"
    THINKING = "thinking"  # AI message content (agent reasoning)
    PLAN = "plan"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    SUBAGENT_START = "subagent_start"  # Sub-agent spawned via task tool
    SUBAGENT_END = "subagent_end"      # Sub-agent completed
    CONTENT_START = "content_start"    # Final response begins
    CONTENT = "content"
    CONTENT_END = "content_end"        # Final response ends
    STATUS = "status"
    RATIONALE = "rationale"  # Deprecated - use THINKING instead
    END = "end"
    ERROR = "error"


class PlanItem(BaseModel):
    """A single item in the plan."""
    id: str
    text: str
    status: str  # pending, in_progress, completed


class StreamEvent(BaseModel):
    """
    Base event model for SSE streaming.
    
    Version 2 schema - enhanced for agentic transparency.
    """
    v: int = Field(default=2, description="Schema version")
    type: EventType = Field(..., description="Event type")
    id: str = Field(..., description="Unique event ID (for SSE resume)")
    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp"
    )
    
    # Event-specific fields (optional, depends on type)
    message_id: Optional[str] = None
    chat_id: Optional[str] = None
    status: Optional[str] = None
    
    # Agent context (NEW - for main vs subagent differentiation)
    agent_type: Optional[str] = None  # "main" | "subagent"
    agent_id: Optional[str] = None    # Unique agent identifier
    parent_call_id: Optional[str] = None  # For subagents: the task tool's call_id
    
    # For PLAN events
    items: Optional[List[PlanItem]] = None
    
    # For TOOL events
    call_id: Optional[str] = None
    name: Optional[str] = None
    args_summary: Optional[str] = None  # Raw JSON summary
    args_display: Optional[str] = None  # Human-readable: "Searching for: GDPR rules"
    result_summary: Optional[str] = None
    ms: Optional[int] = None
    
    # For SUBAGENT events
    subagent_description: Optional[str] = None  # Task description
    
    # For THINKING/RATIONALE/STATUS/CONTENT events
    text: Optional[str] = None
    md: Optional[str] = None
    
    # For END events
    ms_total: Optional[int] = None
    tool_calls: Optional[int] = None
    
    # For ERROR events
    error: Optional[str] = None
    
    class Config:
        use_enum_values = True


def create_start_event(event_id: str, message_id: str, chat_id: str) -> StreamEvent:
    """Create a START event."""
    return StreamEvent(
        type=EventType.START,
        id=event_id,
        message_id=message_id,
        chat_id=chat_id,
        status="processing"
    )


def create_plan_event(event_id: str, items: List[Dict[str, str]]) -> StreamEvent:
    """Create a PLAN event."""
    plan_items = [PlanItem(**item) for item in items]
    return StreamEvent(
        type=EventType.PLAN,
        id=event_id,
        items=plan_items
    )


def create_tool_start_event(
    event_id: str,
    call_id: str,
    name: str,
    args_summary: str
) -> StreamEvent:
    """Create a TOOL_START event."""
    return StreamEvent(
        type=EventType.TOOL_START,
        id=event_id,
        call_id=call_id,
        name=name,
        args_summary=args_summary
    )


def create_tool_end_event(
    event_id: str,
    call_id: str,
    name: str,
    status: str,
    ms: int,
    result_summary: str
) -> StreamEvent:
    """Create a TOOL_END event."""
    return StreamEvent(
        type=EventType.TOOL_END,
        id=event_id,
        call_id=call_id,
        name=name,
        status=status,
        ms=ms,
        result_summary=result_summary
    )


def create_status_event(event_id: str, text: str) -> StreamEvent:
    """Create a STATUS event (heartbeat)."""
    return StreamEvent(
        type=EventType.STATUS,
        id=event_id,
        text=text
    )


def create_rationale_event(event_id: str, text: str) -> StreamEvent:
    """Create a RATIONALE event."""
    return StreamEvent(
        type=EventType.RATIONALE,
        id=event_id,
        text=text
    )


def create_content_event(event_id: str, md: str) -> StreamEvent:
    """Create a CONTENT event."""
    return StreamEvent(
        type=EventType.CONTENT,
        id=event_id,
        md=md
    )


def create_end_event(
    event_id: str,
    status: str,
    ms_total: int,
    tool_calls: int
) -> StreamEvent:
    """Create an END event."""
    return StreamEvent(
        type=EventType.END,
        id=event_id,
        status=status,
        ms_total=ms_total,
        tool_calls=tool_calls
    )


def create_error_event(event_id: str, error: str) -> StreamEvent:
    """Create an ERROR event."""
    return StreamEvent(
        type=EventType.ERROR,
        id=event_id,
        error=error
    )


def create_thinking_event(
    event_id: str,
    text: str,
    agent_type: str = "main",
    agent_id: Optional[str] = None,
    parent_call_id: Optional[str] = None
) -> StreamEvent:
    """Create a THINKING event (AI message content)."""
    return StreamEvent(
        type=EventType.THINKING,
        id=event_id,
        text=text,
        agent_type=agent_type,
        agent_id=agent_id,
        parent_call_id=parent_call_id
    )


def create_subagent_start_event(
    event_id: str,
    agent_id: str,
    parent_call_id: str,
    subagent_description: str
) -> StreamEvent:
    """Create a SUBAGENT_START event."""
    return StreamEvent(
        type=EventType.SUBAGENT_START,
        id=event_id,
        agent_type="subagent",
        agent_id=agent_id,
        parent_call_id=parent_call_id,
        subagent_description=subagent_description
    )


def create_subagent_end_event(
    event_id: str,
    agent_id: str,
    parent_call_id: str,
    ms: Optional[int] = None
) -> StreamEvent:
    """Create a SUBAGENT_END event."""
    return StreamEvent(
        type=EventType.SUBAGENT_END,
        id=event_id,
        agent_type="subagent",
        agent_id=agent_id,
        parent_call_id=parent_call_id,
        ms=ms
    )


def create_content_start_event(
    event_id: str,
    agent_type: str = "main",
    agent_id: Optional[str] = None
) -> StreamEvent:
    """Create a CONTENT_START event."""
    return StreamEvent(
        type=EventType.CONTENT_START,
        id=event_id,
        agent_type=agent_type,
        agent_id=agent_id
    )


def create_content_end_event(
    event_id: str,
    agent_type: str = "main",
    agent_id: Optional[str] = None
) -> StreamEvent:
    """Create a CONTENT_END event."""
    return StreamEvent(
        type=EventType.CONTENT_END,
        id=event_id,
        agent_type=agent_type,
        agent_id=agent_id
    )

