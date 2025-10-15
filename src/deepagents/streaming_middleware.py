"""
Streaming middleware for event capture.

Instruments tool calls and planning events to emit streaming events.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict

from langchain_core.messages import AIMessage
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
        # Create task in current loop - ensures it runs on next loop iteration
        # This is critical: create_task() schedules it in the current loop's queue
        # so it will execute before streaming_store.py checks the emitter queue
        task = loop.create_task(coro)
        # We don't await here (since we're in a sync function), but the task
        # is now scheduled in the loop and will execute before the next await point
        return task
    except RuntimeError:
        # No running loop - can't emit
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
        tool_name = tool_call.get("name", "unknown")
        tool_call_id = tool_call.get("id", str(uuid.uuid4()))
        tool_args = tool_call.get("args", {})
        
        # Record start time
        self._tool_start_times[tool_call_id] = time.time()
        
        # NOTE: modify_tool_call is not actually called by LangChain's AgentMiddleware
        # Tool events are now emitted via the @log_tool_call decorator in logging_utils.py
        
        return tool_call
    
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
        tool_call_id = tool_call.get("id", "unknown")
        tool_name = tool_call.get("name", "unknown")
        
        # Calculate execution time
        start_time = self._tool_start_times.pop(tool_call_id, time.time())
        execution_ms = int((time.time() - start_time) * 1000)
        
        # NOTE: modify_tool_result is not actually called by LangChain's AgentMiddleware
        # Tool events are now emitted via the @log_tool_call decorator in logging_utils.py
        
        return tool_result


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
            # Extract todos from tool call args
            try:
                todos = tool_call.get("args", {}).get("todos", [])
                
                if todos and len(todos) > 0:
                    # Get emitter from context
                    from api.streaming.emitter import get_current_emitter
                    
                    emitter = get_current_emitter()
                    if emitter:
                        # Convert todos to plan items
                        plan_items = []
                        for todo in todos:
                            plan_items.append({
                                "id": todo.get("id", str(uuid.uuid4())),
                                "text": todo.get("content", ""),
                                "status": todo.get("status", "pending")
                            })
                        
                        # Emit plan event using helper to ensure proper scheduling
                        _schedule_emit_sync(
                            emitter.emit_plan(plan_items)
                        )
            except Exception as e:
                logger.warning(f"Failed to emit plan event: {e}")
        
        return tool_result

