"""
Unified Logging System for DeepAgents

A comprehensive, clean logging system that consolidates all tool call logging,
agent interactions, and performance monitoring with structured logging and context tracking.
"""

import json
import logging
import time
import uuid
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from functools import wraps


class UnifiedLogger:
    """
    Unified logging system with context tracking and performance monitoring.
    
    This class consolidates all logging functionality including:
    - Tool call logging with execution time tracking
    - Agent context management
    - Session and run-level tracking
    - Error handling and reporting
    - Performance statistics
    """
    
    def __init__(self, log_file: str = "logs/unified_tool_calls.log", log_level: int = logging.INFO):
        """Initialize the unified logger."""
        self.log_file = log_file
        self.log_level = log_level
        self.current_run_id = None
        self.current_session_id = None
        self.current_agent_context = None
        self._lock = threading.Lock()
        
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        self.logger = logging.getLogger("deepagents_unified")
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
    
    def start_run(self, run_description: str = "DeepAgents Run") -> str:
        """Start a new run session."""
        with self._lock:
            self.current_run_id = str(uuid.uuid4())
            self.current_session_id = None
            self.current_agent_context = None
            
            log_data = {
                "event": "run_start",
                "run_id": self.current_run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "summary": run_summary
                }
                self.logger.info(f"RUN_END: {json.dumps(log_data, default=str)}")
                
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
                "timestamp": datetime.now(timezone.utc).isoformat()
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": description[:1000],
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"SUBAGENT_CALL: {json.dumps(log_data, default=str)}")
        return session_id
    
    def log_agent_call(self, agent_type: str, agent_id: str, subagent_type: Optional[str] = None, description: Optional[str] = None):
        """Log an agent call."""
        log_data = {
            "event": "agent_call",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "agent_type": agent_type,
            "agent_id": agent_id,
            "subagent_type": subagent_type,
            "description": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"AGENT_CALL: {json.dumps(log_data, default=str)}")
    
    def log_streaming_chunk(self, chunk_type: str, content: Optional[str] = None, thread_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """Log a streaming chunk."""
        log_data = {
            "event": "streaming_chunk",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "chunk_type": chunk_type,
            "content": content,
            "thread_id": thread_id,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"STREAMING_CHUNK: {json.dumps(log_data, default=str)}")
    
    def log_memory_operation(self, operation: str, thread_id: str, operation_type: str, details: Optional[Dict[str, Any]] = None):
        """Log memory operations (checkpointer interactions)."""
        log_data = {
            "event": "memory_operation",
            "run_id": self.current_run_id,
            "session_id": self.current_session_id,
            "operation": operation,
            "thread_id": thread_id,
            "operation_type": operation_type,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_context": self.current_agent_context
        }
        self.logger.info(f"MEMORY_OPERATION: {json.dumps(log_data, default=str)}")
    
    def get_tool_call_stats(self) -> Dict[str, Any]:
        """Get tool call statistics from the log file."""
        try:
            stats = {
                "total_tool_calls": 0,
                "tool_call_types": {},
                "execution_times": [],
                "errors": 0,
                "queries_processed": 0,
                "agent_calls": {},
                "subagent_calls": {},
                "runs": 0
            }
            
            if not os.path.exists(self.log_file):
                return {"error": "Log file not found"}
            
            with open(self.log_file, 'r') as f:
                for line in f:
                    if "RUN_START:" in line:
                        stats["runs"] += 1
                    elif "TOOL_CALL_START:" in line:
                        stats["total_tool_calls"] += 1
                        try:
                            data = json.loads(line.split("TOOL_CALL_START: ")[1])
                            tool_name = data.get("tool_name", "unknown")
                            stats["tool_call_types"][tool_name] = stats["tool_call_types"].get(tool_name, 0) + 1
                            
                            agent_context = data.get("agent_context", {})
                            agent_type = agent_context.get("agent_type", "unknown")
                            stats["agent_calls"][agent_type] = stats["agent_calls"].get(agent_type, 0) + 1
                            
                            subagent_type = agent_context.get("subagent_type")
                            if subagent_type:
                                stats["subagent_calls"][subagent_type] = stats["subagent_calls"].get(subagent_type, 0) + 1
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                    elif "TOOL_CALL_END:" in line:
                        try:
                            data = json.loads(line.split("TOOL_CALL_END: ")[1])
                            exec_time = data.get("execution_time_ms", 0)
                            stats["execution_times"].append(exec_time)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                    elif "TOOL_CALL_ERROR:" in line:
                        stats["errors"] += 1
                    elif "SESSION_START:" in line:
                        stats["queries_processed"] += 1

            if stats["execution_times"]:
                stats["avg_execution_time_ms"] = sum(stats["execution_times"]) / len(stats["execution_times"])
                stats["max_execution_time_ms"] = max(stats["execution_times"])
                stats["min_execution_time_ms"] = min(stats["execution_times"])
            
            return stats
            
        except Exception as e:
            return {"error": f"Failed to read tool call stats: {str(e)}"}
    
    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a specific session."""
        try:
            stats = {
                "session_id": session_id,
                "tool_calls": 0,
                "execution_times": [],
                "errors": 0,
                "queries": 0
            }
            
            if not os.path.exists(self.log_file):
                return {"error": "Log file not found"}
            
            with open(self.log_file, 'r') as f:
                for line in f:
                    if session_id in line:
                        if "TOOL_CALL_START:" in line:
                            stats["tool_calls"] += 1
                        elif "TOOL_CALL_END:" in line:
                            try:
                                data = json.loads(line.split("TOOL_CALL_END: ")[1])
                                exec_time = data.get("execution_time_ms", 0)
                                stats["execution_times"].append(exec_time)
                            except (json.JSONDecodeError, KeyError, IndexError):
                                pass
                        elif "TOOL_CALL_ERROR:" in line:
                            stats["errors"] += 1
                        elif "SESSION_START:" in line:
                            stats["queries"] += 1
            
            if stats["execution_times"]:
                stats["avg_execution_time_ms"] = sum(stats["execution_times"]) / len(stats["execution_times"])
                stats["total_execution_time_ms"] = sum(stats["execution_times"])
            
            return stats
            
        except Exception as e:
            return {"error": f"Failed to read session stats: {str(e)}"}


_unified_logger = None

def get_unified_logger() -> UnifiedLogger:
    """Get the global unified logger instance."""
    global _unified_logger
    if _unified_logger is None:
        _unified_logger = UnifiedLogger()
    return _unified_logger


def log_tool_call(func):
    """
    Unified decorator to log tool function calls with agent context.
    
    This decorator wraps tool functions to automatically log:
    - Tool call start with arguments and agent context
    - Tool call end with result and execution time
    - Tool call errors
    """
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        logger = get_unified_logger()
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
            logger.log_tool_call_start(tool_name, tool_call_id, log_args, log_kwargs)
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.log_tool_call_error(tool_name, tool_call_id, e, execution_time)
            raise
    
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = get_unified_logger()
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
            logger.log_tool_call_start(tool_name, tool_call_id, log_args, log_kwargs)
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.log_tool_call_end(tool_name, tool_call_id, result, execution_time)
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.log_tool_call_error(tool_name, tool_call_id, e, execution_time)
            raise
    
    import inspect
    if inspect.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def start_run(run_description: str = "DeepAgents Run") -> str:
    """Start a new run session."""
    logger = get_unified_logger()
    return logger.start_run(run_description)

def end_run(run_summary: str = ""):
    """End the current run session."""
    logger = get_unified_logger()
    logger.end_run(run_summary)

def set_agent_context(agent_type: str, agent_id: str = None, subagent_type: str = None):
    """Set the current agent context for tool calls."""
    logger = get_unified_logger()
    logger.set_agent_context(agent_type, agent_id, subagent_type)

def log_query_start(query: str, session_id: Optional[str] = None) -> str:
    """Log the start of a new query/session."""
    logger = get_unified_logger()
    return logger.start_session(query, session_id)

def log_query_end(session_id: str, result: Any):
    """Log the end of a query/session."""
    logger = get_unified_logger()
    logger.end_session(session_id, result)

def log_subagent_call(subagent_type: str, description: str, session_id: Optional[str] = None):
    """Log subagent calls."""
    logger = get_unified_logger()
    return logger.log_subagent_call(subagent_type, description, session_id)

def log_agent_call(agent_type: str, agent_id: str, subagent_type: Optional[str] = None, description: Optional[str] = None):
    """Log an agent call."""
    logger = get_unified_logger()
    logger.log_agent_call(agent_type, agent_id, subagent_type, description)

def log_streaming_chunk(chunk_type: str, content: Optional[str] = None, thread_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
    """Log a streaming chunk."""
    logger = get_unified_logger()
    logger.log_streaming_chunk(chunk_type, content, thread_id, metadata)

def log_memory_operation(operation: str, thread_id: str, operation_type: str, details: Optional[Dict[str, Any]] = None):
    """Log memory operations."""
    logger = get_unified_logger()
    logger.log_memory_operation(operation, thread_id, operation_type, details)

def get_tool_call_stats() -> Dict[str, Any]:
    """Get tool call statistics."""
    logger = get_unified_logger()
    return logger.get_tool_call_stats()

def get_session_stats(session_id: str) -> Dict[str, Any]:
    """Get statistics for a specific session."""
    logger = get_unified_logger()
    return logger.get_session_stats(session_id)
