# Streaming API - Complete Integration Guide

**For Frontend Developers**

---

## Table of Contents

1. [Overview](#overview)
2. [Complete API Reference](#complete-api-reference)
3. [Frontend Integration](#frontend-integration)
4. [React Implementation](#react-implementation)
5. [UI Components](#ui-components)
6. [Testing](#testing)

---

## Overview

### What This API Provides

The streaming API enables **real-time transparency** into the AI agent's workflow:

- ✅ **Plan/Todo Lists** - See what the agent plans to do
- ✅ **Tool Calls** - Watch the agent search documents, read files, use web search
- ✅ **Thinking** - Understand the agent's reasoning (optional, collapsible)
- ✅ **Status Updates** - Know when long-running operations are happening
- ✅ **Streamed Responses** - Get the answer chunk-by-chunk as it's generated

### Architecture

```
User Action          Frontend                 Backend                  Agent
    |                   |                        |                       |
    |-- Send Message -->|                        |                       |
    |                   |-- POST /messages ----->|                       |
    |                   |<-- {message_id,        |                       |
    |                   |     stream_url} -------|                       |
    |                   |                        |                       |
    |                   |-- GET stream_url ----->|                       |
    |                   |   (EventSource)        |-- invoke_agent ------>|
    |                   |                        |                       |
    |                   |<-- event: start -------|<-- emit(start) -------|
    |                   |<-- event: plan --------|<-- emit(plan) --------|
    |                   |<-- event: tool_start --|<-- emit(tool_start) --|
    |                   |<-- event: tool_end ----|<-- emit(tool_end) ----|
    |<-- Display UI ----|<-- event: content -----|<-- emit(content) -----|
    |<-- Display UI ----|<-- event: end ---------|<-- emit(end) ---------|
    |                   |                        |                       |
    |                   |                        |-- save_to_db -------->|
```

---

## Complete API Reference

### Base URL

```
http://localhost:8000/api
```

### 1. Get or Create User

**Endpoint:** `GET /api/users/{user_id}`

**Description:** Get user details, auto-creates if doesn't exist.

**Response:** `200 OK`
```json
{
  "user_id": "alice@company.com",
  "name": null,
  "email": null,
  "created_at": "2025-10-12T10:00:00Z",
  "last_active": "2025-10-12T10:00:00Z"
}
```

---

### 2. Create Chat (Conversation)

**Endpoint:** `POST /api/users/{user_id}/chats`

**Description:** Start a new conversation.

**Request:**
```json
{
  "title": "SKI 02.15 Analysis"
}
```

**Response:** `201 Created`
```json
{
  "chat_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "alice@company.com",
  "title": "SKI 02.15 Analysis",
  "created_at": "2025-10-12T10:00:00Z",
  "updated_at": "2025-10-12T10:00:00Z",
  "message_count": 0
}
```

---

### 3. Get Chat Details

**Endpoint:** `GET /api/chats/{chat_id}`

**Description:** Get conversation metadata.

**Response:** `200 OK`
```json
{
  "chat_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "alice@company.com",
  "title": "SKI 02.15 Analysis",
  "created_at": "2025-10-12T10:00:00Z",
  "updated_at": "2025-10-12T10:05:00Z",
  "message_count": 5
}
```

---

### 4. Get Message History

**Endpoint:** `GET /api/chats/{chat_id}/messages?page=1&page_size=20`

**Description:** Get conversation history (paginated).

**Query Parameters:**
- `page` (optional, default: 1) - Page number
- `page_size` (optional, default: 20, max: 100) - Items per page

**Response:** `200 OK`
```json
{
  "items": [
    {
      "message_id": "68eb95dcac4dd9ac2789890e",
      "chat_id": "550e8400-e29b-41d4-a716-446655440000",
      "role": "user",
      "content": "Hvad er CSR-kravene?",
      "status": "completed",
      "metadata": {
        "tender_id": "68c99b8a10844521ad051544"
      },
      "created_at": "2025-10-12T10:01:00Z",
      "processing_time_ms": null
    },
    {
      "message_id": "68eb95edac4dd9ac2789890f",
      "chat_id": "550e8400-e29b-41d4-a716-446655440000",
      "role": "assistant",
      "content": "# CSR-krav i Rammeaftale 02.15...",
      "status": "completed",
      "metadata": {},
      "created_at": "2025-10-12T10:01:15Z",
      "processing_time_ms": 15234
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20,
  "total_pages": 1,
  "has_more": false
}
```

---

### 5. Create Message (Send User Message)

**Endpoint:** `POST /api/chats/{chat_id}/messages`

**Description:** Send user message, get stream URL for response.

**Request:**
```json
{
  "content": "Hvad er CSR-kravene?",
  "metadata": {
    "tender_id": "68c99b8a10844521ad051544"
  }
}
```

**Response:** `201 Created`
```json
{
  "message_id": "68eb95dcac4dd9ac2789890e",
  "stream_url": "/api/chats/{chat_id}/messages/{message_id}/stream"
}
```

---

### 6. Stream Message Events (SSE)

**Endpoint:** `GET /api/chats/{chat_id}/messages/{message_id}/stream`

**Description:** Open Server-Sent Events stream for real-time updates.

**Response:** `text/event-stream`

**Format:**
```
event: start
id: 1760270888823_0001_a26344ee
data: {"v":1,"type":"start","message_id":"...","status":"processing"}

event: content
id: 1760270929640_0003_fd9811a3
data: {"v":1,"type":"content","md":"Response text..."}

event: end
id: 1760270930333_0036_c2024cde
data: {"v":1,"type":"end","status":"completed","ms_total":17548}
```

---

### 7. Replay Events (Debugging)

**Endpoint:** `GET /api/messages/{message_id}/events?since={event_id}`

**Description:** Get persisted events for a message (debugging).

**Query Parameters:**
- `since` (optional) - Get events after this event ID

**Response:** `200 OK`
```json
[
  {
    "v": 1,
    "type": "start",
    "id": "...",
    "ts": "2025-10-12T10:01:00Z",
    "message_id": "...",
    "status": "processing"
  },
  ...
]
```

---

## Event Schema (v1)

### Event Types

#### 1. `start` - Processing Started
```json
{
  "v": 1,
  "type": "start",
  "id": "1760270888823_0001_a26344ee",
  "ts": "2025-10-12T12:08:08.823811+00:00",
  "message_id": "68eb9a170b8a377cc7e09834",
  "chat_id": "fc98b84e-c1c4-49ad-a29e-3bb03e67d55f",
  "status": "processing"
}
```

#### 2. `plan` - Agent Created Todo List
```json
{
  "v": 1,
  "type": "plan",
  "id": "...",
  "ts": "...",
  "items": [
    {
      "id": "todo-1",
      "text": "Search tender corpus for CSR requirements",
      "status": "in_progress"
    },
    {
      "id": "todo-2",
      "text": "Analyze Bilag E",
      "status": "pending"
    }
  ]
}
```

**Status values:** `"pending"` | `"in_progress"` | `"completed"`

#### 3. `tool_start` - Tool Execution Started
```json
{
  "v": 1,
  "type": "tool_start",
  "id": "...",
  "ts": "...",
  "call_id": "tool-abc123",
  "name": "search_tender_corpus",
  "args_summary": "query='CSR krav'"
}
```

**Common tool names:**
- `search_tender_corpus` - Searching tender documents
- `get_file_content` - Reading a specific file
- `web_search` - External web search
- `read_file` - Reading from virtual filesystem
- `write_file` - Writing to virtual filesystem
- `task` - Delegating to subagent

#### 4. `tool_end` - Tool Execution Finished
```json
{
  "v": 1,
  "type": "tool_end",
  "id": "...",
  "ts": "...",
  "call_id": "tool-abc123",
  "name": "search_tender_corpus",
  "status": "ok",
  "ms": 2450,
  "result_summary": "Found 3 relevant sections in Bilag E"
}
```

**Status values:** `"ok"` | `"error"`

#### 5. `status` - Long-Running Update
```json
{
  "v": 1,
  "type": "status",
  "id": "...",
  "ts": "...",
  "text": "Analyzing Bilag E (15s elapsed)"
}
```

#### 6. `rationale` - Agent Thinking
```json
{
  "v": 1,
  "type": "rationale",
  "id": "...",
  "ts": "...",
  "text": "I'll cross-check CSR clauses from Bilag E against the framework"
}
```

#### 7. `content` - Response Chunks
```json
{
  "v": 1,
  "type": "content",
  "id": "...",
  "ts": "...",
  "md": "# CSR Requirements\n\nBased on analysis..."
}
```

**Note:** Multiple `content` events stream the response. Concatenate all `md` fields.

#### 8. `end` - Processing Complete
```json
{
  "v": 1,
  "type": "end",
  "id": "...",
  "ts": "...",
  "status": "completed",
  "ms_total": 35124,
  "tool_calls": 5
}
```

**Status values:** `"completed"` | `"error"`

#### 9. `error` - Processing Failed
```json
{
  "v": 1,
  "type": "error",
  "id": "...",
  "ts": "...",
  "error": "Tool execution timeout"
}
```

---

## Frontend Integration

### Complete User Flow

```
1. App loads → GET /api/users/{user_id}
2. Display chat list (if you add list endpoint)
3. User creates/selects chat → POST /api/users/{user_id}/chats
4. Load history → GET /api/chats/{chat_id}/messages
5. Display conversation history
6. User types message → POST /api/chats/{chat_id}/messages
7. Get {message_id, stream_url}
8. Open EventSource(stream_url)
9. Display real-time events as they arrive
10. On 'end' event, close stream
11. User types next message → Repeat steps 6-10
```

---

## React Implementation

### 1. Hook: `useStreamingMessage`

```typescript
import { useState, useEffect, useRef } from 'react';

interface PlanItem {
  id: string;
  text: string;
  status: 'pending' | 'in_progress' | 'completed';
}

interface ToolCall {
  id: string;
  name: string;
  status: 'running' | 'completed' | 'error';
  startTime: number;
  endTime?: number;
  duration?: number;
  result?: string;
  args?: string;
}

interface UseStreamingMessageResult {
  messageId: string | null;
  isStreaming: boolean;
  plan: PlanItem[];
  toolCalls: ToolCall[];
  rationale: string;
  content: string;
  status: string;
  error: string | null;
}

export function useStreamingMessage(
  chatId: string,
  userMessage: string,
  metadata: Record<string, any>
): UseStreamingMessageResult {
  const [messageId, setMessageId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [plan, setPlan] = useState<PlanItem[]>([]);
  const [toolCalls, setToolCalls] = useState<Map<string, ToolCall>>(new Map());
  const [rationale, setRationale] = useState<string>('');
  const [content, setContent] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let mounted = true;

    async function startStreaming() {
      try {
        // Step 1: Create message
        const response = await fetch(`/api/chats/${chatId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: userMessage, metadata })
        });

        if (!response.ok) throw new Error('Failed to create message');

        const { message_id, stream_url } = await response.json();
        if (!mounted) return;
        
        setMessageId(message_id);

        // Step 2: Open SSE stream
        const eventSource = new EventSource(`${window.location.origin}${stream_url}`);
        eventSourceRef.current = eventSource;
        setIsStreaming(true);

        eventSource.onmessage = (event) => {
          if (!mounted) return;
          
          const data = JSON.parse(event.data);

          switch (data.type) {
            case 'start':
              setStatus('Processing...');
              break;

            case 'plan':
              setPlan(data.items || []);
              break;

            case 'tool_start':
              setToolCalls(prev => {
                const updated = new Map(prev);
                updated.set(data.call_id, {
                  id: data.call_id,
                  name: data.name,
                  status: 'running',
                  startTime: Date.now(),
                  args: data.args_summary
                });
                return updated;
              });
              break;

            case 'tool_end':
              setToolCalls(prev => {
                const updated = new Map(prev);
                const tool = updated.get(data.call_id);
                if (tool) {
                  const endTime = Date.now();
                  updated.set(data.call_id, {
                    ...tool,
                    status: data.status === 'ok' ? 'completed' : 'error',
                    endTime,
                    duration: data.ms,
                    result: data.result_summary
                  });
                }
                return updated;
              });
              break;

            case 'status':
              setStatus(data.text);
              break;

            case 'rationale':
              setRationale(data.text);
              break;

            case 'content':
              setContent(prev => prev + data.md);
              break;

            case 'end':
              setIsStreaming(false);
              setStatus(data.status === 'completed' ? 'Completed' : 'Failed');
              eventSource.close();
              break;

            case 'error':
              setError(data.error);
              setIsStreaming(false);
              eventSource.close();
              break;
          }
        };

        eventSource.onerror = () => {
          if (!mounted) return;
          setError('Stream connection lost');
          setIsStreaming(false);
          eventSource.close();
        };

      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : 'Unknown error');
        setIsStreaming(false);
      }
    }

    startStreaming();

    return () => {
      mounted = false;
      eventSourceRef.current?.close();
    };
  }, [chatId, userMessage, metadata]);

  return {
    messageId,
    isStreaming,
    plan,
    toolCalls: Array.from(toolCalls.values()),
    rationale,
    content,
    status,
    error
  };
}
```

### 2. Component: `StreamingMessage`

```typescript
import React from 'react';
import ReactMarkdown from 'react-markdown';
import { useStreamingMessage } from './useStreamingMessage';

interface StreamingMessageProps {
  chatId: string;
  userMessage: string;
  metadata?: Record<string, any>;
}

export function StreamingMessage({ 
  chatId, 
  userMessage, 
  metadata = {} 
}: StreamingMessageProps) {
  const {
    isStreaming,
    plan,
    toolCalls,
    rationale,
    content,
    status,
    error
  } = useStreamingMessage(chatId, userMessage, metadata);

  if (error) {
    return (
      <div className="message-error">
        <span className="error-icon">⚠️</span>
        <span>Error: {error}</span>
      </div>
    );
  }

  return (
    <div className="streaming-message">
      {/* Status Indicator */}
      {isStreaming && status && (
        <div className="status-bar">
          <div className="spinner" />
          <span>{status}</span>
        </div>
      )}

      {/* Plan/Todo List */}
      {plan.length > 0 && (
        <div className="plan-section">
          <h4>📋 Plan</h4>
          <ul className="plan-list">
            {plan.map(item => (
              <li key={item.id} className={`plan-item status-${item.status}`}>
                <span className="plan-icon">
                  {item.status === 'completed' && '✓'}
                  {item.status === 'in_progress' && '⚙️'}
                  {item.status === 'pending' && '○'}
                </span>
                <span className="plan-text">{item.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Tool Calls */}
      {toolCalls.length > 0 && (
        <div className="tools-section">
          <h4>🔧 Tools</h4>
          <div className="tool-list">
            {toolCalls.map(tool => (
              <div key={tool.id} className={`tool-item status-${tool.status}`}>
                <div className="tool-header">
                  <span className="tool-name">{formatToolName(tool.name)}</span>
                  <span className="tool-status">
                    {tool.status === 'running' && <Spinner size="small" />}
                    {tool.status === 'completed' && '✓'}
                    {tool.status === 'error' && '✗'}
                  </span>
                  {tool.duration && (
                    <span className="tool-duration">{tool.duration}ms</span>
                  )}
                </div>
                {tool.args && (
                  <div className="tool-args">{tool.args}</div>
                )}
                {tool.result && (
                  <div className="tool-result">{tool.result}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Thinking (Collapsible) */}
      {rationale && (
        <details className="rationale-section">
          <summary>💭 Agent Thinking</summary>
          <p className="rationale-text">{rationale}</p>
        </details>
      )}

      {/* Response Content */}
      {content && (
        <div className="content-section">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      )}

      {/* Completion Indicator */}
      {!isStreaming && content && (
        <div className="completion-indicator">
          <span className="completion-icon">✓</span>
          <span>Response complete</span>
        </div>
      )}
    </div>
  );
}

function formatToolName(name: string): string {
  const names: Record<string, string> = {
    'search_tender_corpus': 'Searching tender documents',
    'get_file_content': 'Reading file',
    'web_search': 'Web search',
    'read_file': 'Reading workspace',
    'write_file': 'Saving to workspace',
    'task': 'Delegating to specialist'
  };
  return names[name] || name;
}

function Spinner({ size = 'default' }: { size?: 'small' | 'default' }) {
  return (
    <div className={`spinner spinner-${size}`}>
      <div className="spinner-ring" />
    </div>
  );
}
```

### 3. Styles (CSS)

```css
.streaming-message {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 8px;
}

/* Status Bar */
.status-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: #e0f2fe;
  border-left: 3px solid #0284c7;
  border-radius: 4px;
  font-size: 0.875rem;
  color: #0c4a6e;
}

/* Plan Section */
.plan-section {
  background: white;
  padding: 1rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.plan-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
}

.plan-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.plan-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 4px;
  font-size: 0.875rem;
}

.plan-item.status-completed {
  background: #f0fdf4;
  color: #166534;
}

.plan-item.status-in_progress {
  background: #fef3c7;
  color: #92400e;
  animation: pulse 2s infinite;
}

.plan-item.status-pending {
  background: #f3f4f6;
  color: #6b7280;
}

/* Tools Section */
.tools-section {
  background: white;
  padding: 1rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.tools-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
}

.tool-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.tool-item {
  padding: 0.75rem;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
}

.tool-item.status-running {
  background: #fef3c7;
  border-color: #fbbf24;
}

.tool-item.status-completed {
  background: #f0fdf4;
  border-color: #86efac;
}

.tool-item.status-error {
  background: #fef2f2;
  border-color: #fca5a5;
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
}

.tool-duration {
  margin-left: auto;
  font-size: 0.75rem;
  color: #6b7280;
}

.tool-args, .tool-result {
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: #f9fafb;
  border-radius: 4px;
  font-size: 0.75rem;
  color: #6b7280;
}

/* Thinking Section */
.rationale-section {
  background: white;
  padding: 1rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.rationale-section summary {
  cursor: pointer;
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
  user-select: none;
}

.rationale-text {
  margin-top: 0.75rem;
  font-size: 0.875rem;
  color: #6b7280;
  line-height: 1.5;
}

/* Content Section */
.content-section {
  background: white;
  padding: 1.5rem;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
}

.content-section h1 { font-size: 1.5rem; margin-top: 0; }
.content-section h2 { font-size: 1.25rem; margin-top: 1.5rem; }
.content-section h3 { font-size: 1.125rem; margin-top: 1.25rem; }
.content-section p { line-height: 1.6; color: #374151; }
.content-section ul, .content-section ol { padding-left: 1.5rem; }
.content-section li { margin-bottom: 0.5rem; }

/* Completion Indicator */
.completion-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: #f0fdf4;
  border-left: 3px solid #22c55e;
  border-radius: 4px;
  font-size: 0.875rem;
  color: #166534;
}

/* Spinner Animation */
.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
}

.spinner-small {
  width: 12px;
  height: 12px;
}

.spinner-ring {
  width: 100%;
  height: 100%;
  border: 2px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Error State */
.message-error {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: #fef2f2;
  border-left: 3px solid #ef4444;
  border-radius: 4px;
  color: #991b1b;
}
```

---

## Testing

### Manual Test with Browser

1. **Start server:**
   ```bash
   python main.py
   ```

2. **Open browser console:**
   ```javascript
   // Create chat
   const chatResp = await fetch('/api/users/test-user/chats', {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ title: 'Test Chat' })
   });
   const { chat_id } = await chatResp.json();
   console.log('Chat ID:', chat_id);

   // Send message
   const msgResp = await fetch(`/api/chats/${chat_id}/messages`, {
     method: 'POST',
     headers: { 'Content-Type': 'application/json' },
     body: JSON.stringify({ 
       content: 'Who are you?',
       metadata: {}
     })
   });
   const { message_id, stream_url } = await msgResp.json();
   console.log('Stream URL:', stream_url);

   // Open stream
   const eventSource = new EventSource(stream_url);
   eventSource.onmessage = (e) => {
     const data = JSON.parse(e.data);
     console.log(data.type, data);
   };
   ```

### Test with cURL

```bash
# 1. Create chat
CHAT_ID=$(curl -s -X POST http://localhost:8000/api/users/test/chats \
  -H "Content-Type: application/json" \
  -d '{"title":"Test"}' | jq -r '.chat_id')

# 2. Send message
STREAM=$(curl -s -X POST http://localhost:8000/api/chats/$CHAT_ID/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Hello","metadata":{}}' | jq -r '.stream_url')

# 3. Watch stream
curl -N http://localhost:8000$STREAM

# 4. Get history
curl -s http://localhost:8000/api/chats/$CHAT_ID/messages | jq
```

---

## Key Implementation Notes

### 1. SSE Reconnection

```typescript
// Implement automatic reconnection
const createEventSource = (url: string, retries = 3) => {
  const es = new EventSource(url);
  
  es.onerror = () => {
    if (retries > 0) {
      setTimeout(() => {
        createEventSource(url, retries - 1);
      }, 1000);
    }
  };
  
  return es;
};
```

### 2. Message Status

Messages have these statuses:
- `pending` - Created, waiting to process
- `processing` - Agent is working
- `completed` - Finished successfully
- `error` - Failed

### 3. Pagination

Load more messages:
```typescript
const loadMore = async () => {
  const response = await fetch(
    `/api/chats/${chatId}/messages?page=${currentPage + 1}&page_size=20`
  );
  const data = await response.json();
  setMessages(prev => [...prev, ...data.items]);
  setCurrentPage(prev => prev + 1);
  setHasMore(data.has_more);
};
```

### 4. TypeScript Types

```typescript
// Complete type definitions
export interface Message {
  message_id: string;
  chat_id: string;
  role: 'user' | 'assistant';
  content: string;
  status: 'pending' | 'processing' | 'completed' | 'error';
  metadata: Record<string, any>;
  created_at: string;
  processing_time_ms?: number;
  error?: string;
}

export interface Chat {
  chat_id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface StreamEvent {
  v: number;
  type: 'start' | 'plan' | 'tool_start' | 'tool_end' | 'status' | 'rationale' | 'content' | 'end' | 'error';
  id: string;
  ts: string;
  [key: string]: any;
}
```

---

## Production Checklist

- [ ] Backend running on production URL
- [ ] CORS configured for your frontend domain
- [ ] Environment variables set (MONGODB_URL, etc.)
- [ ] Error boundaries in React components
- [ ] Loading states for all API calls
- [ ] Graceful handling of connection drops
- [ ] Message persistence verified
- [ ] Pagination tested with large histories
- [ ] Mobile responsive design
- [ ] Accessibility (keyboard navigation, screen readers)

---

## Support

**Backend:** All streaming infrastructure is complete and tested ✅

**Frontend:** Follow this guide for complete integration. All endpoints, events, and flows are documented.

**Questions?** Check the API responses in browser DevTools Network tab to debug issues.

---

**Ready for Production! 🚀**
