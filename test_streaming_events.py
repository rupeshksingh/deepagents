#!/usr/bin/env python
"""Quick test to verify SSE event streaming with all event types."""

import asyncio
import sys
from collections import Counter
from pymongo import MongoClient
from dotenv import load_dotenv
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.store import ApiStore
from api.streaming.persistence import EventPersistence
from api.streaming_store import stream_agent_response
from api.models import ChatCreateRequest, MessageRole

load_dotenv()

async def test_streaming():
    """Test SSE streaming and verify all event types are emitted."""
    mongo_uri = os.getenv('MONGODB_URL')
    client = MongoClient(mongo_uri)
    
    store = ApiStore(client, 'proposal_assistant')
    event_persist = EventPersistence(client, 'proposal_assistant')
    
    # Create chat
    chat = store.create_chat('test_sse_validation', ChatCreateRequest(title='SSE Event Test'))
    chat_id = chat.chat_id
    
    # Create messages
    query = "Create a 'what-to-deliver' checklist for: 2.3 IT procurement, 2.4 IT security/BC/compliance, 2.7 Program management."
    user_msg = store.create_message(chat_id, 'test_sse_validation', MessageRole.USER, query,
        {'tender_id': '68c99b8a10844521ad051544'})
    
    asst_msg = store.create_message(chat_id, 'test_sse_validation', MessageRole.ASSISTANT, '',
        {'tender_id': '68c99b8a10844521ad051544'})
    
    print(f'Chat: {chat_id}')
    print(f'Assistant Message: {asst_msg.message_id}')
    print('\n=== Streaming Events ===\n')
    
    event_types = []
    tool_events = []
    
    async for event in stream_agent_response(
        store, event_persist, chat_id, asst_msg.message_id, query,
        {'tender_id': '68c99b8a10844521ad051544'}
    ):
        event_types.append(event.type)
        
        # Print important events
        if event.type in ['start', 'end', 'error']:
            print(f'✓ {event.type.upper()}: {event.model_dump_json(exclude_none=True)[:150]}...')
        elif event.type == 'plan':
            print(f'📋 PLAN: {len(event.items)} items')
        elif event.type == 'tool_start':
            print(f'🔧 TOOL_START: {event.name} (call_id={event.call_id[:8]}...)')
            tool_events.append(('start', event.name, event.call_id))
        elif event.type == 'tool_end':
            print(f'✅ TOOL_END: {event.name} - {event.status} ({event.ms}ms, call_id={event.call_id[:8]}...)')
            tool_events.append(('end', event.name, event.call_id))
        elif event.type == 'content':
            if event_types.count('content') <= 3:
                print(f'📝 CONTENT: {event.md[:60]}...')
    
    print('\n=== Event Summary ===')
    counts = Counter(event_types)
    for etype in ['start', 'plan', 'tool_start', 'tool_end', 'status', 'content', 'end', 'error']:
        count = counts.get(etype, 0)
        status = '✓' if count > 0 else '✗'
        print(f'{status} {etype}: {count}')
    
    print(f'\n=== Tool Call Matching ===')
    if tool_events:
        for event_type, name, call_id in tool_events[:10]:
            print(f'  {event_type}: {name} ({call_id[:12]}...)')
    else:
        print('  No tool events captured')
    
    return counts

if __name__ == '__main__':
    result = asyncio.run(test_streaming())
    
    # Validate
    required_events = ['start', 'content', 'end']
    missing = [e for e in required_events if result.get(e, 0) == 0]
    
    if missing:
        print(f'\n❌ FAILED: Missing required events: {missing}')
        sys.exit(1)
    else:
        print('\n✅ SUCCESS: Core streaming events present')
        if result.get('tool_start', 0) > 0 and result.get('tool_end', 0) > 0:
            print('✅ BONUS: Tool events also captured!')
        else:
            print('⚠️  WARNING: No tool events - tools may not be instrumented')

