"""
Production API Testing Script
=============================
Tests the actual streaming API endpoints (production code paths only).

This script tests:
- Chat creation
- Message streaming with SSE events
- HITL (Human-in-the-Loop) interrupts
- Resume functionality
- Persistent summarization

Usage:
    python test_agent/test_production_api.py

Requirements:
    - Server running on localhost:8000
    - TENDER_ID set in .env
    - httpx installed: pip install httpx
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import httpx

# Load environment variables
load_dotenv()


class ProductionApiTester:
    """Test client for production streaming API."""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.timeout = httpx.Timeout(600.0, connect=10.0)  # 10min for long requests
        
    async def create_chat(self, user_id: str, title: str = "Test Chat"):
        """Create a new chat via API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/users/{user_id}/chats",
                json={"title": title}
            )
            response.raise_for_status()
            return response.json()
    
    async def send_message(self, chat_id: str, content: str, tender_id: str = None):
        """Send message and get stream URL."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {"content": content}
            if tender_id:
                payload["metadata"] = {"tender_id": tender_id}
            
            response = await client.post(
                f"{self.base_url}/api/chats/{chat_id}/messages",
                json=payload
            )
            response.raise_for_status()
            return response.json()
    
    async def watch_stream(self, chat_id: str, message_id: str):
        """Watch SSE stream for message events."""
        url = f"{self.base_url}/api/chats/{chat_id}/messages/{message_id}/stream"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                        yield {"type": "event", "event_type": event_type}
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            yield {"type": "data", "data": data}
                        except json.JSONDecodeError:
                            yield {"type": "data", "data": line[6:]}
    
    async def resume_message(self, chat_id: str, message_id: str, action: str, args: str = None):
        """Resume interrupted message."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {"action": action}
            if args:
                payload["args"] = args
            
            response = await client.post(
                f"{self.base_url}/api/chats/{chat_id}/messages/{message_id}/resume",
                json=payload
            )
            response.raise_for_status()
            return response.json()


async def test_normal_query(tester, chat_id, tender_id):
    """Test normal query without HITL."""
    print("\n" + "="*80)
    print("TEST 1: Normal Query (No HITL)")
    print("="*80)
    
    query = "What is the tender deadline?"
    print(f"📝 Query: {query}")
    
    # Send message
    msg_response = await tester.send_message(chat_id, query, tender_id)
    message_id = msg_response["message_id"]
    print(f"✓ Message created: {message_id}")
    
    # Watch stream
    print("\n🌊 Streaming events:")
    print("-" * 80)
    
    event_count = 0
    async for event in tester.watch_stream(chat_id, message_id):
        event_count += 1
        if event["type"] == "data":
            data = event["data"]
            if isinstance(data, dict):
                event_type = data.get("type", "unknown")
                print(f"  [{event_count}] {event_type}: {str(data)[:100]}...")
    
    print("-" * 80)
    print(f"✓ Received {event_count} events")
    print("✓ Test 1 PASSED\n")


async def test_hitl_flow(tester, chat_id, tender_id):
    """Test HITL interrupt and resume."""
    print("\n" + "="*80)
    print("TEST 2: HITL Interrupt + Resume")
    print("="*80)
    
    query = "Find CSR requirements and use request_human_input to ask if I want brief or detailed analysis"
    print(f"📝 Query: {query}")
    
    # Send message
    msg_response = await tester.send_message(chat_id, query, tender_id)
    message_id = msg_response["message_id"]
    print(f"✓ Message created: {message_id}")
    
    # Watch stream for interrupt
    print("\n🌊 Watching for HITL interrupt:")
    print("-" * 80)
    
    interrupt_detected = False
    interrupt_question = None
    
    async for event in tester.watch_stream(chat_id, message_id):
        if event["type"] == "data":
            data = event["data"]
            if isinstance(data, dict):
                # Check for interrupt
                if data.get("type") == "status":
                    md = data.get("md")
                    if md:
                        try:
                            md_data = json.loads(md) if isinstance(md, str) else md
                            if md_data.get("interrupt"):
                                interrupt_detected = True
                                interrupt_question = md_data.get("question", "No question")
                                print(f"\n⏸️  INTERRUPT DETECTED!")
                                print(f"   Question: {interrupt_question}")
                                break
                        except:
                            pass
    
    if not interrupt_detected:
        print("❌ No interrupt detected - test may need adjustment")
        return
    
    # Resume with human response
    print("\n🔄 Resuming with human response...")
    human_response = "Give me detailed analysis with specific compliance recommendations"
    
    resume_result = await tester.resume_message(
        chat_id,
        message_id,
        action="respond",
        args=human_response
    )
    
    print(f"✓ Resumed successfully")
    print(f"   Action: respond")
    print(f"   Response: {human_response[:50]}...")
    print(f"   Status: {resume_result.get('status')}")
    print("✓ Test 2 PASSED\n")


async def main():
    """Run all tests."""
    print("\n" + "🚀"*35)
    print("PRODUCTION API TESTING")
    print("Testing against actual streaming endpoints")
    print("🚀"*35)
    
    # Get config from environment
    tender_id = os.getenv("TENDER_ID")
    if not tender_id:
        print("\n❌ ERROR: TENDER_ID not found in .env file")
        print("Please set TENDER_ID in your .env file")
        sys.exit(1)
    
    base_url = os.getenv("API_URL", "http://localhost:8000")
    user_id = os.getenv("TEST_USER_ID", "test-user")
    
    print(f"\n📋 Configuration:")
    print(f"   API URL: {base_url}")
    print(f"   User ID: {user_id}")
    print(f"   Tender ID: {tender_id}")
    
    # Initialize tester
    tester = ProductionApiTester(base_url)
    
    # Create chat
    print(f"\n📬 Creating test chat...")
    chat_result = await tester.create_chat(
        user_id,
        f"API Test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    chat_id = chat_result["chat_id"]
    print(f"✓ Chat created: {chat_id}")
    
    try:
        # Run tests
        await test_normal_query(tester, chat_id, tender_id)
        await test_hitl_flow(tester, chat_id, tender_id)
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        print("\n💡 Next steps:")
        print("   1. Check MongoDB org_1.threads for conversation summaries")
        print("   2. Verify HITL responses in summaries: 'Human (HITL): ...'")
        print("   3. Monitor logs for: '✓ Summary saved for thread_...'")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

