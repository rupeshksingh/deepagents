# Streaming API - Complete Frontend Integration Guide

**Version:** 2.0  
**Last Updated:** October 14, 2025  
**Status:** Production Ready ✅

---

## Table of Contents

1. [Overview](#overview)
2. [What Changed from v1 to v2](#what-changed-from-v1-to-v2)
3. [Event Schema Reference](#event-schema-reference)
4. [Complete Event Flow Examples](#complete-event-flow-examples)
5. [Frontend Integration Guide](#frontend-integration-guide)
6. [API Endpoints](#api-endpoints)
7. [React Implementation Examples](#react-implementation-examples)

---

## Overview

The DeepAgents streaming API provides real-time visibility into AI agent execution using Server-Sent Events (SSE). Version 2 adds **complete transparency** into agent decision-making, tool execution, and sub-agent activity.

**What You Get:**
- 💭 Agent reasoning/thinking in real-time
- 📋 Task planning with progress tracking (PLAN events)
- 🔧 Human-readable tool descriptions
- 🤖 Sub-agent activity tracking
- 📊 Parallel execution visibility
- ⏸️ Human-in-the-loop interrupts (HITL)
- 📝 Clear content boundaries

**Critical Features Explained:**
- **PLAN Events** → When agent creates todos for complex queries, show progress tracker
- **HITL Interrupts** → When agent needs clarification, pause and show input prompt

---

## What Changed from v1 to v2

### Version 1 (Original)

**Event Types:**
- `start` - Stream begins
- `tool_start` - Tool execution starts
- `tool_end` - Tool completes
- `plan` - Agent creates todos
- `content` - Final response chunks
- `end` - Stream complete

**What Was Missing:**
- ❌ No visibility into agent's thinking/reasoning
- ❌ Tool args shown as raw JSON
- ❌ No distinction between main agent and sub-agents
- ❌ No indication when final response begins/ends
- ❌ Sub-agent execution invisible to frontend

### Version 2 (New - October 2025)

**New Event Types:**
- `thinking` - Agent reasoning before/after decisions
- `subagent_start` - Sub-agent spawned
- `subagent_end` - Sub-agent completed
- `content_start` - Final response begins
- `content_end` - Final response ends

**Enhanced Fields:**
- `agent_type` - "main" | "subagent"
- `agent_id` - Unique agent identifier
- `parent_call_id` - Links sub-agent to parent task
- `args_display` - Human-readable tool description
- `v` - Schema version (now 2)

**What's New:**
- ✅ See agent's thought process
- ✅ Tool calls shown as "Searching for: GDPR requirements"
- ✅ Sub-agent activity wrapped in clear events
- ✅ Know when final answer starts/ends
- ✅ Parallel execution visible

---

## Event Schema Reference

### Base Event Structure

```typescript
interface StreamEvent {
  // Core fields (all events)
  v: number;              // Schema version (2)
  type: string;           // Event type
  id: string;             // Unique event ID
  ts: string;             // ISO 8601 timestamp
  
  // Agent context (NEW in v2)
  agent_type?: "main" | "subagent";
  agent_id?: string;
  parent_call_id?: string;  // For sub-agents
  
  // Type-specific fields below...
}
```

### Event Types

| Type | When | Key Fields |
|------|------|------------|
| `start` | Stream begins | `message_id`, `chat_id`, `status` |
| `thinking` | Agent reasoning | `text`, `agent_type` |
| `plan` | Todos created | `items[]` |
| `tool_start` | Tool begins | `name`, `args_display`, `call_id` |
| `tool_end` | Tool completes | `name`, `status`, `ms`, `call_id` |
| `subagent_start` | Sub-agent spawned | `agent_id`, `subagent_description`, `parent_call_id` |
| `subagent_end` | Sub-agent done | `agent_id`, `ms`, `parent_call_id` |
| `content_start` | Answer begins | `agent_type` |
| `content` | Answer chunk | `md` |
| `content_end` | Answer ends | `agent_type` |
| `status` | Heartbeat | `text` |
| `end` | Stream complete | `status`, `ms_total`, `tool_calls` |
| `error` | Error occurred | `error` |

### Field Definitions

**Agent Context:**
- `agent_type`: "main" for main agent, "subagent" for spawned agents
- `agent_id`: Unique ID like "main_xyz789" or "subagent_advanced_tender_analyst_abc123"
- `parent_call_id`: For sub-agents, the tool call ID that spawned them

**Tool Events:**
- `name`: Tool name (e.g., "search_tender_corpus", "task", "web_search")
- `args_display`: Human-readable description (e.g., "Searching for: GDPR requirements")
- `args_summary`: Raw JSON of arguments (technical detail)
- `call_id`: Unique call identifier to match start/end
- `ms`: Execution time in milliseconds

**Content Events:**
- `text`: Plain text content (for thinking, status)
- `md`: Markdown content (for final response)

**Plan Events:**
- `items`: Array of todo items with `id`, `text`, and `status` fields
- Status values: "pending", "in_progress", "completed", "cancelled"

**Status Events (Special Cases):**
- Regular heartbeat: `{"type": "status", "text": "Processing..."}`
- **HITL (Human-in-the-Loop):** `{"type": "status", "text": "⏸️ Agent needs human input", "md": "{...interrupt data...}"}`

---

## Special Features: PLAN and HITL

### PLAN Events (Todo/Task Planning)

**What:** When the agent receives a complex query, it may create a plan with multiple todo items to track progress.

**When Emitted:**
- Agent calls `write_todos` tool with a list of tasks
- Usually happens early in complex queries
- Can be updated mid-execution as tasks complete

**Event Structure:**
```json
{
  "v": 2,
  "type": "plan",
  "id": "event_id",
  "ts": "2025-10-14T10:30:00.000Z",
  "items": [
    {
      "id": "todo_1",
      "text": "Search for backup requirements",
      "status": "in_progress"
    },
    {
      "id": "todo_2",
      "text": "Search for CSR requirements",
      "status": "pending"
    },
    {
      "id": "todo_3",
      "text": "Analyze findings",
      "status": "pending"
    }
  ]
}
```

**Frontend Handling:**
```typescript
// Display plan as a progress tracker
function PlanTracker({ planEvent }: { planEvent: StreamEvent }) {
  const items = planEvent.items || [];
  const completed = items.filter(i => i.status === 'completed').length;
  const total = items.length;
  
  return (
    <div className="plan-tracker">
      <div className="plan-header">
        <h4>📋 Agent's Plan</h4>
        <span className="progress">{completed}/{total} completed</span>
      </div>
      <div className="plan-items">
        {items.map(item => (
          <div key={item.id} className={`plan-item ${item.status}`}>
            <StatusIcon status={item.status} />
            <span>{item.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Status icon helper
function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed': return <CheckIcon />;
    case 'in_progress': return <Spinner />;
    case 'cancelled': return <XIcon />;
    default: return <ClockIcon />;
  }
}
```

**Plan Updates:**
- Agent may emit multiple PLAN events for the same query
- Later events update the status of existing todos
- Match by `id` field to update existing items

### HITL (Human-in-the-Loop) Interrupts

**What:** When the agent needs clarification or human input, it pauses execution and requests user input.

**When Emitted:**
- Agent calls `request_human_input` tool
- Agent encounters ambiguous requirements
- Agent needs approval for sensitive actions

**Event Structure:**
```json
{
  "v": 2,
  "type": "status",
  "id": "event_id",
  "ts": "2025-10-14T10:30:00.000Z",
  "text": "⏸️ Agent needs human input",
  "md": "{\"interrupt\":true,\"tool\":\"request_human_input\",\"question\":\"Which document format do you prefer?\",\"context\":\"Multiple format options available\",\"thread_id\":\"thread_abc123\",\"instructions\":\"Human input required. Use resume endpoint to continue.\"}"
}
```

**Followed By:**
```json
{
  "v": 2,
  "type": "end",
  "id": "event_id_end",
  "ts": "2025-10-14T10:30:01.000Z",
  "status": "interrupted",
  "ms_total": 5000,
  "tool_calls": 3
}
```

**Frontend Handling:**

**Step 1: Detect Interrupt**
```typescript
function handleStatusEvent(event: StreamEvent) {
  if (event.text?.includes('⏸️ Agent needs human input')) {
    try {
      const interruptData = JSON.parse(event.md || '{}');
      if (interruptData.interrupt) {
        handleInterrupt(interruptData);
      }
    } catch (e) {
      console.error('Failed to parse interrupt data', e);
    }
  }
}
```

**Step 2: Display Input Form**
```tsx
function InterruptPrompt({ interruptData }: { interruptData: any }) {
  const [userInput, setUserInput] = useState('');
  
  return (
    <div className="interrupt-prompt">
      <div className="interrupt-header">
        <PauseIcon />
        <h4>Agent Needs Your Input</h4>
      </div>
      
      <div className="interrupt-content">
        <p className="question">{interruptData.question}</p>
        {interruptData.context && (
          <p className="context">{interruptData.context}</p>
        )}
        
        <textarea
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          placeholder="Enter your response..."
        />
        
        <button onClick={() => resumeAgent(userInput, interruptData.thread_id)}>
          Continue Agent
        </button>
      </div>
    </div>
  );
}
```

**Step 3: Resume Agent**
```typescript
async function resumeAgent(userInput: string, threadId: string) {
  const response = await fetch(`/api/threads/${threadId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command: {
        resume: {
          // Provide the human input as tool result
          result: userInput
        }
      }
    })
  });
  
  // This will resume the stream with a new message
  const result = await response.json();
  
  // Reconnect to stream or create new message
  // The agent will continue from where it left off
}
```

**Important Notes:**
- When interrupt detected, stream ends with `status: "interrupted"`
- Save `thread_id` from interrupt data
- Use resume endpoint to continue execution
- Agent maintains conversation context after resume

---

## Complete Event Flow Examples

### Example 1: Simple Query (No Sub-Agents)

**User Query:** "Summarize the 7 service areas from Bilag F"

```
START
├─ THINKING [main]
│  "I'll search for all 7 service areas systematically..."
│
├─ TOOL_START [main]
│  args_display: "Searching for: Bilag F ydelsesområder 1-7"
│  name: search_tender_corpus
│  call_id: tool_abc123
│
├─ TOOL_END [main]
│  call_id: tool_abc123
│  status: ok
│  ms: 1823
│
├─ THINKING [main]
│  "Perfect! I now have all 7 service areas..."
│
├─ TOOL_START [main] × 3 (parallel)
│  ├─ "Searching for: Ydelsesområde 1..."
│  ├─ "Searching for: Ydelsesområde 2..."
│  └─ "Searching for: Ydelsesområde 3..."
│
├─ TOOL_END × 3
│
├─ CONTENT_START [main]
├─ CONTENT × 32 chunks
│  "Based on my analysis..."
├─ CONTENT_END [main]
│
└─ END (status: completed, ms_total: 6500, tool_calls: 4)
```

### Example 2: Complex Query (With Sub-Agents)

**User Query:** "Analyze risks in three areas: (A) Penalties, (B) CSR, (C) Auditing"

```
START
├─ THINKING [main]
│  "I'll delegate to 3 specialist sub-agents..."
│
├─ PLAN
│  - Search for penalties (in_progress)
│  - Search for CSR requirements (pending)
│  - Search for auditing rules (pending)
│
├─ TOOL_START [main] × 3 (parallel)
│  ├─ args_display: "Sub-agent task: Analyze penalties..."
│  │  call_id: task_xyz123
│  │  
│  │  └─ SUBAGENT_START
│  │     agent_id: subagent_analyst_1
│  │     parent_call_id: task_xyz123
│  │     description: "Analyze penalties..."
│  │     
│  │     ├─ THINKING [subagent]
│  │     │  "Let me search for penalty terms..."
│  │     │
│  │     ├─ TOOL_START [subagent]
│  │     │  "Searching for: penalties breach termination"
│  │     │
│  │     ├─ TOOL_END [subagent]
│  │     │  ms: 1456
│  │     │
│  │     └─ SUBAGENT_END
│  │        ms: 34800 (34.8s)
│  │
│  │  └─ TOOL_END [main]
│  │     call_id: task_xyz123
│  │     ms: 34805
│  │
│  ├─ [Similar flow for sub-agent 2: CSR]
│  └─ [Similar flow for sub-agent 3: Auditing]
│
├─ THINKING [main]
│  "Based on all findings, here's the analysis..."
│
├─ CONTENT_START [main]
├─ CONTENT × 45 chunks
├─ CONTENT_END [main]
│
└─ END (status: completed, ms_total: 104700, tool_calls: 12)
```

### Example 3: Query with HITL Interrupt

**User Query:** "Generate a compliance report"

```
START
├─ THINKING [main]
│  "I'll generate a comprehensive compliance report..."
│
├─ TOOL_START [main]
│  "Searching for: compliance requirements"
│
├─ TOOL_END [main]
│  ms: 1234
│
├─ THINKING [main]
│  "I found multiple report formats. Need to ask the user..."
│
├─ STATUS (HITL Interrupt)
│  text: "⏸️ Agent needs human input"
│  md: {"interrupt": true, "question": "Which format?", ...}
│
└─ END (status: interrupted, ms_total: 5000, tool_calls: 1)

[User provides input: "PDF format please"]

[Resume creates new message and stream]

START
├─ THINKING [main]
│  "User requested PDF format. Continuing..."
│
├─ CONTENT_START [main]
├─ CONTENT × N
│  "Here's your compliance report in PDF format..."
├─ CONTENT_END [main]
│
└─ END (status: completed, ms_total: 8000, tool_calls: 2)
```

### Example Event JSON

```json
{
  "v": 2,
  "type": "thinking",
  "id": "1729000001_0002_def456",
  "ts": "2025-10-14T10:30:01.000Z",
  "agent_type": "main",
  "agent_id": "main_xyz789",
  "text": "I'll analyze all 7 service areas systematically..."
}

{
  "v": 2,
  "type": "tool_start",
  "id": "1729000002_0003_ghi789",
  "ts": "2025-10-14T10:30:02.000Z",
  "call_id": "tool_abc123",
  "name": "search_tender_corpus",
  "args_summary": "{\"query\": \"Bilag F...\"}",
  "args_display": "Searching for: Bilag F ydelsesområder 1-7",
  "agent_type": "main",
  "agent_id": "main_xyz789"
}

{
  "v": 2,
  "type": "subagent_start",
  "id": "1729000010_0011_def890",
  "ts": "2025-10-14T10:30:10.050Z",
  "agent_type": "subagent",
  "agent_id": "subagent_advanced_tender_analyst_xyz12345",
  "parent_call_id": "task_xyz123",
  "subagent_description": "Analyze penalties and breach terms..."
}

{
  "v": 2,
  "type": "content_start",
  "id": "1729000020_0020_vwx678",
  "ts": "2025-10-14T10:30:20.000Z",
  "agent_type": "main",
  "agent_id": "main_xyz789"
}
```

---

## Frontend Integration Guide

### 1. Connection Setup

```typescript
const eventSource = new EventSource(
  `/api/chats/${chatId}/messages/${messageId}/stream`
);

eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  handleStreamEvent(event);
};

eventSource.onerror = (error) => {
  console.error('Stream error:', error);
  eventSource.close();
};
```

### 2. Event Handler Structure

```typescript
function handleStreamEvent(event: StreamEvent) {
  switch (event.type) {
    case 'start':
      handleStart(event);
      break;
    
    case 'thinking':
      handleThinking(event);
      break;
    
    case 'plan':
      handlePlan(event);
      break;
    
    case 'tool_start':
      handleToolStart(event);
      break;
    
    case 'tool_end':
      handleToolEnd(event);
      break;
    
    case 'subagent_start':
      handleSubagentStart(event);
      break;
    
    case 'subagent_end':
      handleSubagentEnd(event);
      break;
    
    case 'content_start':
      handleContentStart(event);
      break;
    
    case 'content':
      handleContent(event);
      break;
    
    case 'content_end':
      handleContentEnd(event);
      break;
    
    case 'status':
      handleStatus(event);
      // Check for HITL interrupt
      if (event.text?.includes('⏸️ Agent needs human input')) {
        handleInterrupt(event);
      }
      break;
    
    case 'end':
      handleEnd(event);
      eventSource.close();
      break;
    
    case 'error':
      handleError(event);
      eventSource.close();
      break;
  }
}
```

### 3. Grouping Sub-Agent Events

**Key Concept:** Group sub-agent events by `parent_call_id`

```typescript
// Organize events into nested structure
function organizeEvents(events: StreamEvent[]) {
  const mainEvents = [];
  const subagentGroups = new Map<string, StreamEvent[]>();
  
  for (const event of events) {
    if (event.agent_type === 'subagent' && event.parent_call_id) {
      // Group sub-agent events
      if (!subagentGroups.has(event.parent_call_id)) {
        subagentGroups.set(event.parent_call_id, []);
      }
      subagentGroups.get(event.parent_call_id)!.push(event);
    } else {
      // Main agent events
      mainEvents.push(event);
    }
  }
  
  return { mainEvents, subagentGroups };
}
```

### 4. Detecting Parallel Execution

```typescript
// Tools started within 100ms are considered parallel
function detectParallelTools(events: StreamEvent[]) {
  const toolStarts = events.filter(e => e.type === 'tool_start');
  const groups: StreamEvent[][] = [];
  
  let currentGroup: StreamEvent[] = [];
  let lastTimestamp = 0;
  
  for (const tool of toolStarts) {
    const ts = new Date(tool.ts).getTime();
    
    if (currentGroup.length === 0 || (ts - lastTimestamp) < 100) {
      currentGroup.push(tool);
    } else {
      if (currentGroup.length > 0) groups.push(currentGroup);
      currentGroup = [tool];
    }
    
    lastTimestamp = ts;
  }
  
  if (currentGroup.length > 0) groups.push(currentGroup);
  
  return groups;
}
```

---

## API Endpoints

### Create Chat

```http
POST /api/users/{user_id}/chats
Content-Type: application/json

{
  "title": "My Chat",
  "metadata": {}
}

Response: 201 Created
{
  "chat_id": "uuid",
  "user_id": "string",
  "title": "string",
  "created_at": "timestamp",
  "message_count": 0
}
```

### Create Message (Start Stream)

```http
POST /api/chats/{chat_id}/messages
Content-Type: application/json

{
  "content": "Your query here",
  "metadata": {
    "tender_id": "optional_tender_id"
  }
}

Response: 201 Created
{
  "message_id": "object_id",
  "chat_id": "uuid",
  "role": "assistant",
  "status": "processing",
  "stream_url": "/api/chats/{chat_id}/messages/{message_id}/stream"
}
```

### Stream Events

```http
GET /api/chats/{chat_id}/messages/{message_id}/stream
Accept: text/event-stream

Response: 200 OK (SSE stream)
data: {"v":2,"type":"start",...}

data: {"v":2,"type":"thinking",...}

data: {"v":2,"type":"tool_start",...}

...
```

---

## React Implementation Examples

### 1. Thinking Bubble Component

```tsx
interface ThinkingProps {
  event: StreamEvent;
}

function ThinkingBubble({ event }: ThinkingProps) {
  const isSubagent = event.agent_type === 'subagent';
  
  return (
    <div className={`thinking-bubble ${isSubagent ? 'subagent' : 'main'}`}>
      <div className="thinking-icon">
        {isSubagent ? '🤖' : '💭'}
      </div>
      <div className="thinking-content">
        <p>{event.text}</p>
        {isSubagent && (
          <span className="badge">Sub-agent</span>
        )}
      </div>
    </div>
  );
}
```

### 2. Tool Execution Card

```tsx
interface ToolCardProps {
  startEvent: StreamEvent;
  endEvent?: StreamEvent;
}

function ToolCard({ startEvent, endEvent }: ToolCardProps) {
  const isRunning = !endEvent;
  const duration = endEvent?.ms;
  
  return (
    <div className={`tool-card ${isRunning ? 'running' : 'completed'}`}>
      <div className="tool-header">
        <ToolIcon name={startEvent.name} />
        <span className="tool-name">{startEvent.args_display}</span>
      </div>
      
      <div className="tool-status">
        {isRunning ? (
          <>
            <Spinner />
            <span>Running...</span>
          </>
        ) : (
          <>
            <CheckIcon />
            <span>{duration}ms</span>
          </>
        )}
      </div>
      
      {startEvent.agent_type === 'subagent' && (
        <span className="badge subagent">Sub-agent</span>
      )}
    </div>
  );
}
```

### 3. Sub-Agent Collapsible Section

```tsx
interface SubAgentSectionProps {
  taskCallId: string;
  events: StreamEvent[];
}

function SubAgentSection({ taskCallId, events }: SubAgentSectionProps) {
  const [isOpen, setIsOpen] = useState(false);
  
  // Find start/end events
  const startEvent = events.find(
    e => e.type === 'subagent_start' && e.parent_call_id === taskCallId
  );
  const endEvent = events.find(
    e => e.type === 'subagent_end' && e.parent_call_id === taskCallId
  );
  
  // Filter events for this sub-agent
  const subagentEvents = events.filter(
    e => e.agent_type === 'subagent' && e.parent_call_id === taskCallId
  );
  
  const duration = endEvent?.ms ? `${(endEvent.ms / 1000).toFixed(1)}s` : '...';
  
  return (
    <div className="subagent-section">
      <button 
        className="subagent-header"
        onClick={() => setIsOpen(!isOpen)}
      >
        <ChevronIcon direction={isOpen ? 'down' : 'right'} />
        <SubAgentIcon />
        <span className="title">{startEvent?.subagent_description}</span>
        {endEvent && <span className="duration">{duration}</span>}
      </button>
      
      {isOpen && (
        <div className="subagent-content">
          {subagentEvents.map(event => renderEvent(event))}
        </div>
      )}
    </div>
  );
}
```

### 4. Parallel Tools Grid

```tsx
interface ParallelToolsProps {
  tools: StreamEvent[];
}

function ParallelToolsGrid({ tools }: ParallelToolsProps) {
  return (
    <div className="parallel-tools-container">
      <div className="parallel-label">
        Running {tools.length} tools in parallel
      </div>
      <div className="parallel-tools-grid">
        {tools.map(tool => (
          <ToolCard key={tool.call_id} startEvent={tool} />
        ))}
      </div>
    </div>
  );
}
```

### 5. Plan Tracker Component

```tsx
interface PlanTrackerProps {
  planEvent: StreamEvent;
}

function PlanTracker({ planEvent }: PlanTrackerProps) {
  const items = planEvent.items || [];
  const completed = items.filter(i => i.status === 'completed').length;
  const inProgress = items.filter(i => i.status === 'in_progress').length;
  const total = items.length;
  
  return (
    <div className="plan-tracker">
      <div className="plan-header">
        <PlanIcon />
        <h4>Agent's Plan</h4>
        <div className="progress-indicator">
          <span className="progress-text">{completed}/{total} completed</span>
          <progress value={completed} max={total} />
        </div>
      </div>
      
      <div className="plan-items">
        {items.map(item => {
          const StatusIcon = {
            'completed': CheckIcon,
            'in_progress': SpinnerIcon,
            'cancelled': XIcon,
            'pending': ClockIcon
          }[item.status] || ClockIcon;
          
          return (
            <div key={item.id} className={`plan-item status-${item.status}`}>
              <StatusIcon className="status-icon" />
              <span className="item-text">{item.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

**Plan Update Handling:**
```typescript
// When multiple PLAN events received, merge by todo ID
const [currentPlan, setCurrentPlan] = useState<PlanItem[]>([]);

function handlePlanEvent(event: StreamEvent) {
  if (!event.items) return;
  
  // Merge new plan with existing
  const updatedPlan = [...currentPlan];
  
  for (const newItem of event.items) {
    const existingIdx = updatedPlan.findIndex(i => i.id === newItem.id);
    
    if (existingIdx >= 0) {
      // Update existing item
      updatedPlan[existingIdx] = newItem;
    } else {
      // Add new item
      updatedPlan.push(newItem);
    }
  }
  
  setCurrentPlan(updatedPlan);
}
```

### 6. HITL Interrupt Handler

```tsx
interface HITLPromptProps {
  statusEvent: StreamEvent;
  onResume: (userInput: string) => void;
}

function HITLPrompt({ statusEvent, onResume }: HITLPromptProps) {
  const [userInput, setUserInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  // Parse interrupt data from md field
  const interruptData = useMemo(() => {
    try {
      return JSON.parse(statusEvent.md || '{}');
    } catch {
      return {};
    }
  }, [statusEvent.md]);
  
  const handleSubmit = async () => {
    if (!userInput.trim() || isSubmitting) return;
    
    setIsSubmitting(true);
    await onResume(userInput);
    setIsSubmitting(false);
  };
  
  return (
    <div className="hitl-interrupt">
      <div className="interrupt-banner">
        <PauseIcon />
        <span>Agent Paused - Needs Your Input</span>
      </div>
      
      <div className="interrupt-content">
        <div className="question-section">
          <h4>Question:</h4>
          <p>{interruptData.question || 'Agent needs clarification'}</p>
        </div>
        
        {interruptData.context && (
          <div className="context-section">
            <h4>Context:</h4>
            <p>{interruptData.context}</p>
          </div>
        )}
        
        <div className="input-section">
          <label>Your Response:</label>
          <textarea
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Enter your response here..."
            rows={4}
          />
        </div>
        
        <button 
          onClick={handleSubmit}
          disabled={!userInput.trim() || isSubmitting}
          className="resume-button"
        >
          {isSubmitting ? 'Resuming...' : 'Continue Agent'}
        </button>
      </div>
      
      <div className="interrupt-info">
        ℹ️ The agent will resume from where it paused once you provide input
      </div>
    </div>
  );
}
```

**Resume Function:**
```typescript
async function resumeInterruptedAgent(
  threadId: string,
  userInput: string
): Promise<void> {
  // Note: Resume endpoint implementation may vary
  // Check with your backend team for exact endpoint
  
  const response = await fetch(`/api/threads/${threadId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command: {
        resume: {
          result: userInput  // User's input becomes tool result
        }
      }
    })
  });
  
  if (!response.ok) {
    throw new Error(`Resume failed: ${response.statusText}`);
  }
  
  const result = await response.json();
  // Agent continues execution with user's input
  return result;
}
```

### 7. Final Response Section

```tsx
function ResponseSection({ events }: { events: StreamEvent[] }) {
  const contentStart = events.find(e => e.type === 'content_start');
  const contentEnd = events.find(e => e.type === 'content_end');
  const contentChunks = events.filter(e => e.type === 'content');
  
  const fullContent = contentChunks.map(e => e.md).join('');
  
  return (
    <div className="response-section">
      {contentStart && (
        <div className="response-header">
          <ResponseIcon />
          <strong>Final Analysis:</strong>
        </div>
      )}
      
      <div className="response-content">
        <ReactMarkdown>{fullContent}</ReactMarkdown>
      </div>
      
      {contentEnd && (
        <div className="response-footer">
          <CheckIcon /> Response complete
        </div>
      )}
    </div>
  );
}
```

### 8. Complete Chat Message Component

```tsx
function ChatMessage({ events }: { events: StreamEvent[] }) {
  const { mainEvents, subagentGroups } = organizeEvents(events);
  const parallelGroups = detectParallelTools(mainEvents);
  const [interruptData, setInterruptData] = useState(null);
  
  // Track plan updates
  const planEvents = events.filter(e => e.type === 'plan');
  const latestPlan = planEvents[planEvents.length - 1]; // Use most recent
  
  // Check for interrupt
  const interruptEvent = events.find(e => 
    e.type === 'status' && e.text?.includes('⏸️ Agent needs human input')
  );
  
  return (
    <div className="chat-message">
      {mainEvents.map((event, idx) => {
        switch (event.type) {
          case 'thinking':
            return <ThinkingBubble key={event.id} event={event} />;
          
          case 'plan':
            return <PlanTracker key={event.id} planEvent={event} />;
          
          case 'status':
            // Check for HITL interrupt
            if (event.text?.includes('⏸️ Agent needs human input')) {
              return <HITLPrompt key={event.id} statusEvent={event} onResume={handleResume} />;
            }
            // Regular status - optionally show as subtle indicator
            return null;
          
          case 'tool_start':
            // Check if part of parallel group
            const parallelGroup = parallelGroups.find(g => 
              g.some(t => t.call_id === event.call_id)
            );
            
            if (parallelGroup && parallelGroup.length > 1) {
              // Render parallel group once
              if (parallelGroup[0].call_id === event.call_id) {
                return <ParallelToolsGrid key={event.id} tools={parallelGroup} />;
              }
              return null;
            }
            
            // Single tool or sub-agent
            if (event.name === 'task') {
              const subEvents = subagentGroups.get(event.call_id) || [];
              return (
                <SubAgentSection 
                  key={event.id}
                  taskCallId={event.call_id}
                  events={[...mainEvents, ...subEvents]}
                />
              );
            }
            
            return <ToolCard key={event.id} startEvent={event} />;
          
          case 'content_start':
            return <ResponseSection key={event.id} events={events} />;
          
          default:
            return null;
        }
      })}
    </div>
  );
}
```

---

## Recommended UI Layout

```
┌─────────────────────────────────────────┐
│ 💭 Agent Thinking                       │
│ "I'll analyze three risk areas by       │
│ delegating to specialist sub-agents..." │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 📋 Agent's Plan             2/3 complete│
│ ✓ Search for penalties                  │
│ ✓ Search for CSR requirements           │
│ ⏳ Analyze and synthesize findings      │
└─────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┐
│ 🔧 Running 3 tools in parallel           │
├──────────────┼──────────────┼──────────────┤
│ 🤖 Sub-agent │ 🤖 Sub-agent │ 🤖 Sub-agent  │
│ Breach &     │ CSR Require- │ Auditing     │
│ Penalties    │ ments        │ Rules        │
│ ⏳ Running   │ ⏳ Running   │ ⏳ Running    │
└──────────────┴──────────────┴──────────────┘

▼ 🤖 Sub-agent: Analyze penalties (34.8s)
  │ 💭 "Let me search for breach terms..."
  │ 🔍 Searching for: penalties breach termination
  │ ✓ Completed in 1,456ms
  └─

▼ 🤖 Sub-agent: Analyze CSR (38.2s)
  └─ [collapsed]

▼ 🤖 Sub-agent: Analyze auditing (50.1s)
  └─ [collapsed]

┌─────────────────────────────────────────┐
│ 💭 Agent Thinking                       │
│ "Based on all findings, here's the      │
│ comprehensive analysis..."              │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ 📝 Final Analysis:                      │
│                                         │
│ ## Risk Analysis                        │
│                                         │
│ ### (A) Breach & Penalties              │
│ Based on the analysis...                │
│                                         │
│ ### (B) CSR Requirements                │
│ Key risks include...                    │
│                                         │
│ ### (C) Auditing Rules                  │
│ Significant considerations...           │
│                                         │
│ ✓ Response complete                     │
└─────────────────────────────────────────┘
```

---

## Migration from v1 to v2

### Breaking Changes
**None** - v2 is fully backwards compatible

### Recommended Updates

**1. Check Schema Version**
```typescript
if (event.v === 2) {
  // Handle v2 features
} else {
  // Fallback to v1 behavior
}
```

**2. Use args_display**
```typescript
// v1: Parse args_summary JSON
const displayText = JSON.parse(event.args_summary).query;

// v2: Use args_display directly
const displayText = event.args_display || event.name;
```

**3. Handle New Event Types**
```typescript
// Add handlers for new types
case 'thinking':
case 'subagent_start':
case 'subagent_end':
case 'content_start':
case 'content_end':
```

**4. Group Sub-Agent Events**
```typescript
// Use parent_call_id to nest sub-agent activity
const subagentEvents = events.filter(
  e => e.parent_call_id === taskCallId
);
```

---

## Best Practices

### 1. Progressive Enhancement
- Show basic events first (tool_start/end, content)
- Layer on thinking bubbles
- Add sub-agent collapsibles
- Enhance with parallel visualization

### 2. Loading States
- Show spinner on `tool_start`
- Replace with checkmark on `tool_end`
- Display duration after completion

### 3. Collapsible Sections
- Sub-agents should be collapsed by default
- Let users expand to see details
- Show duration in header

### 4. Error Handling
```typescript
eventSource.onerror = () => {
  // Attempt reconnection with Last-Event-ID
  const lastId = getLastEventId();
  reconnect(lastId);
};
```

### 5. Performance
- Batch UI updates
- Use virtual scrolling for long event lists
- Debounce content chunk rendering

---

## Testing Checklist

Frontend integration testing:

**Basic Events:**
- [ ] Connect to SSE endpoint
- [ ] Receive and parse all event types
- [ ] Display thinking bubbles (main agent)
- [ ] Show human-readable tool descriptions
- [ ] Display final response with boundaries
- [ ] Handle stream errors gracefully

**Advanced Features:**
- [ ] Render PLAN tracker with progress indicator
- [ ] Update plan items as status changes (pending → in_progress → completed)
- [ ] Render sub-agent sections (collapsed by default)
- [ ] Show sub-agent thinking inside collapsible sections
- [ ] Visualize parallel tool execution (grid layout)
- [ ] Visualize parallel sub-agent execution

**HITL (Human-in-the-Loop):**
- [ ] Detect interrupt STATUS events
- [ ] Parse interrupt data from md field
- [ ] Display interrupt prompt with question
- [ ] Capture user input
- [ ] Resume agent execution with user response
- [ ] Handle resume endpoint correctly

**Edge Cases:**
- [ ] Support reconnection (Last-Event-ID)
- [ ] Handle interrupted streams gracefully
- [ ] Test with complex queries (multiple sub-agents)
- [ ] Test with queries that trigger PLAN events
- [ ] Test with queries that trigger HITL interrupts

---

## Troubleshooting

**Problem:** Events not received
- Check SSE connection is open
- Verify `Accept: text/event-stream` header
- Check CORS settings

**Problem:** Sub-agent events not grouping
- Ensure using `parent_call_id` to match events
- Check `agent_type === "subagent"` filter

**Problem:** args_display missing
- Fallback to `name` field
- Check event schema version (`v: 2`)

**Problem:** Content not rendering
- Wait for `content_start` event
- Accumulate all `content` chunks
- Render after `content_end`

**Problem:** Plan not updating
- Check for multiple `plan` events in stream
- Merge plan items by `id` field (don't replace entire plan)
- Update status of existing items when new PLAN event arrives

**Problem:** HITL interrupt not detected
- Check STATUS events with text containing "⏸️ Agent needs human input"
- Parse `md` field as JSON to get interrupt data
- Ensure END event has `status: "interrupted"`
- Save `thread_id` from interrupt data for resume

**Problem:** Resume not working
- Verify thread_id from interrupt data
- Check resume endpoint exists and accepts correct format
- Ensure user input is passed as `result` field
- Agent state should persist across interrupt/resume

---

## Summary

**What You Need to Know:**

1. **Connect via SSE** to `/api/chats/{chat_id}/messages/{message_id}/stream`
2. **Parse events** and check `type` field
3. **Handle PLAN events** - merge by `id` field, show progress tracker
4. **Group sub-agents** by `parent_call_id`
5. **Detect parallel** tools by timestamp proximity
6. **Handle HITL interrupts** - detect from STATUS events, show prompt, resume with user input
7. **Render progressively** from thinking → plan → tools → content

**Key Benefits:**

- Users see agent's thought process (THINKING events)
- Tool calls are human-readable (args_display)
- Task planning is visible (PLAN tracker with progress)
- Sub-agent work is visible but collapsible
- Parallel execution is obvious (parallel tools/sub-agents)
- Human interaction supported (HITL interrupts)
- Clear separation of process vs answer (content boundaries)

**Your streaming UI will be the most transparent in the industry!** 🎉

---

**Questions?** Check the test query results or review the event flow examples above.

**Last Tested:** October 14, 2025 with complex 3-sub-agent query (104.7s, 61 events)

