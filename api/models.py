"""
Pydantic models for API requests and responses.
Defines the data structure for Users, Chats, and Messages.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, TypeVar, Generic
from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================

class MessageRole(str, Enum):
    """Role of the message sender"""
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(str, Enum):
    """Status of message processing"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StreamChunkType(str, Enum):
    """Type of streaming chunk"""
    START = "start"
    CONTENT = "content"
    END = "end"
    ERROR = "error"


# ============================================================================
# Request Models
# ============================================================================

class ChatCreateRequest(BaseModel):
    """Request model for creating a new chat"""
    title: Optional[str] = Field(
        None, 
        description="Optional title for the chat. If not provided, will be auto-generated.",
        max_length=200
    )


class MessageCreateRequest(BaseModel):
    """Request model for creating a new message"""
    content: str = Field(
        ..., 
        description="The message content",
        min_length=1,
        max_length=50000
    )
    metadata: Optional[dict] = Field(
        None,
        description="Optional metadata (e.g., tender_id, tags, etc.)"
    )


class MessageCreateResponse(BaseModel):
    """Response model for message creation (MVP streaming API)"""
    message_id: str = Field(..., description="Created message ID")
    stream_url: str = Field(..., description="URL to open SSE stream")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "670abc123def456789012345",
                "stream_url": "/api/chats/550e8400-e29b-41d4-a716-446655440000/messages/670abc123def456789012345/stream"
            }
        }


# ============================================================================
# Response Models
# ============================================================================

class UserResponse(BaseModel):
    """Response model for user information"""
    user_id: str = Field(..., description="Unique user identifier")
    name: Optional[str] = Field(None, description="User's display name")
    email: Optional[str] = Field(None, description="User's email address")
    created_at: datetime = Field(..., description="User creation timestamp")
    last_active: datetime = Field(..., description="Last activity timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "name": "John Doe",
                "email": "john@example.com",
                "created_at": "2025-10-08T10:00:00Z",
                "last_active": "2025-10-08T12:30:00Z"
            }
        }


class ChatResponse(BaseModel):
    """Response model for chat information"""
    chat_id: str = Field(..., description="Unique chat identifier (UUID)")
    user_id: str = Field(..., description="Owner user ID")
    title: str = Field(..., description="Chat title")
    created_at: datetime = Field(..., description="Chat creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    message_count: int = Field(0, description="Number of messages in chat")
    
    class Config:
        json_schema_extra = {
            "example": {
                "chat_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user_123",
                "title": "Tender Analysis Chat",
                "created_at": "2025-10-08T10:00:00Z",
                "updated_at": "2025-10-08T12:30:00Z",
                "message_count": 5
            }
        }


class MessageResponse(BaseModel):
    """Response model for message information"""
    message_id: str = Field(..., description="Unique message identifier (MongoDB ObjectId)")
    chat_id: str = Field(..., description="Parent chat ID")
    user_id: str = Field(..., description="User ID")
    role: MessageRole = Field(..., description="Message role (user/assistant)")
    content: str = Field(..., description="Message content")
    status: MessageStatus = Field(..., description="Processing status")
    created_at: datetime = Field(..., description="Message creation timestamp")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "670abc123def456789012345",
                "chat_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user_123",
                "role": "user",
                "content": "Analyze this tender document",
                "status": "completed",
                "created_at": "2025-10-08T10:00:00Z",
                "processing_time_ms": None,
                "metadata": {"tender_id": "T123"},
                "error": None
            }
        }


class StreamChunkResponse(BaseModel):
    """Response model for streaming chunks"""
    message_id: str = Field(..., description="Message ID being streamed")
    chat_id: str = Field(..., description="Chat ID")
    chunk_type: StreamChunkType = Field(..., description="Type of chunk")
    content: Optional[str] = Field(None, description="Chunk content (for content chunks)")
    status: Optional[MessageStatus] = Field(None, description="Status update (for start/end chunks)")
    processing_time_ms: Optional[int] = Field(None, description="Processing time (for end chunks)")
    error: Optional[str] = Field(None, description="Error message (for error chunks)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "670abc123def456789012345",
                "chat_id": "550e8400-e29b-41d4-a716-446655440000",
                "chunk_type": "content",
                "content": "Based on the tender document...",
                "status": None,
                "processing_time_ms": None,
                "error": None
            }
        }


# ============================================================================
# Generic Paginated Response
# ============================================================================

T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response model"""
    items: List[T] = Field(..., description="List of items for current page")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    has_more: bool = Field(..., description="Whether there are more pages")
    
    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "total": 100,
                "page": 1,
                "page_size": 50,
                "total_pages": 2,
                "has_more": True
            }
        }


# Type aliases for common paginated responses
PaginatedChats = PaginatedResponse[ChatResponse]
PaginatedMessages = PaginatedResponse[MessageResponse]


# ============================================================================
# API Info Models
# ============================================================================

class ApiInfoResponse(BaseModel):
    """Response model for API information"""
    name: str = Field(..., description="API name")
    version: str = Field(..., description="API version")
    description: str = Field(..., description="API description")
    endpoints: int = Field(..., description="Number of endpoints")
    features: List[str] = Field(..., description="List of features")


class HealthResponse(BaseModel):
    """Response model for health check"""
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="Current timestamp")
    mongodb: str = Field(..., description="MongoDB connection status")
    agent: str = Field(..., description="Agent service status")
