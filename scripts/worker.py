#!/usr/bin/env python3
"""
Background worker for processing agent tasks from MongoDB queue.

Features:
- Claims tasks from queue with lease-based locking
- Executes agent tasks in background
- Handles lease renewal for long-running tasks
- Graceful shutdown on SIGTERM
- Survives server restarts (tasks persist in MongoDB)

Usage:
    python scripts/worker.py

Environment:
    MONGODB_URL - MongoDB connection string
    WORKER_ID - Optional worker identifier (defaults to hostname-pid)
    WORKER_POLL_INTERVAL - Poll interval in seconds (default: 1.0)
    WORKER_LEASE_SECONDS - Task lease duration (default: 600)
"""

import asyncio
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from pymongo import MongoClient

from api.task_queue import TaskQueue
from api.store import ApiStore
from api.streaming.persistence import EventPersistence
from api.streaming_store import execute_agent_pure, execute_resume_pure

# Load environment
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BackgroundWorker:
    """
    Background worker for processing agent tasks.
    """
    
    def __init__(
        self,
        mongo_client: MongoClient,
        worker_id: str = None,
        poll_interval: float = 1.0,
        lease_seconds: int = 600,
        lease_renewal_interval: int = 60
    ):
        """
        Initialize worker.
        
        Args:
            mongo_client: MongoDB client instance
            worker_id: Unique worker identifier
            poll_interval: Seconds to wait between polling for tasks
            lease_seconds: Task lease duration in seconds
            lease_renewal_interval: Seconds between lease renewals
        """
        self.mongo_client = mongo_client
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.lease_renewal_interval = lease_renewal_interval
        
        # Initialize components
        self.task_queue = TaskQueue(mongo_client, db_name="org_1")
        self.store = ApiStore(mongo_client, db_name="org_1")
        self.event_persistence = EventPersistence(mongo_client, db_name="org_1")
        
        # Shutdown flag
        self.shutdown_requested = False
        self.current_task_id = None
        
        logger.info(f"Worker initialized: {self.worker_id}")
    
    def request_shutdown(self, signum=None, frame=None):
        """
        Request graceful shutdown.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        logger.info(f"Shutdown requested (signal: {signum})")
        self.shutdown_requested = True
    
    async def renew_lease_loop(self, task_id: str):
        """
        Background task to renew lease periodically.
        
        Args:
            task_id: Task identifier
        """
        try:
            while not self.shutdown_requested:
                await asyncio.sleep(self.lease_renewal_interval)
                
                # Renew lease
                renewed = self.task_queue.renew_lease(
                    task_id,
                    self.worker_id,
                    self.lease_seconds
                )
                
                if not renewed:
                    logger.warning(
                        f"Failed to renew lease for task {task_id} "
                        f"(task may have been reassigned)"
                    )
                    break
                
                logger.debug(f"Renewed lease for task {task_id}")
        
        except asyncio.CancelledError:
            logger.debug(f"Lease renewal cancelled for task {task_id}")
        except Exception as e:
            logger.error(f"Error in lease renewal loop for task {task_id}: {e}")
    
    async def execute_task(self, task: dict):
        """
        Execute a task (agent execution or resume).
        
        Args:
            task: Task document from queue
        """
        task_id = str(task["_id"])
        task_type = task["type"]
        message_id = task["message_id"]
        chat_id = task["chat_id"]
        payload = task["payload"]
        
        logger.info(
            f"Executing {task_type} task {task_id} for message {message_id} "
            f"(attempt {task['attempts']}/{task['max_attempts']})"
        )
        
        # Start lease renewal in background
        renewal_task = asyncio.create_task(self.renew_lease_loop(task_id))
        
        try:
            if task_type == "execute":
                # Execute agent
                await execute_agent_pure(
                    store=self.store,
                    event_persistence=self.event_persistence,
                    chat_id=chat_id,
                    message_id=message_id,
                    user_content=payload.get("content", ""),
                    metadata=payload.get("metadata", {})
                )
            
            elif task_type == "resume":
                # Resume interrupted agent
                from langgraph.types import Command
                
                thread_id = payload.get("thread_id")
                resume_command_data = payload.get("resume_command")
                
                if not thread_id or not resume_command_data:
                    raise ValueError("Resume task missing thread_id or resume_command")
                
                # Reconstruct Command object
                resume_command = Command(**resume_command_data)
                
                await execute_resume_pure(
                    store=self.store,
                    event_persistence=self.event_persistence,
                    chat_id=chat_id,
                    message_id=message_id,
                    thread_id=thread_id,
                    resume_command=resume_command,
                    metadata=payload.get("metadata", {})
                )
            
            else:
                raise ValueError(f"Unknown task type: {task_type}")
            
            # Mark task as completed
            self.task_queue.complete_task(task_id)
            
            logger.info(f"Task {task_id} completed successfully")
        
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            
            # Mark task as failed (will requeue if attempts remaining)
            self.task_queue.fail_task(task_id, str(e))
        
        finally:
            # Cancel lease renewal
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass
    
    async def run(self):
        """
        Main worker loop.
        
        Continuously polls for tasks and executes them.
        """
        logger.info(f"Worker {self.worker_id} starting...")
        logger.info(f"Poll interval: {self.poll_interval}s")
        logger.info(f"Lease duration: {self.lease_seconds}s")
        
        # Reset stale tasks on startup
        reset_count = self.task_queue.reset_stale_tasks()
        if reset_count > 0:
            logger.info(f"Recovered {reset_count} stale tasks on startup")
        
        while not self.shutdown_requested:
            try:
                # Claim a task
                task = self.task_queue.claim_task(
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds
                )
                
                if task:
                    self.current_task_id = str(task["_id"])
                    
                    # Execute task
                    await self.execute_task(task)
                    
                    self.current_task_id = None
                else:
                    # No tasks available, wait before polling again
                    await asyncio.sleep(self.poll_interval)
            
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.shutdown_requested = True
                break
            
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)
        
        logger.info(f"Worker {self.worker_id} shutting down...")
        
        # If currently processing a task, log it
        if self.current_task_id:
            logger.warning(
                f"Worker shutting down with task {self.current_task_id} in progress. "
                f"Task will be reclaimed by another worker when lease expires."
            )


async def main():
    """
    Main entry point for worker process.
    """
    # Get configuration from environment
    mongodb_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    worker_id = os.getenv("WORKER_ID")
    poll_interval = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))
    lease_seconds = int(os.getenv("WORKER_LEASE_SECONDS", "600"))
    
    # Connect to MongoDB
    try:
        mongo_client = MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping')
        logger.info(f"Connected to MongoDB: {mongodb_url}")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        sys.exit(1)
    
    # Create worker
    worker = BackgroundWorker(
        mongo_client=mongo_client,
        worker_id=worker_id,
        poll_interval=poll_interval,
        lease_seconds=lease_seconds
    )
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, worker.request_shutdown)
    signal.signal(signal.SIGINT, worker.request_shutdown)
    
    # Run worker
    try:
        await worker.run()
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Close MongoDB connection
        mongo_client.close()
        logger.info("MongoDB connection closed")
    
    logger.info("Worker stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker interrupted")
        sys.exit(0)

