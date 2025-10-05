from typing import Optional

from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import StreamingResponse
from pymongo import MongoClient

from api.models import (
    QueryCreateRequest,
    ConversationCreateRequest,
    QueryResponse,
    ConversationResponse,
    PaginatedQueryResponse,
    PaginatedConversationResponse,
    PaginatedUserQueryResponse,
    StreamingQueryResponse,
    UserQueryParams,
    ConversationQueryParams,
    QueryStatus
)
from api.store import QueryStore

class QueryRouters:
    def __init__(self, client: MongoClient):
        self.query_router = APIRouter(prefix="/api")
        self.query_store = QueryStore(client)

        self.query_router.post("/conversations", status_code=status.HTTP_201_CREATED, tags=["Conversations"])(self.create_conversation)
        self.query_router.get("/conversations", status_code=status.HTTP_200_OK, tags=["Conversations"])(self.get_conversations)
        self.query_router.get("/conversations/{conversation_id}", status_code=status.HTTP_200_OK, tags=["Conversations"])(self.get_conversation)

        self.query_router.post("/queries/stream", status_code=status.HTTP_200_OK, tags=["Queries"])(self.create_streaming_query)
        
        self.query_router.post("/conversations/{conversation_id}/queries", status_code=status.HTTP_201_CREATED, tags=["Queries"])(self.create_query)
        self.query_router.get("/queries/{query_id}", status_code=status.HTTP_200_OK, tags=["Queries"])(self.get_query)
        self.query_router.get("/conversations/{conversation_id}/queries", status_code=status.HTTP_200_OK, tags=["Queries"])(self.get_conversation_queries)
        
        self.query_router.get("/users/{user_id}/queries", status_code=status.HTTP_200_OK, tags=["User Queries"])(self.get_user_queries)

    def _handle_error(self, e: Exception, operation: str) -> HTTPException:
        """Centralized error handling"""
        if isinstance(e, HTTPException):
            return e
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to {operation}: {str(e)}"
        )

    def _validate_pagination(self, page: int, page_size: int):
        """Validate pagination parameters"""
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Page number must be greater than or equal to 1"
            )
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Page size must be between 1 and 100"
            )

    def _validate_id(self, id_value: str, field_name: str):
        """Validate ID parameters"""
        if not id_value or len(id_value.strip()) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{field_name} cannot be empty"
            )
        
    async def create_conversation(
        self,
        conversation_request: ConversationCreateRequest,
        org_id: int = Depends(lambda: 1)
    ) -> ConversationResponse:
        """Create a new conversation"""
        try:
            return await self.query_store.create_conversation(conversation_request, org_id)
        except Exception as e:
            raise self._handle_error(e, "create conversation")
    
    def get_conversations(
        self,
        page: int = 1,
        page_size: int = 50,
        org_id: int = Depends(lambda: 1)
    ) -> PaginatedConversationResponse:
        """Get all conversations with pagination"""
        try:
            self._validate_pagination(page, page_size)
            return self.query_store.get_conversations(page, page_size)
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "get conversations")
    
    def get_conversation(
        self,
        conversation_id: str,
        org_id: int = Depends(lambda: 1)
    ) -> ConversationResponse:
        """Get a single conversation by ID"""
        try:
            self._validate_id(conversation_id, "conversation_id")
            result = self.query_store.get_conversation_by_id(conversation_id)
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conversation with ID {conversation_id} not found"
                )
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "get conversation")
    
    async def create_query(
        self,
        conversation_id: str,
        query_request: QueryCreateRequest,
        org_id: int = Depends(lambda: 1)
    ) -> QueryResponse:
        """Create a new query in a conversation"""
        try:
            self._validate_id(conversation_id, "conversation_id")
            if not query_request.query_text or len(query_request.query_text.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="query_text cannot be empty"
                )
            return await self.query_store.create_query(conversation_id, query_request, org_id)
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "create query")
    
    def get_query(
        self,
        query_id: str,
        org_id: int = Depends(lambda: 1)
    ) -> QueryResponse:
        """Get a single query by ID"""
        try:
            self._validate_id(query_id, "query_id")
            result = self.query_store.get_query_by_id(query_id)
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Query with ID {query_id} not found"
                )
            return result
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "get query")
    
    def get_conversation_queries(
        self,
        conversation_id: str,
        status: Optional[QueryStatus] = None,
        tender_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        org_id: int = Depends(lambda: 1)
    ) -> PaginatedQueryResponse:
        """Get all queries for a conversation with pagination and filtering"""
        try:
            self._validate_id(conversation_id, "conversation_id")
            self._validate_pagination(page, page_size)
            params = ConversationQueryParams(
                status=status,
                tender_id=tender_id,
                page=page,
                page_size=page_size
            )
            return self.query_store.get_conversation_queries(conversation_id, params)
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "get conversation queries")

    async def create_streaming_query(
        self,
        query_request: QueryCreateRequest,
        org_id: int = Depends(lambda: 1)
    ) -> StreamingResponse:
        """Create a streaming query with automatic conversation management"""
        try:
            if not query_request.query_text or len(query_request.query_text.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="query_text cannot be empty"
                )
            
            async def generate_stream():
                try:
                    async for chunk in self.query_store.create_streaming_query(query_request, org_id):
                        yield f"data: {chunk.model_dump_json()}\n\n"
                except Exception as e:
                    error_chunk = StreamingQueryResponse(
                        query_id="",
                        conversation_id="",
                        chunk_type="error",
                        content=f"Streaming error: {str(e)}"
                    )
                    yield f"data: {error_chunk.model_dump_json()}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream"
                }
            )
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "create streaming query")

    def get_user_queries(
        self,
        user_id: str,
        status: Optional[QueryStatus] = None,
        tender_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        org_id: int = Depends(lambda: 1)
    ) -> PaginatedUserQueryResponse:
        """Get all queries for a specific user with pagination and filtering"""
        try:
            self._validate_id(user_id, "user_id")
            self._validate_pagination(page, page_size)
            params = UserQueryParams(
                status=status,
                tender_id=tender_id,
                conversation_id=conversation_id,
                page=page,
                page_size=page_size
            )
            return self.query_store.get_user_queries(user_id, params)
        except HTTPException:
            raise
        except Exception as e:
            raise self._handle_error(e, "get user queries")

def create_query_routers(client: MongoClient) -> QueryRouters:
    """Factory function to create query routers with MongoDB client"""
    return QueryRouters(client)