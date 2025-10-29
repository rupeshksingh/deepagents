"""
MongoDB store for API operations.
Handles all database operations for users, chats, and messages.
Integrates with ReactAgent for message processing.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId

from api.models import (
    UserResponse,
    ChatResponse,
    MessageResponse,
    ChatCreateRequest,
    MessageCreateRequest,
    PaginatedResponse,
    StreamChunkResponse,
    MessageRole,
    MessageStatus,
    StreamChunkType
)
from api.utils import (
    generate_thread_id,
    calculate_pagination,
    validate_object_id,
    validate_chat_id
)
from react_agent import ReactAgent

logger = logging.getLogger(__name__)


class ApiStore:
    """
    Store class for managing all API database operations.
    Handles users, chats, and messages with MongoDB persistence.
    """
    
    def __init__(self, client: MongoClient, db_name: str = "org_1"):
        """
        Initialize the API store with MongoDB client.
        
        Args:
            client: MongoDB client instance
            db_name: Database name to use
        """
        self.client = client
        self.db = client[db_name]

        # Collection names with PA (Proposal Assistant) prefix
        self.users_collection = self.db["pa_users"]
        self.chats_collection = self.db["pa_chats"]
        self.messages_collection = self.db["pa_messages"]
        
        self.agent = None
        
        self._setup_indexes()
        
        logger.info(f"ApiStore initialized with database: {db_name}")
    
    def _setup_indexes(self):
        """Create necessary indexes for performance"""
        try:
            self.users_collection.create_index("user_id", unique=True)
            
            self.chats_collection.create_index("chat_id", unique=True)
            self.chats_collection.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
            
            self.messages_collection.create_index([("chat_id", ASCENDING), ("created_at", ASCENDING)])
            self.messages_collection.create_index("user_id")
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating indexes: {str(e)}")
    
    def _get_agent(self) -> ReactAgent:
        """
        Get or create a ReactAgent instance.
        Agent is cached for reuse.
        
        Returns:
            ReactAgent: The agent instance
        """
        if self.agent is None:
            # Production: enable HITL interrupts for human-in-the-loop interactions
            self.agent = ReactAgent(self.client, org_id=1, enable_hitl=True)
            logger.info("ReactAgent instance created (HITL enabled)")
        return self.agent
    
    # ========================================================================
    # User Operations
    # ========================================================================
    
    def get_or_create_user(self, user_id: str) -> UserResponse:
        """
        Get user by ID, or create if doesn't exist.
        
        Args:
            user_id: The user identifier
            
        Returns:
            UserResponse: User information
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            user_doc = self.users_collection.find_one({"user_id": user_id})
            
            if user_doc:
                self.users_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"last_active": current_time}}
                )
                user_doc["last_active"] = current_time
            else:
                user_doc = {
                    "user_id": user_id,
                    "name": None,
                    "email": None,
                    "created_at": current_time,
                    "last_active": current_time
                }
                self.users_collection.insert_one(user_doc)
                logger.info(f"Created new user: {user_id}")
            
            return UserResponse(
                user_id=user_doc["user_id"],
                name=user_doc.get("name"),
                email=user_doc.get("email"),
                created_at=user_doc["created_at"],
                last_active=user_doc["last_active"]
            )
            
        except Exception as e:
            logger.error(f"Error in get_or_create_user: {str(e)}")
            raise Exception(f"Failed to get/create user: {str(e)}")
    
    def update_user_activity(self, user_id: str) -> None:
        """
        Update user's last active timestamp.
        
        Args:
            user_id: The user identifier
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            self.users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_active": current_time}}
            )
        except Exception as e:
            logger.warning(f"Error updating user activity: {str(e)}")
    
    # ========================================================================
    # Chat Operations
    # ========================================================================
    
    def create_chat(
        self, 
        user_id: str, 
        request: ChatCreateRequest
    ) -> ChatResponse:
        """
        Create a new chat for a user.
        
        Uses MongoDB insertion ObjectId as chat_id for cleaner ID management.
        
        Args:
            user_id: The user identifier
            request: Chat creation request
            
        Returns:
            ChatResponse: Created chat information
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            title = request.title or f"Chat - {current_time.strftime('%Y-%m-%d %H:%M')}"
            
            chat_doc = {
                "user_id": user_id,
                "title": title,
                "created_at": current_time,
                "updated_at": current_time,
                "message_count": 0
            }
            
            # Insert and use insertion ObjectId as chat_id
            result = self.chats_collection.insert_one(chat_doc)
            chat_id = str(result.inserted_id)
            
            # Update document with chat_id field for existing query compatibility
            self.chats_collection.update_one(
                {"_id": result.inserted_id},
                {"$set": {"chat_id": chat_id}}
            )
            
            logger.info(f"Created new chat: {chat_id} for user: {user_id}")
            
            self.update_user_activity(user_id)
            
            return ChatResponse(
                chat_id=chat_id,
                user_id=user_id,
                title=title,
                created_at=current_time,
                updated_at=current_time,
                message_count=0
            )
            
        except Exception as e:
            logger.error(f"Error creating chat: {str(e)}")
            raise Exception(f"Failed to create chat: {str(e)}")
    
    def get_chat(self, chat_id: str) -> Optional[ChatResponse]:
        """
        Get a chat by ID.
        
        Args:
            chat_id: The chat identifier (MongoDB ObjectId string)
            
        Returns:
            ChatResponse: Chat information, or None if not found
        """
        try:
            if not validate_chat_id(chat_id):
                logger.warning(f"Invalid chat_id format: {chat_id}")
                return None
            
            chat_doc = self.chats_collection.find_one({"chat_id": chat_id})
            
            if not chat_doc:
                return None
            
            return ChatResponse(
                chat_id=chat_doc["chat_id"],
                user_id=chat_doc["user_id"],
                title=chat_doc["title"],
                created_at=chat_doc["created_at"],
                updated_at=chat_doc["updated_at"],
                message_count=chat_doc.get("message_count", 0)
            )
            
        except Exception as e:
            logger.error(f"Error getting chat: {str(e)}")
            return None
    
    def list_user_chats(
        self, 
        user_id: str, 
        page: int = 1, 
        page_size: int = 50
    ) -> PaginatedResponse[ChatResponse]:
        """
        List all chats for a user with pagination.
        
        Args:
            user_id: The user identifier
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse[ChatResponse]: Paginated list of chats
        """
        try:
            total = self.chats_collection.count_documents({"user_id": user_id})
            
            pagination = calculate_pagination(total, page, page_size)
            skip = (page - 1) * page_size
            
            cursor = self.chats_collection.find(
                {"user_id": user_id}
            ).sort("updated_at", DESCENDING).skip(skip).limit(page_size)
            
            items = []
            for chat_doc in cursor:
                items.append(ChatResponse(
                    chat_id=chat_doc["chat_id"],
                    user_id=chat_doc["user_id"],
                    title=chat_doc["title"],
                    created_at=chat_doc["created_at"],
                    updated_at=chat_doc["updated_at"],
                    message_count=chat_doc.get("message_count", 0)
                ))
            
            return PaginatedResponse(
                items=items,
                total=pagination["total"],
                page=pagination["page"],
                page_size=pagination["page_size"],
                total_pages=pagination["total_pages"],
                has_more=pagination["has_more"]
            )
            
        except Exception as e:
            logger.error(f"Error listing user chats: {str(e)}")
            raise Exception(f"Failed to list chats: {str(e)}")
    
    def delete_chat(self, chat_id: str) -> bool:
        """
        Delete a chat and all its messages.
        
        Args:
            chat_id: The chat identifier (MongoDB ObjectId string)
            
        Returns:
            bool: True if deleted, False if not found
        """
        try:
            if not validate_chat_id(chat_id):
                logger.warning(f"Invalid chat_id format: {chat_id}")
                return False
            
            self.messages_collection.delete_many({"chat_id": chat_id})
            
            result = self.chats_collection.delete_one({"chat_id": chat_id})
            
            if result.deleted_count > 0:
                logger.info(f"Deleted chat: {chat_id}")
                return True
            else:
                logger.warning(f"Chat not found: {chat_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error deleting chat: {str(e)}")
            raise Exception(f"Failed to delete chat: {str(e)}")
    
    def update_chat_timestamp(self, chat_id: str) -> None:
        """
        Update chat's updated_at timestamp.
        
        Args:
            chat_id: The chat identifier
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            self.chats_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"updated_at": current_time}}
            )
        except Exception as e:
            logger.warning(f"Error updating chat timestamp: {str(e)}")
    
    def increment_message_count(self, chat_id: str) -> None:
        """
        Increment the message count for a chat.
        
        Args:
            chat_id: The chat identifier
        """
        try:
            self.chats_collection.update_one(
                {"chat_id": chat_id},
                {"$inc": {"message_count": 1}}
            )
        except Exception as e:
            logger.warning(f"Error incrementing message count: {str(e)}")
    
    # ========================================================================
    # Message Operations
    # ========================================================================
    
    def create_message(
        self,
        chat_id: str,
        user_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[dict] = None
    ) -> MessageResponse:
        """
        Create a new message in a chat.
        
        Args:
            chat_id: The chat identifier
            user_id: The user identifier
            role: Message role (user/assistant)
            content: Message content
            metadata: Optional metadata
            
        Returns:
            MessageResponse: Created message information
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            message_doc = {
                "chat_id": chat_id,
                "user_id": user_id,
                "role": role.value,
                "content": content,
                "status": MessageStatus.COMPLETED.value if role == MessageRole.USER else MessageStatus.PENDING.value,
                "created_at": current_time,
                "processing_time_ms": None,
                "metadata": metadata or {},
                "error": None
            }
            
            result = self.messages_collection.insert_one(message_doc)
            message_id = str(result.inserted_id)
            
            self.increment_message_count(chat_id)
            self.update_chat_timestamp(chat_id)
            
            logger.info(f"Created message: {message_id} in chat: {chat_id}")
            
            return MessageResponse(
                message_id=message_id,
                chat_id=message_doc["chat_id"],
                user_id=message_doc["user_id"],
                role=MessageRole(message_doc["role"]),
                content=message_doc["content"],
                status=MessageStatus(message_doc["status"]),
                created_at=message_doc["created_at"],
                processing_time_ms=message_doc.get("processing_time_ms"),
                metadata=message_doc.get("metadata"),
                error=message_doc.get("error")
            )
            
        except Exception as e:
            logger.error(f"Error creating message: {str(e)}")
            raise Exception(f"Failed to create message: {str(e)}")
    
    def get_message(self, message_id: str) -> Optional[MessageResponse]:
        """
        Get a message by ID.
        
        Args:
            message_id: The message identifier (ObjectId)
            
        Returns:
            MessageResponse: Message information, or None if not found
        """
        try:
            if not validate_object_id(message_id):
                logger.warning(f"Invalid message_id format: {message_id}")
                return None
            
            message_doc = self.messages_collection.find_one({"_id": ObjectId(message_id)})
            
            if not message_doc:
                return None
            
            return MessageResponse(
                message_id=str(message_doc["_id"]),
                chat_id=message_doc["chat_id"],
                user_id=message_doc["user_id"],
                role=MessageRole(message_doc["role"]),
                content=message_doc["content"],
                status=MessageStatus(message_doc["status"]),
                created_at=message_doc["created_at"],
                processing_time_ms=message_doc.get("processing_time_ms"),
                metadata=message_doc.get("metadata"),
                error=message_doc.get("error")
            )
            
        except Exception as e:
            logger.error(f"Error getting message: {str(e)}")
            return None

    def list_chat_messages(
        self,
        chat_id: str,
        page: int = 1,
        page_size: int = 50
    ) -> PaginatedResponse[MessageResponse]:
        """
        List all messages in a chat with pagination.
        Most recent messages first (reverse chronological order).
        
        Args:
            chat_id: The chat identifier
            page: Page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse[MessageResponse]: Paginated list of messages
        """
        try:
            total = self.messages_collection.count_documents({"chat_id": chat_id})
            
            pagination = calculate_pagination(total, page, page_size)
            skip = (page - 1) * page_size
            
            cursor = self.messages_collection.find(
                {"chat_id": chat_id}
            ).sort("created_at", DESCENDING).skip(skip).limit(page_size)
            
            items = []
            for message_doc in cursor:
                items.append(MessageResponse(
                    message_id=str(message_doc["_id"]),
                    chat_id=message_doc["chat_id"],
                    user_id=message_doc["user_id"],
                    role=MessageRole(message_doc["role"]),
                    content=message_doc["content"],
                    status=MessageStatus(message_doc["status"]),
                    created_at=message_doc["created_at"],
                    processing_time_ms=message_doc.get("processing_time_ms"),
                    metadata=message_doc.get("metadata"),
                    error=message_doc.get("error")
                ))
            
            return PaginatedResponse(
                items=items,
                total=pagination["total"],
                page=pagination["page"],
                page_size=pagination["page_size"],
                total_pages=pagination["total_pages"],
                has_more=pagination["has_more"]
            )
            
        except Exception as e:
            logger.error(f"Error listing chat messages: {str(e)}")
            raise Exception(f"Failed to list messages: {str(e)}")
    
    def update_message_status(
        self, 
        message_id: str,
        status: MessageStatus,
        content: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        error: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> None:
        """
        Update message status and optionally content.
        
        Args:
            message_id: The message identifier
            status: New status
            content: Updated content (for assistant messages)
            processing_time_ms: Processing time
            error: Error message if failed
            metadata: Additional metadata to update
        """
        try:
            update_data = {"status": status.value}
            
            if content is not None:
                update_data["content"] = content
            if processing_time_ms is not None:
                update_data["processing_time_ms"] = processing_time_ms
            if error is not None:
                update_data["error"] = error
            if metadata is not None:
                update_data["metadata"] = metadata
            
            self.messages_collection.update_one(
                {"_id": ObjectId(message_id)},
                {"$set": update_data}
            )
            
        except Exception as e:
            logger.error(f"Error updating message status: {str(e)}")
    
    # ========================================================================
    # Streaming Message Processing - DEPRECATED
    # ========================================================================
    # 
    # NOTE: stream_message() method removed (called deleted ReactAgent.chat_streaming)
    # 
    # Production streaming uses: api/streaming_store.py
    # - StreamingApiRouter.send_message() creates message + returns stream URL
    # - StreamingApiRouter.stream_message() serves SSE via agent.agent.astream()
    # - Includes: HITL interrupt detection, event persistence, background summarization
    # 
    # All streaming paths now unified under api/streaming_router.py + api/streaming_store.py