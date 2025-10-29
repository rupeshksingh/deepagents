"""
MongoDB-backed task queue for durable background agent execution.

Enables:
- Tasks survive server restart (lease-based reclaim)
- No in-memory state (stateless workers)
- Horizontal scaling (multiple workers)
- Simple monitoring via DB queries
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from pymongo import MongoClient, ASCENDING, ReturnDocument
from pymongo.collection import Collection
from bson import ObjectId

logger = logging.getLogger(__name__)


class TaskQueue:
    """
    MongoDB-backed task queue for background agent execution.
    
    Schema:
        {
            "_id": ObjectId,
            "type": "execute" | "resume",
            "chat_id": str,
            "message_id": str,
            "payload": {
                "content": str,
                "metadata": dict,
                "thread_id": str,  # for resume
                "resume_command": dict  # for resume
            },
            "status": "queued" | "running" | "completed" | "failed",
            "lease_until": datetime | None,
            "attempts": int,
            "max_attempts": int,
            "error": str | None,
            "created_at": datetime,
            "updated_at": datetime,
            "worker_id": str | None
        }
    """
    
    def __init__(self, client: MongoClient, db_name: str = "org_1"):
        """
        Initialize task queue.
        
        Args:
            client: MongoDB client instance
            db_name: Database name
        """
        self.client = client
        self.db = client[db_name]
        self.tasks_collection: Collection = self.db["pa_tasks"]
        
        self._setup_indexes()
        
        logger.info(f"TaskQueue initialized with database: {db_name}")
    
    def _setup_indexes(self):
        """Create necessary indexes for performance."""
        try:
            # Index for fast message_id lookup
            self.tasks_collection.create_index("message_id", unique=True)
            
            # Index for claiming tasks (status + lease_until)
            self.tasks_collection.create_index([
                ("status", ASCENDING),
                ("lease_until", ASCENDING)
            ])
            
            # Index for chat-based queries
            self.tasks_collection.create_index("chat_id")
            
            logger.info("Task queue indexes created successfully")
        except Exception as e:
            logger.error(f"Error creating task queue indexes: {e}")
    
    def enqueue_task(
        self,
        task_type: str,
        chat_id: str,
        message_id: str,
        payload: Dict[str, Any],
        max_attempts: int = 3
    ) -> str:
        """
        Enqueue a new task.
        
        Args:
            task_type: "execute" or "resume"
            chat_id: Chat identifier
            message_id: Message identifier
            payload: Task payload (content, metadata, etc.)
            max_attempts: Maximum retry attempts
            
        Returns:
            str: Task ID (ObjectId string)
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            task_doc = {
                "type": task_type,
                "chat_id": chat_id,
                "message_id": message_id,
                "payload": payload,
                "status": "queued",
                "lease_until": None,
                "attempts": 0,
                "max_attempts": max_attempts,
                "error": None,
                "created_at": current_time,
                "updated_at": current_time,
                "worker_id": None
            }
            
            result = self.tasks_collection.insert_one(task_doc)
            task_id = str(result.inserted_id)
            
            logger.info(
                f"Enqueued {task_type} task {task_id} for message {message_id}"
            )
            
            return task_id
            
        except Exception as e:
            logger.error(f"Error enqueuing task for message {message_id}: {e}")
            raise
    
    def claim_task(
        self,
        worker_id: str,
        lease_seconds: int = 600
    ) -> Optional[Dict[str, Any]]:
        """
        Claim a task for execution (atomic operation).
        
        Claims tasks that are:
        - queued (never started)
        - running but lease expired (worker died)
        
        Args:
            worker_id: Unique worker identifier
            lease_seconds: Lease duration in seconds
            
        Returns:
            Task document if claimed, None if no tasks available
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            lease_until = current_time + timedelta(seconds=lease_seconds)
            
            # Find and claim a task atomically
            # Note: We check attempts < max_attempts in application logic since
            # MongoDB find queries don't support field-to-field comparisons
            task = self.tasks_collection.find_one_and_update(
                {
                    "$or": [
                        # Queued tasks
                        {"status": "queued"},
                        # Running tasks with expired lease
                        {
                            "status": "running",
                            "lease_until": {"$lt": current_time}
                        }
                    ],
                    "$expr": {"$lt": ["$attempts", "$max_attempts"]}  # Field-to-field comparison
                },
                {
                    "$set": {
                        "status": "running",
                        "lease_until": lease_until,
                        "worker_id": worker_id,
                        "updated_at": current_time
                    },
                    "$inc": {"attempts": 1}
                },
                return_document=ReturnDocument.AFTER,
                sort=[("created_at", ASCENDING)]  # FIFO order
            )
            
            if task:
                logger.info(
                    f"Worker {worker_id} claimed task {task['_id']} "
                    f"(message {task['message_id']}, attempt {task['attempts']})"
                )
            
            return task
            
        except Exception as e:
            logger.error(f"Error claiming task for worker {worker_id}: {e}")
            return None
    
    def renew_lease(
        self,
        task_id: str,
        worker_id: str,
        lease_seconds: int = 600
    ) -> bool:
        """
        Renew lease for a running task.
        
        Args:
            task_id: Task identifier
            worker_id: Worker identifier (must match)
            lease_seconds: New lease duration
            
        Returns:
            True if renewed, False otherwise
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            lease_until = current_time + timedelta(seconds=lease_seconds)
            
            result = self.tasks_collection.update_one(
                {
                    "_id": ObjectId(task_id),
                    "worker_id": worker_id,
                    "status": "running"
                },
                {
                    "$set": {
                        "lease_until": lease_until,
                        "updated_at": current_time
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.debug(f"Renewed lease for task {task_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error renewing lease for task {task_id}: {e}")
            return False
    
    def complete_task(self, task_id: str) -> bool:
        """
        Mark task as completed.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if updated, False otherwise
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            result = self.tasks_collection.update_one(
                {"_id": ObjectId(task_id)},
                {
                    "$set": {
                        "status": "completed",
                        "lease_until": None,
                        "updated_at": current_time
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Task {task_id} marked as completed")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}")
            return False
    
    def fail_task(self, task_id: str, error: str) -> bool:
        """
        Mark task as failed or requeue for retry.
        
        Args:
            task_id: Task identifier
            error: Error message
            
        Returns:
            True if updated, False otherwise
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # Get current task to check attempts
            task = self.tasks_collection.find_one({"_id": ObjectId(task_id)})
            if not task:
                return False
            
            # If max attempts reached, mark as failed permanently
            if task["attempts"] >= task["max_attempts"]:
                result = self.tasks_collection.update_one(
                    {"_id": ObjectId(task_id)},
                    {
                        "$set": {
                            "status": "failed",
                            "error": error,
                            "lease_until": None,
                            "updated_at": current_time
                        }
                    }
                )
                logger.error(
                    f"Task {task_id} failed permanently after {task['attempts']} attempts: {error}"
                )
            else:
                # Requeue for retry
                result = self.tasks_collection.update_one(
                    {"_id": ObjectId(task_id)},
                    {
                        "$set": {
                            "status": "queued",
                            "error": error,
                            "lease_until": None,
                            "worker_id": None,
                            "updated_at": current_time
                        }
                    }
                )
                logger.warning(
                    f"Task {task_id} requeued for retry "
                    f"(attempt {task['attempts']}/{task['max_attempts']}): {error}"
                )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error failing task {task_id}: {e}")
            return False
    
    def get_task_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task by message ID.
        
        Args:
            message_id: Message identifier
            
        Returns:
            Task document if found, None otherwise
        """
        try:
            task = self.tasks_collection.find_one({"message_id": message_id})
            return task
        except Exception as e:
            logger.error(f"Error getting task for message {message_id}: {e}")
            return None
    
    def get_task_status(self, message_id: str) -> Optional[str]:
        """
        Get task status by message ID.
        
        Args:
            message_id: Message identifier
            
        Returns:
            Status string or None if not found
        """
        task = self.get_task_by_message_id(message_id)
        return task["status"] if task else None
    
    def list_tasks_by_status(
        self,
        status: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List tasks by status.
        
        Args:
            status: Task status filter
            limit: Maximum number of tasks to return
            
        Returns:
            List of task documents
        """
        try:
            tasks = list(
                self.tasks_collection.find({"status": status})
                .sort("created_at", ASCENDING)
                .limit(limit)
            )
            return tasks
        except Exception as e:
            logger.error(f"Error listing tasks by status {status}: {e}")
            return []
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get task queue metrics.
        
        Returns:
            Dict with task counts by status
        """
        try:
            pipeline = [
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            results = list(self.tasks_collection.aggregate(pipeline))
            
            metrics = {
                "queued": 0,
                "running": 0,
                "completed": 0,
                "failed": 0
            }
            
            for result in results:
                status = result["_id"]
                count = result["count"]
                if status in metrics:
                    metrics[status] = count
            
            metrics["total"] = sum(metrics.values())
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error getting task metrics: {e}")
            return {
                "queued": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "total": 0
            }
    
    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed/failed tasks.
        
        Args:
            max_age_hours: Maximum age in hours before cleanup
            
        Returns:
            Number of tasks deleted
        """
        try:
            cutoff_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=max_age_hours)
            
            result = self.tasks_collection.delete_many({
                "status": {"$in": ["completed", "failed"]},
                "updated_at": {"$lt": cutoff_time}
            })
            
            if result.deleted_count > 0:
                logger.info(f"Cleaned up {result.deleted_count} old tasks")
            
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old tasks: {e}")
            return 0
    
    def reset_stale_tasks(self) -> int:
        """
        Reset tasks with expired leases to queued state.
        Called on startup to recover from worker crashes.
        
        Returns:
            Number of tasks reset
        """
        try:
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            
            result = self.tasks_collection.update_many(
                {
                    "status": "running",
                    "lease_until": {"$lt": current_time}
                },
                {
                    "$set": {
                        "status": "queued",
                        "lease_until": None,
                        "worker_id": None,
                        "updated_at": current_time
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(
                    f"Reset {result.modified_count} stale tasks to queued state "
                    f"(recovered from worker crashes)"
                )
            
            return result.modified_count
            
        except Exception as e:
            logger.error(f"Error resetting stale tasks: {e}")
            return 0


# Global task queue instance
_task_queue: Optional[TaskQueue] = None


def get_task_queue(client: MongoClient = None, db_name: str = "org_1") -> TaskQueue:
    """
    Get the global task queue instance.
    
    Args:
        client: MongoDB client (required on first call)
        db_name: Database name
        
    Returns:
        TaskQueue singleton
    """
    global _task_queue
    if _task_queue is None:
        if client is None:
            raise RuntimeError("MongoDB client required to initialize TaskQueue")
        _task_queue = TaskQueue(client, db_name)
    return _task_queue

