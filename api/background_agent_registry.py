"""
Background Agent Registry - Manages independently running agent tasks.

Enables:
- Multiple agents running simultaneously
- Multiple streams watching same agent
- Agents continue regardless of stream connections
- User can switch between chats and see live progress
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """Tracks a running agent task."""
    message_id: str
    chat_id: str
    task: asyncio.Task
    started_at: datetime
    watchers: Set[str] = field(default_factory=set)  # Set of watcher IDs
    completed: bool = False
    error: Optional[str] = None


class BackgroundAgentRegistry:
    """
    Registry for background agent tasks.
    
    Manages agent lifecycle:
    - Start agent as background task on POST
    - Track running agents
    - Allow multiple streams to watch same agent
    - Clean up completed agents
    """
    
    def __init__(self):
        """Initialize the registry."""
        self._tasks: Dict[str, AgentTask] = {}
        self._lock = asyncio.Lock()
    
    async def start_agent(
        self,
        message_id: str,
        chat_id: str,
        agent_coro
    ) -> AgentTask:
        """
        Start an agent as a background task.
        
        Args:
            message_id: Message ID
            chat_id: Chat ID
            agent_coro: Agent coroutine to execute
            
        Returns:
            AgentTask tracking the execution
        """
        async with self._lock:
            # Check if already running
            if message_id in self._tasks:
                logger.warning(f"Agent {message_id} already running")
                return self._tasks[message_id]
            
            # Create background task
            task = asyncio.create_task(
                self._run_agent_wrapper(message_id, agent_coro)
            )
            
            agent_task = AgentTask(
                message_id=message_id,
                chat_id=chat_id,
                task=task,
                started_at=datetime.now(timezone.utc)
            )
            
            self._tasks[message_id] = agent_task
            
            logger.info(f"Started background agent for message {message_id}")
            return agent_task
    
    async def _run_agent_wrapper(self, message_id: str, agent_coro):
        """
        Wrapper to catch errors and mark completion.
        
        Uses asyncio.shield() to protect agent from external cancellation.
        Even if a watcher disconnects, the agent continues running.
        
        Args:
            message_id: Message ID
            agent_coro: Agent coroutine
        """
        try:
            # Shield agent from cancellation
            # This prevents client disconnects from killing the agent
            await asyncio.shield(agent_coro)
            
            async with self._lock:
                if message_id in self._tasks:
                    self._tasks[message_id].completed = True
                    logger.info(f"Agent {message_id} completed successfully")
                    
        except asyncio.CancelledError:
            # Shield was breached (rare - only happens if task is explicitly cancelled)
            logger.warning(f"Agent {message_id} was force-cancelled (shield breached)")
            async with self._lock:
                if message_id in self._tasks:
                    self._tasks[message_id].completed = True
                    self._tasks[message_id].error = "Task was cancelled"
            # Don't re-raise - mark as completed and exit gracefully
            
        except Exception as e:
            # Agent execution error - log but don't crash registry
            logger.error(f"Agent {message_id} failed: {e}", exc_info=True)
            async with self._lock:
                if message_id in self._tasks:
                    self._tasks[message_id].completed = True
                    self._tasks[message_id].error = str(e)
        
        finally:
            # Always ensure task is marked as done
            async with self._lock:
                if message_id in self._tasks and not self._tasks[message_id].completed:
                    self._tasks[message_id].completed = True
                    logger.warning(f"Agent {message_id} marked completed in finally block")
    
    async def get_task(self, message_id: str) -> Optional[AgentTask]:
        """
        Get agent task by message ID.
        
        Args:
            message_id: Message ID
            
        Returns:
            AgentTask if exists, None otherwise
        """
        async with self._lock:
            return self._tasks.get(message_id)
    
    async def is_running(self, message_id: str) -> bool:
        """
        Check if agent is currently running.
        
        Args:
            message_id: Message ID
            
        Returns:
            True if running, False otherwise
        """
        async with self._lock:
            task = self._tasks.get(message_id)
            if not task:
                return False
            return not task.completed
    
    async def register_watcher(self, message_id: str, watcher_id: str):
        """
        Register a stream watching this agent.
        
        Args:
            message_id: Message ID
            watcher_id: Unique watcher identifier
        """
        async with self._lock:
            if message_id in self._tasks:
                self._tasks[message_id].watchers.add(watcher_id)
                logger.info(f"Watcher {watcher_id} registered for agent {message_id}")
    
    async def unregister_watcher(self, message_id: str, watcher_id: str):
        """
        Unregister a stream that was watching this agent.
        
        Args:
            message_id: Message ID
            watcher_id: Unique watcher identifier
        """
        async with self._lock:
            if message_id in self._tasks:
                self._tasks[message_id].watchers.discard(watcher_id)
                logger.info(f"Watcher {watcher_id} unregistered from agent {message_id}")
                
                # Clean up if completed and no watchers
                task = self._tasks[message_id]
                if task.completed and len(task.watchers) == 0:
                    logger.info(f"Cleaning up completed agent {message_id} (no watchers)")
                    del self._tasks[message_id]
    
    async def get_active_count(self) -> int:
        """
        Get count of actively running agents.
        
        Returns:
            Number of running agents
        """
        async with self._lock:
            return sum(1 for t in self._tasks.values() if not t.completed)
    
    async def list_running(self, chat_id: Optional[str] = None) -> list[AgentTask]:
        """
        List running agents, optionally filtered by chat.
        
        Args:
            chat_id: Optional chat ID filter
            
        Returns:
            List of running AgentTask objects
        """
        async with self._lock:
            tasks = [
                t for t in self._tasks.values()
                if not t.completed
            ]
            
            if chat_id:
                tasks = [t for t in tasks if t.chat_id == chat_id]
            
            return tasks
    
    async def cleanup_old_tasks(self, max_age_hours: int = 24):
        """
        Clean up old completed tasks.
        
        Args:
            max_age_hours: Maximum age in hours before cleanup
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            to_remove = []
            
            for message_id, task in self._tasks.items():
                if task.completed and len(task.watchers) == 0:
                    age_hours = (now - task.started_at).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        to_remove.append(message_id)
            
            for message_id in to_remove:
                logger.info(f"Cleaning up old task {message_id}")
                del self._tasks[message_id]
            
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} old tasks")


# Global registry instance
_registry: Optional[BackgroundAgentRegistry] = None


def get_agent_registry() -> BackgroundAgentRegistry:
    """
    Get the global agent registry instance.
    
    Returns:
        BackgroundAgentRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = BackgroundAgentRegistry()
    return _registry

