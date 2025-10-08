"""
Utility functions for API operations.
Handles ID generation, validation, and pagination helpers.
"""

import uuid
from typing import Dict, Any
from bson import ObjectId


def generate_chat_id() -> str:
    """
    Generate a unique chat ID using UUID4.
    
    Returns:
        str: A UUID string to be used as chat_id
    """
    return str(uuid.uuid4())


def generate_thread_id(chat_id: str) -> str:
    """
    Generate a LangGraph thread ID from chat_id.
    This maps the chat to a conversation thread in the agent.
    
    Args:
        chat_id: The chat UUID
        
    Returns:
        str: Thread ID for LangGraph (format: "chat_{chat_id}")
    """
    return f"chat_{chat_id}"


def validate_object_id(id_str: str) -> bool:
    """
    Validate if a string is a valid MongoDB ObjectId.
    
    Args:
        id_str: String to validate
        
    Returns:
        bool: True if valid ObjectId format, False otherwise
    """
    try:
        ObjectId(id_str)
        return True
    except Exception:
        return False


def validate_uuid(uuid_str: str) -> bool:
    """
    Validate if a string is a valid UUID.
    
    Args:
        uuid_str: String to validate
        
    Returns:
        bool: True if valid UUID format, False otherwise
    """
    try:
        uuid.UUID(uuid_str)
        return True
    except Exception:
        return False


def calculate_pagination(
    total: int, 
    page: int, 
    page_size: int
) -> Dict[str, Any]:
    """
    Calculate pagination metadata.
    
    Args:
        total: Total number of items
        page: Current page number (1-indexed)
        page_size: Number of items per page
        
    Returns:
        Dict with pagination metadata
    """
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    has_more = page < total_pages
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_more": has_more
    }


def format_error_message(operation: str, error: Exception) -> str:
    """
    Format a user-friendly error message.
    
    Args:
        operation: The operation that failed
        error: The exception that occurred
        
    Returns:
        str: Formatted error message
    """
    return f"Failed to {operation}: {str(error)}"

