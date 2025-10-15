# Proposal-Assistant Repository Guide

> **Last Updated**: October 15, 2024  
> **Purpose**: AI-powered proposal and tender analysis assistant using multi-agent architecture  
> **Stack**: Python, LangChain, LangGraph, Anthropic Claude, OpenAI, MongoDB

## 🎯 Quick Overview

This is a **multi-agent proposal analysis system** with:
- **Main Agent**: React-based orchestrator with sub-agents
- **Sub-agents**: Specialized for document analysis and web research
- **Storage**: MongoDB (production) / InMemorySaver (development)
- **LLM**: Claude Sonnet 4.5 (Anthropic)
- **Architecture**: LangGraph-based agent framework with middleware pipeline

## 📁 Repository Structure

```
Proposal-Assistant/
├── src/deepagents/          # Core agent framework
│   ├── graph.py             # Agent graph builder (async_create_deep_agent)
│   ├── state.py             # State definitions (DeepAgentState)
│   ├── tools.py             # Built-in tools (write_todos, read_file, etc.)
│   ├── middleware.py        # Planning, Filesystem, SubAgent middleware
│   ├── logging_utils.py     # Unified logging system
│   └── streaming_middleware.py  # Event streaming for UI
├── api/                     # FastAPI backend
│   ├── router.py            # HTTP endpoints
│   ├── streaming_router.py  # SSE streaming endpoints
│   └── streaming/           # Event persistence & emission
├── react_agent.py           # Production agent (MongoDB)
├── react_agent_memory.py    # Development agent (InMemorySaver) ⭐ NEW
├── tools.py                 # Domain-specific tools (search_tender_corpus, etc.)
├── prompts.py               # System prompts
├── test_agent/              # Test suite
│   ├── test_inmemory.py     # Multi-turn conversation tests ⭐ NEW
│   └── run_all_tests.py     # Full test runner
└── logs/                    # Structured logging output
```

## 🔥 Recent Major Changes (Oct 2024)

### Async Tool Support & Middleware Fixes

**Status**: ✅ Complete and Tested (Latest: Oct 15, 2024)

#### The Problems Encountered
1. **Middleware Signature Error**: `MessageTrimmingMiddleware.modify_model_request() takes 3 positional arguments but 4 were given`
2. **Async Tool Error**: `StructuredTool does not support sync invocation`
3. **Missing Async Methods**: `Asynchronous implementation of awrap_model_call is not available`
4. **Import Error**: `ToolConfig` import failing in newer LangChain versions

#### The Solutions

##### 1. Middleware Signature Fix
**Problem**: Middleware methods missing the `runtime` parameter required by LangGraph.

**Solution**: Added `runtime: Runtime` parameter to all middleware methods:
```python
from langgraph.runtime import Runtime

def modify_model_request(
    self, request: ModelRequest, agent_state: DeepAgentState, runtime: Runtime
) -> ModelRequest:
    # Implementation
    return request

async def amodify_model_request(
    self, request: ModelRequest, agent_state: DeepAgentState, runtime: Runtime
) -> ModelRequest:
    # Async version
    return self._trim_messages(request, agent_state)
```

##### 2. Async Tool Support
**Problem**: Tools like `search_tender_corpus`, `retrieve_full_document`, `web_search` are async but were being called with sync `invoke()`.

**Solution**: Changed to use `ainvoke()` directly:
```python
# OLD (caused "StructuredTool does not support sync invocation"):
loop = asyncio.get_event_loop()
response = await loop.run_in_executor(
    None, lambda: self.agent.invoke(state_input, config=config)
)

# NEW (works with async tools):
response = await self.agent.ainvoke(state_input, config=config)
```

##### 3. Custom Middleware Stack
**Problem**: Built-in LangChain middleware (`SummarizationMiddleware`, `AnthropicPromptCachingMiddleware`, `HumanInTheLoopMiddleware`) don't support async.

**Solution**: Created custom middleware stack for `ReactAgentMemory`:
```python
from langchain.agents import create_agent
from src.deepagents.middleware import (
    PlanningMiddleware,
    FilesystemMiddleware,
    SubAgentMiddleware,
    ToolCallLoggingMiddleware,
)

# Build async-compatible middleware stack
async_compatible_middleware = [
    ToolCallLoggingMiddleware(...),
    PlanningMiddleware(),
    FilesystemMiddleware(),
    SubAgentMiddleware(..., is_async=True),
    # Custom middleware (MessageTrimming, MessageDeletion)
    *custom_middleware,
]

# Use create_agent directly instead of async_create_deep_agent
agent_graph = create_agent(
    model,
    system_prompt=TENDER_ANALYSIS_SYSTEM_PROMPT + "\n\n" + BASE_AGENT_PROMPT,
    tools=tools,
    middleware=async_compatible_middleware,
    context_schema=DeepAgentState,
    checkpointer=self.checkpointer,
)
```

##### 4. Streaming Middleware Async Methods
**Problem**: `StreamingMiddleware` and `PlanningStreamingMiddleware` only had sync methods.

**Solution**: Added async method implementations:
```python
class StreamingMiddleware(AgentMiddleware):
    def modify_tool_call(self, tool_call, agent_state):
        # Sync implementation
        return tool_call
    
    async def amodify_tool_call(self, tool_call, agent_state):
        # Async version
        return self.modify_tool_call(tool_call, agent_state)
```

##### 5. Import Fix
**Problem**: `ToolConfig` import failing in LangChain.

**Solution**: Use alias from correct import:
```python
# Wrong (fails):
from langchain.agents.middleware.human_in_the_loop import ToolConfig

# Correct (works):
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig as ToolConfig
```

#### Files Modified
- `react_agent_memory.py` - Async invocation, custom middleware stack
- `src/deepagents/graph.py` - Import fix for ToolConfig
- `src/deepagents/streaming_middleware.py` - Added async methods
- `test_agent/test_inmemory.py` - Simplified to clean 5-10 question test

#### Test Results
```bash
# Run with example questions
python test_agent/test_inmemory.py --example tender_analysis

✅ All 5 questions processed successfully
✅ Response times tracked: Total 124s, Average 25s/query
✅ Memory Maintained: YES (90% confidence via ChatOpenAI)
✅ Context correctly recalled across conversation
```

#### Trade-offs & Limitations
- **Removed Middleware**: `SummarizationMiddleware` and `AnthropicPromptCachingMiddleware` removed from ReactAgentMemory
  - **Impact**: Less automatic prompt caching and summarization
  - **Mitigation**: Manual message trimming middleware compensates
- **No HumanInTheLoopMiddleware**: Disabled due to lack of async support
  - **Impact**: `request_human_input` tool won't interrupt for approval
  - **Mitigation**: Use `ReactAgent` (MongoDB) if this feature is needed

## 🏗️ Architecture

### Agent System

```
┌─────────────────────────────────────────────────┐
│ Main Agent (react_agent.py)                     │
│  - Orchestrates sub-agents                      │
│  - Handles user queries                         │
│  - Manages conversation state                   │
└──────────────────┬──────────────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌─────────────┐       ┌──────────────┐
│ Document    │       │ Web          │
│ Analyst     │       │ Researcher   │
│ Sub-agent   │       │ Sub-agent    │
└─────────────┘       └──────────────┘
```

### Middleware Pipeline

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│ 1. ToolCallLoggingMiddleware        │ Track all tool calls
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 2. PlanningMiddleware               │ Inject planning tools/prompts
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 3. FilesystemMiddleware             │ Inject file tools/virtual FS
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 4. SubAgentMiddleware               │ Enable sub-agent spawning
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 5. SummarizationMiddleware          │ Auto-summarize long contexts
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 6. AnthropicPromptCachingMiddleware │ Cache prompts for efficiency
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 7. StreamingMiddleware (custom)     │ Emit events for UI
└──────────┬──────────────────────────┘
           ▼
┌─────────────────────────────────────┐
│ 8. MessageTrimming/Deletion         │ Memory management (ReactAgentMemory)
└──────────┬──────────────────────────┘
           ▼
    LLM (Claude Sonnet 4.5)
```

### State Management

```python
class DeepAgentState(AgentState):
    todos: NotRequired[list[Todo]]                    # Planning state
    files: Annotated[NotRequired[dict[str, str]], file_reducer]  # Virtual FS
    cluster_id: NotRequired[str]                       # RAG cluster ID
    # messages inherited from AgentState
```

## 🔧 Key Components

### 1. Agent Types

| Component | File | Checkpointer | Use Case |
|-----------|------|--------------|----------|
| **ReactAgent** | `react_agent.py` | MongoDBSaver | Production, persistent state |
| **ReactAgentMemory** | `react_agent_memory.py` | InMemorySaver | Development, testing, fast iteration |

### 2. Core Tools

| Tool | Description | Location |
|------|-------------|----------|
| `search_tender_corpus` | RAG search over tender documents | `tools.py` |
| `retrieve_full_document` | Fetch complete document by ID | `tools.py` |
| `web_search` | Tavily web search integration | `tools.py` |
| `write_todos` | Create/update task plans | `src/deepagents/tools.py` |
| `read_file` / `write_file` | Virtual filesystem operations | `src/deepagents/tools.py` |
| `task` | Spawn sub-agent for complex analysis | Generated by SubAgentMiddleware |

### 3. Logging System

**Unified Logger** (`src/deepagents/logging_utils.py`):
- Tool call tracking with execution times
- Session-scoped logging (one file per session)
- Narrative logs for human readability
- Structured JSON logs for parsing
- Streaming event emission for UI

**Log Files**:
- `logs/tool_calls.log` - All tool calls with metadata
- `logs/narrative.log` - Human-readable narrative
- `logs/session_*.log` - Per-session narratives

## 💻 Common Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run main agent (MongoDB required)
python react_agent.py

# Run in-memory agent (no MongoDB)
python react_agent_memory.py

# Start API server
python main.py
# or
./start_api.sh
```

### Testing

```bash
# Simple 5-10 question test with example sets (RECOMMENDED)
python test_agent/test_inmemory.py --example tender_analysis
python test_agent/test_inmemory.py --example general
python test_agent/test_inmemory.py --example technical

# Custom questions (provide 5-10)
python test_agent/test_inmemory.py --questions "Q1?" "Q2?" "Q3?" "Q4?" "Q5?"

# Run all agent tests
python test_agent/run_all_tests.py

# Consolidated test runner
cd tests
python run_all_consolidated.py
```

**New test_inmemory.py features**:
- ⏱️ Tracks response time for each query
- 🧠 Evaluates memory using ChatOpenAI LLM judge
- 📊 Clean summary output with timing statistics
- ✅ Simple pass/fail based on memory evaluation

## 🔑 Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...      # Claude API key
OPENAI_API_KEY=sk-...             # OpenAI API key (for embeddings/judge)
MONGODB_URI=mongodb://...          # MongoDB connection

# Optional
TAVILY_API_KEY=tvly-...           # Web search
DEEPAGENTS_JSON_CONSOLE=1         # Enable JSON console logging
DEEPAGENTS_NARRATIVE_CONSOLE=1    # Enable narrative console output
```

## 🎓 How to Use Multi-Turn Conversations

### Basic Example

```python
import asyncio
from react_agent_memory import ReactAgentMemory

async def main():
    agent = ReactAgentMemory(org_id=1)
    thread_id = "user_123"
    
    # Turn 1
    r1 = await agent.chat_sync(
        "I'm working on a cloud services proposal",
        thread_id
    )
    print(r1['response'])
    
    # Turn 2 - Agent remembers!
    r2 = await agent.chat_sync(
        "What was I working on?",
        thread_id
    )
    print(r2['response'])  # "You mentioned cloud services proposal"

asyncio.run(main())
```

### Streaming Example

```python
async for chunk in agent.chat_streaming(query, thread_id):
    if chunk["chunk_type"] == "content":
        print(chunk["content"], end="")
```

### Check State

```python
state = agent.get_conversation_state(thread_id)
print(f"Messages: {state['message_count']}")

history = agent.get_conversation_history(thread_id)
for msg in history:
    print(f"{msg['role']}: {msg['content']}")
```

## 🐛 Common Issues & Solutions

### 1. "MessageTrimmingMiddleware.modify_model_request() takes 3 positional arguments but 4 were given"
**Status**: ✅ FIXED

**Cause**: Middleware methods missing `runtime` parameter.

**Solution**: All middleware now includes `runtime: Runtime` parameter in method signatures.

### 2. "StructuredTool does not support sync invocation"
**Status**: ✅ FIXED

**Cause**: Async tools (search_tender_corpus, web_search, etc.) called with sync `invoke()`.

**Solution**: ReactAgentMemory now uses `ainvoke()` directly instead of sync invoke wrapped in executor.

### 3. "Asynchronous implementation of awrap_model_call is not available"
**Status**: ✅ FIXED

**Cause**: Built-in LangChain middleware lack async support; custom middleware missing async methods.

**Solution**: 
- ReactAgentMemory uses custom middleware stack without sync-only middleware
- All custom middleware now have both sync and async method implementations

### 4. Import Errors - "cannot import name 'ToolConfig'"
**Status**: ✅ FIXED

**Cause**: LangChain changed the export name in newer versions.

**Solution**: Use `InterruptOnConfig as ToolConfig`:
```python
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig as ToolConfig
```

### 5. Context Not Maintained
**Troubleshooting**:
- ✅ Ensure same `thread_id` across calls
- ✅ Check `files: {}` is in state_input
- ✅ Verify checkpointer is initialized
- ✅ Test with: `python test_agent/test_inmemory.py --example general`

### 6. MongoDB Connection Issues
```python
# Production agent requires MongoDB
from pymongo import MongoClient
client = MongoClient(MONGODB_URI)
agent = ReactAgent(client, org_id=1)

# Development: use InMemorySaver instead (no MongoDB required)
agent = ReactAgentMemory(org_id=1)
```

## 📊 Performance Benchmarks

| Operation | ReactAgent (MongoDB) | ReactAgentMemory (InMemory) |
|-----------|---------------------|----------------------------|
| First query | ~20s | ~15s |
| Follow-up | ~12s | ~8-10s |
| State retrieval | ~200ms | ~1ms |
| Persistence | ✅ Across restarts | ❌ In-memory only |

## 🔍 Code Patterns

### Creating Custom Middleware

```python
from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langgraph.runtime import Runtime

class MyMiddleware(AgentMiddleware):
    def modify_model_request(
        self, request: ModelRequest, agent_state, runtime: Runtime
    ) -> ModelRequest:
        # Sync version
        request.system_prompt += "\n\nMy custom instructions"
        return request
    
    async def amodify_model_request(
        self, request: ModelRequest, agent_state, runtime: Runtime
    ) -> ModelRequest:
        # Async version - required for ainvoke() support
        return self.modify_model_request(request, agent_state, runtime)
```

**Important**: Always include both sync and async versions if your agent uses async tools!

### Adding Custom Tools

```python
from langchain_core.tools import tool
from src.deepagents.logging_utils import log_tool_call

@tool
@log_tool_call
def my_custom_tool(query: str) -> str:
    """Description for the LLM."""
    # Tool implementation
    return result

# Add to agent
tools = REACT_TOOLS + [my_custom_tool]
agent = ReactAgentMemory(tools=tools)
```

### State Reducer Pattern

```python
from typing import Annotated

def custom_reducer(left, right):
    """Merge logic for state fields."""
    if left is None:
        return right
    if right is None:
        return left
    return {**left, **right}  # Merge dicts

class MyState(AgentState):
    my_field: Annotated[NotRequired[dict], custom_reducer]
```

## 📝 Best Practices

### 1. Thread ID Management
- Use unique, descriptive thread IDs: `f"{user_id}_{session_id}"`
- Don't reuse thread IDs across different conversations
- Clean up old threads periodically

### 2. Memory Management
- Enable trimming for long conversations: `enable_message_trimming=True`
- Enable deletion for very long sessions: `enable_message_deletion=True`
- Tune thresholds based on your use case

### 3. Error Handling
```python
try:
    response = await agent.chat_sync(query, thread_id)
    if not response.get('success'):
        logger.error(f"Agent error: {response.get('error')}")
except Exception as e:
    logger.exception("Fatal error in chat")
```

### 4. Logging
```python
from src.deepagents.logging_utils import (
    log_query_start,
    log_query_end,
    set_agent_context
)

session_id = log_query_start(user_query)
try:
    # Process query
    log_query_end(session_id, response)
except Exception as e:
    log_query_end(session_id, f"Error: {e}")
```

## 🚀 Deployment Checklist

- [ ] Set all environment variables
- [ ] MongoDB connection configured and tested
- [ ] API keys validated (Anthropic, OpenAI, Tavily)
- [ ] Run full test suite: `python test_agent/run_all_tests.py`
- [ ] Check logs directory permissions
- [ ] Configure memory management thresholds
- [ ] Set up monitoring/alerting
- [ ] Document API endpoints (see `api/router.py`)

## 📚 Documentation Files

- `CURSOR.md` (this file) - Repository overview and guide
- `IMPLEMENTATION_SUMMARY.md` - Technical deep dive on multi-turn conversations
- `MULTITURN_CHANGES.md` - Line-by-line code changes
- `QUICK_START_MULTITURN.md` - Quick reference for multi-turn usage
- `ARCHITECTURE.md` - Original architecture documentation
- `FRONTEND_GUIDE.md` - Frontend integration guide
- `BACKGROUND_AGENTS_ARCHITECTURE.md` - Background agents design

## 🔗 Key Dependencies

```
langchain >= 0.3
langgraph >= 0.2
langchain-anthropic
langchain-openai
pymongo
fastapi
uvicorn
pydantic
```

## 🎯 Next Development Priorities

1. **Conversation Export/Import** - Save and restore conversations
2. **Advanced Memory Strategies** - Semantic memory, importance scoring
3. **Multi-Modal Support** - Handle images and files
4. **Performance Optimization** - Reduce latency for follow-up queries
5. **Metrics Dashboard** - Conversation analytics and monitoring

## 📞 Getting Help

1. **Check Logs**: `tail -f logs/narrative.log`
2. **Run Tests**: `python test_agent/test_inmemory.py --example tender_analysis`
3. **Review Docs**: See documentation files listed above
4. **Debug Mode**: Set environment variables for verbose logging

## 🔑 Key Takeaways for Future Development

### When Working with Middleware
- **Always add both sync and async versions** of middleware methods
- **Include `runtime: Runtime` parameter** in all `modify_model_request` signatures
- **Test with async tools** to ensure compatibility

### When Using ReactAgentMemory
- Uses **custom middleware stack** without sync-only LangChain middleware
- Supports **async tools** via `ainvoke()` 
- Trade-off: No automatic summarization or prompt caching
- Best for: **Development, testing, and scenarios with async tools**

### When Using ReactAgent (MongoDB)
- Uses **full middleware stack** including SummarizationMiddleware
- Better for: **Production with sync tools or when summarization is critical**
- Requires: **MongoDB connection**

## 🏷️ Version History

- **Oct 15, 2024 (Latest)**: 
  - ✅ Fixed async tool support (ainvoke instead of sync invoke)
  - ✅ Fixed middleware signature issues (added runtime parameter)
  - ✅ Added async methods to streaming middleware
  - ✅ Created custom async-compatible middleware stack
  - ✅ Fixed ToolConfig import error
  - ✅ Simplified test_inmemory.py to clean 5-10 question format
- **Oct 15, 2024 (Earlier)**: Multi-turn conversation support added to ReactAgentMemory
- **Oct 14, 2024**: Tools fixed, logging enhanced
- **Earlier**: Initial implementation with MongoDB persistence

---

**Pro Tip**: When in doubt, use `ReactAgentMemory` for development and testing, `ReactAgent` for production with persistent state.

