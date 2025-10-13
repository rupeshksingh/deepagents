from langchain_core.tools import tool, InjectedToolCallId, InjectedToolArg
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from typing import Annotated, Union, Optional
from langgraph.prebuilt import InjectedState
from pydantic import create_model
from src.deepagents.state import Todo, FilesystemState
from src.deepagents.prompts import (
    WRITE_TODOS_TOOL_DESCRIPTION,
    LIST_FILES_TOOL_DESCRIPTION,
    READ_FILE_TOOL_DESCRIPTION,
    WRITE_FILE_TOOL_DESCRIPTION,
    EDIT_FILE_TOOL_DESCRIPTION,
)
from src.deepagents.logging_utils import log_tool_call

def _normalize_path(file_path: str, files_dict: dict[str, str]) -> str:
    """Normalize common path variants to keys present in files_dict.

    Strategy:
    - Known /workspace/context/* to canonical filenames used in ReactAgent
    - Exact match if present
    - Basename-insensitive lookup among files_dict keys
    """
    if not file_path:
        return file_path

    # Direct exact match
    if file_path in files_dict:
        return file_path

    # Map known context basenames
    lower = file_path.lower()
    if lower.endswith("/context/tender_summary.md") or lower.endswith("tender_summary.md"):
        candidate = "/workspace/context/tender_summary.md"
        if candidate in files_dict:
            return candidate
    if lower.endswith("/context/file_index.json") or lower.endswith("file_index.json"):
        candidate = "/workspace/context/file_index.json"
        if candidate in files_dict:
            return candidate
    if lower.endswith("/context/cluster_id.txt") or lower.endswith("cluster_id.txt"):
        candidate = "/workspace/context/cluster_id.txt"
        if candidate in files_dict:
            return candidate
    if lower.endswith("/context/supplier_profile.md") or lower.endswith("supplier_profile.md"):
        candidate = "/workspace/context/supplier_profile.md"
        if candidate in files_dict:
            return candidate

    # Basename-insensitive match
    import os

    base = os.path.basename(file_path).lower()
    for key in files_dict.keys():
        if os.path.basename(key).lower() == base:
            return key

    return file_path

@tool(description=WRITE_TODOS_TOOL_DESCRIPTION)
@log_tool_call
def write_todos(
    todos: list[Todo], 
    tool_call_id: Annotated[str, InjectedToolCallId, InjectedToolArg]
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
def ls(state: Annotated[FilesystemState, InjectedState, InjectedToolArg]) -> list[str]:
    """List all files"""
    return list(state.get("files", {}).keys())


@tool(description=READ_FILE_TOOL_DESCRIPTION)
@log_tool_call
def read_file(
    file_path: str,
    state: Annotated[FilesystemState, InjectedState, InjectedToolArg],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    mock_filesystem = state.get("files", {})
    normalized = _normalize_path(file_path, mock_filesystem)
    if normalized not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    content = mock_filesystem[normalized]

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
    content: Optional[str] = None,
    state: Annotated[FilesystemState, InjectedState, InjectedToolArg] = None,
    tool_call_id: Annotated[str, InjectedToolCallId, InjectedToolArg] = "",
) -> Union[Command, str]:
    """Write content to a file in the virtual filesystem.

    Notes:
    - content is optional in schema to avoid pydantic hard-fail; we validate manually
    - on missing content, return a concise error string (no state echo), no state update
    """
    if content is None:
        return (
            "Error: write_file requires a 'content' string. Call as write_file(file_path=..., content=...)"
        )

    files = state.get("files", {}) if state else {}
    # Keep writes on exact given path; if caller used a known context basename, normalize
    target_path = _normalize_path(file_path, files)
    files[target_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {target_path}", tool_call_id=tool_call_id)
            ],
        }
    )


@tool(description=EDIT_FILE_TOOL_DESCRIPTION)
@log_tool_call
def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    state: Annotated[FilesystemState, InjectedState, InjectedToolArg],
    tool_call_id: Annotated[str, InjectedToolCallId, InjectedToolArg],
    replace_all: bool = False,
) -> Union[Command, str]:
    """Write to a file."""
    mock_filesystem = state.get("files", {})
    normalized = _normalize_path(file_path, mock_filesystem)
    if normalized not in mock_filesystem:
        return f"Error: File '{file_path}' not found"

    content = mock_filesystem[normalized]

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

    mock_filesystem[normalized] = new_content
    return Command(
        update={
            "files": mock_filesystem,
            "messages": [ToolMessage(result_msg, tool_call_id=tool_call_id)],
        }
    )
