# Danish Tender Analysis Agent - Architecture Documentation

## Executive Summary

This is a production-ready AI agent system built on LangGraph for analyzing Danish public procurement tenders. The agent uses a hierarchical architecture with specialized subagents, progressive information disclosure (L1/L2/L3), and mandatory citation tracking for high-stakes tender analysis.

**Key Capabilities:**
- Multi-document analysis with RAG (Retrieval Augmented Generation)
- Language-aware search (Danish/English adaptive queries)
- Human-in-the-loop for ambiguous decisions
- Persistent conversation memory across sessions
- Specialized subagents for focused analysis
- Virtual filesystem for artifact management

---

## 1. Core Architectural Principles

### 1.1 Progressive Disclosure (L1/L2/L3)

The agent accesses tender information through three escalating levels:

**L1 - Metadata (Filesystem Context)**
- **Purpose**: Fast overview, initial orientation
- **Location**: Virtual filesystem `/workspace/context/`
- **Contents**:
  - `tender_summary.md`: High-level overview (scope, deadlines, evaluation criteria)
  - `file_index.json`: Complete file inventory with summaries and IDs
  - `supplier_profile.md`: Bidding organization info (placeholder in MVP)
- **When Used**: ALWAYS the first step for any tender-related query

**L2 - Semantic Search (RAG)**
- **Purpose**: Find specific information across documents without reading entire files
- **Tool**: `search_tender_corpus(query, tender_id, file_ids=None)`
- **Technology**: Qdrant vector database with hybrid search (semantic + keyword)
- **Filter Strategy**: Scoped by `cluster_id` (tender-specific) and `metadata.type="pc"`
- **Returns**: Top 10 relevant chunks with citations `{file_name, file_id}`
- **When Used**: Targeted fact-finding, requirement extraction, cross-document searches

**L3 - Full Document Retrieval (MongoDB)**
- **Purpose**: Deep reading for verbatim quotes, legal analysis, contradiction detection
- **Tool**: `retrieve_full_document(file_id)`
- **Technology**: MongoDB with full markdown content
- **Returns**: Complete document text (average 15-50k characters)
- **When Used**: Precision tasks, document comparison, structural analysis

### 1.2 Language-Aware RAG Strategy

**Challenge**: Danish tender documents require Danish keywords for optimal retrieval.

**Solution**: Adaptive query refinement based on detected language

**Workflow**:
1. **Initial Search**: Use query language (often English from user)
2. **Language Detection**: Examine returned chunks for Danish indicators
   - Markers: "Leverandøren", "skal", "aftale", "krav", "betingelser"
3. **Adaptation**: If Danish detected, switch to Danish keywords
   - Example: "CSR requirements" → "samfundsansvar menneskerettigheder arbejdstagerrettigheder miljø"
4. **Refinement**: Continue with Danish-optimized queries

**Implementation**: Real-time detection in `_targeted_hybrid_search()` with console feedback `🇩🇰 DANISH` or `🇬🇧 English`

### 1.3 Single-Tender Scope Enforcement

**Guarantee**: One conversation thread = one tender. No cross-tender contamination.

**Implementation**:
- MongoDB collection: `threads` with binding `{thread_id, tender_id}`
- First query: Creates binding
- Subsequent queries: Validates binding, raises error if mismatch

**Code**: `ReactAgent._ensure_single_tender_scope()`

### 1.4 Traceability & Citations

**Requirement**: Every claim from tender documents MUST be cited.

**Citation Schema**:
```json
{
  "file_name": "02.15 Bilag E CSR.pdf",
  "file_id": "68c99b92bcf6f21608c63d1a"
}
```

**Display Format** (user-facing):
- Natural inline: `[Source: 02.15 Bilag E CSR.pdf]`
- With sections: `[Source: Contract.pdf, Section 3.2]`
- **Never** show `file_id` to users (internal use only)

**External Sources**: Web search results labeled separately with clickable links

---

## 2. Agent Hierarchy

### 2.1 Main Agent (Bid Coordinator)

**Role**: Orchestrator, planner, user interface, synthesizer

**Responsibilities**:
1. **Query Assessment**: Simple vs. complex, tender-specific vs. general
2. **Context Loading**: Read L1 files (`tender_summary.md`, `file_index.json`)
3. **Information Strategy**: Decide L1/L2/L3 approach, language detection
4. **Task Planning**: Create TODO lists for complex queries
5. **Delegation**: Assign focused tasks to subagents
6. **Synthesis**: Combine subagent results into coherent response
7. **Human Interaction**: Invoke HITL when needed, respond in user's language
8. **Quality Control**: Ensure citations, separate external sources

**Available Tools**:
- L1: `read_file`, `ls`, `write_file` (filesystem)
- L2: `search_tender_corpus` (RAG)
- L3: `retrieve_full_document` (MongoDB)
- External: `web_search`
- Interaction: `request_human_input`
- Planning: `create_todo`, `update_todo`
- Delegation: `task(description, agent_type)`

**Persona**: Professional research assistant built by Pentimenti, bilingual (Danish/English), adaptive tone, quality-focused

### 2.2 Subagent: Document Analyzer

**Role**: Deep document analysis, comparison, synthesis with citations

**Specialization**:
- Single-file deep reading
- Multi-file comparison
- Contradiction detection
- Evidence extraction
- Report generation

**Available Tools**:
- `search_tender_corpus` (L2)
- `retrieve_full_document` (L3)
- Filesystem tools (save reports to `/workspace/analysis/`)

**Typical Tasks**:
- "Compare response time requirements in Contract A vs Contract B"
- "Extract all mandatory qualifications from SOW"
- "Identify exclusion criteria across all documents"
- "Summarize Annex E (CSR requirements)"

**Output**: Structured analysis with mandatory citations saved to `/workspace/analysis/*.md`

### 2.3 Subagent: Web Researcher

**Role**: External research with web search, context compilation

**Specialization**:
- Danish/Nordic/European regulatory context
- Market standards and benchmarks
- Company background research
- Technical definitions and standards
- Industry best practices

**Available Tools**:
- `web_search` (only tool)

**Typical Tasks**:
- "Research Danish data protection requirements for public contracts"
- "Find industry SLA benchmarks for IT services"
- "Background on Company X mentioned in tender"
- "Explain GDPR Article 28 requirements"

**Output**: Structured brief with "External Sources" section containing links

**Critical Rule**: Always label findings as external, never mix with tender-derived claims

---

## 3. Technology Stack

### 3.1 Core Framework

**LangGraph (LangChain)**
- State management: `DeepAgentState` with filesystem context
- Checkpointing: MongoDB-based persistence
- Tool calling: OpenAI function calling
- Streaming: Real-time response generation

### 3.2 LLM Models

**Main Agent**: Claude 3.5 Sonnet (Anthropic)
- Reasoning: Superior for complex planning and multi-step tasks
- Context: 200k tokens
- Bilingual: Excellent Danish/English

**Subagents**: Same model, specialized prompts

**Embeddings**: OpenAI `text-embedding-3-small` (RAG)

### 3.3 Data Infrastructure

**MongoDB** (`pymongo`)
- Collections:
  - `proposals`: Tender metadata, summaries
  - `proposal_files`: File content (markdown), metadata
  - `checkpoints`: LangGraph state persistence
  - `threads`: Thread-to-tender bindings
- Organization: `org_{org_id}` database structure

**Qdrant** (Vector Database)
- Collection: `org_1_v2`
- Filter fields: `metadata.type="pc"`, `metadata.cluster_id`, `metadata.file_id`
- Retrieval: Hybrid search (50 docs retrieved, top 10 reranked)

**Virtual Filesystem** (in-memory)
- Managed by LangChain middleware
- Persisted in checkpoint state
- Structure:
  ```
  /workspace/
    /context/      # Read-only L1 context (pre-populated)
    /analysis/     # Working artifacts
    /output/       # Final deliverables
  ```

### 3.4 Retrieval Pipeline

**Custom Retriever**: `CustomRetriever` class
- Hybrid search: Vector similarity + keyword matching
- Deduplication: Content-based
- Reranking: Cross-encoder model
- Parameters: k=50 (retrieve), p=10 (return)

---

## 4. Key Workflows

### 4.1 Simple Query Flow

**Example**: "What is the submission deadline?"

```
User Query → Main Agent
  ↓
Read L1: tender_summary.md
  ↓
Extract deadline information
  ↓
Respond directly (no RAG, no subagents, no TODO)
```

**Tools Called**: `read_file` (1x)
**Duration**: ~3-5 seconds

### 4.2 Document Search Flow

**Example**: "What are the CSR requirements?"

```
User Query → Main Agent
  ↓
Read L1: tender_summary.md, file_index.json
  ↓
L2 Search (English): "corporate social responsibility CSR"
  ↓
Detect Language: 🇩🇰 DANISH
  ↓
L2 Search (Danish): "samfundsansvar menneskerettigheder arbejdstagerrettigheder miljø"
  ↓
Identify relevant file: "Bilag E CSR.pdf"
  ↓
L3 Retrieve: Full document content
  ↓
Synthesize response with citations
```

**Tools Called**: `read_file` (2x), `search_tender_corpus` (2-3x), `retrieve_full_document` (1x)
**Duration**: ~40-70 seconds

### 4.3 Complex Analysis with Delegation

**Example**: "Compare SLA requirements across all contracts and research industry benchmarks"

```
User Query → Main Agent
  ↓
Create TODO:
  [1] Extract SLA requirements from contracts (pending)
  [2] Research industry benchmarks (pending)
  [3] Synthesize comparison (pending)
  ↓
Read L1: file_index.json (identify contract files)
  ↓
Delegate to Document Analyzer:
  "Extract SLA requirements from Contract A, Contract B, Annex C"
  ↓ (parallel)
Delegate to Web Researcher:
  "Research Danish IT services SLA industry standards"
  ↓
Await subagent results
  ↓
Update TODO: [1] completed, [2] completed, [3] in_progress
  ↓
Synthesize: Compare tender requirements vs benchmarks
  ↓
Save report: /workspace/output/sla_analysis.md
  ↓
Respond with summary + file reference + citations
```

**Tools Called**: 
- Main: `read_file` (1x), `task` (2x)
- Document Analyzer: `retrieve_full_document` (3x), `write_file` (1x)
- Web Researcher: `web_search` (3-4x)
**Duration**: ~2-3 minutes

### 4.4 Human-in-the-Loop Flow

**Example**: Agent finds contradictory deadline information

```
Agent detects contradiction:
  File A: "Deadline 2024-12-15"
  File B: "Deadline 2024-12-20"
  ↓
Call: request_human_input(
  question="Found conflicting deadlines...",
  context="File A states Dec 15, File B states Dec 20. Which is correct?"
)
  ↓
LangGraph interrupts execution
  ↓
User provides clarification: "Use Dec 20, File B is the latest version"
  ↓
Resume execution with user input
  ↓
Continue analysis with correct deadline
```

---

## 5. Monitoring & Observability

### 5.1 Logging System

**Tool Call Logging** (`@log_tool_call` decorator):
- Unified logger: `deepagents_unified`
- Events: `TOOL_CALL_START`, `TOOL_CALL_END`, `SESSION_END`
- Metadata: `session_id`, `tool_name`, `execution_time_ms`, `agent_context`

**Console Output** (User-friendly):
```
🔎 SEARCH: Query='samfundsansvar...' | Searching all tender files
   ✓ Found 10 chunks | Language detected: 🇩🇰 DANISH

📄 RETRIEVE FULL DOC: file_id=68c99b92bcf6...
   ✓ Retrieved 24366 characters
```

### 5.2 Performance Metrics

**Typical Query Times**:
- Simple (L1 only): 3-5s
- RAG search (L2): 10-15s per search
- Full document (L3): 2-5s per document
- Web search: 5-10s per search
- Complex analysis: 1-3 minutes

**RAG Performance**:
- Retrieval: 50 candidates in ~2-3s
- Reranking: Top 10 in ~1-2s
- Hit rate: ~80-90% for Danish-adapted queries

---

## 6. Prompt Engineering Strategy

### 6.1 Main Agent Prompt

**Structure**:
1. **Persona**: Research assistant, professional but approachable
2. **Capabilities**: Comprehensive tool overview
3. **Communication Style**: Adaptive, bilingual, quality-focused
4. **Quality Philosophy**: Accuracy paramount, evidence-based
5. **Workspace Explanation**: Virtual filesystem structure
6. **Tool Documentation**: When/why to use each tool
7. **Decision Framework**: Query assessment logic
8. **Information Access Strategy**: L1/L2/L3 workflow with language detection
9. **Delegation Strategy**: When to use subagents
10. **Error Handling**: Retry logic, alternatives, HITL escalation
11. **Output Standards**: Citation format, response quality

**Key Directive**: "ALWAYS start by reading L1 context files, then detect language from search results and adapt queries accordingly"

### 6.2 Document Analyzer Prompt

**Focus**:
- Systematic analysis workflow
- Citation discipline
- When to escalate from L2 to L3
- Report generation in `/workspace/analysis/`

**Key Tools**: Primarily L3 (`retrieve_full_document`) for precision

### 6.3 Web Researcher Prompt

**Focus**:
- Efficient multi-search strategy
- Source verification
- Clear external labeling
- Link attribution

**Key Tool**: Only `web_search`

---

## 7. Security & Data Isolation

### 7.1 Tender Isolation

**MongoDB Filter**:
```python
{
  "metadata.cluster_id": "<tender_specific_cluster_id>",
  "metadata.type": "pc"  # proposal/contract files only
}
```

**Thread Binding**: Enforced at application level (see Section 1.3)

### 7.2 Organization Isolation

**Database Separation**: `org_{org_id}` databases
**Qdrant Collection**: `org_1_v2` (scoped by cluster_id within collection)

---

## 8. Deployment & Configuration

### 8.1 Environment Variables

```bash
MONGODB_URL=mongodb://...
QDRANT_URL=https://...
QDRANT_API_KEY=...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### 8.2 Python Dependencies

- `langchain>=0.1.0`
- `langgraph>=0.0.30`
- `pymongo>=4.0`
- `qdrant-client>=1.7`
- `openai>=1.0`
- `anthropic>=0.18`

### 8.3 Entry Point

**Class**: `ReactAgent` in `react_agent.py`

**Initialization**:
```python
agent = ReactAgent(
    mongo_client=MongoClient(mongodb_url),
    org_id=1,
    db_name="org_1"
)
```

**Conversation**:
```python
# Synchronous
result = await agent.chat_sync(
    user_query="What are the CSR requirements?",
    thread_id="thread_123",
    tender_id="68c99b8a10844521ad051544"
)

# Streaming
async for chunk in agent.chat_streaming(
    user_query="...",
    thread_id="thread_123",
    tender_id="68c99b8a10844521ad051544"
):
    print(chunk)
```

---

## 9. Limitations & Future Enhancements

### 9.1 Current Limitations (MVP)

- **Supplier Profile**: Placeholder only (not populated from data)
- **Artifact Manifest**: Filesystem-only, no persistent tracking
- **Language Support**: Danish/English only
- **File Formats**: Markdown only (PDFs pre-converted)
- **Single Org**: Hardcoded to `org_id=1`

### 9.2 Planned Enhancements

- **Phase 2**: Multi-tender comparison, proposal drafting workflows
- **Phase 3**: Compliance matrix automation, risk scoring
- **Phase 4**: CV matching, team composition recommendations
- **Future**: Real-time tender monitoring, deadline alerts

---

## 10. Testing Strategy

See `TEST_SUITE.md` for comprehensive test cases with expected tool call sequences and validation criteria.

---

## Architecture Diagrams

### High-Level Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                         USER                                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    MAIN AGENT                               │
│  (Claude 3.5 Sonnet + LangGraph)                           │
│                                                             │
│  • Query Assessment                                         │
│  • L1/L2/L3 Strategy                                        │
│  • Language Detection                                       │
│  • Delegation                                               │
│  • Synthesis                                                │
└───┬─────────────────┬─────────────────┬─────────────────┬──┘
    │                 │                 │                 │
    ▼                 ▼                 ▼                 ▼
┌────────┐    ┌──────────────┐  ┌──────────────┐  ┌──────────┐
│   L1   │    │      L2      │  │      L3      │  │ External │
│Virtual │    │   Qdrant     │  │   MongoDB    │  │   Web    │
│FileSystem│  │  (RAG/Vector)│  │(Full Docs)   │  │  Search  │
└────────┘    └──────────────┘  └──────────────┘  └──────────┘
    │
    ├─ /context/tender_summary.md
    ├─ /context/file_index.json
    ├─ /analysis/
    └─ /output/

       ┌──────────────────────────────────────────────┐
       │           SUBAGENTS                          │
       │                                              │
       │  ┌──────────────────┐  ┌─────────────────┐ │
       │  │ Document Analyzer│  │  Web Researcher │ │
       │  │ (L2/L3 + Files)  │  │  (Web Search)   │ │
       │  └──────────────────┘  └─────────────────┘ │
       └──────────────────────────────────────────────┘

       ┌──────────────────────────────────────────────┐
       │          PERSISTENCE                         │
       │                                              │
       │  MongoDB: Checkpoints + Thread Bindings     │
       └──────────────────────────────────────────────┘
```

### Query Flow Decision Tree
```
User Query
    │
    ├─ General/Non-Tender?
    │   └─> Direct Response (no tools)
    │
    ├─ Simple Tender Query?
    │   └─> L1 Only (read_file)
    │
    ├─ Specific Info Search?
    │   └─> L1 → L2 (RAG)
    │       │
    │       ├─ Danish Detected? → Adapt Query (Danish keywords)
    │       ├─ Need Precision? → L3 (retrieve_full_document)
    │       └─> Respond with citations
    │
    ├─ Complex Analysis?
    │   └─> L1 → TODO → Delegate
    │       ├─> Document Analyzer (L2/L3)
    │       ├─> Web Researcher (web_search)
    │       └─> Synthesize + Respond
    │
    └─ Ambiguous/Missing Info?
        └─> request_human_input → Wait → Resume
```

---

**Document Version**: 1.0 (MVP)  
**Last Updated**: October 2025  
**Maintained By**: Pentimenti Development Team

