"""
Sanitization utilities for tool arguments and results.

Implements whitelist-based sanitization to prevent PII/sensitive data leakage.
"""

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Whitelist of safe fields per tool
TOOL_ARG_WHITELIST: Dict[str, list[str]] = {
    "search_tender_corpus": ["query"],
    "get_file_content": ["file_id"],
    "web_search": ["query"],
    "read_file": ["file_path"],
    "write_file": ["file_path"],
    "edit_file": ["file_path"],
    "ls": [],
    "write_todos": [],  # Don't expose todo content in args
    "task": ["subagent_type"],  # Don't expose full description
}

# Whitelist of safe result fields per tool
TOOL_RESULT_WHITELIST: Dict[str, list[str]] = {
    "search_tender_corpus": ["num_results", "sources"],
    "get_file_content": ["file_name", "page_count"],
    "web_search": ["num_results"],
    "read_file": ["file_name", "line_count"],
    "write_file": ["file_name", "success"],
    "edit_file": ["file_name", "success"],
    "ls": ["num_files"],
}


def sanitize_tool_args(tool_name: str, args: Dict[str, Any]) -> str:
    """
    Sanitize tool arguments for safe streaming.
    
    Args:
        tool_name: Name of the tool
        args: Raw tool arguments
        
    Returns:
        Safe string summary of arguments
    """
    if tool_name not in TOOL_ARG_WHITELIST:
        logger.warning(f"No whitelist for tool: {tool_name}, redacting all args")
        return "(redacted)"
    
    whitelist = TOOL_ARG_WHITELIST[tool_name]
    
    if not whitelist:
        # Tool has no safe args
        return "(no args)"
    
    safe_args = {}
    for key in whitelist:
        if key in args:
            value = args[key]
            # Truncate long strings
            if isinstance(value, str) and len(value) > 100:
                value = value[:97] + "..."
            safe_args[key] = value
    
    if not safe_args:
        return "(no args)"
    
    # Format as compact string
    parts = [f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" 
             for k, v in safe_args.items()]
    return ", ".join(parts)


def sanitize_tool_result(tool_name: str, result: Any) -> str:
    """
    Sanitize tool result for safe streaming.
    
    Args:
        tool_name: Name of the tool
        result: Raw tool result
        
    Returns:
        Safe string summary of result
    """
    # Handle errors
    if isinstance(result, str) and result.startswith("Error:"):
        return "Failed"
    
    if tool_name not in TOOL_RESULT_WHITELIST:
        logger.warning(f"No result whitelist for tool: {tool_name}")
        return "Completed"
    
    # Special handling for search results
    if tool_name == "search_tender_corpus":
        if isinstance(result, str):
            # Count number of sections mentioned
            if "section" in result.lower() or "found" in result.lower():
                # Extract count from phrases like "Found 3 sections"
                words = result.split()
                for i, word in enumerate(words):
                    if word.lower() in ["found", "identified"]:
                        if i + 1 < len(words) and words[i + 1].isdigit():
                            return f"Found {words[i + 1]} results"
                return "Found results"
            return "Completed search"
        return "Completed"
    
    # For file operations
    if tool_name in ["read_file", "get_file_content"]:
        if isinstance(result, str):
            line_count = result.count("\n")
            if line_count > 0:
                return f"Read {line_count} lines"
            word_count = len(result.split())
            return f"Read {word_count} words"
        return "Read file"
    
    if tool_name in ["write_file", "edit_file"]:
        return "Updated file"
    
    if tool_name == "ls":
        if isinstance(result, str):
            # Count files in output
            lines = result.strip().split("\n")
            return f"Listed {len(lines)} items"
        return "Listed directory"
    
    if tool_name == "web_search":
        return "Found web results"
    
    # Default
    return "Completed"


def sanitize_error_message(error: str) -> str:
    """
    Sanitize error message to prevent leaking sensitive info.
    
    Args:
        error: Raw error message
        
    Returns:
        Safe error message
    """
    # Remove file paths
    if "/" in error:
        error = error.split("/")[-1]  # Keep only filename
    
    # Remove long stack traces
    if "\n" in error:
        lines = error.split("\n")
        # Keep only first line
        error = lines[0]
    
    # Truncate if too long
    if len(error) > 200:
        error = error[:197] + "..."
    
    return error

