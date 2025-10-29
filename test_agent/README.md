# Testing Guide

## Production API Testing

**All testing now uses the production API endpoints** to ensure consistency between test and production environments.

### Quick Start

```bash
# 1. Ensure .env file has required variables
MONGODB_URL=mongodb://localhost:27017
TENDER_ID=68c99b8a10844521ad051544
GOOGLE_API_KEY=your_key_here

# 2. Start the server
python main.py

# 3. Run production API tests
python test_agent/test_production_api.py
```

---

## Test Script: `test_production_api.py`

Tests the complete production flow including:
- ✅ Chat creation via API
- ✅ Message streaming (SSE)
- ✅ Normal queries
- ✅ HITL (Human-in-the-Loop) interrupts
- ✅ Resume functionality
- ✅ Background summarization

### What It Tests

**Test 1: Normal Query**
- Sends regular question
- Watches SSE stream for events
- Verifies completion

**Test 2: HITL Flow**
- Sends query that triggers `request_human_input`
- Detects interrupt event
- Resumes with human response
- Verifies completion + summarization

### Expected Output

```
🚀🚀🚀 PRODUCTION API TESTING 🚀🚀🚀

📋 Configuration:
   API URL: http://localhost:8000
   User ID: test-user
   Tender ID: 68c99b8a10844521ad051544

✓ Chat created: abc-123-def...

================================================================================
TEST 1: Normal Query (No HITL)
================================================================================
📝 Query: What is the tender deadline?
✓ Message created: 507f1f77bcf86cd799439011

🌊 Streaming events:
  [1] start: ...
  [2] thinking: ...
  [15] content: ...
  [20] end: ...
✓ Test 1 PASSED

================================================================================
TEST 2: HITL Interrupt + Resume
================================================================================
📝 Query: Find CSR requirements and ask me...
✓ Message created: 507f1f77bcf86cd799439012

⏸️  INTERRUPT DETECTED!
   Question: Do you want brief or detailed analysis?

🔄 Resuming with human response...
✓ Resumed successfully
✓ Test 2 PASSED

✅ ALL TESTS PASSED
```

---

## Database Structure

All data is stored in `org_1` database:

```javascript
// Collections:
org_1.pa_users               // User records
org_1.pa_chats               // Chat sessions
org_1.pa_messages            // Message history
org_1.threads                // LangGraph checkpointer + summaries
org_1.message_events         // Streaming event persistence
org_1.message_counters       // Event sequencing

// Thread document (includes summary):
{
  "thread_id": "chat_abc-123...",
  "tender_id": "68c99b8a10844521ad051544",
  "message_count": 5,
  "conversation_summary": {
    "summary_text": "## Conversation Summary\n...",
    "last_message_id": "msg_xyz",
    "token_estimate": 3500,
    "version": 2,
    "messages_summarized_count": 150,
    "excluded_exchanges": 2,
    "strategy": "full"
  }
}
```

---

## Thread ID Pattern

Production uses a consistent pattern:

```python
# API level
chat_id = "550e8400-e29b-41d4-a716-446655440000"  # UUID

# LangGraph level (internal)
thread_id = f"chat_{chat_id}"
# = "chat_550e8400-e29b-41d4-a716-446655440000"
```

**Key Point:** `thread_id` is derived from `chat_id` using `generate_thread_id()` function.

---

## HITL (Human-in-the-Loop) Testing

### Triggering HITL

The agent will interrupt when it calls `request_human_input` tool.

**Example queries that trigger HITL:**
```
"Find CSR requirements and ask me using request_human_input if I want brief or detailed analysis"

"Search for penalty clauses, then use the human input tool to ask which penalty type I want details on"

"Analyze the tender and use request_human_input to confirm if I need compliance recommendations"
```

### Resume Actions

When interrupted, you can resume with:

**1. Accept** - Continue with agent's proposed action
```bash
curl -X POST "http://localhost:8000/api/chats/{chat_id}/messages/{msg_id}/resume" \
  -H "Content-Type: application/json" \
  -d '{"action": "accept"}'
```

**2. Respond** - Provide human response
```bash
curl -X POST "http://localhost:8000/api/chats/{chat_id}/messages/{msg_id}/resume" \
  -H "Content-Type: application/json" \
  -d '{"action": "respond", "args": "Give me detailed analysis with recommendations"}'
```

**3. Edit** - Modify the proposed action
```bash
curl -X POST "http://localhost:8000/api/chats/{chat_id}/messages/{msg_id}/resume" \
  -H "Content-Type: application/json" \
  -d '{"action": "edit", "args": {"modified_params": "..."}}'
```

**4. Ignore** - Skip and continue
```bash
curl -X POST "http://localhost:8000/api/chats/{chat_id}/messages/{msg_id}/resume" \
  -H "Content-Type: application/json" \
  -d '{"action": "ignore"}'
```

---

## Verifying Summarization

### Check Logs
```bash
# Server logs should show:
INFO: Summarization needed for thread_chat_abc: 42,000 smart tokens
INFO: ✓ Summary saved for thread_chat_abc: v1 (full)
INFO: ✓ Injected summary v1: 180 msgs → 17 msgs
```

### Check MongoDB
```javascript
// In MongoDB shell or Compass:
use org_1

// View conversation summary:
db.threads.findOne(
  {"tender_id": "68c99b8a10844521ad051544"},
  {"conversation_summary": 1}
)

// Check if HITL response is in summary:
db.threads.findOne(
  {"tender_id": "68c99b8a10844521ad051544"},
  {"conversation_summary.summary_text": 1}
)
// Should contain: "Human (HITL): Give me detailed analysis..."
```

---

## Manual API Testing

### 1. Create Chat
```bash
curl -X POST "http://localhost:8000/api/users/test-user/chats" \
  -H "Content-Type: application/json" \
  -d '{"title": "Manual Test"}'

# Returns: {"chat_id": "...", ...}
```

### 2. Send Message
```bash
curl -X POST "http://localhost:8000/api/chats/{CHAT_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Your query here",
    "metadata": {"tender_id": "68c99b8a10844521ad051544"}
  }'

# Returns: {"message_id": "...", "stream_url": "..."}
```

### 3. Watch Stream (SSE)
```bash
curl -N "http://localhost:8000/api/chats/{CHAT_ID}/messages/{MSG_ID}/stream"

# You'll see Server-Sent Events:
# event: start
# data: {...}
#
# event: thinking
# data: {...}
#
# event: content
# data: {...}
#
# event: end
# data: {...}
```

### 4. Resume (if interrupted)
```bash
curl -X POST "http://localhost:8000/api/chats/{CHAT_ID}/messages/{MSG_ID}/resume" \
  -H "Content-Type: application/json" \
  -d '{"action": "respond", "args": "Your human response"}'
```

---

## Architecture Notes

### Production Code Path
```
User Request (API)
    ↓
POST /api/chats/{chat_id}/messages
    ↓
api/streaming_store.py: stream_agent_response()
    ↓
agent.agent.astream(initial_state, config)  ← Real LangGraph streaming
    ↓
Stream SSE events to client
    ↓
On completion: agent._schedule_summarization()  ← Background task
    ↓
Summary saved to org_1.threads
    ↓
Next request: Summary injected via PersistentSummarizationMiddleware
```

### No More Direct Agent Testing
- ❌ Removed: `ReactAgent.chat_streaming()`
- ❌ Removed: Direct `agent.ainvoke()` test paths
- ✅ Only: Production API endpoints

This ensures:
- No code path divergence
- Tests reflect actual production behavior
- Single source of truth
- HITL interrupts work correctly
- Summarization triggers properly

---

## Troubleshooting

### "Connection refused"
→ Make sure server is running: `python main.py`

### "TENDER_ID not found"
→ Set in .env file: `TENDER_ID=68c99b8a10844521ad051544`

### "No interrupt detected"
→ Make sure query explicitly mentions `request_human_input` tool

### "Summary not found in MongoDB"
→ Wait for background task to complete (check logs for "✓ Summary saved")
→ Verify you've exceeded token threshold (default: 120K, testing: 40K)

---

For more information, see the main README.md in the project root.
