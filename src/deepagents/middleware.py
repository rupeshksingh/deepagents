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
from langchain_core.tools import BaseTool, tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain.agents.tool_node import InjectedState
from langchain.chat_models import init_chat_model
from langgraph.types import Command
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
        self, request: ModelRequest, agent_state: PlanningState
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
        self, request: ModelRequest, agent_state: FilesystemState
    ) -> ModelRequest:
        request.system_prompt = (
            request.system_prompt + "\n\n" + FILESYSTEM_SYSTEM_PROMPT
        )
        return request


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
        self, request: ModelRequest, agent_state: AgentState
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
            prompt=BASE_AGENT_PROMPT,
            tools=default_subagent_tools,
            checkpointer=False,
            middleware=default_subagent_middleware,
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
            prompt=_agent["prompt"],
            tools=_tools,
            middleware=_middleware,
            checkpointer=False,
            # Note: State schema inherited via FilesystemMiddleware.state_schema
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

    if is_async:

        @tool(
            description=TASK_TOOL_DESCRIPTION.format(other_agents=other_agents_string)
        )
        @log_tool_call
        async def task(
            description: str,
            subagent_type: str,
            state: Annotated[FilesystemState, InjectedState],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ):
            if subagent_type not in agents:
                return f"Error: invoked agent of type {subagent_type}, the only allowed types are {[f'`{k}`' for k in agents]}"

            set_agent_context("subagent", f"subagent_{subagent_type}", subagent_type)

            log_subagent_call(subagent_type, description)

            sub_agent = agents[subagent_type]
            # Create clean state for subagent with ONLY the task description
            # Subagents should use read_file to access context, not inherit pre-loaded content
            # This prevents context explosion (main agent's pre-loaded context + subagent's file reads)
            subagent_state = {
                "messages": [{"role": "user", "content": description}],
                "files": state.get("files", {}),  # Pass files dict for read_file access
                # Don't pass todos or other accumulated context
            }
            result = await sub_agent.ainvoke(subagent_state)
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
            state: Annotated[FilesystemState, InjectedState],
            tool_call_id: Annotated[str, InjectedToolCallId],
        ):
            if subagent_type not in agents:
                return f"Error: invoked agent of type {subagent_type}, the only allowed types are {[f'`{k}`' for k in agents]}"

            set_agent_context("subagent", f"subagent_{subagent_type}", subagent_type)

            log_subagent_call(subagent_type, description)

            sub_agent = agents[subagent_type]
            # Create clean state for subagent with ONLY the task description
            # Subagents should use read_file to access context, not inherit pre-loaded content
            # This prevents context explosion (main agent's pre-loaded content + subagent's file reads)
            subagent_state = {
                "messages": [{"role": "user", "content": description}],
                "files": state.get("files", {}),  # Pass files dict for read_file access
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

    return task
