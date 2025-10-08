"""
FastAPI router for all API endpoints.
Handles user, chat, and message operations with clean RESTful design.
"""

import logging
from fastapi import APIRouter, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from pymongo import MongoClient

from api.models import (
    UserResponse,
    ChatResponse,
    MessageResponse,
    ChatCreateRequest,
    MessageCreateRequest,
    PaginatedResponse,
    StreamChunkResponse
)
from api.store import ApiStore
from api.utils import validate_uuid, validate_object_id

logger = logging.getLogger(__name__)


class ApiRouter:
    """
    API Router class managing all endpoints.
    Follows RESTful design with user → chat → message hierarchy.
    """
    
    def __init__(self, client: MongoClient, db_name: str = "proposal_assistant"):
        """
        Initialize the API router with MongoDB client.
        
        Args:
            client: MongoDB client instance
            db_name: Database name to use
        """
        self.router = APIRouter(prefix="/api", tags=["API"])
        self.store = ApiStore(client, db_name)
        
        self._register_routes()
        
        logger.info("ApiRouter initialized with all endpoints")
    
    def _register_routes(self):
        """Register all API routes"""
        self.router.add_api_route(
            "/users/{user_id}",
            self.get_user,
            methods=["GET"],
            response_model=UserResponse,
            status_code=status.HTTP_200_OK,
            summary="Get or create user",
            description="Get user information. Creates user if doesn't exist."
        )
        
        self.router.add_api_route(
            "/users/{user_id}/chats",
            self.list_user_chats,
            methods=["GET"],
            response_model=PaginatedResponse[ChatResponse],
            status_code=status.HTTP_200_OK,
            summary="List user's chats",
            description="Get paginated list of all chats for a user."
        )
        
        self.router.add_api_route(
            "/users/{user_id}/chats",
            self.create_chat,
            methods=["POST"],
            response_model=ChatResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create new chat",
            description="Create a new chat for the user."
        )
        
        self.router.add_api_route(
            "/chats/{chat_id}",
            self.get_chat,
            methods=["GET"],
            response_model=ChatResponse,
            status_code=status.HTTP_200_OK,
            summary="Get chat details",
            description="Get information about a specific chat."
        )
        
        self.router.add_api_route(
            "/chats/{chat_id}",
            self.delete_chat,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete chat",
            description="Delete a chat and all its messages."
        )
        
        self.router.add_api_route(
            "/chats/{chat_id}/messages",
            self.send_message,
            methods=["POST"],
            status_code=status.HTTP_200_OK,
            summary="Send message (streaming)",
            description="Send a message and stream the AI response."
        )
        
        self.router.add_api_route(
            "/chats/{chat_id}/messages",
            self.get_messages,
            methods=["GET"],
            response_model=PaginatedResponse[MessageResponse],
            status_code=status.HTTP_200_OK,
            summary="Get chat messages",
            description="Get paginated message history for a chat."
        )
        
        self.router.add_api_route(
            "/messages/{message_id}",
            self.get_message,
            methods=["GET"],
            response_model=MessageResponse,
            status_code=status.HTTP_200_OK,
            summary="Get message details",
            description="Get information about a specific message."
        )
    
    # ========================================================================
    # User Endpoints
    # ========================================================================
    
    async def get_user(self, user_id: str) -> UserResponse:
        """
        Get user information. Creates user if doesn't exist.
        
        Args:
            user_id: The user identifier
            
        Returns:
            UserResponse: User information
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            if not user_id or len(user_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user_id cannot be empty"
                )
            
            return self.store.get_or_create_user(user_id)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in get_user: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get user: {str(e)}"
            )
    
    async def list_user_chats(
        self,
        user_id: str,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=100, description="Items per page")
    ) -> PaginatedResponse[ChatResponse]:
        """
        List all chats for a user with pagination.
        
        Args:
            user_id: The user identifier
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse[ChatResponse]: Paginated list of chats
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            if not user_id or len(user_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user_id cannot be empty"
                )
            
            return self.store.list_user_chats(user_id, page, page_size)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in list_user_chats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list chats: {str(e)}"
            )
    
    # ========================================================================
    # Chat Endpoints
    # ========================================================================
    
    async def create_chat(
        self,
        user_id: str,
        request: ChatCreateRequest
    ) -> ChatResponse:
        """
        Create a new chat for the user.
        
        Args:
            user_id: The user identifier
            request: Chat creation request
            
        Returns:
            ChatResponse: Created chat information
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            if not user_id or len(user_id.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user_id cannot be empty"
                )
            
            # Ensure user exists
            self.store.get_or_create_user(user_id)
            
            return self.store.create_chat(user_id, request)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in create_chat: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create chat: {str(e)}"
            )
    
    async def get_chat(self, chat_id: str) -> ChatResponse:
        """
        Get information about a specific chat.
        
        Args:
            chat_id: The chat identifier
            
        Returns:
            ChatResponse: Chat information
            
        Raises:
            HTTPException: If chat not found or operation fails
        """
        try:
            if not validate_uuid(chat_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id format"
                )
            
            chat = self.store.get_chat(chat_id)
            
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat with ID {chat_id} not found"
                )
            
            return chat
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in get_chat: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get chat: {str(e)}"
            )
    
    async def delete_chat(self, chat_id: str) -> None:
        """
        Delete a chat and all its messages.
        
        Args:
            chat_id: The chat identifier
            
        Raises:
            HTTPException: If chat not found or operation fails
        """
        try:
            if not validate_uuid(chat_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id format"
                )
            
            deleted = self.store.delete_chat(chat_id)
            
            if not deleted:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat with ID {chat_id} not found"
                )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in delete_chat: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete chat: {str(e)}"
            )
    
    # ========================================================================
    # Message Endpoints
    # ========================================================================
    
    async def send_message(
        self,
        chat_id: str,
        request: MessageCreateRequest
    ) -> StreamingResponse:
        """
        Send a message and stream the AI response.
        
        Args:
            chat_id: The chat identifier
            request: Message creation request
            
        Returns:
            StreamingResponse: Server-sent events stream
            
        Raises:
            HTTPException: If chat not found or operation fails
        """
        try:
            if not validate_uuid(chat_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id format"
                )
            
            if not request.content or len(request.content.strip()) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Message content cannot be empty"
                )
            
            # Verify chat exists
            chat = self.store.get_chat(chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat with ID {chat_id} not found"
                )
            
            # Stream response
            async def generate_stream():
                """Generate Server-Sent Events stream"""
                try:
                    async for chunk in self.store.stream_message(
                        chat_id=chat_id,
                        user_id=chat.user_id,
                        request=request
                    ):
                        yield f"data: {chunk.model_dump_json()}\n\n"
                        
                except Exception as e:
                    logger.error(f"Streaming error: {str(e)}")
                    error_chunk = StreamChunkResponse(
                        message_id="",
                        chat_id=chat_id,
                        chunk_type="error",
                        error=f"Streaming error: {str(e)}"
                    )
                    yield f"data: {error_chunk.model_dump_json()}\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                    "X-Accel-Buffering": "no"
                }
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in send_message: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send message: {str(e)}"
            )
    
    async def get_messages(
        self,
        chat_id: str,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(50, ge=1, le=100, description="Items per page")
    ) -> PaginatedResponse[MessageResponse]:
        """
        Get paginated message history for a chat.
        
        Args:
            chat_id: The chat identifier
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse[MessageResponse]: Paginated list of messages
            
        Raises:
            HTTPException: If chat not found or operation fails
        """
        try:
            if not validate_uuid(chat_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id format"
                )
            
            # Verify chat exists
            chat = self.store.get_chat(chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat with ID {chat_id} not found"
                )
            
            return self.store.list_chat_messages(chat_id, page, page_size)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in get_messages: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get messages: {str(e)}"
            )
    
    async def get_message(self, message_id: str) -> MessageResponse:
        """
        Get information about a specific message.
        
        Args:
            message_id: The message identifier
            
        Returns:
            MessageResponse: Message information
            
        Raises:
            HTTPException: If message not found or operation fails
        """
        try:
            if not validate_object_id(message_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid message_id format"
                )
            
            message = self.store.get_message(message_id)
            
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Message with ID {message_id} not found"
                )
            
            return message
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in get_message: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get message: {str(e)}"
            )


def create_api_router(client: MongoClient, db_name: str = "proposal_assistant") -> APIRouter:
    """
    Factory function to create and configure the API router.
    
    Args:
        client: MongoDB client instance
        db_name: Database name to use
        
    Returns:
        APIRouter: Configured FastAPI router
    """
    api_router = ApiRouter(client, db_name)
    return api_router.router
