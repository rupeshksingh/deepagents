from datetime import datetime, timezone
from typing import Any, Optional
import asyncio
import logging
from pymongo import MongoClient
from bson import ObjectId
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
    QueryStatus,
    ConversationQueryParams
)
from react_agent import TenderAnalysisAgent

logger = logging.getLogger(__name__)

class QueryStore:
    """Store class for managing query operations with MongoDB"""
    
    def __init__(self, client: MongoClient):
        self.client = client
        self.db = client["org_1"]
        self.queries_collection = self.db["proposal_assistant_queries"]
        self.conversations_collection = self.db["proposal_assistant_chat"]
        self.users_collection = self.db["proposal_assistant_users"]
        
        self.agents = {}
        
    def _get_agent(self, org_id: int = 1) -> TenderAnalysisAgent:
        """Get or create an agent instance for the organization"""
        if org_id not in self.agents:
            self.agents[org_id] = TenderAnalysisAgent(org_id=org_id)
        return self.agents[org_id]
    
    def _update_query(
        self, 
        query_id: str | ObjectId, 
        update_data: dict[str, Any], 
        return_document: bool = False
    ) -> Optional[dict[str, Any]]:
        """Update a query document"""
        if isinstance(query_id, str):
            query_id = ObjectId(query_id)
            
        update_data["last_modified"] = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if return_document:
            return self.queries_collection.find_one_and_update(
                {"_id": query_id}, 
                {"$set": update_data}, 
                return_document=True
            )
        else:
            self.queries_collection.update_one({"_id": query_id}, {"$set": update_data})
            return None
    
    async def create_conversation(self, conversation_request: ConversationCreateRequest, org_id: int = 1) -> ConversationResponse:
        """Create a new conversation"""
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            conversation_doc = {
                "name": conversation_request.name,
                "created_at": current_time,
                "org_id": org_id,
                "query_count": 0
            }
            
            result = self.conversations_collection.insert_one(conversation_doc)
            conversation_id = str(result.inserted_id)
            
            return ConversationResponse(
                id=conversation_id,
                name=conversation_request.name,
                created_at=current_time,
                query_count=0
            )
            
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            raise Exception(f"Failed to create conversation: {str(e)}")

    async def create_streaming_query(self, query_request: QueryCreateRequest, org_id: int = 1):
        """Create a streaming query with automatic conversation management"""
        try:
            conversation_id = query_request.conversation_id
            
            if query_request.create_new_conversation or not conversation_id:
                conversation_response = await self.create_conversation(
                    ConversationCreateRequest(name=f"Chat with {query_request.user_id or 'User'}"), 
                    org_id
                )
                conversation_id = conversation_response.id
            
            if not self.conversations_collection.find_one({"_id": ObjectId(conversation_id)}):
                raise Exception(f"Conversation {conversation_id} not found")
            
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            query_doc = {
                "conversation_id": conversation_id,
                "query_text": query_request.query_text,
                "tender_id": query_request.tender_id,
                "user_id": query_request.user_id,
                "status": QueryStatus.PENDING.value,
                "response_text": None,
                "error_message": None,
                "created_at": current_time,
                "completed_at": None,
                "org_id": org_id,
                "processing_started_at": None,
                "processing_time_ms": None
            }
            
            result = self.queries_collection.insert_one(query_doc)
            query_id = str(result.inserted_id)

            self.conversations_collection.update_one(
                {"_id": ObjectId(conversation_id)},
                {"$inc": {"query_count": 1}}
            )
            
            async for chunk in self._process_streaming_query(query_id, conversation_id, org_id):
                yield chunk
            
        except Exception as e:
            logger.error(f"Error creating streaming query: {str(e)}")
            raise Exception(f"Failed to create streaming query: {str(e)}")

    async def create_query(self, conversation_id: str, query_request: QueryCreateRequest, org_id: int = 1) -> QueryResponse:
        """Create a new query and start processing it asynchronously"""
        try:
            if not self.conversations_collection.find_one({"_id": ObjectId(conversation_id)}):
                raise Exception(f"Conversation {conversation_id} not found")
            
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            query_doc = {
                "conversation_id": conversation_id,
                "query_text": query_request.query_text,
                "tender_id": query_request.tender_id,
                "status": QueryStatus.PENDING.value,
                "response_text": None,
                "error_message": None,
                "created_at": current_time,
                "completed_at": None,
                "org_id": org_id,
                "processing_started_at": None,
                "processing_time_ms": None
            }
            
            result = self.queries_collection.insert_one(query_doc)
            query_id = str(result.inserted_id)

            self.conversations_collection.update_one(
                {"_id": ObjectId(conversation_id)},
                {"$inc": {"query_count": 1}}
            )

            asyncio.create_task(self._process_query_async(query_id, org_id))
            
            return QueryResponse(
                id=query_id,
                conversation_id=conversation_id,
                query_text=query_request.query_text,
                response_text=None,
                status=QueryStatus.PENDING,
                tender_id=query_request.tender_id,
                created_at=current_time,
                completed_at=None,
                error_message=None,
                processing_time_ms=None
            )
            
        except Exception as e:
            logger.error(f"Error creating query: {str(e)}")
            raise Exception(f"Failed to create query: {str(e)}")
    
    async def _process_query_async(self, query_id: str, org_id: int):
        """Process query asynchronously using the TenderAnalysisAgent"""
        try:
            self._update_query(query_id, {
                "status": QueryStatus.PROCESSING.value,
                "processing_started_at": datetime.now(timezone.utc).replace(tzinfo=None)
            })
            
            query_doc = self.queries_collection.find_one({"_id": ObjectId(query_id)})
            if not query_doc:
                logger.error(f"Query not found: {query_id}")
                return
            
            agent = self._get_agent(org_id)
            start_time = datetime.now()
            
            response = await agent.chat(
                user_query=query_doc["query_text"],
                tender_id=query_doc.get("tender_id")
            )
            
            end_time = datetime.now()
            processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
            
            self._update_query(query_id, {
                "status": QueryStatus.COMPLETED.value,
                "response_text": response,
                "completed_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "processing_time_ms": processing_time_ms
            })
            
            logger.info(f"Successfully processed query {query_id} in {processing_time_ms}ms")
            
        except Exception as e:
            logger.error(f"Error processing query {query_id}: {str(e)}")
            self._update_query(query_id, {
                "status": QueryStatus.FAILED.value,
                "error_message": str(e),
                "completed_at": datetime.now(timezone.utc).replace(tzinfo=None)
            })

    async def _process_streaming_query(self, query_id: str, conversation_id: str, org_id: int):
        """Process query with streaming response"""
        try:
            self._update_query(query_id, {
                "status": QueryStatus.PROCESSING.value,
                "processing_started_at": datetime.now(timezone.utc).replace(tzinfo=None)
            })
            
            yield StreamingQueryResponse(
                query_id=query_id,
                conversation_id=conversation_id,
                chunk_type="start",
                status=QueryStatus.PROCESSING,
                metadata={"message": "Processing started"}
            )
            
            query_doc = self.queries_collection.find_one({"_id": ObjectId(query_id)})
            if not query_doc:
                logger.error(f"Query not found: {query_id}")
                yield StreamingQueryResponse(
                    query_id=query_id,
                    conversation_id=conversation_id,
                    chunk_type="error",
                    status=QueryStatus.FAILED,
                    content="Query not found"
                )
                return
            
            agent = self._get_agent(org_id)
            start_time = datetime.now()
            
            response = await agent.chat(
                user_query=query_doc["query_text"],
                tender_id=query_doc.get("tender_id")
            )
            
            end_time = datetime.now()
            processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
            
            words = response.split()
            chunk_size = 10
            
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                yield StreamingQueryResponse(
                    query_id=query_id,
                    conversation_id=conversation_id,
                    chunk_type="content",
                    content=chunk,
                    status=QueryStatus.PROCESSING
                )
                await asyncio.sleep(0.1)
            
            self._update_query(query_id, {
                "status": QueryStatus.COMPLETED.value,
                "response_text": response,
                "completed_at": datetime.now(timezone.utc).replace(tzinfo=None),
                "processing_time_ms": processing_time_ms
            })
            
            yield StreamingQueryResponse(
                query_id=query_id,
                conversation_id=conversation_id,
                chunk_type="end",
                status=QueryStatus.COMPLETED,
                metadata={"processing_time_ms": processing_time_ms}
            )
            
            logger.info(f"Successfully processed streaming query {query_id} in {processing_time_ms}ms")
            
        except Exception as e:
            logger.error(f"Error processing streaming query {query_id}: {str(e)}")
            self._update_query(query_id, {
                "status": QueryStatus.FAILED.value,
                "error_message": str(e),
                "completed_at": datetime.now(timezone.utc).replace(tzinfo=None)
            })
            
            yield StreamingQueryResponse(
                query_id=query_id,
                conversation_id=conversation_id,
                chunk_type="error",
                status=QueryStatus.FAILED,
                content=str(e)
            )
    
    def get_query_by_id(self, query_id: str) -> Optional[QueryResponse]:
        """Get a single query by ID"""
        try:
            query_doc = self.queries_collection.find_one({"_id": ObjectId(query_id)})
            if not query_doc:
                return None
            
            return self._convert_to_query_response(query_doc)
            
        except Exception as e:
            logger.error(f"Error getting query {query_id}: {str(e)}")
            return None

    def get_conversation_by_id(self, conversation_id: str) -> Optional[ConversationResponse]:
        """Get a single conversation by ID"""
        try:
            conversation_doc = self.conversations_collection.find_one({"_id": ObjectId(conversation_id)})
            if not conversation_doc:
                return None
            
            return ConversationResponse(
                id=str(conversation_doc["_id"]),
                name=conversation_doc.get("name"),
                created_at=conversation_doc["created_at"],
                query_count=conversation_doc.get("query_count", 0)
            )
            
        except Exception as e:
            logger.error(f"Error getting conversation {conversation_id}: {str(e)}")
            return None

    def get_conversations(self, page: int = 1, page_size: int = 50) -> PaginatedConversationResponse:
        """Get all conversations with pagination"""
        try:
            total_count = self.conversations_collection.count_documents({})
            total_pages = (total_count + page_size - 1) // page_size
            
            skip = (page - 1) * page_size
            cursor = self.conversations_collection.find({}).sort("created_at", -1).skip(skip).limit(page_size)
            docs = list(cursor)
            
            items = []
            for doc in docs:
                items.append(ConversationResponse(
                    id=str(doc["_id"]),
                    name=doc.get("name"),
                    created_at=doc["created_at"],
                    query_count=doc.get("query_count", 0)
                ))
            
            return PaginatedConversationResponse(
                items=items,
                total=total_count,
                page=page,
                page_size=page_size,
                total_pages=total_pages
            )
            
        except Exception as e:
            logger.error(f"Error getting conversations: {str(e)}")
            raise Exception(f"Failed to get conversations: {str(e)}")
    
    def get_conversation_queries(
        self, 
        conversation_id: str,
        params: ConversationQueryParams
    ) -> PaginatedQueryResponse:
        """Get all queries for a conversation with pagination"""
        try:
            query_filter = {"conversation_id": conversation_id}
            
            if params.status:
                query_filter["status"] = params.status.value
                
            if params.tender_id:
                query_filter["tender_id"] = params.tender_id
            
            total_count = self.queries_collection.count_documents(query_filter)
            total_pages = (total_count + params.page_size - 1) // params.page_size
            
            skip = (params.page - 1) * params.page_size
            cursor = self.queries_collection.find(query_filter).sort("created_at", -1).skip(skip).limit(params.page_size)
            docs = list(cursor)
            
            items = [self._convert_to_query_response(doc) for doc in docs]
            
            return PaginatedQueryResponse(
                items=items,
                total=total_count,
                page=params.page,
                page_size=params.page_size,
                total_pages=total_pages,
                conversation_id=conversation_id
            )
            
        except Exception as e:
            logger.error(f"Error getting conversation queries: {str(e)}")
            raise Exception(f"Failed to get conversation queries: {str(e)}")
    
    def get_user_queries(self, user_id: str, params: UserQueryParams) -> PaginatedUserQueryResponse:
        """Get all queries for a specific user with pagination and filtering"""
        try:
            query_filter = {"user_id": user_id}
            
            if params.status:
                query_filter["status"] = params.status.value
                
            if params.tender_id:
                query_filter["tender_id"] = params.tender_id
                
            if params.conversation_id:
                query_filter["conversation_id"] = params.conversation_id
            
            total_count = self.queries_collection.count_documents(query_filter)
            total_pages = (total_count + params.page_size - 1) // params.page_size
            
            skip = (params.page - 1) * params.page_size
            cursor = self.queries_collection.find(query_filter).sort("created_at", -1).skip(skip).limit(params.page_size)
            docs = list(cursor)
            
            items = [self._convert_to_query_response(doc) for doc in docs]
            
            return PaginatedUserQueryResponse(
                items=items,
                total=total_count,
                page=params.page,
                page_size=params.page_size,
                total_pages=total_pages,
                user_id=user_id
            )
            
        except Exception as e:
            logger.error(f"Error getting user queries: {str(e)}")
            raise Exception(f"Failed to get user queries: {str(e)}")

    def _convert_to_query_response(self, doc: dict) -> QueryResponse:
        """Convert MongoDB document to QueryResponse"""
        return QueryResponse(
            id=str(doc["_id"]),
            conversation_id=doc["conversation_id"],
            query_text=doc["query_text"],
            response_text=doc.get("response_text"),
            status=QueryStatus(doc["status"]),
            tender_id=doc.get("tender_id"),
            user_id=doc.get("user_id"),
            created_at=doc["created_at"],
            completed_at=doc.get("completed_at"),
            error_message=doc.get("error_message"),
            processing_time_ms=doc.get("processing_time_ms")
        )
    
    def get_query_stats(self, conversation_id: Optional[str] = None) -> dict[str, Any]:
        """Get query statistics"""
        try:
            filter_query = {}
            if conversation_id:
                filter_query["conversation_id"] = conversation_id
            
            pipeline = [
                {"$match": filter_query},
                {"$group": {
                    "_id": "$status",
                    "count": {"$sum": 1}
                }}
            ]
            
            stats = {}
            for result in self.queries_collection.aggregate(pipeline):
                stats[result["_id"]] = result["count"]
            
            total_queries = sum(stats.values())
            
            return {
                "total_queries": total_queries,
                "status_breakdown": stats,
                "conversation_id": conversation_id
            }
            
        except Exception as e:
            logger.error(f"Error getting query stats: {str(e)}")
            return {"error": str(e)}
