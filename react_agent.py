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
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient
import pytz
import os

from src.deepagents.graph import async_create_deep_agent
from src.deepagents.state import DeepAgentState
from src.deepagents.streaming_middleware import StreamingMiddleware, PlanningStreamingMiddleware
from src.deepagents.middleware import PersistentSummarizationMiddleware
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


class ConversationSummaryManager:
    """Manages persistent conversation summaries in MongoDB."""
    
    def __init__(self, mongo_client: MongoClient, db_name: str, model):
        self.mongo_client = mongo_client
        self.db_name = db_name
        self.model = model  # Main agent model (Claude)
        self.threads_collection = mongo_client[db_name]["threads"]
        
        # Initialize Gemini for summarization (1M context, cheaper, optimized for long texts)
        try:
            self.summary_model = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.3,
                google_api_key=os.getenv("GOOGLE_API_KEY"),
            )
            logger.info("✓ Gemini model initialized for summarization")
        except Exception as e:
            logger.warning(f"Gemini not available, falling back to main model: {e}")
            self.summary_model = model
        
        # Use tiktoken cl100k_base as Claude approximation
        try:
            import tiktoken
            self.encoder = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"tiktoken not available, using char estimation: {e}")
            self.encoder = None
        
        # Config
        self.MAX_TOKENS_BEFORE_SUMMARY = 120000
        self.SUMMARIZATION_TIMEOUT = 90
    
    def count_tokens(self, messages):
        """Count tokens in messages."""
        if self.encoder:
            total = 0
            for msg in messages:
                content = str(msg.content) if hasattr(msg, 'content') else str(msg)
                try:
                    total += len(self.encoder.encode(content))
                except:
                    total += len(content) // 3  # Fallback
            return total
        else:
            # Fallback: char-based estimation (1 token ≈ 3 chars for Claude)
            total_chars = sum(len(str(msg.content if hasattr(msg, 'content') else msg)) for msg in messages)
            return total_chars // 3
    
    def load_summary(self, thread_id: str):
        """Load existing summary from MongoDB."""
        try:
            doc = self.threads_collection.find_one(
                {"thread_id": thread_id},
                {"conversation_summary": 1}
            )
            
            if doc and "conversation_summary" in doc:
                return doc["conversation_summary"]
            
            return None
        except Exception as e:
            logger.error(f"Error loading summary for {thread_id}: {e}")
            return None
    
    def should_summarize(self, thread_id: str, messages):
        """Check if summarization is needed using smart token counting.
        
        Smart counting:
        - Last 2 complete exchanges: Count ALL tokens (including tools)
        - Everything before: Count ONLY user/AI message tokens (stripped)
        
        This prevents tool call "noise" from triggering premature summarization.
        """
        if not messages or len(messages) < 10:
            return False
        
        # Group into exchanges
        exchanges = self._group_into_exchanges(messages)
        
        if len(exchanges) < 3:
            return False  # Need at least 3 exchanges to consider summarization
        
        # Smart token counting
        num_complete = 2  # Keep last 2 complete
        num_stripped = max(0, len(exchanges) - num_complete)
        
        total_tokens = 0
        
        # Count stripped exchanges (user/AI only, no tools)
        for exchange in exchanges[:num_stripped]:
            stripped = self._strip_tools_from_exchange(exchange)
            total_tokens += self.count_tokens(stripped)
        
        # Count complete exchanges (everything)
        for exchange in exchanges[num_stripped:]:
            total_tokens += self.count_tokens(exchange)
        
        if total_tokens > self.MAX_TOKENS_BEFORE_SUMMARY:
            logger.info(f"Summarization needed for {thread_id}: {total_tokens:,} smart tokens "
                       f"({num_stripped} stripped + {num_complete} complete exchanges)")
            return True
        
        return False
    
    async def create_and_save_summary(self, thread_id: str, messages):
        """Create and save summary, excluding last 2 complete exchanges."""
        if not messages:
            return
        
        try:
            old_summary = self.load_summary(thread_id)
            
            # Group into exchanges
            exchanges = self._group_into_exchanges(messages)
            
            if len(exchanges) < 3:
                logger.info(f"Not enough exchanges to summarize for {thread_id}")
                return
            
            # Exclude last 2 complete exchanges from summarization
            num_to_exclude = 2
            exchanges_to_summarize = exchanges[:-num_to_exclude]
            excluded_exchanges = exchanges[-num_to_exclude:]
            
            # Flatten exchanges back to messages
            messages_to_summarize = []
            for exchange in exchanges_to_summarize:
                messages_to_summarize.extend(exchange)
            
            # Find last message ID (end of summarized content)
            last_message_id = messages_to_summarize[-1].id if messages_to_summarize and hasattr(messages_to_summarize[-1], 'id') else None
            
            # Strategy: Always do FULL re-summarization
            # This is simpler and prevents drift from incremental compression
            # Cost is low since we only summarize when truly needed (smart threshold)
            strategy = "full"
            new_messages = messages_to_summarize  # All messages to be summarized
            previous_summary = None
            
            # Generate summary with timeout
            async with asyncio.timeout(self.SUMMARIZATION_TIMEOUT):
                summary_text = await self._generate_summary(
                    new_messages, 
                    strategy, 
                    previous_summary
                )
            
            # Create summary doc
            new_version = (old_summary.get("version", 0) + 1) if old_summary else 1
            
            # Calculate token estimate directly from summary text
            if self.encoder:
                token_estimate = len(self.encoder.encode(summary_text))
            else:
                token_estimate = len(summary_text) // 3  # Fallback estimation
            
            summary_doc = {
                "schema_version": 1,
                "summary_text": summary_text,
                "last_message_id": last_message_id,
                "created_at": datetime.now(timezone.utc),
                "token_estimate": token_estimate,
                "version": new_version,
                "messages_summarized_count": len(messages_to_summarize),
                "excluded_exchanges": num_to_exclude,
                "strategy": strategy
            }
            
            # Save with optimistic locking
            old_version = old_summary.get("version", 0) if old_summary else 0
            result = self.threads_collection.update_one(
                {
                    "thread_id": thread_id,
                    "$or": [
                        {"conversation_summary.version": old_version},
                        {"conversation_summary": {"$exists": False}}
                    ]
                },
                {"$set": {"conversation_summary": summary_doc}}
            )
            
            if result.modified_count > 0:
                logger.info(f"✓ Summary saved for {thread_id}: v{new_version} ({strategy}) - "
                           f"summarized {len(exchanges_to_summarize)} exchanges, "
                           f"excluded last {num_to_exclude} complete")
            else:
                logger.warning(f"Version conflict for {thread_id}, skipping")
            
        except Exception as e:
            logger.error(f"Error creating summary for {thread_id}: {e}", exc_info=True)
    
    def _find_message_index(self, messages, message_id):
        """Find index of message by ID."""
        if not message_id:
            return None
        for i, msg in enumerate(messages):
            if hasattr(msg, 'id') and msg.id == message_id:
                return i
        return None
    
    async def _generate_summary(self, messages, strategy="full", previous_summary=None):
        """Generate summary using Gemini (always full re-summarization).
        
        Uses Gemini 2.5 Flash for:
        - 1M token context window (can handle very long conversations)
        - Cost-effective summarization
        - High-quality structured output
        
        We always re-summarize from scratch because:
        - Prevents drift from repeated incremental compression
        - Simpler logic, fewer edge cases
        - Smart threshold means we only summarize when needed
        """
        prompt = f"""You are a summarization assistant for a tender analysis AI agent. Your task is to create a comprehensive, structured summary of the conversation below.

CONTEXT:
This is a conversation between a User and an AI Assistant that helps analyze tender documents. The assistant searches documents, reads files, and answers questions about tender requirements.

CONVERSATION:
{self._format_messages(messages)}

INSTRUCTIONS:
Create a detailed summary with the following structure:

## Conversation Summary

### User's Primary Objective
Describe what the user is trying to accomplish with this tender analysis. What is their main goal?

### Key Questions Asked
List the main questions the user has asked throughout the conversation.

### Key Findings & Discoveries
List all important findings with source citations in [Source: filename] format:
- Requirements, constraints, deadlines
- Important clauses, terms, conditions
- Compliance requirements
- Financial terms (budgets, penalties, payment terms)
- Any red flags or areas of concern

### Documents & Files Analyzed
For each document examined:
- Document name
- Key information extracted
- Relevant sections/pages referenced

### Pending Questions & Next Steps
- Questions that remain unanswered
- Areas that need further investigation
- Suggested next actions

### Important Context
Any other critical information that would help understand the conversation flow.

GUIDELINES:
- Be comprehensive but concise
- Always include [Source: filename] citations for findings
- Focus on OUTCOMES and INFORMATION, not tool mechanics (don't mention "used search tool" etc.)
- Preserve specific details: dates, numbers, percentages, amounts
- Organize information logically
Generate the summary now:"""
        
        response = await self.summary_model.ainvoke([{"role": "user", "content": prompt}])
        return response.content if hasattr(response, 'content') else str(response)
    
    def _format_messages(self, messages):
        """Format messages for summary prompt.
        
        Optimizes for Gemini's 1M context window:
        - Includes ALL user/AI messages (no arbitrary limit)
        - Minimal truncation (Gemini can handle long messages)
        - Skips tool messages (verbose, not needed for summary)
        """
        formatted = []
        for msg in messages:
            if msg.type == "tool":
                # Skip tool messages - too verbose, not useful for summary
                continue
            
            role = "User" if msg.type == "human" else "Assistant"
            content = str(msg.content)
            
            # Only truncate extremely long messages (> 10K chars)
            if len(content) > 10000:
                content = content[:10000] + "... [truncated]"
            
            if content.strip():  # Only include non-empty messages
                formatted.append(f"{role}: {content}")
        
        return "\n\n".join(formatted)
    
    def inject_summary(self, thread_id: str, request):
        """Inject summary with smart context optimization.
        
        Structure:
        - Summary of old messages (excludes last 2 exchanges)
        - Last 7-8 user/AI pairs (stripped of tool calls)
        - Last 2 complete exchanges (with all tool calls)
        - New query
        """
        from langchain_core.messages import AIMessage
        
        all_messages = request.messages
        summary_doc = self.load_summary(thread_id)
        
        if not summary_doc:
            return request  # No summary yet
        
        # Find cutoff point
        last_msg_id = summary_doc.get("last_message_id")
        cutoff_index = None
        
        if last_msg_id:
            for i, msg in enumerate(all_messages):
                if hasattr(msg, 'id') and msg.id == last_msg_id:
                    cutoff_index = i
                    break
        
        # Fallback to message count
        if cutoff_index is None:
            summarized_count = summary_doc.get("messages_summarized_count", 0)
            if summarized_count < len(all_messages):
                cutoff_index = summarized_count - 1
            else:
                logger.warning(f"Summary stale for {thread_id}, skipping")
                return request
        
        # Get messages after summary
        recent_messages = all_messages[cutoff_index + 1:]
        
        # Apply smart optimization: keep last 7-8 pairs stripped + last 2 complete
        optimized_context = self._optimize_context(recent_messages, keep_pairs=8, keep_complete=2)
        
        # Build final context
        summary_msg = AIMessage(
            content=f"<conversation_summary>\n{summary_doc['summary_text']}\n</conversation_summary>",
            id=f"summary_v{summary_doc['version']}"
        )
        request.messages = [summary_msg] + optimized_context
        
        logger.info(f"✓ Injected summary v{summary_doc['version']}: "
                   f"{len(all_messages)} → {len(request.messages)} messages "
                   f"(optimized from {len(recent_messages)} recent)")
        
        return request
    
    def _optimize_context(self, messages, keep_pairs=4, keep_complete=1):
        """Optimize context by keeping N user/AI pairs stripped + M complete exchanges.
        
        Args:
            messages: Recent messages after summary
            keep_pairs: Number of user/AI pairs to keep (stripped of tools)
            keep_complete: Number of complete exchanges to keep (with tools)
        
        Returns:
            Optimized message list
        """
        if len(messages) <= (keep_pairs + keep_complete) * 3:
            # Too few messages, keep all
            return messages
        
        # Find all exchanges (groups starting with HumanMessage)
        exchanges = self._group_into_exchanges(messages)
        
        if len(exchanges) <= keep_complete:
            # Not enough exchanges to optimize
            return messages
        
        # Split: older exchanges (stripped) + recent exchanges (complete)
        num_stripped = max(0, len(exchanges) - keep_complete)
        num_complete = min(keep_complete, len(exchanges))
        
        # Take last N stripped exchanges (but only if we have more than keep_pairs)
        num_to_strip = min(keep_pairs, num_stripped)
        
        optimized = []
        
        # Add stripped exchanges (user/AI pairs only, no tools)
        strip_start_idx = max(0, num_stripped - num_to_strip)
        for exchange in exchanges[strip_start_idx:num_stripped]:
            optimized.extend(self._strip_tools_from_exchange(exchange))
        
        # Add complete exchanges (everything)
        for exchange in exchanges[num_stripped:]:
            optimized.extend(exchange)
        
        return optimized
    
    def _group_into_exchanges(self, messages):
        """Group messages into exchanges (each starting with HumanMessage)."""
        exchanges = []
        current_exchange = []
        
        for msg in messages:
            if msg.type == "human" and current_exchange:
                # Start new exchange
                exchanges.append(current_exchange)
                current_exchange = [msg]
            else:
                current_exchange.append(msg)
        
        if current_exchange:
            exchanges.append(current_exchange)
        
        return exchanges
    
    def _strip_tools_from_exchange(self, exchange):
        """Remove tool calls and tool messages, keep only user/AI conversation."""
        stripped = []
        
        for msg in exchange:
            if msg.type == "human":
                # Always keep user messages
                stripped.append(msg)
            elif msg.type == "ai":
                # Keep AI message but strip tool_calls
                from langchain_core.messages import AIMessage
                # Create clean AI message with just content
                if hasattr(msg, 'content') and msg.content:
                    clean_msg = AIMessage(content=msg.content)
                    # Preserve message ID if present
                    if hasattr(msg, 'id'):
                        clean_msg.id = msg.id
                    stripped.append(clean_msg)
            # Skip tool messages entirely
        
        return stripped


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

        self.model = ChatAnthropic(
            model="claude-sonnet-4-5-20250929",
            max_tokens=120000
        )

        set_agent_context("react_agent", f"react_agent_{org_id}")

        # Initialize summary manager
        self.summary_manager = ConversationSummaryManager(
            mongo_client=mongo_client,
            db_name=self.db_name,
            model=self.model
        )
        self.summary_tasks = set()  # Track async tasks

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
            # Inject current date into system prompt
            copenhagen_tz = pytz.timezone('Europe/Copenhagen')
            current_date = datetime.now(copenhagen_tz).strftime("%A, %B %d, %Y")
            
            system_prompt = TENDER_ANALYSIS_SYSTEM_PROMPT.format(current_date=current_date)
            
            tools = REACT_TOOLS

            subagents = [
                {
                    "name": "advanced_tender_analyst",
                    "description": (
                        "Specialized subagent for deep tender document analysis. Use when the task requires: "
                        "(1) **Multi-document analysis**: Analyzing MULTIPLE Bilag documents or Rammeaftale sections in depth, "
                        "(2) **Iterative exploration**: One search reveals leads requiring follow-up searches (e.g., finding 'bod' → searching for amounts → cross-referencing consequences), "
                        "(3) **Cross-document synthesis**: Connecting information across Rammeaftale + multiple Bilag (e.g., penalties in Section 8 + Bilag C + Bilag D), "
                        "(4) **Procedure extraction**: Understanding step-by-step workflows (Direkte Tildeling process, Miniudbud rules, escalation paths), "
                        "(5) **Pattern identification**: Finding ALL mentions of X across entire tender (backup requirements, reporting obligations, termination triggers), "
                        "(6) **Risk/compliance analysis**: Extracting penalties (bod), breach consequences (misligholdelse), CSR obligations, audit requirements. "
                        ""
                        "This subagent understands **Danish tender terminology**: "
                        "• Rammeaftale (framework agreement), Bilag A-F (appendices), SKI (Danish procurement agency) "
                        "• Direkte Tildeling (direct award), Miniudbud (mini-competition) "
                        "• Bod (penalty), sanktioner (sanctions), misligholdelse (breach), ophævelse (termination) "
                        "• Krav (requirements), forpligtelser (obligations), rapportering (reporting), omsætning (turnover) "
                        "• Leveringsaftale (delivery contract), genopretning (recovery), sikkerhedskopiering (backup) "
                        ""
                        "**Language handling**: Will automatically adapt search keywords to match tender language (Danish/English). "
                        ""
                        "**DO NOT use for**: Simple lookups (deadline, contact, single fact) - use search_tender_corpus directly. "
                        "**Multi-part questions**: Spawn multiple agents in parallel (one per independent sub-question). "
                        "**Delegation**: Give complete task descriptions with specific documents, information needed, format, and language."
                    ),
                    "prompt": DOCUMENT_ANALYZER_PROMPT,
                    "tools": REACT_TOOLS_DOC,
                },
                {
                    "name": "web_researcher",
                    "description": (
                        "Specialized subagent for external tender intelligence and market research. Use for: "
                        "(1) **Competitor analysis**: Research multiple companies bidding on similar SKI frameworks (capabilities, past wins, pricing models), "
                        "(2) **Market intelligence**: Danish/Nordic IT consulting rates, industry salary benchmarks, pricing strategies, "
                        "(3) **Regulatory research**: Danish GDPR updates, EU procurement law, SKI framework policies, CSR directives, "
                        "(4) **Technical standards**: ISO requirements (27001, 9001, 20000), Danish IT security standards, framework comparisons, "
                        "(5) **CSR compliance**: Danish supply chain due diligence, EU CSR reporting requirements, sustainability standards, "
                        "(6) **Company/client research**: Background on contracting authorities, past procurement patterns, industry trends. "
                        ""
                        "This subagent will: "
                        "• Conduct 3-7 iterative web searches with refinement based on findings "
                        "• Prioritize Danish sources (.dk domains) for Danish market context "
                        "• Cross-verify information across multiple sources "
                        "• Synthesize findings into structured intelligence with source links "
                        ""
                        "**Common Danish/Nordic sources**: datatilsynet.dk (Danish GDPR), konkurrence-styrelsen.dk (competition authority), "
                        "SKI.dk (procurement), arbejdstilsynet.dk (labor inspectorate), ISO.org (standards). "
                        ""
                        "**DO NOT use for**: Single straightforward web lookups - call web_search tool directly. "
                        "**Multi-topic research**: For 3+ independent topics (e.g., 3 competitors), spawn multiple agents in parallel (one per topic). "
                        "**Delegation**: Specify research angles, target companies/topics, Danish market focus, and desired output format."
                    ),
                    "prompt": RESEARCH_AGENT_PROMPT,
                    "tools": REACT_TOOLS_WEB,
                },
            ]

            # Create streaming middleware for MVP transparency
            custom_middleware = [
                StreamingMiddleware(),
                PlanningStreamingMiddleware(),
                PersistentSummarizationMiddleware(self.summary_manager)
            ]
            
            agent_graph = async_create_deep_agent(
                tools=tools,
                subagents=subagents,
                instructions=system_prompt,  # Use formatted prompt with current date
                model=self.model,
                checkpointer=self.checkpointer,
                context_schema=DeepAgentState,
                middleware=custom_middleware,
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
                    "message_count": 0,  # Track messages to control context injection
                }
            )
            return
        if existing.get("tender_id") and existing["tender_id"] != tender_id:
            raise ValueError(
                f"Thread {thread_id} is bound to tender {existing['tender_id']}, got {tender_id}"
            )
    
    def _should_inject_tender_context(self, thread_id: str) -> bool:
        """
        Determine if tender context should be injected.
        Only inject for the FIRST message in a thread to avoid memory bloat.
        
        Returns:
            True if this is the first message (inject context)
            False if this is a follow-up message (skip context)
        """
        try:
            threads_coll = self.mongo_client[self.db_name]["threads"]
            thread = threads_coll.find_one({"thread_id": thread_id})
            
            if thread is None:
                # Brand new thread - inject context
                return True
            
            # Check if message_count field exists and is 0
            message_count = thread.get("message_count", 0)
            return message_count == 0
            
        except Exception as e:
            # If we can't determine, inject context (safe default)
            logger.warning(f"Error checking thread context injection status: {e}")
            return True

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
            # Summary is already fetched as agent_summary (with fallback) from tool_utils.get_proposal_files_summary
            s = d.get("summary", "No summary available")
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
                file_index, ensure_ascii=False, indent=2, sort_keys=True
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

            # Build context files first - they'll be available in state
            context_files = self._build_context_files(tender_id) if tender_id else {}
            
            # Check if we should inject tender context (only for first message)
            should_inject_context = self._should_inject_tender_context(thread_id) if tender_id else False
            
            # Pre-load summary & file index for main agent to answer generic questions quickly
            # Subagents won't get this - they only get files in state (via middleware filtering)
            # ONLY inject on first message to avoid memory bloat
            if tender_id and context_files and should_inject_context:
                tender_summary = context_files.get(self.CONTEXT_SUMMARY_PATH, "")
                file_index = context_files.get(self.CONTEXT_FILE_INDEX_PATH, "")
                
                enhanced_query = f"""<tender_context>
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
                # Follow-up message - just use plain query
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
            # IMPORTANT: files must be set unconditionally so checkpointer doesn't drop them
            state_input: Dict[str, Any] = {
                "messages": messages,
                "files": context_files,  # Always set, even if empty dict
            }
            if tender_id and context_files:
                # Also store cluster_id at top-level for tools to access without file read
                state_input["cluster_id"] = context_files.get(self.CONTEXT_CLUSTER_ID_PATH, "68c99b8a10844521ad051543")

            yield {
                "chunk_type": "start",
                "content": "Processing query...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "thread_id": thread_id,
                "tender_id": tender_id,
                "user_id": user_id,
            }

            response = await self.agent.ainvoke(state_input, config=config)

            # Trigger async summarization (non-blocking)
            self._schedule_summarization(thread_id, config)

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
            
            # Increment message count after successful response
            if tender_id:
                try:
                    threads_coll = self.mongo_client[self.db_name]["threads"]
                    threads_coll.update_one(
                        {"thread_id": thread_id},
                        {"$inc": {"message_count": 1}}
                    )
                except Exception as msg_count_err:
                    logger.warning(f"Failed to increment message count: {msg_count_err}")

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

            # Build context files first - they'll be available in state
            context_files = self._build_context_files(tender_id) if tender_id else {}
            
            # Check if we should inject tender context (only for first message)
            should_inject_context = self._should_inject_tender_context(thread_id) if tender_id else False
            
            # Pre-load summary & file index for main agent to answer generic questions quickly
            # Subagents won't get this - they only get files in state (via middleware filtering)
            # ONLY inject on first message to avoid memory bloat
            if tender_id and context_files and should_inject_context:
                tender_summary = context_files.get(self.CONTEXT_SUMMARY_PATH, "")
                file_index = context_files.get(self.CONTEXT_FILE_INDEX_PATH, "")
                
                enhanced_query = f"""<tender_context>
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
                # Follow-up message - just use plain query
                messages = [{"role": "user", "content": user_query}]

            config = {"configurable": {"thread_id": thread_id}}

            # Enforce single-tender-per-thread guard
            self._ensure_single_tender_scope(thread_id, tender_id)

            # Bootstrap /context files into virtual filesystem state
            # IMPORTANT: files must be set unconditionally so checkpointer doesn't drop them
            state_input: Dict[str, Any] = {
                "messages": messages,
                "files": context_files,  # Always set, even if empty dict
            }
            if tender_id and context_files:
                state_input["cluster_id"] = context_files.get(self.CONTEXT_CLUSTER_ID_PATH, "68c99b8a10844521ad051543")

            response = await self.agent.ainvoke(state_input, config=config)
            
            # Trigger async summarization (non-blocking) - same as streaming path
            self._schedule_summarization(thread_id, config)

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
            
            # Increment message count after successful response
            if tender_id:
                try:
                    threads_coll = self.mongo_client[self.db_name]["threads"]
                    threads_coll.update_one(
                        {"thread_id": thread_id},
                        {"$inc": {"message_count": 1}}
                    )
                except Exception as msg_count_err:
                    logger.warning(f"Failed to increment message count: {msg_count_err}")

            return {
                "response": agent_response,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "user_id": user_id,
                "processing_time_ms": processing_time_ms,
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

    def _schedule_summarization(self, thread_id: str, config: dict):
        """Schedule background summarization without blocking."""
        task = asyncio.create_task(
            self._async_summarize_with_tracking(thread_id, config)
        )
        self.summary_tasks.add(task)
        task.add_done_callback(lambda t: self.summary_tasks.discard(t))
    
    async def _async_summarize_with_tracking(self, thread_id: str, config: dict):
        """Background summarization with error handling."""
        try:
            # Load current state from checkpointer (named arg for API stability)
            checkpoint = self.checkpointer.get(config=config)
            if not checkpoint or not hasattr(checkpoint, 'values') or "messages" not in checkpoint.values:
                return
            
            messages = checkpoint.values["messages"]
            
            # Check if summarization needed
            if self.summary_manager.should_summarize(thread_id, messages):
                await self.summary_manager.create_and_save_summary(thread_id, messages)
        except Exception as e:
            logger.error(f"Async summarization failed for {thread_id}: {e}")

    def get_agent_info(self) -> Dict[str, Any]:
        """Get agent information and statistics."""
        return {
            "org_id": self.org_id,
            "agent_initialized": self.agent is not None,
            "checkpointer_type": "MongoDBSaver",
            "model": getattr(self.model, "model", "unknown"),  # Get actual model name
            "mongodb_connected": True,
            "mongodb_database": self.db_name,
            "tools_available": len(REACT_TOOLS) if REACT_TOOLS else 0,
            "subagents": ["advanced_tender_analyst", "web_researcher"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def cleanup(self):
        """Clean up resources and wait for pending summarization tasks."""
        # Wait for pending summarization tasks to complete
        if self.summary_tasks:
            logger.info(f"Waiting for {len(self.summary_tasks)} pending summarization tasks...")
            await asyncio.gather(*self.summary_tasks, return_exceptions=True)
            logger.info("All summarization tasks completed")
        
        if self.mongo_client:
            logger.info("ReactAgent cleanup completed")
