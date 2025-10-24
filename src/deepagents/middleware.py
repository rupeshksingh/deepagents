"""DeepAgents implemented as Middleware"""

import json
from datetime import datetime
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    SummarizationMiddleware,
)
from langchain.agents.middleware.prompt_caching import AnthropicPromptCachingMiddleware
from langchain_core.tools import BaseTool, tool, InjectedToolCallId, InjectedToolArg
from langchain_core.messages import ToolMessage
from langchain.tools.tool_node import InjectedState
from langchain.chat_models import init_chat_model
from langgraph.types import Command
from langgraph.runtime import Runtime
from typing import Annotated
from src.deepagents.state import PlanningState, FilesystemState
from src.deepagents.tools import write_todos, ls, read_file, write_file, edit_file
from src.deepagents.prompts import (
    WRITE_TODOS_SYSTEM_PROMPT,
    TASK_SYSTEM_PROMPT,
    FILESYSTEM_SYSTEM_PROMPT,
    TASK_TOOL_DESCRIPTION,
    BASE_AGENT_PROMPT,
)
from src.deepagents.types import SubAgent, CustomSubAgent
from src.deepagents.logging_utils import (
    log_tool_call,
    log_subagent_call,
    set_agent_context,
    get_unified_logger,
)

###########################
# Tool Call Logging Middleware
###########################


class ToolCallLoggingMiddleware(AgentMiddleware):
    """Simplified middleware to log all tool calls at the agent level with context."""

    def __init__(self, agent_type: str = "main_agent", agent_id: str = None):
        """Initialize with agent context."""
        self.agent_type = agent_type
        self.agent_id = agent_id or f"agent_{id(self)}"
        self.logger = get_unified_logger()
        set_agent_context(self.agent_type, self.agent_id)

    def modify_tool_call(self, tool_call, agent_state):
        """Log tool calls before they are executed with unified context."""
        tool_name = tool_call.get("name", "unknown")
        tool_call_id = tool_call.get("id", "unknown")

        log_data = {
            "event": "agent_tool_call",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "timestamp": datetime.now().isoformat(),
            "args": tool_call.get("args", {}),
            "agent_context": {
                "agent_type": self.agent_type,
                "agent_id": self.agent_id,
                "middleware": "ToolCallLoggingMiddleware",
            },
        }
        self.logger.logger.info(f"AGENT_TOOL_CALL: {json.dumps(log_data, default=str)}")

        return tool_call


###########################
# Planning Middleware
###########################


class PlanningMiddleware(AgentMiddleware):
    state_schema = PlanningState
    tools = [write_todos]

    def modify_model_request(
        self, request: ModelRequest, agent_state: PlanningState, runtime: Runtime
    ) -> ModelRequest:
        request.system_prompt = (
            request.system_prompt + "\n\n" + WRITE_TODOS_SYSTEM_PROMPT
        )
        return request


###########################
# Filesystem Middleware
###########################


class FilesystemMiddleware(AgentMiddleware):
    state_schema = FilesystemState
    tools = [ls, read_file, write_file, edit_file]

    def modify_model_request(
        self, request: ModelRequest, agent_state: FilesystemState, runtime: Runtime
    ) -> ModelRequest:
        request.system_prompt = (
            request.system_prompt + "\n\n" + FILESYSTEM_SYSTEM_PROMPT
        )
        return request
    
    def modify_tool_call(self, tool_call, agent_state):
        """Inject agent_state files into tool args for cross-graph compatibility."""
        import logging
        logger = logging.getLogger(__name__)
        tool_name = tool_call.get("name", "")
        # For filesystem tools, inject state from agent_state since InjectedState
        # doesn't work across graph boundaries (parent → subagent)
        if tool_name in ["ls", "read_file", "write_file", "edit_file"]:
            args = tool_call.get("args", {})
            files_dict = agent_state.get("files", {})
            logger.warning(f"FILESYSTEM_MIDDLEWARE: tool={tool_name}, agent_state_keys={list(agent_state.keys()) if isinstance(agent_state, dict) else 'not_dict'}, files_count={len(files_dict)}, files_keys={list(files_dict.keys())[:3]}")
            # Inject minimal state with only 'files' to avoid bloating tool call traces
            # (Tools only need the files dict, not entire agent state)
            args["state"] = {"files": files_dict}
            tool_call["args"] = args
        return tool_call


###########################
# SubAgent Middleware
###########################


class SubAgentMiddleware(AgentMiddleware):
    def __init__(
        self,
        default_subagent_tools: list[BaseTool] = [],
        subagents: list[SubAgent | CustomSubAgent] = [],
        model=None,
        is_async=False,
    ) -> None:
        super().__init__()
        task_tool = create_task_tool(
            default_subagent_tools=default_subagent_tools,
            subagents=subagents,
            model=model,
            is_async=is_async,
        )
        self.tools = [task_tool]

    def modify_model_request(
        self, request: ModelRequest, agent_state: AgentState, runtime: Runtime
    ) -> ModelRequest:
        request.system_prompt = request.system_prompt + "\n\n" + TASK_SYSTEM_PROMPT
        return request


def _get_agents(
    default_subagent_tools: list[BaseTool],
    subagents: list[SubAgent | CustomSubAgent],
    model,
):
    from src.deepagents.state import DeepAgentState
    
    default_subagent_middleware = [
        PlanningMiddleware(),
        FilesystemMiddleware(),
        # Memory Optimization
        ToolOutputCompactionMiddleware(),
        # NOTE: No persistent summarization for subagents (they're ephemeral, checkpointer=False)
        SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=150000,  # Aligned with main agent threshold
            messages_to_keep=12,
        ),
        # Caching
        AnthropicPromptCachingMiddleware(ttl="5m", unsupported_model_behavior="ignore"),
    ]
    agents = {
        "general_tender_analyst": create_agent(
            model,
            system_prompt=BASE_AGENT_PROMPT,
            tools=default_subagent_tools,
            checkpointer=False,
            middleware=default_subagent_middleware,
            context_schema=DeepAgentState,  # Ensure 'files' is preserved in state
        )
    }
    for _agent in subagents:
        if "graph" in _agent:
            agents[_agent["name"]] = _agent["graph"]
            continue
        if "tools" in _agent:
            _tools = _agent["tools"]
        else:
            _tools = default_subagent_tools.copy()
        if "model" in _agent:
            agent_model = _agent["model"]
            if isinstance(agent_model, dict):
                sub_model = init_chat_model(**agent_model)
            else:
                sub_model = agent_model
        else:
            sub_model = model
        if "middleware" in _agent:
            _middleware = [*default_subagent_middleware, *_agent["middleware"]]
        else:
            _middleware = default_subagent_middleware
        agents[_agent["name"]] = create_agent(
            sub_model,
            system_prompt=_agent["prompt"],
            tools=_tools,
            middleware=_middleware,
            checkpointer=False,
            context_schema=DeepAgentState,  # Preserve 'files' & compatible structure
        )
    return agents


def _get_subagent_description(subagents: list[SubAgent | CustomSubAgent]):
    return [f"- {_agent['name']}: {_agent['description']}" for _agent in subagents]


def create_task_tool(
    default_subagent_tools: list[BaseTool],
    subagents: list[SubAgent | CustomSubAgent],
    model,
    is_async: bool = False,
):
    agents = _get_agents(default_subagent_tools, subagents, model)
    other_agents_string = _get_subagent_description(subagents)
    
    def _fix_task_tool_schema(tool_obj):
        """Remove injected params from tool schema to prevent validation errors."""
        if hasattr(tool_obj, 'args_schema') and tool_obj.args_schema is not None:
            schema = tool_obj.args_schema
            if hasattr(schema, 'model_fields'):
                if 'state' in schema.model_fields:
                    field = schema.model_fields['state']
                    field.default = None
                    field.default_factory = None
                    if hasattr(schema, '__pydantic_required__'):
                        schema.__pydantic_required__.discard('state')
                if 'tool_call_id' in schema.model_fields:
                    field = schema.model_fields['tool_call_id']
                    field.default = None
                    field.default_factory = None
                    if hasattr(schema, '__pydantic_required__'):
                        schema.__pydantic_required__.discard('tool_call_id')
        return tool_obj

    if is_async:

        @tool(
            description=TASK_TOOL_DESCRIPTION.format(other_agents=other_agents_string)
        )
        @log_tool_call
        async def task(
            description: str,
            subagent_type: str,
            state: Annotated[FilesystemState, InjectedState, InjectedToolArg] = None,
            tool_call_id: Annotated[str, InjectedToolCallId, InjectedToolArg] = "",
        ):
            # Validate required parameters
            if not description or not description.strip():
                return f"❌ Error: 'description' parameter is required and cannot be empty. The task tool requires BOTH 'subagent_type' AND 'description'. This error usually means the model hit max_tokens while generating tool calls. Please retry with a briefer explanation before the tool calls."
            
            if subagent_type not in agents:
                return f"Error: invoked agent of type {subagent_type}, the only allowed types are {[f'`{k}`' for k in agents]}"

            set_agent_context("subagent", f"subagent_{subagent_type}", subagent_type)

            log_subagent_call(subagent_type, description)
            
            # Emit SUBAGENT_START event for streaming
            subagent_id = f"subagent_{subagent_type}_{tool_call_id[:8]}"
            try:
                from api.streaming.emitter import get_current_emitter
                emitter = get_current_emitter()
                if emitter:
                    await emitter.emit_subagent_start(
                        agent_id=subagent_id,
                        parent_call_id=tool_call_id,
                        subagent_description=description
                    )
            except Exception:
                pass  # Don't break if streaming fails

            sub_agent = agents[subagent_type]
            # Create clean state for subagent with ONLY the task description
            # Filter to only pass the three critical context files to subagents
            files_dict = state.get("files", {}) if state else {}
            context_files = {
                k: v for k, v in files_dict.items()
                if k in [
                    "/workspace/context/tender_summary.md",
                    "/workspace/context/file_index.json",
                    "/workspace/context/cluster_id.txt",
                ]
            }
            get_unified_logger().logger.info(
                f"TASK_PASS_FILES: subagent={subagent_type} total_files={len(files_dict)} context_files={len(context_files)} keys={list(context_files.keys())}"
            )
            subagent_state = {
                "messages": [{"role": "user", "content": description}],
                "files": context_files,  # Only pass context files
                # Get cluster_id from top-level state, not file content
                "cluster_id": state.get("cluster_id") if state else None,
                # Don't pass todos or other accumulated context
            }
            get_unified_logger().logger.warning(
                f"SUBAGENT_INVOKE_DEBUG: about to invoke {subagent_type}, state_keys={list(subagent_state.keys())}, files_in_state={len(subagent_state.get('files', {}))}"
            )
            import time
            subagent_start_time = time.time()
            result = await sub_agent.ainvoke(subagent_state)
            subagent_execution_ms = int((time.time() - subagent_start_time) * 1000)
            
            get_unified_logger().logger.warning(
                f"SUBAGENT_RESULT_DEBUG: {subagent_type} returned, result_keys={list(result.keys()) if isinstance(result, dict) else 'not_dict'}, files_in_result={len(result.get('files', {})) if isinstance(result, dict) else 0}"
            )
            
            # Emit SUBAGENT_END event for streaming
            try:
                from api.streaming.emitter import get_current_emitter
                emitter = get_current_emitter()
                if emitter:
                    await emitter.emit_subagent_end(
                        agent_id=subagent_id,
                        parent_call_id=tool_call_id,
                        ms=subagent_execution_ms
                    )
            except Exception:
                pass  # Don't break if streaming fails
            
            state_update = {}
            for k, v in result.items():
                if k not in ["todos", "messages"]:
                    state_update[k] = v
            return Command(
                update={
                    **state_update,
                    "messages": [
                        ToolMessage(
                            result["messages"][-1].content, tool_call_id=tool_call_id
                        )
                    ],
                }
            )

    else:

        @tool(
            description=TASK_TOOL_DESCRIPTION.format(other_agents=other_agents_string)
        )
        @log_tool_call
        def task(
            description: str,
            subagent_type: str,
            state: Annotated[FilesystemState, InjectedState, InjectedToolArg] = None,
            tool_call_id: Annotated[str, InjectedToolCallId, InjectedToolArg] = "",
        ):
            # Validate required parameters
            if not description or not description.strip():
                return f"❌ Error: 'description' parameter is required and cannot be empty. The task tool requires BOTH 'subagent_type' AND 'description'. This error usually means the model hit max_tokens while generating tool calls. Please retry with a briefer explanation before the tool calls."
            
            if subagent_type not in agents:
                return f"Error: invoked agent of type {subagent_type}, the only allowed types are {[f'`{k}`' for k in agents]}"

            set_agent_context("subagent", f"subagent_{subagent_type}", subagent_type)

            log_subagent_call(subagent_type, description)
            
            # Emit SUBAGENT_START event for streaming (sync version - schedule coroutine)
            subagent_id = f"subagent_{subagent_type}_{tool_call_id[:8]}"
            try:
                from api.streaming.emitter import get_current_emitter
                import asyncio
                emitter = get_current_emitter()
                if emitter:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(emitter.emit_subagent_start(
                            agent_id=subagent_id,
                            parent_call_id=tool_call_id,
                            subagent_description=description
                        ))
                    except RuntimeError:
                        pass  # No running loop
            except Exception:
                pass  # Don't break if streaming fails

            sub_agent = agents[subagent_type]
            # Create clean state for subagent with ONLY the task description
            # Filter to only pass the three critical context files to subagents
            files_dict = state.get("files", {}) if state else {}
            context_files = {
                k: v for k, v in files_dict.items()
                if k in [
                    "/workspace/context/tender_summary.md",
                    "/workspace/context/file_index.json",
                    "/workspace/context/cluster_id.txt",
                ]
            }
            get_unified_logger().logger.info(
                f"TASK_PASS_FILES: subagent={subagent_type} total_files={len(files_dict)} context_files={len(context_files)} keys={list(context_files.keys())}"
            )
            subagent_state = {
                "messages": [{"role": "user", "content": description}],
                "files": context_files,  # Only pass context files
                # Get cluster_id from top-level state, not file content
                "cluster_id": state.get("cluster_id") if state else None,
                # Don't pass todos or other accumulated context
            }
            import time
            subagent_start_time = time.time()
            result = sub_agent.invoke(subagent_state)
            subagent_execution_ms = int((time.time() - subagent_start_time) * 1000)
            
            # Emit SUBAGENT_END event for streaming (sync version - schedule coroutine)
            try:
                from api.streaming.emitter import get_current_emitter
                import asyncio
                emitter = get_current_emitter()
                if emitter:
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(emitter.emit_subagent_end(
                            agent_id=subagent_id,
                            parent_call_id=tool_call_id,
                            ms=subagent_execution_ms
                        ))
                    except RuntimeError:
                        pass  # No running loop
            except Exception:
                pass  # Don't break if streaming fails
            
            state_update = {}
            for k, v in result.items():
                if k not in ["todos", "messages"]:
                    state_update[k] = v
            return Command(
                update={
                    **state_update,
                    "messages": [
                        ToolMessage(
                            result["messages"][-1].content, tool_call_id=tool_call_id
                        )
                    ],
                }
            )

    # Fix the tool schema to remove injected parameters
    from src.deepagents.tools import _fix_injected_params_schema as _fix_schema
    return _fix_schema(task)


###########################
# Cache Monitoring Middleware (Phase 2)
###########################


class CacheMonitoringMiddleware(AgentMiddleware):
    """Track Anthropic prompt caching performance for observability and cost."""
    
    # Anthropic Claude 3.5 Sonnet pricing (as of 2025)
    # Source: https://www.anthropic.com/pricing
    COST_PER_1M_INPUT_TOKENS = 3.00  # $3 per 1M input tokens
    COST_PER_1M_OUTPUT_TOKENS = 15.00  # $15 per 1M output tokens
    COST_PER_1M_CACHE_WRITE = 3.75  # $3.75 per 1M tokens (cache creation)
    COST_PER_1M_CACHE_READ = 0.30  # $0.30 per 1M tokens (cache hits - 90% discount!)
    
    def __init__(self):
        """Initialize cache statistics tracking."""
        import logging
        self.logger = logging.getLogger(__name__)
        self.cache_stats = {
            "hits": 0,
            "misses": 0,
            "total_requests": 0,
            "tokens_saved": 0,
            "tokens_created": 0,
            # Token counts
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    
    def process_model_response(self, response, agent_state, runtime):
        """Track cache performance and costs from model response metadata."""
        self.logger.info(f"🔍 DEBUG: CacheMonitoringMiddleware.process_model_response called! Response type: {type(response)}")
        self.cache_stats["total_requests"] += 1
        
        # Extract usage metadata from response
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            # Try alternative attribute names
            usage = getattr(response, "response_metadata", {}).get("usage", {})
        
        self.logger.info(f"🔍 DEBUG: Usage metadata extracted: {usage}")
        
        if not usage:
            self.logger.warning(f"⚠️  No usage metadata found in response! Response attributes: {dir(response)}")
        
        if usage:
            # Extract all token counts
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            
            # Update totals
            self.cache_stats["input_tokens"] += input_tokens
            self.cache_stats["output_tokens"] += output_tokens
            self.cache_stats["cache_read_tokens"] += cache_read
            self.cache_stats["cache_write_tokens"] += cache_creation
            
            # Calculate costs for this request
            cost_input = (input_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS
            cost_output = (output_tokens / 1_000_000) * self.COST_PER_1M_OUTPUT_TOKENS
            cost_cache_read = (cache_read / 1_000_000) * self.COST_PER_1M_CACHE_READ
            cost_cache_write = (cache_creation / 1_000_000) * self.COST_PER_1M_CACHE_WRITE
            total_cost = cost_input + cost_output + cost_cache_read + cost_cache_write
            
            # Log detailed info
            if cache_read > 0:
                self.cache_stats["hits"] += 1
                self.cache_stats["tokens_saved"] += cache_read
                hit_rate = (self.cache_stats["hits"] / self.cache_stats["total_requests"]) * 100
                
                # Calculate savings (cache read vs normal input)
                saved_cost = (cache_read / 1_000_000) * (self.COST_PER_1M_INPUT_TOKENS - self.COST_PER_1M_CACHE_READ)
                
                self.logger.info(
                    f"✓ Cache HIT: {cache_read:,} tokens (saved ${saved_cost:.4f}) | "
                    f"Hit rate: {hit_rate:.1f}% | "
                    f"Cost: ${total_cost:.4f} (in:{input_tokens}, out:{output_tokens})"
                )
            else:
                self.cache_stats["misses"] += 1
                hit_rate = (self.cache_stats["hits"] / self.cache_stats["total_requests"]) * 100
                self.logger.info(
                    f"✗ Cache MISS | "
                    f"Hit rate: {hit_rate:.1f}% | "
                    f"Cost: ${total_cost:.4f} (in:{input_tokens}, out:{output_tokens})"
                )
            
            if cache_creation > 0:
                self.cache_stats["tokens_created"] += cache_creation
                self.logger.info(f"📝 Cache CREATED: {cache_creation:,} tokens (cost: ${cost_cache_write:.4f})")
        
        return response
    
    def get_stats_summary(self):
        """Return formatted cache statistics summary with cost analysis."""
        total = self.cache_stats["total_requests"]
        if total == 0:
            return "No cache statistics available yet."
        
        hit_rate = (self.cache_stats["hits"] / total) * 100
        
        # Calculate total costs
        input_tokens = self.cache_stats["input_tokens"]
        output_tokens = self.cache_stats["output_tokens"]
        cache_read_tokens = self.cache_stats["cache_read_tokens"]
        cache_write_tokens = self.cache_stats["cache_write_tokens"]
        
        cost_input = (input_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS
        cost_output = (output_tokens / 1_000_000) * self.COST_PER_1M_OUTPUT_TOKENS
        cost_cache_read = (cache_read_tokens / 1_000_000) * self.COST_PER_1M_CACHE_READ
        cost_cache_write = (cache_write_tokens / 1_000_000) * self.COST_PER_1M_CACHE_WRITE
        total_cost = cost_input + cost_output + cost_cache_read + cost_cache_write
        
        # Calculate what it would have cost without caching
        cost_without_cache = ((input_tokens + cache_read_tokens) / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS + cost_output
        savings = cost_without_cache - total_cost
        savings_pct = (savings / cost_without_cache * 100) if cost_without_cache > 0 else 0
        
        return f"""
╔════════════════════════════════════════════════════════════════════════════╗
║                    CACHE PERFORMANCE & COST SUMMARY                        ║
╚════════════════════════════════════════════════════════════════════════════╝

📊 Cache Statistics:
   • Total Requests: {total}
   • Cache Hits: {self.cache_stats['hits']} ({hit_rate:.1f}%)
   • Cache Misses: {self.cache_stats['misses']}
   • Tokens Cached: {cache_read_tokens:,} (saved from re-processing)
   • Tokens Written to Cache: {cache_write_tokens:,}

🔢 Token Usage:
   • Input Tokens: {input_tokens:,}
   • Output Tokens: {output_tokens:,}
   • Cache Read Tokens: {cache_read_tokens:,}
   • Cache Write Tokens: {cache_write_tokens:,}
   • Total Tokens: {input_tokens + output_tokens + cache_read_tokens + cache_write_tokens:,}

💰 Cost Breakdown:
   • Input Cost: ${cost_input:.4f} ({input_tokens:,} tokens @ ${self.COST_PER_1M_INPUT_TOKENS}/1M)
   • Output Cost: ${cost_output:.4f} ({output_tokens:,} tokens @ ${self.COST_PER_1M_OUTPUT_TOKENS}/1M)
   • Cache Read Cost: ${cost_cache_read:.4f} ({cache_read_tokens:,} tokens @ ${self.COST_PER_1M_CACHE_READ}/1M) ⚡
   • Cache Write Cost: ${cost_cache_write:.4f} ({cache_write_tokens:,} tokens @ ${self.COST_PER_1M_CACHE_WRITE}/1M)
   • TOTAL COST: ${total_cost:.4f}

💸 Savings from Caching:
   • Cost without cache: ${cost_without_cache:.4f}
   • Cost with cache: ${total_cost:.4f}
   • Savings: ${savings:.4f} ({savings_pct:.1f}% cheaper!)

📈 Cache Efficiency:
   • Cache hit rate: {hit_rate:.1f}%
   • Tokens saved from cache: {cache_read_tokens:,}
   • Cost savings per cache hit: ${ (savings / self.cache_stats['hits']) if self.cache_stats['hits'] > 0 else 0:.6f}
"""


###########################
# Tool Output Compaction Middleware (Phase 1)
###########################


class ToolOutputCompactionMiddleware(AgentMiddleware):
    """Compact old get_file_content outputs to save context space.
    
    Following Manus principle: "drop big blobs from the window but retain resolvable pointers."
    Keeps recent exchanges intact for working memory.
    """
    
    TOOLS_TO_COMPACT = ["get_file_content"]
    KEEP_RECENT_EXCHANGES = 2  # Keep last 2 Q&A pairs intact (4 messages)
    
    def __init__(self):
        """Initialize compaction middleware."""
        import logging
        self.logger = logging.getLogger(__name__)
        self.compaction_stats = {"total_compacted": 0, "tokens_saved": 0}
    
    def modify_model_request(
        self, request: ModelRequest, agent_state: AgentState, runtime: Runtime
    ) -> ModelRequest:
        """Compact old get_file_content outputs before sending to model."""
        messages = request.messages
        
        if len(messages) <= self.KEEP_RECENT_EXCHANGES * 2:
            # Not enough messages to compact
            return request
        
        # Protect recent messages (last 2 exchanges = 4 messages minimum)
        protect_from_index = max(0, len(messages) - (self.KEEP_RECENT_EXCHANGES * 2))
        
        # Build a map of tool_call_id -> tool call info for metadata extraction
        tool_call_map = {}
        for i, msg in enumerate(messages):
            # AIMessage contains tool_calls (the requests)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    # Handle both dict and object tool_call formats
                    if isinstance(tool_call, dict):
                        tool_call_id = tool_call.get("id")
                        tool_call_name = tool_call.get("name")
                        tool_call_args = tool_call.get("args", {})
                    else:
                        tool_call_id = getattr(tool_call, "id", None)
                        tool_call_name = getattr(tool_call, "name", None)
                        tool_call_args = getattr(tool_call, "args", {})
                    
                    if tool_call_id and tool_call_name == "get_file_content":
                        tool_call_map[tool_call_id] = {
                            "name": tool_call_name,
                            "args": tool_call_args
                        }
                        self.logger.debug(f"[Compaction] Mapped {tool_call_id} -> get_file_content(file_id={tool_call_args.get('file_id', '?')})")
        
        compacted_messages = []
        for i, msg in enumerate(messages):
            if i >= protect_from_index:
                # Keep recent intact
                compacted_messages.append(msg)
            elif self._is_get_file_content_output(msg):
                # Compact old file outputs
                compacted = self._compact_message(msg, tool_call_map)
                compacted_messages.append(compacted)
                
                # Track savings
                original_size = len(str(msg.content))
                compacted_size = len(str(compacted.content))
                tokens_saved = (original_size - compacted_size) // 4  # Rough estimate
                self.compaction_stats["total_compacted"] += 1
                self.compaction_stats["tokens_saved"] += tokens_saved
                
                self.logger.info(
                    f"📦 Compacted get_file_content output: "
                    f"{original_size:,} → {compacted_size:,} chars "
                    f"(~{tokens_saved:,} tokens saved)"
                )
            else:
                # Keep other messages as-is
                compacted_messages.append(msg)
        
        request.messages = compacted_messages
        return request
    
    def _is_get_file_content_output(self, msg) -> bool:
        """Check if message is a get_file_content tool output."""
        # Check if it's a tool message from get_file_content
        if not hasattr(msg, "type") or msg.type != "tool":
            return False
        
        # Check tool name in message or adjacent message
        tool_name = getattr(msg, "name", "")
        if tool_name == "get_file_content":
            return True
        
        # Check content for file content markers (fallback)
        content = str(msg.content)
        if len(content) > 10000:  # Large outputs likely from get_file_content
            return True
        
        return False
    
    def _compact_message(self, msg, tool_call_map):
        """Replace large file content with resolvable reference."""
        content = str(msg.content)
        original_size = len(content)
        
        # Get file_id from the original tool call (not from content)
        tool_call_id = getattr(msg, "tool_call_id", None)
        file_id = "unknown"
        filename = "Unknown file"
        
        # Debug: Log what we're trying to match
        self.logger.debug(f"[Compaction] Looking for tool_call_id: {tool_call_id}")
        self.logger.debug(f"[Compaction] Available IDs in map: {list(tool_call_map.keys())}")
        
        if tool_call_id and tool_call_id in tool_call_map:
            tool_info = tool_call_map[tool_call_id]
            args = tool_info.get("args", {})
            file_id = args.get("file_id", "unknown")
            
            # Use file_id as filename (will show the actual MongoDB ID)
            filename = file_id
            
            self.logger.info(f"✓ Extracted from tool call: file_id={file_id}")
        else:
            # Fallback: try to extract from content
            self.logger.warning(f"⚠️  Tool call ID '{tool_call_id}' not found in map, trying content extraction")
            extracted_id = self._extract_file_id(content)
            if extracted_id != "unknown":
                file_id = extracted_id
                filename = file_id
                self.logger.info(f"✓ Extracted from content: file_id={file_id}")
        
        # Create compact reference (simple format)
        compact_content = f"""📄 File content reference (compacted to save context space)
File: {filename}
File ID: {file_id}
Original size: ~{original_size:,} characters (~{original_size // 4:,} tokens)

Note: This content was automatically compacted to save context space.
To access this file again, call: get_file_content(file_id='{file_id}')
"""
        
        # Create new message with same metadata but compact content
        from langchain_core.messages import ToolMessage
        compacted = ToolMessage(
            content=compact_content,
            tool_call_id=getattr(msg, "tool_call_id", "unknown"),
            name=getattr(msg, "name", "get_file_content")
        )
        
        return compacted
    
    def _extract_file_id(self, content: str) -> str:
        """Extract file_id from content."""
        import re
        # Try to find file_id pattern
        match = re.search(r'file_id["\s:=]+([a-f0-9]{24})', content, re.IGNORECASE)
        if match:
            return match.group(1)
        return "unknown"
    
    def _extract_filename(self, content: str) -> str:
        """Extract filename from content."""
        import re
        # Try to find filename pattern
        match = re.search(r'(?:File:|Filename:)\s*([^\n]+)', content, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Fallback: Look for common file extensions
        match = re.search(r'([^\\/\n]+\.(?:pdf|docx?|xlsx?|txt|md))', content, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return "Unknown file"
    
    def get_stats_summary(self):
        """Return formatted compaction statistics summary."""
        return f"""
Tool Output Compaction Summary:
- Files Compacted: {self.compaction_stats['total_compacted']}
- Tokens Saved: {self.compaction_stats['tokens_saved']:,}
"""


###########################
# Persistent Summarization Middleware
###########################


class PersistentSummarizationMiddleware(AgentMiddleware):
    """Inject persistent conversation summaries into context.
    
    Summaries are created and stored by ReactAgent's ConversationSummaryManager.
    This middleware only handles injection during requests.
    """
    
    def __init__(self, summary_manager):
        """Initialize with summary manager from ReactAgent."""
        import logging
        self.logger = logging.getLogger(__name__)
        self.summary_manager = summary_manager
    
    def modify_model_request(
        self, request: ModelRequest, agent_state: AgentState, runtime: Runtime
    ) -> ModelRequest:
        """Inject summary if available."""
        try:
            thread_id = runtime.config.get("configurable", {}).get("thread_id")
            if not thread_id:
                return request
            
            # Inject summary (replaces old messages with summary)
            request = self.summary_manager.inject_summary(thread_id, request)
            
        except Exception as e:
            self.logger.error(f"Error injecting summary: {e}")
            # Don't fail the request, just skip summarization
        
        return request


###########################
# Tender Summarization Preprocessor (Phase 5)
###########################


class TenderSummarizationPreprocessor(AgentMiddleware):
    """Pre-process messages with tender-specific compression before LLM summarization.
    
    Applies domain-aware rules to preserve tender citations and key facts
    while reducing token usage.
    """
    
    def __init__(self, max_tokens_threshold=120000):
        """Initialize with token threshold for triggering compression."""
        import logging
        self.logger = logging.getLogger(__name__)
        self.max_tokens_threshold = max_tokens_threshold
        self.compression_stats = {"messages_compressed": 0, "tokens_saved": 0}
    
    def modify_model_request(
        self, request: ModelRequest, agent_state: AgentState, runtime: Runtime
    ) -> ModelRequest:
        """Apply domain-specific compression when approaching token threshold."""
        messages = request.messages
        
        # Estimate tokens (rough: 1 token ≈ 4 chars)
        total_chars = sum(len(str(m.content)) for m in messages)
        estimated_tokens = total_chars // 4
        
        # Only apply if approaching threshold (80%)
        threshold = self.max_tokens_threshold * 0.8
        if estimated_tokens < threshold:
            return request
        
        self.logger.info(
            f"🔧 Applying tender-specific compression: "
            f"{estimated_tokens:,} tokens (threshold: {threshold:,})"
        )
        
        # Apply domain-specific compression
        compressed_messages = []
        for msg in messages:
            compressed = self._compress_message(msg)
            compressed_messages.append(compressed)
            
            # Track savings
            if compressed != msg:
                original_size = len(str(msg.content))
                compressed_size = len(str(compressed.content))
                tokens_saved = (original_size - compressed_size) // 4
                self.compression_stats["messages_compressed"] += 1
                self.compression_stats["tokens_saved"] += tokens_saved
        
        request.messages = compressed_messages
        
        # Log final savings
        new_total_chars = sum(len(str(m.content)) for m in compressed_messages)
        new_estimated_tokens = new_total_chars // 4
        total_saved = estimated_tokens - new_estimated_tokens
        
        self.logger.info(
            f"✓ Compression complete: {estimated_tokens:,} → {new_estimated_tokens:,} tokens "
            f"(saved {total_saved:,} tokens, {(total_saved/estimated_tokens)*100:.1f}%)"
        )
        
        return request
    
    def _compress_message(self, msg):
        """Apply tender-specific compression rules."""
        
        # Rule 1: User queries - NEVER compress
        if hasattr(msg, "type") and msg.type == "human":
            return msg
        
        # Rule 2: Already-compacted references - NEVER touch
        if "📄 File content reference (compacted)" in str(msg.content):
            return msg
        
        # Rule 3: File references - already compact
        if hasattr(msg, "type") and msg.type == "tool" and "file_ref" in str(msg.content):
            return msg
        
        # Rule 4: Failed tool calls - compress to error type only
        if hasattr(msg, "type") and msg.type == "tool" and "ERROR:" in str(msg.content):
            return self._compress_error(msg)
        
        # Rule 5: Search results - keep citations, compress prose
        if hasattr(msg, "name") and msg.name == "search_tender_corpus":
            return self._compress_search(msg)
        
        # Rule 6: Assistant responses - keep structure + facts
        if hasattr(msg, "type") and msg.type == "ai":
            return self._compress_assistant(msg)
        
        return msg
    
    def _compress_error(self, msg):
        """Keep error type, drop verbose details."""
        content = str(msg.content)
        if "ERROR:" in content and len(content) > 500:
            # Extract just the first line (error type)
            error_line = content.split("\n")[0]
            
            # Create compressed message
            compressed = msg.copy() if hasattr(msg, "copy") else msg
            compressed.content = f"{error_line}\n(Details omitted to save context)"
            
            return compressed
        return msg
    
    def _compress_search(self, msg):
        """Keep citations and key points, compress prose."""
        content = str(msg.content)
        if len(content) < 1000:
            return msg  # Already compact
        
        lines = content.split("\n")
        
        # Extract important elements
        citations = [l for l in lines if "[Source:" in l or "File:" in l]
        key_points = [l for l in lines if l.strip().startswith(("- ", "• ", "1.", "2.", "3.", "4.", "5."))]
        headers = [l for l in lines if l.startswith("#")]
        
        # Build compressed content
        compressed_content = "\n".join([
            "Search results (domain-compressed):",
            *headers[:3],
            "",
            *key_points[:15],  # Keep top 15 bullet points
            "",
            "Sources:",
            *citations[:8],  # Keep top 8 citations
            "",
            "(Full synthesis compressed to save context. Key facts and citations preserved.)"
        ])
        
        # Only compress if we actually saved space
        if len(compressed_content) < len(content) * 0.7:
            from langchain_core.messages import ToolMessage
            compressed = ToolMessage(
                content=compressed_content,
                tool_call_id=getattr(msg, "tool_call_id", "unknown"),
                name=getattr(msg, "name", "search_tender_corpus")
            )
            return compressed
        
        return msg
    
    def _compress_assistant(self, msg):
        """Keep headers, citations, bullets; remove verbose prose."""
        content = str(msg.content)
        if len(content) < 2000:
            return msg  # Already compact
        
        lines = content.split("\n")
        important = []
        
        for line in lines:
            # Keep important elements
            if (line.startswith("#") or                          # Headers
                "[Source:" in line or                            # Citations
                "File:" in line or                                # File references
                line.strip().startswith(("- ", "• ", "1.", "2.", "3.", "4.", "5.")) or  # Bullets/lists
                (len(line) < 200 and line.strip() and not line.strip().endswith((".", ":", "!")))):  # Short statements
                important.append(line)
        
        compressed_content = "\n".join(important)
        
        # Only compress if we saved significant space (>30%)
        if len(compressed_content) < len(content) * 0.7:
            from langchain_core.messages import AIMessage
            compressed = AIMessage(content=compressed_content + "\n\n(Verbose explanations compressed to save context)")
            
            # Preserve message ID if present
            if hasattr(msg, "id"):
                compressed.id = msg.id
            
            return compressed
        
        return msg
    
    def get_stats_summary(self):
        """Return formatted compression statistics summary."""
        return f"""
Tender Summarization Preprocessor Summary:
- Messages Compressed: {self.compression_stats['messages_compressed']}
- Tokens Saved: {self.compression_stats['tokens_saved']:,}
"""
