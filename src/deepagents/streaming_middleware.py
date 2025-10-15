"""
Streaming middleware for event capture.

Instruments tool calls and planning events to emit streaming events.
"""

import asyncio
import logging
import time
import uuid
from typing import Dict

from src.deepagents.middleware import AgentMiddleware
from src.deepagents.logging_utils import get_unified_logger

logger = logging.getLogger(__name__)

def _schedule_emit_sync(coro):
    """
    Schedule an emit coroutine to run in the current event loop.
    
    This helper ensures that emit events are properly scheduled and queued
    before the middleware returns control. Called from synchronous middleware
    methods that run within an async context.
    
    Args:
        coro: The coroutine to schedule (emit operation)
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        return task
    except RuntimeError:
        logger.warning("No running event loop, cannot emit streaming event")
        return None

class StreamingMiddleware(AgentMiddleware):
    """
    Middleware that captures agent events and emits them for streaming.
    
    Integrates with StreamingEventEmitter via context vars.
    """
    
    def __init__(self):
        """Initialize streaming middleware."""
        self.logger = get_unified_logger()
        self._tool_start_times: Dict[str, float] = {}
    
    def modify_tool_call(self, tool_call, agent_state):
        """
        Capture tool call start and emit event.
        
        Args:
            tool_call: The tool call being made
            agent_state: Current agent state
            
        Returns:
            Modified tool call (unchanged)
        """
        tool_call_id = tool_call.get("id", str(uuid.uuid4()))
        self._tool_start_times[tool_call_id] = time.time()
        return tool_call
    
    async def amodify_tool_call(self, tool_call, agent_state):
        """Async version of modify_tool_call."""
        return self.modify_tool_call(tool_call, agent_state)
    
    def modify_tool_result(self, tool_result, tool_call, agent_state):
        """
        Capture tool call end and emit event.
        
        Args:
            tool_result: The tool result
            tool_call: The original tool call
            agent_state: Current agent state
            
        Returns:
            Modified tool result (unchanged)
        """
        return tool_result
    
    async def amodify_tool_result(self, tool_result, tool_call, agent_state):
        """Async version of modify_tool_result."""
        return self.modify_tool_result(tool_result, tool_call, agent_state)


class PlanningStreamingMiddleware(AgentMiddleware):
    """
    Middleware that captures planning (write_todos) events.
    
    Emits plan snapshots when todos are created/updated.
    """
    
    def __init__(self):
        """Initialize planning streaming middleware."""
        self.logger = get_unified_logger()
    
    def modify_tool_result(self, tool_result, tool_call, agent_state):
        """
        Capture write_todos and emit plan event.
        
        Args:
            tool_result: The tool result
            tool_call: The original tool call
            agent_state: Current agent state
            
        Returns:
            Modified tool result (unchanged)
        """
        tool_name = tool_call.get("name", "")
        
        if tool_name == "write_todos":
            try:
                todos = tool_call.get("args", {}).get("todos", [])
                
                if todos and len(todos) > 0:
                    from api.streaming.emitter import get_current_emitter
                    
                    emitter = get_current_emitter()
                    if emitter:
                        plan_items = []
                        for todo in todos:
                            plan_items.append({
                                "id": todo.get("id", str(uuid.uuid4())),
                                "text": todo.get("content", ""),
                                "status": todo.get("status", "pending")
                            })
                        
                        _schedule_emit_sync(
                            emitter.emit_plan(plan_items)
                        )
            except Exception as e:
                logger.warning(f"Failed to emit plan event: {e}")
        
        return tool_result
    
    async def amodify_tool_result(self, tool_result, tool_call, agent_state):
        """Async version of modify_tool_result."""
        return self.modify_tool_result(tool_result, tool_call, agent_state)