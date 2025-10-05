"""
Enhanced logging utilities for tracking tool calls in deepagents.
Supports run-level tracking, agent identification, and detailed tool call logging.
"""

import logging
import json
import time
import os
from datetime import datetime
from typing import Any, Dict, Optional
from functools import wraps
import uuid
import threading


class EnhancedToolCallLogger:
    """Enhanced logger for tracking tool calls with run-level and agent-level context."""
    
    def __init__(self, base_log_dir: str = "logs", log_level: int = logging.INFO):
        """
        Initialize the enhanced tool call logger.
        
        Args:
            base_log_dir: Base directory for log files
            log_level: Logging level (default: INFO)
        """
        self.base_log_dir = base_log_dir
        self.log_level = log_level
        self.current_run_id = None
        self.current_session_id = None
        self.current_agent_context = None
        self._lock = threading.Lock()
        
        os.makedirs(base_log_dir, exist_ok=True)
        
        self.logger = logging.getLogger("deepagents_enhanced")
        self.logger.setLevel(log_level)
        
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        self.logger.propagate = False
    
    def start_run(self, run_description: str = "DeepAgents Run") -> str:
        """Start a new run session."""
        with self._lock:
            self.current_run_id = str(uuid.uuid4())
            self.current_session_id = None
            self.current_agent_context = None
            
            run_log_file = os.path.join(self.base_log_dir, f"run_{self.current_run_id}.log")
            
            file_handler = logging.FileHandler(run_log_file)
            file_handler.setLevel(self.log_level)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
            log_data = {
                "event": "run_start",
                "run_id": self.current_run_id,
                "timestamp": datetime.now().isoformat(),
                "description": run_description
            }
            self.logger.info(f"RUN_START: {json.dumps(log_data, default=str)}")
            
            return self.current_run_id
    
    def end_run(self, run_summary: str = ""):
        """End the current run session."""
        with self._lock:
            if self.current_run_id:
                log_data = {
                    "event": "run_end",
                    "run_id": self.current_run_id,
                    "timestamp": datetime.now().isoformat(),
                    "summary": run_summary
                }
                self.logger.info(f"RUN_END: {json.dumps(log_data, default=str)}")
                
                handlers_to_remove = [h for h in self.logger.handlers if isinstance(h, logging.FileHandler)]
                for handler in handlers_to_remove:
                    handler.close()
                    self.logger.removeHandler(handler)
                
                self.current_run_id = None
                self.current_session_id = None
                self.current_agent_context = None
    
    def set_agent_context(self, agent_type: str, agent_id: str = None, subagent_type: str = None):
        """Set the current agent context for tool calls."""
        with self._lock:
            self.current_agent_context = {
                "agent_type": agent_type,
                "agent_id": agent_id or str(uuid.uuid4()),
                "subagent_type": subagent_type,
                "timestamp": datetime.now().isoformat()
            }
    
    def start_session(self, query: str, session_id: Optional[str] = None) -> str:
        """Start a new query session within the current run."""
        with self._lock:
            if session_id is None:
                session_id = str(uuid.uuid4())
            self.current_session_id = session_id
            
            log_data = {
                "event": "session_start",
                "run_id": self.current_run_id,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "query": query[:1000],
                "agent_context": self.current_agent_context
            }
            self.logger.info(f"SESSION_START: {json.dumps(log_data, default=str)}")
            return session_id
    
    def end_session(self, session_id: str, result: Any):
        """End a query session."""
        with self._lock:
            log_data = {
                "event": "session_end",
                "run_id": self.current_run_id,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "result_preview": str(result)[:1000] if result is not None else None,
                "agent_context": self.current_agent_context
            }
            self.logger.info(f"SESSION_END: {json.dumps(log_data, default=str)}")
    
    def log_tool_call_start(self, tool_name: str, tool_call_id: str, args: Dict[str, Any], kwargs: Dict[str, Any]):
        """Log the start of a tool call with full context."""
        log_data = {
            "event": "tool_call_start",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "args": args,
            "kwargs": kwargs,
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"TOOL_CALL_START: {json.dumps(log_data, default=str)}")
    
    def log_tool_call_end(self, tool_name: str, tool_call_id: str, result: Any, execution_time: float):
        """Log the end of a tool call with full context and detailed output."""
        result_details = {
            "type": type(result).__name__,
            "preview": str(result)[:1000] if result is not None else None,
            "size_bytes": len(str(result).encode('utf-8')) if result is not None else 0
        }

        if isinstance(result, dict):
            result_details["keys"] = list(result.keys())[:10]
            result_details["is_empty"] = len(result) == 0
        
        log_data = {
            "event": "tool_call_end",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": round(execution_time * 1000, 2),
            "result": result_details,
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"TOOL_CALL_END: {json.dumps(log_data, default=str)}")
    
    def log_tool_call_error(self, tool_name: str, tool_call_id: str, error: Exception, execution_time: float):
        """Log an error during tool call execution with full context."""
        log_data = {
            "event": "tool_call_error",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": round(execution_time * 1000, 2),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "agent_context": self.current_agent_context
        }
        self.logger.error(f"TOOL_CALL_ERROR: {json.dumps(log_data, default=str)}")
    
    def log_subagent_call(self, subagent_type: str, description: str, session_id: Optional[str] = None):
        """Log subagent calls with full context."""
        if session_id is None:
            session_id = self.current_session_id
        
        log_data = {
            "event": "subagent_call",
            "run_id": self.current_run_id,
            "session_id": session_id,
            "subagent_type": subagent_type,
            "timestamp": datetime.now().isoformat(),
            "description": description[:1000],
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"SUBAGENT_CALL: {json.dumps(log_data, default=str)}")
        return session_id

_enhanced_logger = None

def get_enhanced_logger() -> EnhancedToolCallLogger:
    """Get the global enhanced logger instance."""
    global _enhanced_logger
    if _enhanced_logger is None:
        _enhanced_logger = EnhancedToolCallLogger()
    return _enhanced_logger


class ToolCallLogger:
    """Legacy logger for backward compatibility."""
    
    def __init__(self, log_file: str = "tool_calls.log", log_level: int = logging.INFO):
        """Initialize the legacy tool call logger."""
        self.logger = logging.getLogger("deepagents_tool_calls")
        self.logger.setLevel(log_level)

        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.propagate = False
    
    def log_tool_call_start(self, tool_name: str, tool_call_id: str, args: Dict[str, Any], kwargs: Dict[str, Any]):
        """Log the start of a tool call."""
        log_data = {
            "event": "tool_call_start",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "args": args,
            "kwargs": kwargs
        }
        self.logger.info(f"TOOL_CALL_START: {json.dumps(log_data, default=str)}")
    
    def log_tool_call_end(self, tool_name: str, tool_call_id: str, result: Any, execution_time: float):
        """Log the end of a tool call."""
        log_data = {
            "event": "tool_call_end",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": round(execution_time * 1000, 2),
            "result_type": type(result).__name__,
            "result_preview": str(result)[:500] if result is not None else None
        }
        self.logger.info(f"TOOL_CALL_END: {json.dumps(log_data, default=str)}")
    
    def log_tool_call_error(self, tool_name: str, tool_call_id: str, error: Exception, execution_time: float):
        """Log an error during tool call execution."""
        log_data = {
            "event": "tool_call_error",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": round(execution_time * 1000, 2),
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        self.logger.error(f"TOOL_CALL_ERROR: {json.dumps(log_data, default=str)}")


_tool_logger = None

def get_tool_logger() -> ToolCallLogger:
    """Get the global tool logger instance."""
    global _tool_logger
    if _tool_logger is None:
        _tool_logger = ToolCallLogger()
    return _tool_logger


def log_tool_call(func):
    """
    Enhanced decorator to log tool function calls with agent context.
    
    This decorator wraps tool functions to automatically log:
    - Tool call start with arguments and agent context
    - Tool call end with result and execution time
    - Tool call errors
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            logger = get_enhanced_logger()
            use_enhanced = True
        except Exception:
            logger = get_tool_logger()
            use_enhanced = False
        
        tool_name = func.__name__
        tool_call_id = str(uuid.uuid4())
        
        log_args = {}
        log_kwargs = {}
        
        for i, arg in enumerate(args):
            if not hasattr(arg, '__dict__') or not isinstance(arg, dict):
                log_args[f"arg_{i}"] = str(arg)[:200]
        
        excluded_params = {'state', 'tool_call_id'}
        for key, value in kwargs.items():
            if key not in excluded_params:
                log_kwargs[key] = str(value)[:200]
        
        start_time = time.time()
        
        try:
            if use_enhanced:
                logger.log_tool_call_start(tool_name, tool_call_id, log_args, log_kwargs)
            else:
                logger.log_tool_call_start(tool_name, tool_call_id, log_args, log_kwargs)
            
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            if use_enhanced:
                logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
            else:
                logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
            
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            if use_enhanced:
                logger.log_tool_call_error(tool_name, tool_call_id, e, execution_time)
            else:
                logger.log_tool_call_error(tool_name, tool_call_id, e, execution_time)
            raise
    
    return wrapper


def log_query_start(query: str, session_id: Optional[str] = None):
    """Log the start of a new query/session."""
    try:
        logger = get_enhanced_logger()
        return logger.start_session(query, session_id)
    except Exception:
        logger = get_tool_logger()
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        log_data = {
            "event": "query_start",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "query": query[:500]
        }
        logger.logger.info(f"QUERY_START: {json.dumps(log_data, default=str)}")
        return session_id


def log_query_end(session_id: str, result: Any):
    """Log the end of a query/session."""
    try:
        logger = get_enhanced_logger()
        logger.end_session(session_id, result)
    except Exception:
        logger = get_tool_logger()
        log_data = {
            "event": "query_end",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "result_preview": str(result)[:500] if result is not None else None
        }
        logger.logger.info(f"QUERY_END: {json.dumps(log_data, default=str)}")


def log_subagent_call(subagent_type: str, description: str, session_id: Optional[str] = None):
    """Log subagent calls."""
    try:
        logger = get_enhanced_logger()
        return logger.log_subagent_call(subagent_type, description, session_id)
    except Exception:
        logger = get_tool_logger()
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        log_data = {
            "event": "subagent_call",
            "session_id": session_id,
            "subagent_type": subagent_type,
            "timestamp": datetime.now().isoformat(),
            "description": description[:500]
        }
        logger.logger.info(f"SUBAGENT_CALL: {json.dumps(log_data, default=str)}")
        return session_id


def start_run(run_description: str = "DeepAgents Run") -> str:
    """Start a new run session."""
    logger = get_enhanced_logger()
    return logger.start_run(run_description)


def end_run(run_summary: str = ""):
    """End the current run session."""
    logger = get_enhanced_logger()
    logger.end_run(run_summary)


def set_agent_context(agent_type: str, agent_id: str = None, subagent_type: str = None):
    """Set the current agent context for tool calls."""
    logger = get_enhanced_logger()
    logger.set_agent_context(agent_type, agent_id, subagent_type)