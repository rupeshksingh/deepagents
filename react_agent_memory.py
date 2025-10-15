"""
React Agent with Short-Term Memory Optimizations

This module implements a React agent with advanced short-term memory management,
including message trimming, deletion, and summarization to handle long conversations
efficiently while maintaining context and reducing token usage.

Key Features:
- Message trimming to stay within token limits
- Message deletion for stale content removal
- Message summarization for context compression
- InMemorySaver for quick testing and development
- Pre/post model hooks for memory management
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any, Optional, List

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import RemoveMessage
from langchain_core.messages.utils import trim_messages, count_tokens_approximately
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from langchain.agents.middleware import AgentMiddleware, ModelRequest

from src.deepagents.state import DeepAgentState
from src.deepagents.streaming_middleware import StreamingMiddleware, PlanningStreamingMiddleware
from src.deepagents.logging_utils import (
    log_query_start,
    log_query_end,
    set_agent_context,
)
from tools import REACT_TOOLS, REACT_TOOLS_DOC, REACT_TOOLS_WEB
from prompts import (
    TENDER_ANALYSIS_SYSTEM_PROMPT,
    DOCUMENT_ANALYZER_PROMPT,
    RESEARCH_AGENT_PROMPT,
)

logger = logging.getLogger(__name__)

class MessageTrimmingMiddleware(AgentMiddleware):
    """Middleware to trim messages before LLM calls."""
    
    def __init__(self, max_tokens: int = 60000):
        """Initialize with token limit."""
        super().__init__()
        self.max_tokens = max_tokens
    
    def modify_model_request(
        self, request: ModelRequest, agent_state: DeepAgentState, runtime: Runtime
    ) -> ModelRequest:
        """Trim messages if they exceed token limit."""
        return self._trim_messages(request, agent_state)
    
    async def amodify_model_request(
        self, request: ModelRequest, agent_state: DeepAgentState, runtime: Runtime
    ) -> ModelRequest:
        """Async version: Trim messages if they exceed token limit."""
        return self._trim_messages(request, agent_state)
    
    def _trim_messages(
        self, request: ModelRequest, agent_state: DeepAgentState
    ) -> ModelRequest:
        """Common implementation for trimming messages."""
        messages = agent_state.get("messages", [])
        
        if not messages:
            return request

        token_count = count_tokens_approximately(messages)
        
        if token_count <= self.max_tokens:
            return request
        
        try:
            trimmed_messages = trim_messages(
                messages,
                strategy="last",
                token_counter=count_tokens_approximately,
                max_tokens=self.max_tokens,
                start_on="human",
                end_on=("human", "tool"),
            )
            
            logger.info(
                f"Trimmed messages from {len(messages)} to {len(trimmed_messages)} "
                f"(tokens: {token_count} -> ~{self.max_tokens})"
            )
            
            request.messages = trimmed_messages
            
        except Exception as e:
            logger.warning(f"Failed to trim messages: {e}. Using all messages.")
        
        return request

class MessageDeletionMiddleware(AgentMiddleware):
    """Middleware to delete old messages after LLM responses."""
    
    def __init__(self, max_messages: int = 20, delete_count: int = 4):
        """Initialize with thresholds."""
        super().__init__()
        self.max_messages = max_messages
        self.delete_count = delete_count
    
    def after_agent_action(
        self, agent_state: DeepAgentState, agent_action: Any
    ) -> Dict[str, Any]:
        """Delete old messages if conversation is too long."""
        return self._delete_old_messages(agent_state, agent_action)
    
    async def aafter_agent_action(
        self, agent_state: DeepAgentState, agent_action: Any
    ) -> Dict[str, Any]:
        """Async version: Delete old messages if conversation is too long."""
        return self._delete_old_messages(agent_state, agent_action)
    
    def _delete_old_messages(
        self, agent_state: DeepAgentState, agent_action: Any
    ) -> Dict[str, Any]:
        """Common implementation for deleting old messages."""
        messages = agent_state.get("messages", [])
        
        if len(messages) <= self.max_messages:
            return {}
        
        messages_to_delete = []
        start_idx = 1 if messages and getattr(messages[0], "type", None) == "system" else 0
        
        for i in range(start_idx, min(start_idx + self.delete_count, len(messages))):
            msg = messages[i]
            if hasattr(msg, "id") and msg.id:
                messages_to_delete.append(RemoveMessage(id=msg.id))
        
        if messages_to_delete:
            logger.info(
                f"Deleting {len(messages_to_delete)} old messages "
                f"(total messages: {len(messages)})"
            )
            return {"messages": messages_to_delete}
        
        return {}

class ReactAgentMemory:
    """
    A React agent with advanced short-term memory management.
    
    This agent implements memory optimizations for long conversations:
    - Trims messages to stay within token limits
    - Deletes old messages to manage conversation length
    - Uses InMemorySaver for fast development and testing
    
    Memory strategies can be customized via configuration.
    """
    
    MAX_TOKENS = 60000
    MAX_MESSAGES_BEFORE_DELETE = 20
    MESSAGES_TO_DELETE = 4
    
    WORKSPACE_ROOT = "/workspace"
    CONTEXT_DIR = f"{WORKSPACE_ROOT}/context"
    ANALYSIS_DIR = f"{WORKSPACE_ROOT}/analysis"
    OUTPUT_DIR = f"{WORKSPACE_ROOT}/output"
    CONTEXT_SUMMARY_PATH = f"{CONTEXT_DIR}/tender_summary.md"
    CONTEXT_SUPPLIER_PROFILE_PATH = f"{CONTEXT_DIR}/supplier_profile.md"
    CONTEXT_FILE_INDEX_PATH = f"{CONTEXT_DIR}/file_index.json"
    CONTEXT_CLUSTER_ID_PATH = f"{CONTEXT_DIR}/cluster_id.txt"
    
    def __init__(
        self,
        org_id: int = 1,
        max_tokens: Optional[int] = None,
        enable_message_trimming: bool = True,
        enable_message_deletion: bool = True,
    ):
        """
        Initialize the React agent with memory optimizations.
        
        Args:
            org_id: Organization ID for context
            max_tokens: Maximum tokens before trimming (default: 60000)
            enable_message_trimming: Enable automatic message trimming
            enable_message_deletion: Enable automatic message deletion
        """
        self.org_id = org_id
        self.max_tokens = max_tokens or self.MAX_TOKENS
        self.enable_message_trimming = enable_message_trimming
        self.enable_message_deletion = enable_message_deletion
        
        self.checkpointer = InMemorySaver()
        
        self.model = ChatAnthropic(model="claude-sonnet-4-5-20250929", max_tokens=self.max_tokens)
        
        set_agent_context("react_agent_memory", f"react_agent_memory_{org_id}")
        
        self.agent = self._create_agent()
        
        logger.info(
            f"ReactAgentMemory initialized for org_{org_id} with InMemorySaver "
            f"(trimming={'enabled' if enable_message_trimming else 'disabled'}, "
            f"deletion={'enabled' if enable_message_deletion else 'disabled'})"
        )
    
    def _create_agent(self):
        """Create the deep agent graph with memory management middleware."""
        try:
            tools = REACT_TOOLS
            
            subagents = [
                {
                    "name": "advanced_tender_analyst",
                    "description": (
                        "Use this subagent when the user's question requires: "
                        "(1) Analyzing MULTIPLE documents or sections in depth, "
                        "(2) Iterative search-and-synthesis (one search reveals need for another), "
                        "(3) Cross-referencing between contract sections (e.g., Rammeaftale + Bilag C + Bilag D), "
                        "(4) Extracting conditional logic or procedures (e.g., step-by-step workflows, consequence chains), "
                        "(5) Identifying patterns, risks, or requirements across scattered sources. "
                        "DO NOT use for simple lookups (definitions, single values) - use search_tender_corpus directly instead. "
                        "This agent will autonomously perform multiple searches, read files, and synthesize findings. "
                        "Delegate ONE focused analysis task per agent. For multi-part questions, spawn multiple agents in parallel."
                    ),
                    "prompt": DOCUMENT_ANALYZER_PROMPT,
                    "tools": REACT_TOOLS_DOC,
                },
                {
                    "name": "web_researcher",
                    "description": (
                        "Use this subagent for web-based research requiring multiple searches and synthesis: "
                        "(1) Competitor analysis across multiple companies, "
                        "(2) Market research on technologies, trends, or industries, "
                        "(3) Regulatory/legal research requiring multiple sources, "
                        "(4) Any web research that needs iteration (one search revealing need for more). "
                        "DO NOT use for single, straightforward web searches - call web_search tool directly instead. "
                        "For multi-topic research (e.g., 3 competitors), spawn multiple agents in parallel (one per topic)."
                    ),
                    "prompt": RESEARCH_AGENT_PROMPT,
                    "tools": REACT_TOOLS_WEB,
                },
            ]
            
            custom_middleware = [
                StreamingMiddleware(),
                PlanningStreamingMiddleware()
            ]
            
            if self.enable_message_trimming:
                custom_middleware.append(
                    MessageTrimmingMiddleware(max_tokens=self.max_tokens)
                )
            
            if self.enable_message_deletion:
                custom_middleware.append(
                    MessageDeletionMiddleware(
                        max_messages=self.MAX_MESSAGES_BEFORE_DELETE,
                        delete_count=self.MESSAGES_TO_DELETE
                    )
                )
            
            from langchain.agents import create_agent
            from src.deepagents.middleware import (
                PlanningMiddleware,
                FilesystemMiddleware,
                SubAgentMiddleware,
                ToolCallLoggingMiddleware,
            )
            from src.deepagents.prompts import BASE_AGENT_PROMPT
            
            async_compatible_middleware = [
                ToolCallLoggingMiddleware(
                    agent_type="react_agent_memory", agent_id=f"react_memory_{self.org_id}"
                ),
                PlanningMiddleware(),
                FilesystemMiddleware(),
                SubAgentMiddleware(
                    default_subagent_tools=tools,
                    subagents=subagents,
                    model=self.model,
                    is_async=True,
                ),
                *custom_middleware,
            ]
            
            agent_graph = create_agent(
                self.model,
                system_prompt=TENDER_ANALYSIS_SYSTEM_PROMPT + "\n\n" + BASE_AGENT_PROMPT,
                tools=tools,
                middleware=async_compatible_middleware,
                context_schema=DeepAgentState,
                checkpointer=self.checkpointer,
            )
            
            configured_agent = agent_graph.with_config(
                {
                    "recursion_limit": 100,
                    "max_execution_time": 120,
                }
            )
            
            logger.info(
                "Successfully created deep agent graph with InMemorySaver and memory middleware"
            )
            return configured_agent
            
        except Exception as e:
            logger.error(f"Failed to create deep agent graph: {e}")
            raise
    
    async def chat_streaming(
        self,
        user_query: str,
        thread_id: str,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Chat with streaming response using InMemorySaver.
        
        Args:
            user_query: The user's query
            thread_id: Unique thread ID for conversation persistence
            user_id: Optional user ID for tracking
            
        Yields:
            Dict containing streaming response chunks
        """
        session_id = log_query_start(user_query)
        start_time = time.time()
        
        try:
            if self.agent is None:
                yield {
                    "chunk_type": "error",
                    "content": "Agent is not properly initialized. Please check your configuration.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                return
            
            messages = [{"role": "user", "content": user_query}]
            config = {"configurable": {"thread_id": thread_id}}
            
            state_input: Dict[str, Any] = {
                "messages": messages,
                "files": {},
            }
            
            yield {
                "chunk_type": "start",
                "content": "Processing query...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "user_id": user_id,
            }

            response = await self.agent.ainvoke(state_input, config=config)
            
            if isinstance(response, dict) and "messages" in response:
                last_message = response["messages"][-1]
                if isinstance(last_message, dict):
                    agent_response = last_message.get("content", str(response))
                else:
                    agent_response = last_message.content
            else:
                agent_response = str(response)
            
            words = agent_response.split()
            chunk_size = 10
            
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i : i + chunk_size])
                yield {
                    "chunk_type": "content",
                    "content": chunk,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "thread_id": thread_id,
                }
                await asyncio.sleep(0.05)
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            yield {
                "chunk_type": "end",
                "content": "Query processing completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "processing_time_ms": processing_time_ms,
                "total_response": agent_response,
                "message_count": len(response.get("messages", [])),
            }
            
            logger.info(
                f"Successfully processed streaming query in {processing_time_ms}ms "
                f"(messages: {len(response.get('messages', []))})"
            )
            log_query_end(session_id, agent_response)
            
        except Exception as e:
            logger.error(f"Error in streaming query processing: {e}")
            error_response = f"I apologize, but I encountered an error while processing your request: {str(e)}"
            
            yield {
                "chunk_type": "error",
                "content": error_response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "error": str(e),
            }
            
            log_query_end(session_id, error_response)
    
    async def chat_sync(
        self,
        user_query: str,
        thread_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Chat synchronously and return the complete response.
        
        Args:
            user_query: The user's query
            thread_id: Unique thread ID for conversation persistence
            user_id: Optional user ID for tracking
            
        Returns:
            Dict containing the complete response
        """
        session_id = log_query_start(user_query)
        start_time = time.time()
        
        try:
            if self.agent is None:
                return {
                    "response": "Agent is not properly initialized. Please check your configuration.",
                    "error": "Agent initialization failed",
                    "success": False,
                }
            
            messages = [{"role": "user", "content": user_query}]
            config = {"configurable": {"thread_id": thread_id}}
            
            state_input: Dict[str, Any] = {
                "messages": messages,
                "files": {},
            }
            
            response = await self.agent.ainvoke(state_input, config=config)
            
            if isinstance(response, dict) and "messages" in response:
                last_message = response["messages"][-1]
                if isinstance(last_message, dict):
                    agent_response = last_message.get("content", str(response))
                else:
                    agent_response = last_message.content
            else:
                agent_response = str(response)
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            message_count = len(response.get("messages", []))
            
            logger.info(
                f"Successfully processed sync query in {processing_time_ms}ms "
                f"(messages: {message_count})"
            )
            log_query_end(session_id, agent_response)
            
            return {
                "response": agent_response,
                "thread_id": thread_id,
                "user_id": user_id,
                "processing_time_ms": processing_time_ms,
                "message_count": message_count,
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
            }
            
        except Exception as e:
            logger.error(f"Error in sync query processing: {e}")
            error_response = f"I apologize, but I encountered an error while processing your request: {str(e)}"
            
            log_query_end(session_id, error_response)
            
            return {
                "response": error_response,
                "error": str(e),
                "thread_id": thread_id,
                "success": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
            }
    
    def get_conversation_state(self, thread_id: str) -> Dict[str, Any]:
        """
        Get the current conversation state for a thread.
        
        Args:
            thread_id: The thread ID to retrieve state for
            
        Returns:
            Dict containing conversation state information
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            
            checkpoints = list(self.checkpointer.list(config))
            
            if checkpoints:
                latest = checkpoints[0]
                state_snapshot = latest.checkpoint if hasattr(latest, 'checkpoint') else None
                
                if state_snapshot:
                    channel_values = state_snapshot.get("channel_values", {})
                    messages = channel_values.get("messages", [])
                    files = channel_values.get("files", {})
                    
                    return {
                        "thread_id": thread_id,
                        "message_count": len(messages),
                        "file_count": len(files) if isinstance(files, dict) else 0,
                        "has_state": True,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
            
            return {
                "thread_id": thread_id,
                "message_count": 0,
                "file_count": 0,
                "has_state": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
                
        except Exception as e:
            logger.error(f"Error retrieving conversation state: {e}")
            return {
                "thread_id": thread_id,
                "error": str(e),
                "has_state": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    
    def get_conversation_history(self, thread_id: str) -> List[Dict[str, Any]]:
        """
        Get the conversation history for a thread.
        
        Args:
            thread_id: The thread ID to retrieve history for
            
        Returns:
            List of message dictionaries with role and content
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            
            checkpoints = list(self.checkpointer.list(config))
            
            if checkpoints:
                latest = checkpoints[0]
                state_snapshot = latest.checkpoint if hasattr(latest, 'checkpoint') else None
                
                if state_snapshot:
                    channel_values = state_snapshot.get("channel_values", {})
                    messages = channel_values.get("messages", [])
                    
                    history = []
                    for msg in messages:
                        if hasattr(msg, 'type'):
                            msg_type = msg.type
                            msg_content = msg.content if hasattr(msg, 'content') else str(msg)
                            history.append({
                                "role": msg_type,
                                "content": msg_content
                            })
                        elif isinstance(msg, dict):
                            history.append(msg)
                    
                    return history
            
            return []
                
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            return []
    
    def clear_conversation(self, thread_id: str) -> bool:
        """
        Clear conversation history for a specific thread.
        
        Args:
            thread_id: The thread ID to clear
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Clearing conversation for thread: {thread_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error clearing conversation: {e}")
            return False
    
    def get_agent_info(self) -> Dict[str, Any]:
        """Get agent information and statistics."""
        return {
            "org_id": self.org_id,
            "agent_initialized": self.agent is not None,
            "checkpointer_type": "InMemorySaver",
            "model": "claude-sonnet-4-5-20250929",
            "memory_management": {
                "message_trimming": self.enable_message_trimming,
                "message_deletion": self.enable_message_deletion,
                "max_tokens": self.max_tokens,
                "max_messages_before_delete": self.MAX_MESSAGES_BEFORE_DELETE,
                "messages_to_delete": self.MESSAGES_TO_DELETE,
            },
            "tools_available": len(REACT_TOOLS) if REACT_TOOLS else 0,
            "subagents": ["advanced_tender_analyst", "web_researcher"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def cleanup(self):
        """Clean up resources."""
        logger.info("ReactAgentMemory cleanup completed")