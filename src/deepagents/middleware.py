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
        tool_name = tool_call.get("name", "")
        # For filesystem tools, inject state from agent_state since InjectedState
        # doesn't work across graph boundaries (parent → subagent)
        if tool_name in ["ls", "read_file", "write_file", "edit_file"]:
            args = tool_call.get("args", {})
            # Inject minimal state with only 'files' to avoid bloating tool call traces
            # (Tools only need the files dict, not entire agent state)
            args["state"] = {"files": agent_state.get("files", {})}
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
        # TODO: Add this back when fixed
        SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=60000,
            messages_to_keep=12,
        ),
        AnthropicPromptCachingMiddleware(ttl="5m", unsupported_model_behavior="ignore"),
    ]
    agents = {
        "general-purpose": create_agent(
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
            result = await sub_agent.ainvoke(subagent_state)
            get_unified_logger().logger.warning(
                f"SUBAGENT_RESULT_DEBUG: {subagent_type} returned, result_keys={list(result.keys()) if isinstance(result, dict) else 'not_dict'}, files_in_result={len(result.get('files', {})) if isinstance(result, dict) else 0}"
            )
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
            result = sub_agent.invoke(subagent_state)
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
