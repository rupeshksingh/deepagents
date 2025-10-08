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
    generate_chat_id,
    generate_thread_id,
    calculate_pagination,
    validate_object_id,
    validate_uuid
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

        self.users_collection = self.db["proposal_assistant_users"]
        self.chats_collection = self.db["proposal_assistant_chat"]
        self.messages_collection = self.db["proposal_assistant_messages"]
        
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
            self.agent = ReactAgent(self.client, org_id=1)
            logger.info("ReactAgent instance created")
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
        
        Args:
            user_id: The user identifier
            request: Chat creation request
            
        Returns:
            ChatResponse: Created chat information
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            chat_id = generate_chat_id()
            
            title = request.title or f"Chat - {current_time.strftime('%Y-%m-%d %H:%M')}"
            
            chat_doc = {
                "chat_id": chat_id,
                "user_id": user_id,
                "title": title,
                "created_at": current_time,
                "updated_at": current_time,
                "message_count": 0
            }
            
            self.chats_collection.insert_one(chat_doc)
            logger.info(f"Created new chat: {chat_id} for user: {user_id}")
            
            self.update_user_activity(user_id)
            
            return ChatResponse(
                chat_id=chat_doc["chat_id"],
                user_id=chat_doc["user_id"],
                title=chat_doc["title"],
                created_at=chat_doc["created_at"],
                updated_at=chat_doc["updated_at"],
                message_count=chat_doc["message_count"]
            )
            
        except Exception as e:
            logger.error(f"Error creating chat: {str(e)}")
            raise Exception(f"Failed to create chat: {str(e)}")
    
    def get_chat(self, chat_id: str) -> Optional[ChatResponse]:
        """
        Get a chat by ID.
        
        Args:
            chat_id: The chat identifier
            
        Returns:
            ChatResponse: Chat information, or None if not found
        """
        try:
            if not validate_uuid(chat_id):
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
            chat_id: The chat identifier
            
        Returns:
            bool: True if deleted, False if not found
        """
        try:
            if not validate_uuid(chat_id):
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
            ).sort("created_at", ASCENDING).skip(skip).limit(page_size)
            
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
        error: Optional[str] = None
    ) -> None:
        """
        Update message status and optionally content.
        
        Args:
            message_id: The message identifier
            status: New status
            content: Updated content (for assistant messages)
            processing_time_ms: Processing time
            error: Error message if failed
        """
        try:
            update_data = {"status": status.value}
            
            if content is not None:
                update_data["content"] = content
            if processing_time_ms is not None:
                update_data["processing_time_ms"] = processing_time_ms
            if error is not None:
                update_data["error"] = error
            
            self.messages_collection.update_one(
                {"_id": ObjectId(message_id)},
                {"$set": update_data}
            )
            
        except Exception as e:
            logger.error(f"Error updating message status: {str(e)}")
    
    # ========================================================================
    # Streaming Message Processing
    # ========================================================================
    
    async def stream_message(
        self,
        chat_id: str,
        user_id: str,
        request: MessageCreateRequest
    ) -> AsyncGenerator[StreamChunkResponse, None]:
        """
        Process a user message and stream the assistant's response.
        
        Args:
            chat_id: The chat identifier
            user_id: The user identifier
            request: Message creation request
            
        Yields:
            StreamChunkResponse: Streaming chunks
        """
        try:
            user_message = self.create_message(
                chat_id=chat_id,
                user_id=user_id,
                role=MessageRole.USER,
                content=request.content,
                metadata=request.metadata
            )
            
            assistant_message = self.create_message(
                chat_id=chat_id,
                user_id=user_id,
                role=MessageRole.ASSISTANT,
                content="",
                metadata=request.metadata
            )
            
            self.update_message_status(
                assistant_message.message_id,
                MessageStatus.PROCESSING
            )
            
            yield StreamChunkResponse(
                message_id=assistant_message.message_id,
                chat_id=chat_id,
                chunk_type=StreamChunkType.START,
                status=MessageStatus.PROCESSING
            )
            
            agent = self._get_agent()
            thread_id = generate_thread_id(chat_id)
            
            full_response = ""
            start_time = datetime.now()
            
            try:
                async for chunk in agent.chat_streaming(
                    user_query=request.content,
                    thread_id=thread_id,
                    tender_id=request.metadata.get("tender_id") if request.metadata else None,
                user_id=user_id
                ):
                    if chunk["chunk_type"] == "content":
                        content = chunk.get("content", "")
                        full_response += content + " "
                        
                        yield StreamChunkResponse(
                            message_id=assistant_message.message_id,
                            chat_id=chat_id,
                            chunk_type=StreamChunkType.CONTENT,
                            content=content
                        )
                    
                    elif chunk["chunk_type"] == "end":
                        end_time = datetime.now()
                        processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
                        
                        final_response = chunk.get("total_response", full_response.strip())
                        
                        self.update_message_status(
                            assistant_message.message_id,
                            MessageStatus.COMPLETED,
                            content=final_response,
                            processing_time_ms=processing_time_ms
                        )
                        
                        yield StreamChunkResponse(
                            message_id=assistant_message.message_id,
                            chat_id=chat_id,
                            chunk_type=StreamChunkType.END,
                            status=MessageStatus.COMPLETED,
                            processing_time_ms=processing_time_ms
                        )
                    
                    elif chunk["chunk_type"] == "error":
                        error_msg = chunk.get("content", "Unknown error")
                        
                        self.update_message_status(
                            assistant_message.message_id,
                            MessageStatus.FAILED,
                            error=error_msg
                        )
                        
                        yield StreamChunkResponse(
                            message_id=assistant_message.message_id,
                            chat_id=chat_id,
                            chunk_type=StreamChunkType.ERROR,
                            status=MessageStatus.FAILED,
                            error=error_msg
                        )
                        return
            
            except Exception as e:
                error_msg = f"Agent processing error: {str(e)}"
                logger.error(error_msg)
                
                self.update_message_status(
                    assistant_message.message_id,
                    MessageStatus.FAILED,
                    error=error_msg
                )
                
                yield StreamChunkResponse(
                    message_id=assistant_message.message_id,
                    chat_id=chat_id,
                    chunk_type=StreamChunkType.ERROR,
                    status=MessageStatus.FAILED,
                    error=error_msg
                )
            
        except Exception as e:
            error_msg = f"Stream processing error: {str(e)}"
            logger.error(error_msg)
            
            yield StreamChunkResponse(
                message_id="",
                chat_id=chat_id,
                chunk_type=StreamChunkType.ERROR,
                status=MessageStatus.FAILED,
                error=error_msg
            )