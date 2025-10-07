from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional

class QueryStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class QueryCreateRequest(BaseModel):
    """Model for creating a new query"""
    query_text: str = Field(..., min_length=1, description="The query text to process")
    tender_id: Optional[str] = Field(None, description="Optional tender ID for context")
    user_id: Optional[str] = Field(None, description="User ID for tracking queries")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID for continued chat")
    create_new_conversation: bool = Field(False, description="Whether to create a new conversation")

class ConversationCreateRequest(BaseModel):
    """Model for creating a new conversation"""
    name: Optional[str] = Field(None, description="Conversation name")

class QueryResponse(BaseModel):
    """Model for a single query response"""
    id: str = Field(..., description="MongoDB ObjectId")
    conversation_id: str = Field(..., description="Conversation ID")
    query_text: str = Field(..., description="The original query text")
    response_text: Optional[str] = Field(None, description="The agent's response")
    status: QueryStatus = Field(..., description="Current status of the query")
    tender_id: Optional[str] = Field(None, description="Associated tender ID")
    user_id: Optional[str] = Field(None, description="User ID who created the query")
    created_at: datetime = Field(..., description="Creation timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    error_message: Optional[str] = Field(None, description="Error message if query failed")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")

class ConversationResponse(BaseModel):
    """Model for conversation response"""
    id: str = Field(..., description="MongoDB ObjectId")
    name: Optional[str] = Field(None, description="Conversation name")
    created_at: datetime = Field(..., description="Creation timestamp")
    query_count: int = Field(0, description="Number of queries in conversation")

class ConversationQueryParams(BaseModel):
    """Query parameters for conversation queries endpoint"""
    status: Optional[QueryStatus] = Field(None, description="Filter by query status")
    tender_id: Optional[str] = Field(None, description="Filter by tender ID")
    page: int = Field(default=1, ge=1, description="Page number for pagination")
    page_size: int = Field(default=50, ge=1, le=100, description="Number of items per page")

class PaginatedQueryResponse(BaseModel):
    """Model for paginated query responses"""
    items: List[QueryResponse]
    total: Optional[int] = None
    page: Optional[int] = None
    page_size: int
    total_pages: Optional[int] = None
    conversation_id: str = Field(..., description="Conversation ID")

class PaginatedConversationResponse(BaseModel):
    """Model for paginated conversation responses"""
    items: List[ConversationResponse]
    total: Optional[int] = None
    page: Optional[int] = None
    page_size: int
    total_pages: Optional[int] = None

class StreamingQueryResponse(BaseModel):
    """Model for streaming query response chunks"""
    query_id: str = Field(..., description="Query ID")
    conversation_id: str = Field(..., description="Conversation ID")
    chunk_type: str = Field(..., description="Type of chunk: start, content, end, error")
    content: Optional[str] = Field(None, description="Chunk content")
    status: Optional[QueryStatus] = Field(None, description="Current status")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

class UserQueryParams(BaseModel):
    """Query parameters for user queries endpoint"""
    status: Optional[QueryStatus] = Field(None, description="Filter by query status")
    tender_id: Optional[str] = Field(None, description="Filter by tender ID")
    conversation_id: Optional[str] = Field(None, description="Filter by conversation ID")
    page: int = Field(default=1, ge=1, description="Page number for pagination")
    page_size: int = Field(default=50, ge=1, le=100, description="Number of items per page")

class PaginatedUserQueryResponse(BaseModel):
    """Model for paginated user query responses"""
    items: List[QueryResponse]
    total: Optional[int] = None
    page: Optional[int] = None
    page_size: int
    total_pages: Optional[int] = None
    user_id: str = Field(..., description="User ID")
