from typing import Optional

from fastapi import APIRouter, Depends, status, HTTPException
from pymongo import MongoClient

from api.models import (
    QueryCreateRequest,
    ConversationCreateRequest,
    QueryResponse,
    ConversationResponse,
    PaginatedQueryResponse,
    PaginatedConversationResponse,
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

        self.query_router.post("/conversations/{conversation_id}/queries", status_code=status.HTTP_201_CREATED, tags=["Queries"])(self.create_query)
        self.query_router.get("/queries/{query_id}", status_code=status.HTTP_200_OK, tags=["Queries"])(self.get_query)
        self.query_router.get("/conversations/{conversation_id}/queries", status_code=status.HTTP_200_OK, tags=["Queries"])(self.get_conversation_queries)
        
    async def create_conversation(
        self,
        conversation_request: ConversationCreateRequest,
        org_id: int = Depends(lambda: 1)
    ) -> ConversationResponse:
        """Create a new conversation"""
        try:
            result = await self.query_store.create_conversation(conversation_request, org_id)
            return result
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create conversation: {str(e)}"
            )
    
    def get_conversations(
        self,
        page: int = 1,
        page_size: int = 50,
        org_id: int = Depends(lambda: 1)
    ) -> PaginatedConversationResponse:
        """Get all conversations with pagination"""
        try:
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
            
            result = self.query_store.get_conversations(page, page_size)
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get conversations: {str(e)}"
            )
    
    def get_conversation(
        self,
        conversation_id: str,
        org_id: int = Depends(lambda: 1)
    ) -> ConversationResponse:
        """Get a single conversation by ID"""
        try:
            if not conversation_id or len(conversation_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conversation_id cannot be empty"
                )
            
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get conversation: {str(e)}"
            )
    
    async def create_query(
        self,
        conversation_id: str,
        query_request: QueryCreateRequest,
        org_id: int = Depends(lambda: 1)
    ) -> QueryResponse:
        """Create a new query in a conversation"""
        try:
            if not conversation_id or len(conversation_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conversation_id cannot be empty"
                )
            
            if not query_request.query_text or len(query_request.query_text.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="query_text cannot be empty"
                )
            
            result = await self.query_store.create_query(conversation_id, query_request, org_id)
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create query: {str(e)}"
            )
    
    def get_query(
        self,
        query_id: str,
        org_id: int = Depends(lambda: 1)
    ) -> QueryResponse:
        """Get a single query by ID"""
        try:
            if not query_id or len(query_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="query_id cannot be empty"
                )
            
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get query: {str(e)}"
            )
    
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
            if not conversation_id or len(conversation_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="conversation_id cannot be empty"
                )
            
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
            
            params = ConversationQueryParams(
                status=status,
                tender_id=tender_id,
                page=page,
                page_size=page_size
            )
            
            result = self.query_store.get_conversation_queries(conversation_id, params)
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get conversation queries: {str(e)}"
            )

def create_query_routers(client: MongoClient) -> QueryRouters:
    """Factory function to create query routers with MongoDB client"""
    return QueryRouters(client)
