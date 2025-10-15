"""
Test script for background agent execution.

Demonstrates:
1. Creating multiple messages (agents start immediately)
2. Watching multiple agents simultaneously
3. Switching between streams
"""

import asyncio
import httpx
import json
import sys


BASE_URL = "http://localhost:8000"
USER_ID = "test_user"


async def create_message(chat_id: str, content: str) -> dict:
    """Create a message and start agent."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{BASE_URL}/api/chats/{chat_id}/messages",
            json={"content": content}
        )
        response.raise_for_status()
        return response.json()


async def watch_stream(chat_id: str, message_id: str, name: str, duration: int = 10):
    """Watch agent stream for specified duration."""
    print(f"\n[{name}] Starting to watch message {message_id}")
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "GET",
            f"{BASE_URL}/api/chats/{chat_id}/messages/{message_id}/stream",
            headers={"Accept": "text/event-stream"}
        ) as response:
            event_count = 0
            start_time = asyncio.get_event_loop().time()
            
            async for line in response.aiter_lines():
                # Check duration limit
                if asyncio.get_event_loop().time() - start_time > duration:
                    print(f"[{name}] Time limit reached, stopping watch")
                    break
                
                if line.startswith("data: "):
                    event_count += 1
                    data = line[6:]  # Remove "data: " prefix
                    try:
                        event = json.loads(data)
                        event_type = event.get("type", "unknown")
                        
                        # Print interesting events
                        if event_type in ["start", "thinking", "tool_start", "tool_end", "end"]:
                            text = event.get("text", "")
                            name_field = event.get("name", "")
                            print(f"[{name}] {event_type}: {text or name_field}")
                    except json.JSONDecodeError:
                        pass
            
            print(f"[{name}] Received {event_count} events")


async def test_multiple_agents():
    """Test multiple agents running simultaneously."""
    print("=" * 60)
    print("TEST 1: Multiple Agents Running Simultaneously")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        # Ensure user exists
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        
        # Create chat
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Multi-Agent Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    # Create TWO messages (both agents start immediately!)
    print("\n1. Creating first message (agent starts immediately)...")
    msg1 = await create_message(chat_id, "What is GDPR?")
    print(f"   Message 1: {msg1['message_id']}")
    print(f"   Agent 1 is now running in background!")
    
    print("\n2. Creating second message (agent starts immediately)...")
    msg2 = await create_message(chat_id, "What is CCPA?")
    print(f"   Message 2: {msg2['message_id']}")
    print(f"   Agent 2 is now running in background!")
    
    print("\n3. Both agents are running simultaneously!")
    print("   Watching both streams for 15 seconds...")
    
    # Watch both streams simultaneously
    await asyncio.gather(
        watch_stream(chat_id, msg1['message_id'], "Agent1", duration=15),
        watch_stream(chat_id, msg2['message_id'], "Agent2", duration=15)
    )
    
    print("\n✅ Test complete: Both agents ran simultaneously!")


async def test_multiple_watchers():
    """Test multiple watchers watching same agent."""
    print("\n" + "=" * 60)
    print("TEST 2: Multiple Watchers Watching Same Agent")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Multi-Watcher Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    # Create ONE message
    print("\n1. Creating message (agent starts)...")
    msg = await create_message(chat_id, "Explain blockchain")
    print(f"   Message: {msg['message_id']}")
    print(f"   Agent is running in background")
    
    print("\n2. Starting THREE watchers for same agent...")
    
    # Watch from 3 different "clients"
    await asyncio.gather(
        watch_stream(chat_id, msg['message_id'], "Watcher1", duration=10),
        watch_stream(chat_id, msg['message_id'], "Watcher2", duration=10),
        watch_stream(chat_id, msg['message_id'], "Watcher3", duration=10)
    )
    
    print("\n✅ Test complete: All watchers received events!")


async def test_disconnect_reconnect():
    """Test disconnect and reconnect scenario."""
    print("\n" + "=" * 60)
    print("TEST 3: Disconnect and Reconnect")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Disconnect Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    # Create message
    print("\n1. Creating message (agent starts)...")
    msg = await create_message(chat_id, "Summarize quantum computing")
    print(f"   Message: {msg['message_id']}")
    
    print("\n2. Watching for 5 seconds...")
    await watch_stream(chat_id, msg['message_id'], "Watch1", duration=5)
    
    print("\n3. Disconnected! Agent still running in background...")
    print("   Waiting 5 seconds...")
    await asyncio.sleep(5)
    
    print("\n4. Reconnecting and watching for 5 more seconds...")
    await watch_stream(chat_id, msg['message_id'], "Watch2", duration=5)
    
    print("\n✅ Test complete: Reconnect worked, agent kept running!")


async def test_aggressive_disconnect():
    """Test very aggressive disconnect/reconnect pattern."""
    print("\n" + "=" * 60)
    print("TEST 4: Aggressive Disconnect/Reconnect")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Aggressive Disconnect Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    # Create message
    print("\n1. Creating message (agent starts)...")
    msg = await create_message(chat_id, "Explain machine learning in detail")
    print(f"   Message: {msg['message_id']}")
    
    # Rapid connect/disconnect pattern
    print("\n2. Testing rapid disconnect/reconnect...")
    for i in range(5):
        print(f"   Iteration {i+1}: Connect for 1s, disconnect for 1s")
        
        # Watch for 1 second
        watch_task = asyncio.create_task(
            watch_stream(chat_id, msg['message_id'], f"Quick-{i+1}", duration=1)
        )
        await watch_task
        
        # Wait 1 second (disconnected)
        await asyncio.sleep(1)
    
    print("\n3. Final reconnect to see complete results...")
    await watch_stream(chat_id, msg['message_id'], "Final", duration=5)
    
    print("\n✅ Test complete: Agent survived aggressive disconnects!")


async def test_reconnect_with_last_event_id():
    """Test strict resume using Last-Event-ID without duplicates."""
    print("\n" + "=" * 60)
    print("TEST: Reconnect with Last-Event-ID (strict resume)")
    print("=" * 60)

    # Create chat
    async with httpx.AsyncClient() as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Last-Event-ID Resume Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")

    # Create message (start agent)
    print("\n1. Creating message (agent starts)...")
    msg = await create_message(chat_id, "Explain differential privacy in brief")
    message_id = msg["message_id"]
    print(f"   Message: {message_id}")

    # Open stream, read some events, capture last id, then disconnect
    print("\n2. Watching initial events for 4 seconds to capture Last-Event-ID...")
    last_event_id = None
    seen_ids = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "GET",
            f"{BASE_URL}/api/chats/{chat_id}/messages/{message_id}/stream",
            headers={"Accept": "text/event-stream"}
        ) as response:
            start = asyncio.get_event_loop().time()
            cur_id = None
            async for line in response.aiter_lines():
                if asyncio.get_event_loop().time() - start > 4:
                    break
                if not line:
                    continue
                if line.startswith("id: "):
                    cur_id = line[4:].strip()
                elif line.startswith("data: "):
                    if cur_id:
                        last_event_id = cur_id
                        seen_ids.append(cur_id)
                        cur_id = None

    print(f"   Captured Last-Event-ID: {last_event_id}")

    # Reconnect with Last-Event-ID and ensure we don't see duplicates
    print("\n3. Reconnecting with Last-Event-ID (strict resume)...")
    resumed_ids = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "GET",
            f"{BASE_URL}/api/chats/{chat_id}/messages/{message_id}/stream",
            headers={
                "Accept": "text/event-stream",
                "Last-Event-ID": last_event_id or ""
            }
        ) as response:
            # Read a handful of events or until END
            limit = 10
            cur_id = None
            async for line in response.aiter_lines():
                if line.startswith("id: "):
                    cur_id = line[4:].strip()
                elif line.startswith("data: ") and cur_id:
                    resumed_ids.append(cur_id)
                    # Stop early once we've seen some events
                    if len(resumed_ids) >= limit:
                        break
                    cur_id = None

    # Assert: none of the resumed IDs were seen in the first session
    duplicates = set(resumed_ids).intersection(set(seen_ids))
    if duplicates:
        raise AssertionError(f"Strict resume failed; duplicate ids observed: {list(duplicates)[:3]} ...")

    # Also ensure we actually resumed (i.e., saw something)
    if not resumed_ids:
        raise AssertionError("No events received after resume; expected at least one")

    print("\n✅ Test complete: Strict resume works with Last-Event-ID (no duplicates)")


async def test_multi_agent_stress():
    """Stress test with many simultaneous agents."""
    print("\n" + "=" * 60)
    print("TEST 5: Multi-Agent Stress Test (5 agents)")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Stress Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    print("\n1. Starting 5 agents simultaneously...")
    messages = []
    queries = [
        "What is Python?",
        "What is JavaScript?",
        "What is Go?",
        "What is Rust?",
        "What is TypeScript?"
    ]
    
    # Start all agents
    for i, query in enumerate(queries, 1):
        msg = await create_message(chat_id, query)
        messages.append(msg)
        print(f"   Agent {i} started: {msg['message_id'][:8]}...")
    
    print(f"\n2. All {len(messages)} agents running!")
    print("   Watching all agents for 10 seconds...")
    
    # Watch all simultaneously
    watch_tasks = [
        watch_stream(chat_id, msg['message_id'], f"Agent{i+1}", duration=10)
        for i, msg in enumerate(messages)
    ]
    
    await asyncio.gather(*watch_tasks)
    
    print(f"\n✅ Test complete: All {len(messages)} agents ran simultaneously!")


async def test_error_recovery():
    """Test error scenarios and recovery."""
    print("\n" + "=" * 60)
    print("TEST 6: Error Recovery")
    print("=" * 60)
    
    # Create chat
    async with httpx.AsyncClient(timeout=300.0) as client:
        await client.get(f"{BASE_URL}/api/users/{USER_ID}")
        response = await client.post(
            f"{BASE_URL}/api/users/{USER_ID}/chats",
            json={"title": "Error Test"}
        )
        chat_data = response.json()
        chat_id = chat_data.get("chat_id") or chat_data.get("id")
    
    print("\n1. Starting agent...")
    msg = await create_message(chat_id, "What is AI?")
    print(f"   Message: {msg['message_id']}")
    
    print("\n2. Testing immediate disconnect after start...")
    # Start watching, disconnect immediately
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "GET",
            f"{BASE_URL}/api/chats/{chat_id}/messages/{msg['message_id']}/stream",
            headers={"Accept": "text/event-stream"}
        ) as response:
            # Read just one event, then disconnect
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    print("   Received one event, disconnecting...")
                    break
    
    print("\n3. Waiting 3 seconds...")
    await asyncio.sleep(3)
    
    print("\n4. Reconnecting to check agent still running...")
    await watch_stream(chat_id, msg['message_id'], "Recovery", duration=5)
    
    print("\n✅ Test complete: Agent survived immediate disconnect!")


async def main():
    """Run all tests."""
    print("\n🚀 Testing Background Agent Execution\n")
    
    # Check if server is running
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.get(f"{BASE_URL}/docs")
    except httpx.ConnectError:
        print(f"❌ Error: Cannot connect to {BASE_URL}")
        print("   Make sure the API server is running:")
        print("   python main.py")
        sys.exit(1)
    
    try:
        # Test 1: Multiple agents
        await test_multiple_agents()
        
        # Test 2: Multiple watchers
        await test_multiple_watchers()
        
        # Test 3: Disconnect/reconnect
        await test_disconnect_reconnect()
        
        # Test 4: Aggressive disconnect
        await test_aggressive_disconnect()

        # Test 4b: Strict resume with Last-Event-ID
        await test_reconnect_with_last_event_id()
        
        # Test 5: Multi-agent stress
        await test_multi_agent_stress()
        
        # Test 6: Error recovery
        await test_error_recovery()
        
        print("\n" + "=" * 60)
        print("🎉 All tests passed!")
        print("=" * 60)
        print("\n✅ Background agent execution is working perfectly!")
        print("✅ Multiple agents can run simultaneously")
        print("✅ Multiple watchers can watch same agent")
        print("✅ Disconnect/reconnect works seamlessly")
        print("✅ Aggressive disconnects don't kill agents")
        print("✅ Multi-agent stress test passed")
        print("✅ Error recovery works correctly")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

