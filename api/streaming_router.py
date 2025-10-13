"""
Enhanced streaming router for MVP agent transparency.

New endpoints:
- POST /api/chats/{chat_id}/messages → Create message, return stream URL
- GET /api/chats/{chat_id}/messages/{message_id}/stream → SSE stream
- GET /api/messages/{message_id}/events → Replay events
"""

import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse
from pymongo import MongoClient

from api.models import (
    MessageCreateRequest,
    MessageCreateResponse,
    ChatResponse,
    ChatCreateRequest,
    UserResponse,
    MessageResponse,
    PaginatedResponse,
)
from api.store import ApiStore
from api.utils import validate_uuid, validate_object_id
from api.streaming.persistence import EventPersistence

logger = logging.getLogger(__name__)


class StreamingApiRouter:
    """
    Enhanced API router for MVP streaming transparency.
    
    Implements the split POST (create) / GET (stream) pattern.
    """
    
    def __init__(self, client: MongoClient, db_name: str = "org_1"):
        """
        Initialize the streaming API router.
        
        Args:
            client: MongoDB client instance
            db_name: Database name to use
        """
        self.router = APIRouter(prefix="/api", tags=["Streaming API (MVP)"])
        self.store = ApiStore(client, db_name)
        self.event_persistence = EventPersistence(client, db_name)
        
        self._register_routes()
        
        logger.info("StreamingApiRouter initialized")
    
    def _register_routes(self):
        """Register streaming API routes."""
        
        # User endpoints
        self.router.add_api_route(
            "/users/{user_id}",
            self.get_or_create_user,
            methods=["GET"],
            response_model=UserResponse,
            status_code=status.HTTP_200_OK,
            summary="Get or create user",
            description="Get user by ID, auto-create if doesn't exist."
        )
        
        # Chat endpoints
        self.router.add_api_route(
            "/users/{user_id}/chats",
            self.list_user_chats,
            methods=["GET"],
            response_model=PaginatedResponse[ChatResponse],
            status_code=status.HTTP_200_OK,
            summary="List user chats",
            description="Get all chats for a user (paginated)."
        )
        
        self.router.add_api_route(
            "/users/{user_id}/chats",
            self.create_chat,
            methods=["POST"],
            response_model=ChatResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create chat",
            description="Create a new chat session for a user."
        )
        
        self.router.add_api_route(
            "/chats/{chat_id}",
            self.get_chat,
            methods=["GET"],
            response_model=ChatResponse,
            status_code=status.HTTP_200_OK,
            summary="Get chat details",
            description="Get chat information including message count."
        )
        
        # Message history
        self.router.add_api_route(
            "/chats/{chat_id}/messages",
            self.get_messages,
            methods=["GET"],
            response_model=PaginatedResponse[MessageResponse],
            status_code=status.HTTP_200_OK,
            summary="Get message history",
            description="Get paginated message history for a chat."
        )
        
        # Create message (returns stream URL)
        self.router.add_api_route(
            "/chats/{chat_id}/messages",
            self.create_message,
            methods=["POST"],
            response_model=MessageCreateResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Create message and get stream URL",
            description="Create a new message and return URL for SSE streaming."
        )
        
        # Stream message events (SSE)
        self.router.add_api_route(
            "/chats/{chat_id}/messages/{message_id}/stream",
            self.stream_message,
            methods=["GET"],
            summary="Stream message events (SSE)",
            description="Open Server-Sent Events stream for real-time agent updates."
        )
        
        # Replay events
        self.router.add_api_route(
            "/messages/{message_id}/events",
            self.get_message_events,
            methods=["GET"],
            summary="Get message events (replay)",
            description="Retrieve events for replay/debugging."
        )
        
        # HITL resume endpoint
        self.router.add_api_route(
            "/chats/{chat_id}/messages/{message_id}/resume",
            self.resume_interrupted_message,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            summary="Resume interrupted message (HITL)",
            description="Resume an interrupted message with human input (accept/edit/respond/ignore)."
        )
    
    # ========================================================================
    # User & Chat Endpoints
    # ========================================================================
    
    async def get_or_create_user(self, user_id: str) -> UserResponse:
        """
        Get or create a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            UserResponse with user details
        """
        try:
            user = self.store.get_or_create_user(user_id)
            return user
        except Exception as e:
            logger.error(f"Failed to get/create user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get/create user: {str(e)}"
            )
    
    async def list_user_chats(
        self,
        user_id: str,
        page: int = Query(1, ge=1, description="Page number (1-based)"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page")
    ) -> PaginatedResponse[ChatResponse]:
        """
        Get all chats for a user (paginated).
        
        Args:
            user_id: User identifier
            page: Page number (1-based)
            page_size: Number of chats per page
            
        Returns:
            PaginatedResponse with chat list
        """
        try:
            # Get or create user to ensure they exist
            self.store.get_or_create_user(user_id)
            
            # Get paginated chats for user
            result = self.store.list_user_chats(
                user_id=user_id,
                page=page,
                page_size=page_size
            )
            
            return result
        except Exception as e:
            logger.error(f"Failed to list chats for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to list chats: {str(e)}"
            )
    
    async def create_chat(
        self,
        user_id: str,
        request: ChatCreateRequest
    ) -> ChatResponse:
        """
        Create a new chat session.
        
        Args:
            user_id: User identifier
            request: Chat creation request
            
        Returns:
            ChatResponse with chat details
        """
        try:
            # Ensure user exists
            self.store.get_or_create_user(user_id)
            
            # Create chat (returns ChatResponse already)
            chat = self.store.create_chat(
                user_id=user_id,
                request=request
            )
            
            return chat
        except Exception as e:
            logger.error(f"Failed to create chat for user {user_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create chat: {str(e)}"
            )
    
    async def get_chat(self, chat_id: str) -> ChatResponse:
        """
        Get chat details.
        
        Args:
            chat_id: Chat identifier
            
        Returns:
            ChatResponse with chat details and message count
        """
        try:
            validate_uuid(chat_id)
            chat = self.store.get_chat(chat_id)
            
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat {chat_id} not found"
                )
            
            return chat
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get chat {chat_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get chat: {str(e)}"
            )
    
    async def get_messages(
        self,
        chat_id: str,
        page: int = Query(1, ge=1, description="Page number (1-based)"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page")
    ) -> PaginatedResponse[MessageResponse]:
        """
        Get message history for a chat (paginated).
        
        Args:
            chat_id: Chat identifier
            page: Page number (1-based)
            page_size: Number of messages per page
            
        Returns:
            PaginatedResponse with message list
        """
        try:
            validate_uuid(chat_id)
            
            # Check if chat exists
            chat = self.store.get_chat(chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat {chat_id} not found"
                )
            
            # Get paginated messages
            result = self.store.list_chat_messages(
                chat_id=chat_id,
                page=page,
                page_size=page_size
            )
            
            return result
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get messages for chat {chat_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get messages: {str(e)}"
            )
    
    # ========================================================================
    # Create Message (Step 1)
    # ========================================================================
    
    async def create_message(
        self,
        chat_id: str,
        request: MessageCreateRequest
    ) -> MessageCreateResponse:
        """
        Create a message and return stream URL.
        
        This is Step 1 of the MVP streaming flow:
        1. POST creates the message
        2. Client opens GET SSE stream at the returned URL
        
        Args:
            chat_id: The chat identifier
            request: Message creation request
            
        Returns:
            MessageCreateResponse with message_id and stream_url
            
        Raises:
            HTTPException: If validation fails
        """
        try:
            # Validate input
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
            chat: ChatResponse = self.store.get_chat(chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chat with ID {chat_id} not found"
                )
            
            # Create user message in DB
            from api.models import MessageRole
            user_message = self.store.create_message(
                chat_id=chat_id,
                user_id=chat.user_id,
                role=MessageRole.USER,
                content=request.content,
                metadata=request.metadata
            )
            
            # Create empty assistant message (will be populated during streaming)
            assistant_message = self.store.create_message(
                chat_id=chat_id,
                user_id=chat.user_id,
                role=MessageRole.ASSISTANT,
                content="",
                metadata=request.metadata
            )
            
            # Build stream URL
            stream_url = f"/api/chats/{chat_id}/messages/{assistant_message.message_id}/stream"
            
            logger.info(
                f"Created message pair for chat {chat_id}: "
                f"user={user_message.message_id}, assistant={assistant_message.message_id}"
            )
            
            return MessageCreateResponse(
                message_id=assistant_message.message_id,
                stream_url=stream_url
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating message: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create message: {str(e)}"
            )
    
    # ========================================================================
    # Stream Message (Step 2)
    # ========================================================================
    
    async def stream_message(
        self,
        chat_id: str,
        message_id: str,
        request: Request,
        since: Optional[str] = Query(None, description="Event ID to resume from")
    ) -> StreamingResponse:
        """
        Stream agent events via Server-Sent Events.
        
        This is Step 2 of the MVP streaming flow.
        The frontend opens this endpoint with EventSource after POSTing.
        
        Args:
            chat_id: The chat identifier
            message_id: The assistant message identifier
            
        Returns:
            StreamingResponse with SSE stream
            
        Raises:
            HTTPException: If validation fails
        """
        try:
            # Validate
            if not validate_uuid(chat_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid chat_id format"
                )
            
            if not validate_object_id(message_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid message_id format"
                )
            
            # Verify message exists
            message = self.store.get_message(message_id)
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Message {message_id} not found"
                )
            
            if message.chat_id != chat_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Message does not belong to specified chat"
                )
            
            # Get the user message (previous message in chat)
            # We need its content to pass to the agent
            messages = self.store.list_chat_messages(chat_id, page=1, page_size=100)
            user_content = None
            # Sort messages chronologically (oldest first) to find the latest user message before assistant
            for msg in sorted(messages.items, key=lambda m: m.created_at, reverse=False):
                if msg.role.value == "user" and msg.created_at <= message.created_at:
                    user_content = msg.content
            
            if not user_content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not find user message for this response"
                )
            
            # Stream agent response
            async def generate_sse():
                """Generate SSE stream with proper formatting."""
                try:
                    # Check for resume from Last-Event-ID header or since query param
                    last_event_id = request.headers.get("last-event-id") or since
                    
                    # Replay historical events first if resuming
                    if last_event_id:
                        logger.info(f"Resuming stream from event {last_event_id}")
                        past_events = self.event_persistence.get_events(
                            message_id=message_id,
                            since_id=last_event_id,
                            limit=1000
                        )
                        for e in past_events:
                            # Format historical event as SSE
                            yield f"retry: 3000\n"
                            yield f"event: {e.get('type', 'status')}\n"
                            yield f"id: {e.get('id', '')}\n"
                            yield f"data: {json.dumps(e, default=str)}\n\n"
                    
                    # Import here to avoid circular dependency
                    from api.streaming_store import stream_agent_response
                    
                    async for event in stream_agent_response(
                        store=self.store,
                        event_persistence=self.event_persistence,
                        chat_id=chat_id,
                        message_id=message_id,
                        user_content=user_content,
                        metadata=message.metadata or {}
                    ):
                        # Format as SSE with proper event type value
                        # event: {type}
                        # id: {id}
                        # data: {json}
                        yield f"retry: 3000\n"
                        yield f"event: {event.type.value if hasattr(event.type, 'value') else event.type}\n"
                        yield f"id: {event.id}\n"
                        yield f"data: {event.model_dump_json(exclude_none=True)}\n\n"
                    
                except Exception as e:
                    logger.error(f"Streaming error for message {message_id}: {e}")
                    # Send error event
                    from api.streaming.events import create_error_event
                    error_event = create_error_event(
                        f"error_{message_id}",
                        f"Streaming error: {str(e)}"
                    )
                    yield f"retry: 3000\n"
                    yield f"event: error\n"
                    yield f"id: {error_event.id}\n"
                    yield f"data: {error_event.model_dump_json()}\n\n"
            
            return StreamingResponse(
                generate_sse(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # Disable Nginx buffering
                }
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in stream_message: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to stream message: {str(e)}"
            )
    
    # ========================================================================
    # Replay Events
    # ========================================================================
    
    async def get_message_events(
        self,
        message_id: str,
        since: Optional[str] = Query(None, description="Event ID to start from")
    ) -> dict:
        """
        Get events for a message (replay functionality).
        
        Args:
            message_id: The message identifier
            since: Optional event ID to start from
            
        Returns:
            Dict with events array
            
        Raises:
            HTTPException: If message not found
        """
        try:
            if not validate_object_id(message_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid message_id format"
                )
            
            # Verify message exists
            message = self.store.get_message(message_id)
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Message {message_id} not found"
                )
            
            # Get events from persistence layer
            events = self.event_persistence.get_events(
                message_id=message_id,
                since_id=since,
                limit=1000
            )
            
            # Convert datetime objects to ISO strings for JSON serialization
            for event in events:
                if "ts" in event and hasattr(event["ts"], "isoformat"):
                    event["ts"] = event["ts"].isoformat()
                # Remove internal MongoDB fields
                event.pop("_id", None)
                event.pop("message_id", None)
                event.pop("chat_id", None)
            
            return {
                "message_id": message_id,
                "events": events,
                "count": len(events)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting events for message {message_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get events: {str(e)}"
            )
    
    # ========================================================================
    # HITL Resume Endpoint
    # ========================================================================
    
    async def resume_interrupted_message(
        self,
        chat_id: str,
        message_id: str,
        request: dict
    ) -> dict:
        """
        Resume an interrupted message with human input (HITL).
        
        Args:
            chat_id: Chat identifier
            message_id: Message identifier
            request: Resume request with action type and args
                - action: "accept", "edit", "respond", or "ignore"
                - args: Arguments for the action (optional)
                
        Returns:
            dict with completion status and final response
        """
        try:
            validate_uuid(chat_id)
            validate_object_id(message_id)
            
            # Get message to verify it's interrupted
            message = self.store.get_message(message_id)
            if not message:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Message {message_id} not found"
                )
            
            # Check if message is interrupted
            metadata = message.get("metadata", {})
            if not metadata.get("interrupted"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Message is not interrupted"
                )
            
            # Get thread_id from metadata
            thread_id = metadata.get("thread_id")
            if not thread_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Thread ID not found in message metadata"
                )
            
            # Parse resume action
            action = request.get("action", "accept")
            args = request.get("args")
            
            # Build resume command
            from langgraph.types import Command
            
            if action == "accept":
                resume_args = [{"type": "accept"}]
            elif action == "edit":
                if not args:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Edit action requires 'args' parameter"
                    )
                resume_args = [{"type": "edit", "args": args}]
            elif action == "respond":
                if not args:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Respond action requires 'args' parameter (human response)"
                    )
                resume_args = [{"type": "respond", "args": args}]
            elif action == "ignore":
                resume_args = [{"type": "ignore"}]
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid action: {action}. Must be accept/edit/respond/ignore"
                )
            
            # Resume the agent
            agent = self.store._get_agent()
            config = {"configurable": {"thread_id": thread_id}}
            
            # Resume with command
            result = await agent.agent.ainvoke(
                Command(resume=resume_args),
                config=config
            )
            
            # Extract final response
            from langchain_core.messages import AIMessage
            final_response = ""
            if "messages" in result and result["messages"]:
                last_message = result["messages"][-1]
                if isinstance(last_message, AIMessage):
                    final_response = last_message.content
            
            # Update message with final response
            from api.models import MessageStatus
            self.store.update_message_status(
                message_id,
                MessageStatus.COMPLETED,
                content=final_response,
                metadata={"resumed": True, "resume_action": action}
            )
            
            logger.info(f"Resumed message {message_id} with action: {action}")
            
            return {
                "message_id": message_id,
                "status": "completed",
                "action": action,
                "response": final_response
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to resume message {message_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resume message: {str(e)}"
            )


def create_streaming_router(client: MongoClient, db_name: str = "org_1") -> APIRouter:
    """
    Factory function to create the streaming API router.
    
    Args:
        client: MongoDB client instance
        db_name: Database name
        
    Returns:
        APIRouter: Configured router
    """
    streaming_router = StreamingApiRouter(client, db_name)
    return streaming_router.router

