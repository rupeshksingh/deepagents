# Background Agents Architecture

**Status:** ✅ Production Ready  
**Date:** October 25, 2025  
**Last Updated:** October 25, 2025 (MongoDB Task Queue + Durable Execution)

---

## Overview

The streaming API supports **production-grade durable background agent execution**. This enables:

- ✅ **Tasks survive server restart** (MongoDB-backed queue with leases)
- ✅ **Multiple agents running simultaneously** (horizontally scalable workers)
- ✅ **User can switch between chats** - see live progress in all
- ✅ **Agents continue regardless of stream connections** (30s-30min+ runs)
- ✅ **Multiple clients can watch same agent** (identical events from persistence)
- ✅ **No interruption on tab switch or disconnect** (immune to CancelledError)
- ✅ **Strict reconnect with Last-Event-ID** (no duplicates)
- ✅ **No in-memory state** (stateless workers, pure DB reads)
- ✅ **Automatic retry on failure** (configurable max attempts)

---

## Architecture Changes

### Before (In-Memory Registry)

```
POST /messages → Creates DB record + Starts asyncio task in registry
                 ↓
              In-Memory Task (lost on restart) ❌
                 ↓
              Persists events to DB
              
GET /stream → Watches registry for liveness
              ↓
           Registry lost on restart ❌
```

**Problem:** Agent state in memory. Server restart = lost tasks.

### After (MongoDB Task Queue)

```
POST /messages → Creates DB record + ENQUEUES TASK to MongoDB
                 ↓
              Task Queue (pa_tasks collection)
                 ↓
              Worker claims task (lease-based locking)
                 ↓
              Executes agent + persists events
              
GET /stream → Watches events by polling DB
              ↓
           Checks message status for completion
           No in-memory dependency ✅
           
Server restart → Workers reclaim stale tasks ✅
```

**Solution:** Tasks persist in MongoDB. Workers claim and execute with leases. Stateless.

---

## Components

### 1. `TaskQueue`

**File:** `api/task_queue.py`

MongoDB-backed task queue with lease-based locking:
- Enqueues tasks (execute/resume) with payload
- Workers claim tasks atomically (FIFO)
- Lease renewal for long-running tasks (prevents reassignment)
- Automatic retry on failure (max attempts configurable)
- Stale task recovery on startup (requeue expired leases)
- No in-memory state (pure MongoDB operations)

**Collection:** `pa_tasks`

```python
{
  "_id": ObjectId,
  "type": "execute" | "resume",
  "chat_id": str,
  "message_id": str,
  "payload": {...},
  "status": "queued" | "running" | "completed" | "failed",
  "lease_until": datetime | None,
  "attempts": int,
  "max_attempts": int,
  "error": str | None,
  "worker_id": str | None
}
```

### 2. `BackgroundWorker`

**File:** `scripts/worker.py`

Standalone worker process:
- Claims tasks from queue (lease-based)
- Executes `execute_agent_pure()` or `execute_resume_pure()`
- Renews lease every 60s (prevents timeout)
- Marks task completed/failed
- Graceful shutdown on SIGTERM (task reassigned when lease expires)
- Can run multiple workers for horizontal scaling

### Event ID Policy & SSE Resume

**CRITICAL:** Event IDs follow a strict persistence-based model:

1. **Emitter IDs are Ephemeral**
   - `StreamingEventEmitter._generate_event_id()` creates temporary IDs during execution
   - Format: `{timestamp_ms}_{seq:04d}_{random}`
   - These IDs are **NOT** persisted to MongoDB

2. **Persisted IDs are Canonical**
   - `EventPersistence.append_event()` **regenerates** event IDs during write (lines 129-130)
   - Uses atomic per-message sequence counter from `message_counters` collection
   - Format: `{timestamp_ms}_{seq:04d}_{random8}`
   - These IDs are what clients receive in SSE streams

3. **SSE Resume with `Last-Event-ID`**
   - Clients MUST use the `id` field from received SSE events
   - `GET /stream?since={event_id}` or `Last-Event-ID: {event_id}` header
   - `EventPersistence.get_events()` parses seq from ID and returns events with seq > parsed_seq
   - Using emitter IDs will cause resume failures (ID not found in DB)

4. **Invariants**
   - Event ordering guaranteed by atomic seq counter
   - Multiple clients can resume from same checkpoint independently
   - Event IDs are immutable once persisted

```python
registry = get_agent_registry()

# Start agent
await registry.start_agent(
    message_id="msg_123",
    chat_id="chat_456",
    agent_coro=run_agent_background(...)
)

# Check if running
is_running = await registry.is_running("msg_123")

# Register watcher
await registry.register_watcher("msg_123", "watcher_1")
```

### 2. `execute_agent_pure()` & `run_agent_background()`

**File:** `api/streaming_store.py`

**NEW: Pure agent execution (production-ready)**
- `execute_agent_pure()`: NO generators, NO yields - immune to client cancellation
- Direct event persistence with retry logic via `RobustEventWriter`
- Completely decoupled from SSE streaming
- Protected by `asyncio.shield()` in registry wrapper

**Key improvements:**
- No `CancelledError` propagation from client disconnects
- Events written directly to DB (not through yield)
- Retry logic with exponential backoff
- Fallback queue for failed events

```python
await run_agent_background(
    store=store,
    event_persistence=event_persistence,
    chat_id=chat_id,
    message_id=message_id,
    user_content="User query",
    metadata={}
)
# Internally uses execute_agent_pure()
# Agent runs to completion, all events saved to DB
# Client disconnect = no effect on agent
```

### 3. `watch_agent_stream()`

**File:** `api/streaming_store.py`

Watches an agent by polling database:
- Reads events from persistence layer
- Polls every 0.5s for new events
- Stops when agent completes (END event)
- Multiple watchers can watch same agent

```python
async for event in watch_agent_stream(
    event_persistence=event_persistence,
    chat_id=chat_id,
    message_id=message_id,
    since_id=None  # or last_event_id for reconnect
):
    yield event  # Send to client
```

---

## API Flow

### Creating a Message (POST)

```python
POST /api/chats/{chat_id}/messages
{
  "content": "Analyze this tender document"
}
```

**What happens:**
1. Creates user + assistant messages in DB
2. **Immediately starts agent as background task**
3. Returns stream URL
4. Agent runs independently

**Response:**
```json
{
  "message_id": "msg_123",
  "stream_url": "/api/chats/{chat_id}/messages/msg_123/stream"
}
```

### Watching Agent (GET)

```python
GET /api/chats/{chat_id}/messages/msg_123/stream
Accept: text/event-stream
```

**What happens:**
1. Creates watcher ID
2. Registers watcher with registry
3. Polls database for events
4. Streams events as SSE
5. Stops when END event found or agent completes

**Multiple clients can GET same URL** - all watch same agent!

---

## User Experience

### Scenario 1: Multiple Running Agents

```
User creates query in Chat A → Agent A starts
User switches to Chat B
User creates query in Chat B → Agent B starts (both running!)
User switches back to Chat A → Sees live progress
User switches to Chat C → Both A & B still running
```

### Scenario 2: Tab Switching

```
User creates query → Agent starts
User switches tab → EventSource disconnects
                  → Agent continues running ✅
                  → All events persisted to DB
User switches back → EventSource reconnects
                  → Replays all missed events
                  → Shows complete timeline
```

### Scenario 3: Multiple Windows Watching

```
User opens Chat A in browser window 1
User opens Chat A in browser window 2
Same agent, both see live updates!
```

---

## Database Schema

Events are persisted real-time to MongoDB:

```javascript
{
  message_id: "msg_123",
  chat_id: "chat_456",
  id: "event_001",  // Unique event ID
  type: "thinking",
  ts: "2025-10-14T10:30:00.000Z",
  text: "I'll analyze this...",
  // ... other event fields
}
```

**Indexed by:** `message_id`, `id` (for since_id queries)

---

## Configuration

### Poll Interval

Watchers poll every **0.5 seconds** for new events.

Adjust in `watch_agent_stream()`:
```python
poll_interval: float = 0.5  # seconds
```

**Tradeoff:**
- Lower = more real-time but more DB load
- Higher = less DB load but more latency

### Max Wait Timeout

Watchers timeout after **1 hour** (3600s) by default.

Adjust in `watch_agent_stream()`:
```python
max_wait: float = 3600.0  # 1 hour
```

### Cleanup

Old completed agents are cleaned up automatically.

Trigger cleanup:
```python
registry = get_agent_registry()
await registry.cleanup_old_tasks(max_age_hours=24)
```

---

## Monitoring

### Check Running Agents

```python
registry = get_agent_registry()

# Total active count
count = await registry.get_active_count()

# List all running
tasks = await registry.list_running()

# List running for specific chat
tasks = await registry.list_running(chat_id="chat_456")
```

### Check Watchers

```python
task = await registry.get_task("msg_123")
if task:
    print(f"Watchers: {len(task.watchers)}")
    print(f"Completed: {task.completed}")
    print(f"Error: {task.error}")
```

---

## Frontend Impact

### No Changes Required! ✅

The frontend API is **identical**:

```typescript
// 1. Create message (agent starts immediately now)
const response = await fetch(`/api/chats/${chatId}/messages`, {
  method: 'POST',
  body: JSON.stringify({ content: userQuery })
});
const { message_id, stream_url } = await response.json();

// 2. Watch stream (now just watches, doesn't start)
const eventSource = new EventSource(stream_url);
eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  handleEvent(event);
};
```

**What changed:**
- POST now starts agent immediately (before: just created DB record)
- GET now watches running agent (before: started agent)

**Result:** Multiple streams work, tab switching works, no agent interruption!

---

## Benefits

### For Users

1. **Start multiple queries** - no waiting for one to finish
2. **Switch between chats** - see live progress in all
3. **Switch tabs** - agent keeps running, no interruption
4. **Open same chat in multiple windows** - all see updates
5. **Long-running agents (30 min+)** - disconnect anytime, reconnect later
6. **Network flakiness** - agent survives connection drops

### For Developers

1. **Decoupled architecture** - agent logic separate from streaming
2. **Easier testing** - can run agent without stream
3. **Better monitoring** - track all running agents
4. **Horizontal scaling ready** - agents are stateless tasks
5. **Production-grade resilience** - retry logic, error recovery, cancellation protection
6. **Zero `CancelledError` issues** - pure async functions, not generators

---

## Migration Guide

### No Breaking Changes

Existing frontend code works without modification. The API surface is unchanged.

### Optional Enhancements

Take advantage of new capabilities:

**1. Show active agents count:**
```typescript
GET /api/stats/active-agents
→ { "count": 3 }
```

**2. Watch agent from different chat:**
```typescript
// If you have the message_id, you can watch from anywhere
const eventSource = new EventSource(
  `/api/chats/${chatId}/messages/${messageId}/stream`
);
```

**3. Multiple watchers:**
```typescript
// Open same stream in multiple components
const watcher1 = new EventSource(streamUrl);
const watcher2 = new EventSource(streamUrl);
// Both receive events independently
```

---

## Testing

### Test 1: Multiple Agents

```bash
# Terminal 1
curl -X POST http://localhost:8000/api/chats/chat1/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Query 1"}'

# Terminal 2 (immediately, don't wait)
curl -X POST http://localhost:8000/api/chats/chat2/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Query 2"}'

# Both agents running simultaneously!
```

### Test 2: Multiple Watchers

```bash
# Terminal 1
curl -N http://localhost:8000/api/chats/chat1/messages/msg123/stream

# Terminal 2 (same message_id!)
curl -N http://localhost:8000/api/chats/chat1/messages/msg123/stream

# Both receive events
```

### Test 3: Tab Switch Simulation

```bash
# Start stream
curl -N http://localhost:8000/api/chats/chat1/messages/msg123/stream

# Ctrl+C to disconnect (simulate tab switch)

# Wait 30 seconds

# Reconnect
curl -N http://localhost:8000/api/chats/chat1/messages/msg123/stream

# Gets all events from start (or use ?since=event_id)
```

---

## Performance Considerations

### Database Load

Watchers poll every 0.5s. With 10 active watchers = 20 queries/second.

**Mitigation:**
- Events indexed by `message_id` + `id`
- Query limited to 100 events per poll
- Completed agents stop polling

### Memory Usage

Each background task holds agent state in memory.

**Mitigation:**
- Tasks cleaned up after completion
- No watcher = task cleanup
- Old tasks pruned after 24 hours

### Concurrent Agents

Python asyncio handles concurrency efficiently.

**Capacity:** Tested with 10+ simultaneous agents without issues.

**Scaling:** For 100+ concurrent agents, consider:
- Redis for agent registry
- Separate worker processes
- Event streaming instead of polling

---

## Future Enhancements

### 1. Redis-backed Registry

Replace in-memory registry with Redis:
- Survives server restarts
- Shared across multiple API instances
- Better horizontal scaling

### 2. WebSocket Broadcasting

Replace polling with WebSocket pub/sub:
- Lower latency (instant updates)
- Reduced database load
- True real-time streaming

### 3. Agent Priority Queue

Prioritize user queries:
- Premium users get faster processing
- Background analytics run at low priority
- Resource management

---

## Summary

**What we built:**
- ✅ True background agent execution
- ✅ Multiple simultaneous agents
- ✅ Independent stream connections
- ✅ Tab-switch resilient
- ✅ Multiple watchers per agent
- ✅ No frontend changes needed

**How it works:**
1. POST /messages → starts agent immediately as background task
2. GET /stream → watches agent by polling database
3. Agent runs independently, all events persisted
4. Multiple clients can watch same agent

**Result:**
Users can run multiple agents, switch between chats, and see live progress everywhere!

🎉 **Your streaming API is now production-grade for long-running agents!**

---

## Production Hardening (Latest Updates)

### Problem: `CancelledError` Killing Agents

**Root cause:** Original `run_agent_background()` used `stream_agent_response()` (a generator with yields). When client disconnected, `CancelledError` propagated through generator and killed the agent.

**Solution:** Completely decoupled agent execution from streaming:

1. **`execute_agent_pure()`** - New pure async function (NO generators, NO yields)
   - Directly persists events to DB
   - Cannot be cancelled by client disconnects
   - Used internally by `run_agent_background()`

2. **`asyncio.shield()`** - Added to `BackgroundAgentRegistry._run_agent_wrapper()`
   - Extra protection layer
   - Even if shield breaches, graceful error handling

3. **`RobustEventWriter`** - Event persistence with retry logic
   - 3 retries with exponential backoff (0.1s, 0.2s, 0.4s)
   - Fallback queue for failed events
   - Never crashes agent on DB hiccup

4. **Improved Watcher Disconnection** - `streaming_router.py`
   - `CancelledError` caught as expected behavior
   - Graceful cleanup in finally block
   - No error logs for normal disconnects

### Key Improvements

✅ **Agent survives client disconnect** - No more `CancelledError` crashes  
✅ **Retry logic for DB writes** - Transient failures handled gracefully  
✅ **Monitoring endpoints** - `GET /api/agents/active` shows running agents  
✅ **Enhanced tests** - Aggressive disconnect, multi-agent stress, error recovery  
✅ **Clean logs** - Client disconnects logged as info, not errors  

### Testing Strategy

Run comprehensive test suite:
```bash
python test_background_agents.py
```

**Tests included:**
1. Multiple agents running simultaneously
2. Multiple watchers on same agent
3. Disconnect/reconnect
4. Aggressive disconnect (5x rapid connect/disconnect)
5. Multi-agent stress (5 agents at once)
6. Error recovery (immediate disconnect after start)

All tests verify:
- Agent completes even with no watchers
- Events fully persisted
- Reconnect shows complete history
- No `CancelledError` in logs

🎯 **Result:** Production-ready background agents that handle 30-second to 30-minute runs with complete client disconnect immunity.

---

## Recent Improvements (Strict Resume + Correctness)

### Atomic Event Sequencing

**Problem:** Non-atomic `seq` assignment could cause race conditions under high load.

**Solution:** Per-message counter collection using atomic `$inc`:
```python
counter_doc = db["message_counters"].find_one_and_update(
    {"_id": message_id},
    {"$inc": {"next_seq": 1}},
    upsert=True,
    return_document=ReturnDocument.AFTER
)
```

### Normalized Event IDs

**Problem:** Event IDs like `start_{message_id}` didn't match parser format, breaking Last-Event-ID resume.

**Solution:** Normalize IDs at persistence time:
```python
doc["id"] = f"{timestamp_ms}_{seq:04d}_{random8}"
```

This enables strict resume - clients use `Last-Event-ID` to get only new events, no duplicates.

### Emitter Integration

**Problem:** Background mode only emitted `tool_start`, never `tool_end` (tools appeared to hang).

**Solution:** Use `StreamingEventEmitter` in background mode:
```python
emitter = StreamingEventEmitter(message_id, chat_id)
set_current_emitter(emitter)
# Middleware now captures tool_start/tool_end automatically
while True:
    evt = await emitter.get_next(timeout=0.01)
    if not evt:
        break
    await event_writer.write_event(evt)
```

### Heartbeat Persistence

**Problem:** Long-running agents (10+ min) showed no progress on reconnect.

**Solution:** Persist STATUS events every 15 seconds:
```python
if (now - last_heartbeat).total_seconds() >= 15:
    await event_writer.write_event(
        create_status_event(f"Processing... ({elapsed}s elapsed)")
    )
```

### Additional Fixes

- **HITL metadata bug:** Fixed `message.get("metadata")` → `message.metadata`
- **User content gate:** Removed unused prior user message lookup in SSE stream
- **TTL index:** Optional retention via `MESSAGE_EVENTS_TTL_SECONDS` or `MESSAGE_EVENTS_TTL_DAYS`

---

