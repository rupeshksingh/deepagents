# Frontend Integration Guide - SSE Streaming API

## Overview

This API provides real-time visibility into AI agent workflow through Server-Sent Events (SSE). You'll see tool calls, plan updates, and responses as they happen.

**Flow:** Two-step process
1. **POST** to create message → Get `stream_url`
2. **GET** `stream_url` with EventSource → Receive real-time events

---

## Step 1: Create Message (POST)

**Endpoint:** `POST /api/chats/{chat_id}/messages`

**Request:**
```json
{
  "content": "Your user query here",
  "metadata": {
    "tender_id": "68c99b8a10844521ad051544"  // Optional
  }
}
```

**Response:** `201 Created`
```json
{
  "message_id": "68ecd564660e15ed7c206fc5",
  "stream_url": "/api/chats/{chat_id}/messages/{message_id}/stream"
}
```

**Frontend Action:** Immediately open EventSource to `stream_url`

---

## Step 2: Open SSE Stream (GET)

**Endpoint:** `GET {stream_url}` (from POST response)

**Connection:**
```javascript
const eventSource = new EventSource(baseUrl + stream_url);
```

**Auto-reconnect:** EventSource handles this automatically with 3-second retry

**Resume capability:** EventSource automatically sends `Last-Event-ID` header on reconnect

---

## Event Types You'll Receive

All events follow this SSE format:
```
retry: 3000
event: {event_type}
id: {unique_id}
data: {json}

```

### 1. **start** - Processing Began
```json
{
  "v": 1,
  "type": "start",
  "id": "1760270888823_0001_a26344ee",
  "ts": "2025-10-13T10:08:08.823Z",
  "message_id": "68eb9a170b8a377cc7e09834",
  "status": "processing"
}
```

**Frontend Action:** Show loading indicator, "Agent is thinking..."

---

### 2. **plan** - Agent Created Todo List
```json
{
  "v": 1,
  "type": "plan",
  "id": "1760270890123_0002_b3f21a9c",
  "ts": "2025-10-13T10:08:10.123Z",
  "items": [
    {
      "id": "todo-1",
      "text": "Search tender corpus for CSR requirements",
      "status": "pending"
    },
    {
      "id": "todo-2",
      "text": "Read Bilag E document",
      "status": "pending"
    },
    {
      "id": "todo-3",
      "text": "Draft compliance statement",
      "status": "pending"
    }
  ]
}
```

**Status values:** `"pending"` | `"in_progress"` | `"completed"`

**Frontend Action:** 
- Display todo list with checkboxes
- Update when new plan events arrive (agent updates the plan)
- Show progress (2 of 3 completed)

**Plan Updates:** Agent may emit multiple `plan` events as it progresses. Replace the entire todo list each time.

---

### 3. **tool_start** - Tool Execution Started
```json
{
  "v": 1,
  "type": "tool_start",
  "id": "1760270892456_0003_c4d82b5e",
  "ts": "2025-10-13T10:08:12.456Z",
  "call_id": "tool_abc123",
  "name": "search_tender_corpus",
  "args_summary": "query='CSR krav'"
}
```

**Common tool names:**
- `search_tender_corpus` - Searching documents
- `get_file_content` - Reading a file
- `read_file` - Reading workspace file
- `task` - Delegating to subagent
- `ls` - Listing files
- `web_search` - External web search

**Frontend Action:** Show "🔧 Searching documents..." or similar based on tool name

---

### 4. **tool_end** - Tool Execution Finished
```json
{
  "v": 1,
  "type": "tool_end",
  "id": "1760270895906_0004_d5e93f2a",
  "ts": "2025-10-13T10:08:15.906Z",
  "call_id": "tool_abc123",
  "name": "search_tender_corpus",
  "status": "ok",
  "ms": 3450,
  "result_summary": "Found 3 relevant sections"
}
```

**Status values:** `"ok"` | `"error"`

**Frontend Action:** 
- Show "✓ Found 3 relevant sections (3.4s)"
- Match `call_id` with corresponding `tool_start`
- Update tool progress indicator

---

### 5. **status** - Progress Update (Heartbeat)
```json
{
  "v": 1,
  "type": "status",
  "id": "1760270910123_0005_e6f8a4b1",
  "ts": "2025-10-13T10:08:30.123Z",
  "text": "Processing... (15s elapsed)"
}
```

**Frequency:** Every 15 seconds during long operations

**Frontend Action:** Update status text, keep loading indicator active

**Special case - HITL:** If `text` contains "⏸️ Agent needs human input", check the `md` field for interrupt details:
```json
{
  "text": "⏸️ Agent needs human input",
  "md": "{\"interrupt\":true,\"question\":\"...\",\"context\":\"...\",\"thread_id\":\"...\"}"
}
```

---

### 6. **content** - Response Chunks
```json
{
  "v": 1,
  "type": "content",
  "id": "1760270920456_0015_f7a9b2c3",
  "ts": "2025-10-13T10:08:40.456Z",
  "md": "# CSR Requirements\n\nBased on Bilag E..."
}
```

**Frontend Action:** 
- Append to response text
- Render as markdown
- Multiple `content` events = progressive response

---

### 7. **end** - Processing Complete
```json
{
  "v": 1,
  "type": "end",
  "id": "1760270930333_0036_c2024cde",
  "ts": "2025-10-13T10:08:50.333Z",
  "status": "completed",
  "ms_total": 41500,
  "tool_calls": 5
}
```

**Status values:** `"completed"` | `"interrupted"` | `"error"`

**Frontend Action:** 
- Close EventSource
- Hide loading indicator
- Show "Completed in 41.5s"
- If status is `"interrupted"`, show resume options

---

### 8. **error** - Processing Failed
```json
{
  "v": 1,
  "type": "error",
  "id": "1760270895000_0004_abc123",
  "ts": "2025-10-13T10:08:15.000Z",
  "error": "Connection timeout"
}
```

**Frontend Action:** 
- Close EventSource
- Show error message
- Provide retry button

---

## Implementation Pattern

### Basic Setup
```javascript
function streamAgentResponse(streamUrl) {
  const eventSource = new EventSource(baseUrl + streamUrl);
  
  // Initialize state
  const state = {
    plan: [],
    tools: new Map(),
    content: "",
    status: "processing"
  };
  
  // Listen for each event type
  eventSource.addEventListener("start", (e) => {
    const data = JSON.parse(e.data);
    updateUI({ status: "Agent started..." });
  });
  
  eventSource.addEventListener("plan", (e) => {
    const data = JSON.parse(e.data);
    state.plan = data.items;
    renderTodoList(data.items);
  });
  
  eventSource.addEventListener("tool_start", (e) => {
    const data = JSON.parse(e.data);
    state.tools.set(data.call_id, {
      name: data.name,
      status: "running",
      startTime: Date.now()
    });
    updateToolUI(data.call_id, "running");
  });
  
  eventSource.addEventListener("tool_end", (e) => {
    const data = JSON.parse(e.data);
    const tool = state.tools.get(data.call_id);
    if (tool) {
      tool.status = data.status;
      tool.duration = data.ms;
      tool.result = data.result_summary;
    }
    updateToolUI(data.call_id, data.status, data.ms, data.result_summary);
  });
  
  eventSource.addEventListener("status", (e) => {
    const data = JSON.parse(e.data);
    updateStatusText(data.text);
  });
  
  eventSource.addEventListener("content", (e) => {
    const data = JSON.parse(e.data);
    state.content += data.md;
    renderMarkdown(state.content);
  });
  
  eventSource.addEventListener("end", (e) => {
    const data = JSON.parse(e.data);
    eventSource.close();
    updateUI({
      status: data.status === "completed" ? "Completed" : data.status,
      stats: `${data.ms_total}ms, ${data.tool_calls} tools`
    });
  });
  
  eventSource.addEventListener("error", (e) => {
    // Only close on real errors, not reconnect attempts
    if (eventSource.readyState === EventSource.CLOSED) {
      const data = JSON.parse(e.data || "{}");
      showError(data.error || "Connection lost");
      eventSource.close();
    }
  });
  
  return eventSource;
}
```

### Complete Flow
```javascript
async function sendMessage(chatId, content, metadata = {}) {
  // Step 1: POST to create message
  const response = await fetch(`/api/chats/${chatId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata })
  });
  
  const { message_id, stream_url } = await response.json();
  
  // Step 2: Open SSE stream
  const eventSource = streamAgentResponse(stream_url);
  
  // Return cleanup function
  return () => eventSource.close();
}
```

---

## UI Components Mapping

| Event | UI Component | Update Trigger |
|-------|--------------|----------------|
| `start` | Loading spinner | Show |
| `plan` | Todo list with checkboxes | Replace entire list |
| `tool_start` | Tool progress card | Add/update |
| `tool_end` | Tool progress card | Mark complete |
| `status` | Status text | Update text |
| `content` | Markdown viewer | Append |
| `end` | Stats summary | Show |

---

## Error Handling

### Connection Lost
EventSource automatically reconnects with:
- 3-second retry delay (from `retry: 3000`)
- Automatic `Last-Event-ID` header
- Server replays missed events

**No frontend code needed** - it's automatic.

### Manual Retry
```javascript
eventSource.onerror = (error) => {
  if (eventSource.readyState === EventSource.CLOSED) {
    // Permanent failure - show retry button
    showRetryButton(() => {
      eventSource.close();
      streamAgentResponse(stream_url);
    });
  }
  // EventSource is reconnecting - do nothing
};
```

---

## Long-Running Queries (30s - 30m)

**Heartbeats:** Every 15s you'll receive `status` events to keep connection alive

**Timeouts:** None on server side - stream stays open until completion

**Mobile:** EventSource survives app backgrounding/foregrounding

---

## Plan Updates Behavior

The agent updates its plan as it progresses:

**Initial plan:**
```json
{
  "items": [
    {"id": "1", "text": "Search documents", "status": "pending"},
    {"id": "2", "text": "Analyze results", "status": "pending"},
    {"id": "3", "text": "Draft response", "status": "pending"}
  ]
}
```

**After completing step 1:**
```json
{
  "items": [
    {"id": "1", "text": "Search documents", "status": "completed"},
    {"id": "2", "text": "Analyze results", "status": "in_progress"},
    {"id": "3", "text": "Draft response", "status": "pending"}
  ]
}
```

**Frontend:** Replace entire todo list on each `plan` event. Match by `id` to animate transitions.

---

## Testing

### With curl
```bash
# Step 1: Create message
RESPONSE=$(curl -X POST http://localhost:8000/api/chats/$CHAT_ID/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Test query","metadata":{}}')

STREAM_URL=$(echo $RESPONSE | jq -r '.stream_url')

# Step 2: Watch stream
curl -N http://localhost:8000$STREAM_URL
```

### With Browser Console
```javascript
// Create message
const res = await fetch('/api/chats/YOUR_CHAT_ID/messages', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    content: 'Test query',
    metadata: {}
  })
});

const { stream_url } = await res.json();

// Open stream
const es = new EventSource(stream_url);
es.onmessage = (e) => console.log('Event:', e.type, JSON.parse(e.data));
```

---

## Key Points

1. **Two-step process:** Always POST first, then GET stream_url
2. **Named events:** Use `addEventListener(type, handler)` not just `onmessage`
3. **Plan updates:** Replace entire list when you receive new `plan` event
4. **Auto-reconnect:** EventSource handles it - no frontend code needed
5. **Close on end:** Always close EventSource when you receive `end` event
6. **Tool matching:** Use `call_id` to match `tool_start` with `tool_end`
7. **Heartbeats:** `status` events every 15s keep connection alive

---

## Production Checklist

- [ ] Handle all 8 event types
- [ ] Close EventSource on `end` event
- [ ] Show loading state on `start`
- [ ] Render todo list on `plan` events
- [ ] Update todo list when receiving new `plan` events
- [ ] Match tool_start/tool_end by `call_id`
- [ ] Append `content` events (don't replace)
- [ ] Test with long queries (>1 minute)
- [ ] Test reconnection (kill network, restore)
- [ ] Handle error events gracefully

---

## API Base URL

**Development:** `http://localhost:8000`
**Production:** Your deployment URL

**Stream URLs:** Relative paths (e.g., `/api/chats/...`) - prepend base URL

---

## Support

**Backend Status:** ✅ Fully implemented and tested

**Event Persistence:** All events saved to MongoDB for debugging

**Resume:** Automatic via EventSource's `Last-Event-ID` header

**Documentation:** See `STREAMING_API_INTEGRATION.md` for detailed React examples

---

**Ready for Integration** 🚀

