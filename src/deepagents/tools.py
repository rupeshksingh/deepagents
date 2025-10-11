from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain.agents.tool_node import InjectedState
from langgraph.types import Command
from typing import Annotated, Union
from src.deepagents.state import Todo, FilesystemState
from src.deepagents.prompts import (
    WRITE_TODOS_TOOL_DESCRIPTION,
    LIST_FILES_TOOL_DESCRIPTION,
    READ_FILE_TOOL_DESCRIPTION,
    WRITE_FILE_TOOL_DESCRIPTION,
    EDIT_FILE_TOOL_DESCRIPTION,
)
from src.deepagents.logging_utils import log_tool_call

@tool(description=WRITE_TODOS_TOOL_DESCRIPTION)
@log_tool_call
def write_todos(
    todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id)
            ],
        }
    )

@tool(description=LIST_FILES_TOOL_DESCRIPTION)
@log_tool_call
def ls(state: Annotated[FilesystemState, InjectedState]) -> list[str]:
    """List all files"""
    return list(state.get("files", {}).keys())

@tool(description=READ_FILE_TOOL_DESCRIPTION)
@log_tool_call
def read_file(
    file_path: str,
    state: Annotated[FilesystemState, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    mock_filesystem = state.get("files", {})
    if file_path not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    content = mock_filesystem[file_path]

    if not content or content.strip() == "":
        return "System reminder: File exists but has empty contents"

    lines = content.splitlines()

    start_idx = offset
    end_idx = min(start_idx + limit, len(lines))

    if start_idx >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

    result_lines = []
    for i in range(start_idx, end_idx):
        line_content = lines[i]

        if len(line_content) > 2000:
            line_content = line_content[:2000]

        line_number = i + 1
        result_lines.append(f"{line_number:6d}\t{line_content}")

    return "\n".join(result_lines)

@tool(description=WRITE_FILE_TOOL_DESCRIPTION)
@log_tool_call
def write_file(
    file_path: str,
    content: str,
    state: Annotated[FilesystemState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)
            ],
        }
    )

@tool(description=EDIT_FILE_TOOL_DESCRIPTION)
@log_tool_call
def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    state: Annotated[FilesystemState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    replace_all: bool = False,
) -> Union[Command, str]:
    """Write to a file."""
    mock_filesystem = state.get("files", {})
    if file_path not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    content = mock_filesystem[file_path]

    if old_string not in content:
        return f"Error: String not found in file: '{old_string}'"

    if not replace_all:
        occurrences = content.count(old_string)
        if occurrences > 1:
            return f"Error: String '{old_string}' appears {occurrences} times in file. Use replace_all=True to replace all instances, or provide a more specific string with surrounding context."
        elif occurrences == 0:
            return f"Error: String not found in file: '{old_string}'"

    if replace_all:
        new_content = content.replace(old_string, new_string)
        replacement_count = content.count(old_string)
        result_msg = f"Successfully replaced {replacement_count} instance(s) of the string in '{file_path}'"
    else:
        new_content = content.replace(
            old_string, new_string, 1
        )
        result_msg = f"Successfully replaced string in '{file_path}'"

    mock_filesystem[file_path] = new_content
    return Command(
        update={
            "files": mock_filesystem,
            "messages": [ToolMessage(result_msg, tool_call_id=tool_call_id)],
        }
    )