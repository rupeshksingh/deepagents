"""
Logging Compatibility Layer

This module provides backward compatibility for the old logging system
by redirecting all calls to the new unified logging system.
"""

from typing import Any

from src.deepagents.logging_utils import (
    get_unified_logger,
)

class EnhancedToolCallLogger:
    """Legacy compatibility class - redirects to UnifiedLogger."""
    
    def __init__(self, base_log_dir: str = "logs", log_level: int = None):
        self._logger = get_unified_logger()
    
    def start_run(self, run_description: str = "DeepAgents Run") -> str:
        return self._logger.start_run(run_description)
    
    def end_run(self, run_summary: str = ""):
        return self._logger.end_run(run_summary)
    
    def set_agent_context(self, agent_type: str, agent_id: str = None, subagent_type: str = None):
        return self._logger.set_agent_context(agent_type, agent_id, subagent_type)
    
    def start_session(self, query: str, session_id: str = None) -> str:
        return self._logger.start_session(query, session_id)
    
    def end_session(self, session_id: str, result: Any):
        return self._logger.end_session(session_id, result)
    
    def log_tool_call_start(self, tool_name: str, tool_call_id: str, args: dict, kwargs: dict):
        return self._logger.log_tool_call_start(tool_name, tool_call_id, args, kwargs)
    
    def log_tool_call_end(self, tool_name: str, tool_call_id: str, result: Any, execution_time: float):
        return self._logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
    
    def log_tool_call_error(self, tool_name: str, tool_call_id: str, error: Exception, execution_time: float):
        return self._logger.log_tool_call_error(tool_name, tool_call_id, error, execution_time)
    
    def log_subagent_call(self, subagent_type: str, description: str, session_id: str = None):
        return self._logger.log_subagent_call(subagent_type, description, session_id)

class ToolCallLogger:
    """Compatibility class - redirects to UnifiedLogger."""
    
    def __init__(self, log_file: str = "tool_calls.log", log_level: int = None):
        self._logger = get_unified_logger()
    
    def log_tool_call_start(self, tool_name: str, tool_call_id: str, args: dict, kwargs: dict):
        return self._logger.log_tool_call_start(tool_name, tool_call_id, args, kwargs)
    
    def log_tool_call_end(self, tool_name: str, tool_call_id: str, result: Any, execution_time: float):
        return self._logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
    
    def log_tool_call_error(self, tool_name: str, tool_call_id: str, error: Exception, execution_time: float):
        return self._logger.log_tool_call_error(tool_name, tool_call_id, error, execution_time)

_enhanced_logger = None
_tool_logger = None

def get_enhanced_logger() -> EnhancedToolCallLogger:
    """Get the global enhanced logger instance."""
    global _enhanced_logger
    if _enhanced_logger is None:
        _enhanced_logger = EnhancedToolCallLogger()
    return _enhanced_logger

def get_tool_logger() -> ToolCallLogger:
    """Get the global tool logger instance."""
    global _tool_logger
    if _tool_logger is None:
        _tool_logger = ToolCallLogger()
    return _tool_logger