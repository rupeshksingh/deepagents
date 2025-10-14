# Frontend Integration Guide - Background Agents

**Date:** October 14, 2025  
**Status:** Production Ready

---

## What Changed

**Before:** Agents would crash if users switched tabs or lost connection.

**Now:** Agents run in the background independently. Users can:
- Switch tabs freely
- Close the browser
- Lose network connection
- Come back anytime to see live progress or final results

**Your code doesn't need to change.** The API is identical, but now it's bulletproof.

---

## Quick Start

### 1. Create a Message (Starts Agent Immediately)

```typescript
const response = await fetch(`/api/chats/${chatId}/messages`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: userQuery })
});

const { message_id, stream_url } = await response.json();
// Agent is now running in background!
```

**Important:** The agent **starts immediately** when you POST. You don't need to open the stream right away.

### 2. Watch Events via SSE

```typescript
const eventSource = new EventSource(stream_url);

eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  
  switch (event.type) {
    case 'start':
      console.log('Agent started');
      break;
    case 'thinking':
      console.log('Thinking:', event.text);
      break;
    case 'tool_start':
      console.log('Tool:', event.name);
      break;
    case 'tool_end':
      console.log('Tool finished:', event.name, `(${event.ms}ms)`);
      break;
    case 'status':
      console.log('Status:', event.text); // Heartbeat every 15s
      break;
    case 'content':
      appendToUI(event.md); // Final response chunks
      break;
    case 'end':
      console.log('Agent completed');
      eventSource.close();
      break;
  }
};

eventSource.onerror = () => {
  console.log('Connection lost - agent still running');
  // Handle reconnect (see below)
};
```

---

## Key Features

### ✅ Background Execution

Agents run **independently** of the stream. If the user:
- Switches tabs → Agent continues
- Closes browser → Agent continues
- Loses network → Agent continues

When they come back, they see:
- Live progress (if still running)
- Complete results (if finished)

### ✅ Reconnect with Last-Event-ID

If connection drops, reconnect from where you left off:

```typescript
let lastEventId = null;

eventSource.onmessage = (e) => {
  lastEventId = e.lastEventId; // Save for reconnect
  const event = JSON.parse(e.data);
  // ... handle event
};

// On reconnect:
const eventSource = new EventSource(
  `${stream_url}?since=${lastEventId}`
);
```

**No duplicate events!** The backend sends only new events after the `lastEventId`.

### ✅ Heartbeats

For long-running agents (30+ minutes), the backend sends STATUS events every 15 seconds:

```json
{
  "type": "status",
  "text": "Processing... (347s elapsed)"
}
```

Show these to indicate the agent is still working.

### ✅ Multiple Watchers

Multiple users can watch the same agent:

```typescript
// User 1 opens chat
const watcher1 = new EventSource(streamUrl);

// User 2 opens same chat
const watcher2 = new EventSource(streamUrl);

// Both see identical events in real-time
```

---

## Event Types Reference

| Type | Description | Key Fields |
|------|-------------|------------|
| `start` | Agent started | `message_id`, `chat_id` |
| `thinking` | Agent reasoning | `text` |
| `tool_start` | Tool call begins | `name`, `call_id` |
| `tool_end` | Tool call ends | `name`, `ms`, `status` |
| `status` | Heartbeat / progress | `text` |
| `content_start` | Final response begins | - |
| `content` | Response chunk | `md` |
| `content_end` | Final response ends | - |
| `end` | Agent completed | `status`, `ms_total`, `tool_calls` |
| `error` | Error occurred | `error` |

---

## Complete Example: React Component

```typescript
import { useEffect, useState } from 'react';

function AgentChat({ chatId }) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState('idle');
  const [lastEventId, setLastEventId] = useState(null);
  
  async function sendMessage(content: string) {
    // 1. Create message (starts agent)
    const res = await fetch(`/api/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    
    const { message_id, stream_url } = await res.json();
    
    // 2. Watch stream
    watchStream(stream_url);
  }
  
  function watchStream(streamUrl: string) {
    const url = lastEventId 
      ? `${streamUrl}?since=${lastEventId}`
      : streamUrl;
    
    const eventSource = new EventSource(url);
    
    eventSource.onmessage = (e) => {
      setLastEventId(e.lastEventId);
      const event = JSON.parse(e.data);
      
      switch (event.type) {
        case 'start':
          setStatus('running');
          break;
          
        case 'thinking':
          addMessage({ role: 'thinking', content: event.text });
          break;
          
        case 'tool_start':
          setStatus(`Running tool: ${event.name}`);
          break;
          
        case 'status':
          setStatus(event.text); // Show heartbeat
          break;
          
        case 'content':
          appendToLastMessage(event.md);
          break;
          
        case 'end':
          setStatus('completed');
          eventSource.close();
          break;
          
        case 'error':
          setStatus(`Error: ${event.error}`);
          eventSource.close();
          break;
      }
    };
    
    eventSource.onerror = () => {
      setStatus('disconnected - agent still running');
      eventSource.close();
      
      // Auto-reconnect after 3 seconds
      setTimeout(() => watchStream(streamUrl), 3000);
    };
  }
  
  return (
    <div>
      <div>Status: {status}</div>
      {messages.map((msg, i) => (
        <div key={i}>{msg.content}</div>
      ))}
    </div>
  );
}
```

---

## Best Practices

### ✅ DO:
- Save `lastEventId` for reconnection
- Show heartbeat status during long operations
- Auto-reconnect on connection loss
- Close EventSource when done

### ❌ DON'T:
- Don't restart the agent on reconnect (it's already running!)
- Don't ignore heartbeats (users want to know it's working)
- Don't assume connection = agent running (it's independent)

---

## Monitoring Active Agents

Check running agents (optional):

```typescript
const res = await fetch('/api/agents/active');
const { count, agents } = await res.json();

console.log(`${count} agents running`);
agents.forEach(agent => {
  console.log(`- Message ${agent.message_id}: ${agent.watchers} watchers`);
});
```

---

## Migration from Old System

**No code changes needed!** 

If you were using the old streaming API:
- POST creates message → ✅ Works (now also starts agent)
- GET watches stream → ✅ Works (now watches background agent)
- EventSource handling → ✅ Works (same event format)

**What's new:**
- Agent doesn't die on disconnect (automatically fixed)
- Last-Event-ID resume works properly (no duplicates)
- Heartbeats show liveness (every 15s)
- tool_end events now present (shows tool completion)

---

## Troubleshooting

**Problem:** Events seem to stop

**Check:**
1. Is the agent still running? (`GET /api/agents/active`)
2. Did you get an `end` event? (agent finished)
3. Connection lost? (check `eventSource.onerror`)

**Problem:** Duplicate events on reconnect

**Solution:** Use `Last-Event-ID` or `?since=` parameter (see reconnect section above)

**Problem:** No progress updates for long tasks

**Solution:** Look for `status` events (heartbeats every 15s) - shows the agent is working

---

## Summary

**What you get:**
- ✅ Agents run 30 seconds to 30+ minutes without issues
- ✅ Users can switch tabs/browsers freely
- ✅ Network flakiness doesn't matter
- ✅ Multiple users can watch same agent
- ✅ Precise reconnect without duplicates
- ✅ Progress indicators via heartbeats

**What you do:**
- ✅ Same API (POST to create, GET to watch)
- ✅ Handle events same way
- ✅ Add reconnect logic with Last-Event-ID (recommended)
- ✅ Show status heartbeats (recommended)

**What changed:**
- ✅ Backend is now bulletproof (no crashes)
- ✅ Events are strictly ordered (no duplicates)
- ✅ Heartbeats included (show liveness)
- ✅ tool_end events present (complete tool info)

That's it! Your streaming agents are now production-ready. 🚀

