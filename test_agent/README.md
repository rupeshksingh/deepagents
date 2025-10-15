# Bid Management Agent Testing Guide

This directory contains testing utilities for the Bid Management Agent built on the Deep Agents framework.

## Overview

The `run_query.py` script provides a CLI interface to test the agent with proper logging, statistics tracking, and comprehensive output generation.

## Prerequisites

1. **Environment Setup**: Ensure you have a `.env` file in the project root with:
   ```bash
   MONGODB_URL=your_mongodb_connection_string
   TENDER_ID=your_default_tender_id
   ANTHROPIC_API_KEY=your_anthropic_api_key
   TAVILY_API_KEY=your_tavily_api_key  # For web search
   ```

2. **Virtual Environment**: Activate your virtual environment:
   ```bash
   source ../venv/bin/activate  # or your venv path
   ```

## Usage

### Basic Usage

Run with default query (from .env TENDER_ID):
```bash
python run_query.py
```

### Custom Query

```bash
python run_query.py "What are the key deadlines in this tender?"
```

### Multi-word Query

```bash
python run_query.py Extract all mandatory obligations related to persondata and it-security
```

### Testing Different Tenders

Set a different tender ID in your environment:
```bash
export TENDER_ID=68c99b8a10844521ad051544
python run_query.py "Summarize the tender scope"
```

## What Gets Generated

### 1. Console Output
The script provides real-time feedback:
- Query and context information (Run ID, Thread ID, Tender ID)
- Execution summary with statistics
- Response preview (first 500 chars)
- Log file locations

### 2. Output File: `run_output_YYYYMMDD_HHMMSS.txt`
A comprehensive report including:
- **Metadata**: Run ID, Thread ID, Tender ID, Duration
- **Execution Statistics**: 
  - Total tool calls
  - Tool usage breakdown (search_tender_corpus, get_file_content, web_search, etc.)
  - Execution times (avg, max, min)
  - Error count
- **Agent Thinking (Narrative)**: Step-by-step reasoning process
- **Final Response**: The complete agent response

### 3. Log Files

#### `logs/tool_calls.log`
Structured JSON logging of all tool calls with:
- Tool call start/end events
- Arguments and results
- Execution times
- Agent context

#### `logs/narrative.log`
Human-readable narrative of agent thinking:
- Session starts/ends
- Tool usage with thinking process
- Progress indicators

#### `logs/session_<session_id>.log`
Session-specific narrative log for each query execution.

## Logging System

The agent uses a unified logging system from `src/deepagents/logging_utils.py`:

### Features
- **Automatic tool call tracking**: All tool invocations are logged
- **Performance monitoring**: Execution time tracking
- **Context awareness**: Agent and subagent context tracking
- **Session isolation**: Each query gets its own session log
- **Statistics generation**: Tool usage analytics

### Controlling Log Output

**Disable JSON console output** (reduces noise):
```bash
export DEEPAGENTS_JSON_CONSOLE=0
```

**Disable narrative console output**:
```bash
export DEEPAGENTS_NARRATIVE_CONSOLE=0
```

## Example Test Queries

### Analysis Queries
```bash
# Compliance extraction
python run_query.py "Extract all GDPR and data protection requirements"

# Deadline analysis
python run_query.py "Create a timeline of all submission deadlines and milestones"

# Scope summary
python run_query.py "What is the contract scope and estimated value?"
```

### Document-Specific Queries
```bash
# Multi-document analysis (triggers document-analyzer subagent)
python run_query.py "Compare the technical requirements across all specification documents"

# Full document review
python run_query.py "Analyze the contract conditions document in detail"
```

### Research Queries
```bash
# Web research (triggers web-researcher subagent)
python run_query.py "What are the latest EU regulations on public procurement in 2025?"

# Market research
python run_query.py "Find information about the contracting authority's previous tenders"
```

### Complex Queries
```bash
# Multi-step analysis
python run_query.py "Identify all risk factors in this tender and suggest mitigation strategies based on EU best practices"
```

## Understanding the Output

### Execution Statistics
Monitor agent efficiency:
- **Tool Calls**: Number of times tools were invoked
- **Errors**: Failed tool calls (investigate if high)
- **Avg/Max/Min Execution Time**: Performance metrics

### Tool Usage Breakdown
See which tools the agent used:
- `search_tender_corpus`: RAG searches across tender documents
- `get_file_content`: Direct file retrieval (raw markdown)
- `web_search`: External research via Tavily
- `task`: Subagent delegation calls
- `read_file`, `write_file`, `ls`: Virtual filesystem operations

### Agent Thinking (Narrative)
Follow the agent's reasoning:
```
STEP 1: search tender corpus
   💭 Thinking: Search for 'GDPR requirements'
   🌐 Scope: all tender files
   ✓ Completed in 1.23s

STEP 2: task (document-analyzer)
   💭 Delegating to specialist for deep analysis
   ✓ Completed in 5.67s
```

## Troubleshooting

### "TENDER_ID not found"
Ensure your `.env` file has `TENDER_ID=<valid_id>` or export it:
```bash
export TENDER_ID=68c99b8a10844521ad051544
```

### "MONGODB_URL not found"
Add to `.env`:
```bash
MONGODB_URL=mongodb://localhost:27017  # or your connection string
```

### No logs directory
The script auto-creates `logs/` on first run. If issues persist:
```bash
mkdir -p logs
```

### Import errors
Ensure you're running from the correct directory and virtual environment:
```bash
cd test_agent/
source ../venv/bin/activate
python run_query.py
```

## Advanced Usage

### Programmatic Testing
Import and use the `run_query` function in your own scripts:

```python
import asyncio
from run_query import run_query

async def test_multiple_queries():
    queries = [
        "What is the tender scope?",
        "List all deadlines",
        "Extract GDPR requirements"
    ]
    
    for query in queries:
        result = await run_query(query, "68c99b8a10844521ad051544")
        print(f"Query: {query}")
        print(f"Success: {result['success']}")
        print("-" * 50)

asyncio.run(test_multiple_queries())
```

### Analyzing Logs Programmatically
```python
from src.deepagents.logging_utils import get_tool_call_stats, get_session_stats

# Overall statistics
stats = get_tool_call_stats()
print(f"Total tool calls: {stats['total_tool_calls']}")

# Session-specific statistics
session_stats = get_session_stats("<session_id>")
print(f"Session tool calls: {session_stats['tool_calls']}")
```

## Integration with Deep Agents Architecture

This test script validates the full Deep Agents implementation:

1. **Main Agent**: Orchestrator that receives your query
2. **Subagents**: 
   - `document-analyzer`: Multi-document analysis
   - `web-researcher`: External research
3. **Tools**:
   - `search_tender_corpus`: Hybrid RAG
   - `get_file_content`: Direct file access (max 40 pages)
   - `web_search`: Tavily integration
4. **Virtual Filesystem**: Context files auto-injected:
   - `/workspace/context/tender_summary.md`
   - `/workspace/context/file_index.json`
5. **State Management**: MongoDB checkpointer for conversation history

## Next Steps

After successful testing:
1. Review the narrative logs to understand agent reasoning
2. Check tool usage patterns for optimization opportunities
3. Analyze execution times to identify bottlenecks
4. Test with various tender IDs and query types
5. Monitor error rates and investigate failures

## Support

For issues or questions:
1. Check the logs in `logs/` directory
2. Review the output file for detailed execution trace
3. Examine `logs/tool_calls.log` for JSON-structured events
4. Enable console logging for real-time debugging

