"""
React Agent for Proposal Assistant

A clean implementation of the React agent with streaming responses,
MongoDB checkpointer integration, and comprehensive tool support.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, Any, Optional, List

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from src.deepagents.graph import async_create_deep_agent
from src.deepagents.state import DeepAgentState
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
from tool_utils import (
    get_proposal_summary,
    get_proposal_files_summary,
)

logger = logging.getLogger(__name__)


class ReactAgent:
    """
    A React agent for tender analysis with MongoDB persistence and streaming support.

    This agent provides intelligent analysis of tender documents, maintains conversation
    context, and uses multi-agent architecture for specialized tasks with MongoDB-backed
    persistence for long context memory.
    """

    def __init__(self, mongo_client: MongoClient, org_id: int = 1):
        self.mongo_client = mongo_client
        self.org_id = org_id
        self.db_name = f"org_{org_id}"

        self.checkpointer = MongoDBSaver(
            client=mongo_client,
            db_name=self.db_name,
        )

        self.model = ChatAnthropic(model="claude-sonnet-4-5-20250929")

        set_agent_context("react_agent", f"react_agent_{org_id}")

        self.agent = self._create_agent()

        logger.info(f"ReactAgent initialized for org_{org_id}")

    # Workspace constants (virtual filesystem paths)
    WORKSPACE_ROOT = "/workspace"
    CONTEXT_DIR = f"{WORKSPACE_ROOT}/context"
    ANALYSIS_DIR = f"{WORKSPACE_ROOT}/analysis"
    OUTPUT_DIR = f"{WORKSPACE_ROOT}/output"
    CONTEXT_SUMMARY_PATH = f"{CONTEXT_DIR}/tender_summary.md"
    CONTEXT_SUPPLIER_PROFILE_PATH = f"{CONTEXT_DIR}/supplier_profile.md"
    CONTEXT_FILE_INDEX_PATH = f"{CONTEXT_DIR}/file_index.json"
    CONTEXT_CLUSTER_ID_PATH = f"{CONTEXT_DIR}/cluster_id.txt"

    def _create_agent(self):
        """Create the deep agent graph with custom tools and subagents."""
        try:
            tools = REACT_TOOLS

            subagents = [
                {
                    "name": "document-analyzer",
                    "description": (
                        "Advanced tender analyst for iterative, deep analysis across one or more files. "
                        "Use when a single RAG lookup is insufficient; expects synthesized findings with citations."
                    ),
                    "prompt": DOCUMENT_ANALYZER_PROMPT,
                    "tools": REACT_TOOLS_DOC,
                },
                {
                    "name": "web-researcher",
                    "description": (
                        "EU/Danish-focused web researcher for iterative external research and validation. "
                        "Keeps findings separate from tender-derived claims and returns links."
                    ),
                    "prompt": RESEARCH_AGENT_PROMPT,
                    "tools": REACT_TOOLS_WEB,
                },
            ]

            agent_graph = async_create_deep_agent(
                tools=tools,
                subagents=subagents,
                instructions=TENDER_ANALYSIS_SYSTEM_PROMPT,
                model=self.model,
                checkpointer=self.checkpointer,
                context_schema=DeepAgentState,
                tool_configs={
                    # Interrupt when the agent calls HITL tool
                    "request_human_input": True,
                },
            )

            configured_agent = agent_graph.with_config(
                {"recursion_limit": 1000, "max_execution_time": 300}
            )

            logger.info(
                "Successfully created deep agent graph with MongoDB-backed subagents"
            )
            return configured_agent

        except Exception as e:
            logger.error(f"Failed to create deep agent graph: {e}")
            raise

    def _ensure_single_tender_scope(
        self, thread_id: str, tender_id: Optional[str]
    ) -> None:
        """Enforce single-tender scope per thread in MongoDB.

        Creates a binding on first use; raises if a different tender is used later.
        """
        if not tender_id:
            return
        coll = self.mongo_client[self.db_name]["threads"]
        existing = coll.find_one({"thread_id": thread_id})
        if existing is None:
            coll.insert_one(
                {
                    "thread_id": thread_id,
                    "tender_id": tender_id,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return
        if existing.get("tender_id") and existing["tender_id"] != tender_id:
            raise ValueError(
                f"Thread {thread_id} is bound to tender {existing['tender_id']}, got {tender_id}"
            )

    def _build_context_files(self, tender_id: str) -> Dict[str, str]:
        """Build /context files for the virtual filesystem from MongoDB metadata."""
        # Get requirement cluster ID - this is critical for RAG search filtering
        from tool_utils import get_requirement_cluster_id
        cluster_id = get_requirement_cluster_id(self.mongo_client, tender_id, self.org_id)
        if cluster_id is None:
            cluster_id = "UNKNOWN"
            logger.warning(f"Could not find requirement_cluster_id for tender {tender_id}")
        
        summary = get_proposal_summary(self.mongo_client, tender_id, self.org_id)
        if summary is None:
            summary = "Summary not found"

        docs = (
            get_proposal_files_summary(self.mongo_client, tender_id, self.org_id) or []
        )
        file_index = []
        for d in docs:
            s = d.get("summary")
            file_index.append(
                {
                    "file_id": str(d.get("file_id")),
                    "filename": d.get("file_name"),
                    "summary": s,
                }
            )

        files: Dict[str, str] = {
            self.CONTEXT_SUMMARY_PATH: summary,
            self.CONTEXT_SUPPLIER_PROFILE_PATH: "Supplier profile not provided.",
            self.CONTEXT_FILE_INDEX_PATH: json.dumps(
                file_index, ensure_ascii=False, indent=2
            ),
            self.CONTEXT_CLUSTER_ID_PATH: cluster_id,  # Add cluster_id for RAG search
        }
        return files

    async def chat_streaming(
        self,
        user_query: str,
        thread_id: str,
        tender_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Chat with streaming response using MongoDB checkpointer.

        Args:
            user_query: The user's query
            thread_id: Unique thread ID for conversation persistence
            tender_id: Optional tender ID for context
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

            # Build context files first
            context_files = self._build_context_files(tender_id) if tender_id else {}
            
            # Pre-load critical context into the initial message to avoid LLM tool calls
            if tender_id and context_files:
                tender_summary = context_files.get(self.CONTEXT_SUMMARY_PATH, "")
                file_index = context_files.get(self.CONTEXT_FILE_INDEX_PATH, "")
                
                enhanced_query = f"""Tender ID: {tender_id}

<tender_context>
<tender_summary>
{tender_summary}
</tender_summary>

<file_index>
{file_index}
</file_index>
</tender_context>

User Query: {user_query}"""
                messages = [{"role": "user", "content": enhanced_query}]
            else:
                messages = [{"role": "user", "content": user_query}]

            config = {"configurable": {"thread_id": thread_id}}

            # Enforce single-tender-per-thread guard
            try:
                self._ensure_single_tender_scope(thread_id, tender_id)
            except Exception as guard_err:
                yield {
                    "chunk_type": "error",
                    "content": str(guard_err),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "thread_id": thread_id,
                }
                return

            # Bootstrap /context files into virtual filesystem state
            # (Files still available via read_file for reference, but context is pre-loaded)
            state_input: Dict[str, Any] = {"messages": messages}
            if tender_id:
                state_input["files"] = context_files

            yield {
                "chunk_type": "start",
                "content": "Processing query...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "tender_id": tender_id,
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
            }

            logger.info(
                f"Successfully processed streaming query in {processing_time_ms}ms"
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
        tender_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Chat synchronously and return the complete response.

        Args:
            user_query: The user's query
            thread_id: Unique thread ID for conversation persistence
            tender_id: Optional tender ID for context
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

            # Build context files first
            context_files = self._build_context_files(tender_id) if tender_id else {}
            
            # Pre-load critical context into the initial message to avoid LLM tool calls
            if tender_id and context_files:
                tender_summary = context_files.get(self.CONTEXT_SUMMARY_PATH, "")
                file_index = context_files.get(self.CONTEXT_FILE_INDEX_PATH, "")
                
                enhanced_query = f"""Tender ID: {tender_id}

<tender_context>
<tender_summary>
{tender_summary}
</tender_summary>

<file_index>
{file_index}
</file_index>
</tender_context>

User Query: {user_query}"""
                messages = [{"role": "user", "content": enhanced_query}]
            else:
                messages = [{"role": "user", "content": user_query}]

            config = {"configurable": {"thread_id": thread_id}}

            # Enforce single-tender-per-thread guard
            self._ensure_single_tender_scope(thread_id, tender_id)

            # Bootstrap /context files into virtual filesystem state
            # (Files still available via read_file for reference, but context is pre-loaded)
            state_input: Dict[str, Any] = {"messages": messages}
            if tender_id:
                state_input["files"] = context_files

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

            logger.info(f"Successfully processed sync query in {processing_time_ms}ms")
            log_query_end(session_id, agent_response)

            return {
                "response": agent_response,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "user_id": user_id,
                "processing_time_ms": processing_time_ms,
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
            }

    def get_conversation_history(self, _thread_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve conversation history for a specific thread.

        Args:
            thread_id: The thread ID to retrieve history for

        Returns:
            List of conversation messages
        """
        try:
            # This would typically query the MongoDB checkpointer for conversation history
            # For now, return empty list as the checkpointer handles this internally
            return []
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            return []

    def get_agent_info(self) -> Dict[str, Any]:
        """Get agent information and statistics."""
        return {
            "org_id": self.org_id,
            "agent_initialized": self.agent is not None,
            "checkpointer_type": "MongoDBSaver",
            "model": "gpt-5",
            "mongodb_connected": True,
            "mongodb_database": self.db_name,
            "tools_available": len(REACT_TOOLS) if REACT_TOOLS else 0,
            "subagents": ["document-analyzer", "web-researcher"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def cleanup(self):
        """Clean up resources."""
        if self.mongo_client:
            logger.info("ReactAgent cleanup completed")
