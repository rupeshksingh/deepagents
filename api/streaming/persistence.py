"""
Event persistence to MongoDB.

Handles batch writes to separate message_events collection.
"""

import logging
from datetime import datetime, timezone
import os
import time
from uuid import uuid4
from typing import List, Optional
from pymongo import MongoClient, ASCENDING, ReturnDocument
from pymongo.collection import Collection

from api.streaming.events import StreamEvent

logger = logging.getLogger(__name__)


class EventPersistence:
    """
    Handles persistence of streaming events to MongoDB.
    
    Uses a separate 'message_events' collection to avoid 16MB document limit
    and improve write performance via batching.
    """
    
    def __init__(self, mongo_client: MongoClient, db_name: str = "org_1"):
        """
        Initialize persistence layer.
        
        Args:
            mongo_client: MongoDB client
            db_name: Database name
        """
        self.db = mongo_client[db_name]
        self.events_collection: Collection = self.db["message_events"]
        # Per-message atomic counters for sequencing
        self.counters_collection: Collection = self.db["message_counters"]
        
        # Create indexes for efficient querying
        self._ensure_indexes()
        
        logger.info(f"EventPersistence initialized with database: {db_name}")
    
    def _ensure_indexes(self) -> None:
        """Create indexes for the message_events collection."""
        try:
            # Compound index for querying events by message
            self.events_collection.create_index(
                [("message_id", ASCENDING), ("seq", ASCENDING)],
                name="message_id_seq",
                unique=True
            )
            
            # Index for chat-level queries
            self.events_collection.create_index(
                [("chat_id", ASCENDING), ("ts", ASCENDING)],
                name="chat_id_ts"
            )
            
            # Optional: TTL index for automatic cleanup (14 days)
            # Enable via env var MESSAGE_EVENTS_TTL_DAYS or MESSAGE_EVENTS_TTL_SECONDS
            ttl_seconds = None
            try:
                if os.getenv("MESSAGE_EVENTS_TTL_SECONDS"):
                    ttl_seconds = int(os.getenv("MESSAGE_EVENTS_TTL_SECONDS", "0"))
                elif os.getenv("MESSAGE_EVENTS_TTL_DAYS"):
                    days = int(os.getenv("MESSAGE_EVENTS_TTL_DAYS", "0"))
                    ttl_seconds = days * 24 * 60 * 60
            except Exception:
                ttl_seconds = None

            if ttl_seconds and ttl_seconds > 0:
                try:
                    self.events_collection.create_index(
                        "ts",
                        name="event_ttl",
                        expireAfterSeconds=ttl_seconds
                    )
                    logger.info(f"TTL index enabled on message_events: {ttl_seconds}s")
                except Exception as e:
                    logger.warning(f"Failed to create TTL index: {e}")
            
            logger.info("Message events indexes created successfully")
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
    
    def append_event(
        self,
        message_id: str,
        chat_id: str,
        event: StreamEvent,
        max_retries: int = 3
    ) -> bool:
        """
        Append a single event to MongoDB (for real-time persistence).
        
        Includes retry logic with exponential backoff for transient failures.
        
        Args:
            message_id: The message this event belongs to
            chat_id: The chat this message belongs to
            event: Event to append
            max_retries: Maximum number of retry attempts
            
        Returns:
            True if successful, False otherwise
        """
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # Allocate next sequence number atomically per message
                counter_doc = self.db["message_counters"].find_one_and_update(
                    {"_id": message_id},
                    {"$inc": {"next_seq": 1}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                seq = int(counter_doc.get("next_seq", 1)) - 1

                doc = event.model_dump(exclude_none=True)
                doc["message_id"] = message_id
                doc["chat_id"] = chat_id
                doc["seq"] = seq
                # Normalize event ID to support precise resume: {timestamp_ms}_{seq}_{rand}
                now_ms = int(time.time() * 1000)
                doc["id"] = f"{now_ms}_{seq:04d}_{uuid4().hex[:8]}"
                
                # Convert ts string to datetime for better querying
                if "ts" in doc:
                    try:
                        doc["ts"] = datetime.fromisoformat(doc["ts"].replace('Z', '+00:00'))
                    except Exception:
                        doc["ts"] = datetime.now(timezone.utc)
                
                self.events_collection.insert_one(doc)
                
                # Log retry success if this wasn't the first attempt
                if attempt > 0:
                    logger.info(
                        f"Successfully persisted event for message {message_id} "
                        f"after {attempt + 1} attempts"
                    )
                
                return True
                
            except Exception as e:
                last_exception = e
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 0.1s, 0.2s, 0.4s
                    sleep_time = 0.1 * (2 ** attempt)
                    logger.warning(
                        f"Failed to append event for message {message_id} "
                        f"(attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {sleep_time}s..."
                    )
                    time.sleep(sleep_time)
                else:
                    # Final attempt failed
                    logger.error(
                        f"Failed to append event for message {message_id} "
                        f"after {max_retries} attempts: {last_exception}"
                    )
        
        return False
    
    def batch_write_events(
        self,
        message_id: str,
        chat_id: str,
        events: List[StreamEvent]
    ) -> bool:
        """
        Write a batch of events to MongoDB.
        
        Args:
            message_id: The message these events belong to
            chat_id: The chat this message belongs to
            events: List of events to write
            
        Returns:
            True if successful, False otherwise
        """
        if not events:
            return True
        
        try:
            documents = []
            for event in events:
                # Allocate next sequence number atomically
                counter_doc = self.db["message_counters"].find_one_and_update(
                    {"_id": message_id},
                    {"$inc": {"next_seq": 1}},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
                seq = int(counter_doc.get("next_seq", 1)) - 1

                doc = event.model_dump(exclude_none=True)
                doc["message_id"] = message_id
                doc["chat_id"] = chat_id
                doc["seq"] = seq
                # Normalize id
                now_ms = int(time.time() * 1000)
                doc["id"] = f"{now_ms}_{seq:04d}_{uuid4().hex[:8]}"
                # Convert ts string to datetime for better querying
                if "ts" in doc:
                    try:
                        doc["ts"] = datetime.fromisoformat(doc["ts"].replace('Z', '+00:00'))
                    except Exception:
                        doc["ts"] = datetime.now(timezone.utc)
                documents.append(doc)

            if not documents:
                return True

            result = self.events_collection.insert_many(documents, ordered=False)
            
            logger.info(
                f"Batch wrote {len(result.inserted_ids)} events for "
                f"message {message_id}"
            )
            return True
            
        except Exception as e:
            logger.error(
                f"Error batch writing events for message {message_id}: {e}"
            )
            return False
    
    def get_events(
        self,
        message_id: str,
        since_id: Optional[str] = None,
        limit: int = 1000
    ) -> List[dict]:
        """
        Retrieve events for a message.
        
        Args:
            message_id: The message to retrieve events for
            since_id: Optional event ID to start from (for replay)
            limit: Maximum number of events to return
            
        Returns:
            List of event documents
        """
        try:
            query = {"message_id": message_id}
            
            # If since_id provided, only return events after it
            if since_id:
                # Extract sequence from event ID format: {timestamp_ms}_{seq}_{random}
                try:
                    seq_str = since_id.split("_")[1]
                    since_seq = int(seq_str)
                    query["seq"] = {"$gt": since_seq}
                except Exception:
                    logger.warning(f"Invalid since_id format: {since_id}")
            
            cursor = self.events_collection.find(query).sort("seq", ASCENDING).limit(limit)
            events = list(cursor)
            
            logger.info(
                f"Retrieved {len(events)} events for message {message_id}"
                f"{' (since ' + since_id + ')' if since_id else ''}"
            )
            
            return events
            
        except Exception as e:
            logger.error(f"Error retrieving events for message {message_id}: {e}")
            return []
    
    def get_event_count(self, message_id: str) -> int:
        """
        Get total count of events for a message.
        
        Args:
            message_id: The message to count events for
            
        Returns:
            Number of events
        """
        try:
            return self.events_collection.count_documents({"message_id": message_id})
        except Exception as e:
            logger.error(f"Error counting events for message {message_id}: {e}")
            return 0
    
    def delete_events(self, message_id: str) -> bool:
        """
        Delete all events for a message.
        
        Args:
            message_id: The message to delete events for
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.events_collection.delete_many({"message_id": message_id})
            logger.info(
                f"Deleted {result.deleted_count} events for message {message_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting events for message {message_id}: {e}")
            return False

