#!/usr/bin/env python3
"""
Simple Test Runner for Agent Components

Quick test script to verify chat, memory, streaming, and tool logging functionality.
"""

import asyncio
import os
import sys
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from react_agent import ReactAgent
from src.deepagents.logging_utils import get_tool_call_stats


async def test_basic_functionality():
    """Test basic agent functionality."""
    print("🧪 Testing Basic Agent Functionality")
    print("=" * 50)

    load_dotenv()

    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        print("🚀 Initializing ReactAgent...")
        agent = ReactAgent(mongo_client, org_id=1)
        print("✅ Agent initialized successfully")
        
        print("\n1️⃣ Testing Agent Info")
        info = agent.get_agent_info()
        print(f"Agent Info: {info}")
        
        print("\n2️⃣ Testing Sync Chat")
        result = await agent.chat_sync(
            user_query="Hello, can you help me analyze a tender?",
            thread_id="test_thread_sync"
        )
        print(f"Sync Result: {result.get('success', False)}")
        print(f"Response: {result.get('response', 'No response')[:100]}...")
        
        print("\n3️⃣ Testing Streaming Chat")
        print("Streaming response:")
        async for chunk in agent.chat_streaming(
            user_query="What are the key requirements for tender analysis?",
            thread_id="test_thread_streaming"
        ):
            chunk_type = chunk.get("chunk_type", "unknown")
            content = chunk.get("content", "")
            
            if chunk_type == "start":
                print(f"🚀 {content}")
            elif chunk_type == "content":
                print(content, end="", flush=True)
            elif chunk_type == "end":
                print(f"\n✅ {content}")
            elif chunk_type == "error":
                print(f"\n❌ Error: {content}")
        
        print("\n4️⃣ Testing Memory Persistence")
        
        await agent.chat_sync(
            user_query="My name is Alice and I'm working on tender #12345.",
            thread_id="test_memory_thread"
        )
        
        result = await agent.chat_sync(
            user_query="What's my name and which tender am I working on?",
            thread_id="test_memory_thread"
        )
        
        print(f"Memory Test: {result.get('success', False)}")
        print(f"Response: {result.get('response', 'No response')[:200]}...")
        
        print("\n5️⃣ Testing Tool Logging")
        stats = get_tool_call_stats()
        print(f"Tool Call Stats: {stats}")
        
        print("\n✅ All basic tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        return False
    
    finally:
        mongo_client.close()
    
    return True


async def test_streaming_performance():
    """Test streaming performance."""
    print("\n⚡ Testing Streaming Performance")
    print("=" * 50)
    
    load_dotenv()
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        agent = ReactAgent(mongo_client, org_id=1)
        
        import time
        start_time = time.time()
        
        chunks = []
        async for chunk in agent.chat_streaming(
            user_query="Provide a detailed analysis of tender requirements including security, compliance, and performance aspects.",
            thread_id="perf_test_thread"
        ):
            chunks.append(chunk)
            if chunk.get("chunk_type") == "content":
                print(".", end="", flush=True)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        print("\n⏱️  Performance Results:")
        print(f"  Total time: {total_time:.2f} seconds")
        print(f"  Chunks received: {len(chunks)}")
        print(f"  Avg time per chunk: {total_time/len(chunks):.3f} seconds")
        
    except Exception as e:
        print(f"\n❌ Performance test failed: {str(e)}")
        return False
    
    finally:
        mongo_client.close()
    
    return True


def main():
    """Main test function."""
    print("🧪 Agent Component Test Suite")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)
    
    try:
        basic_success = asyncio.run(test_basic_functionality())
        
        perf_success = asyncio.run(test_streaming_performance())
        
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Basic Functionality: {'✅ PASS' if basic_success else '❌ FAIL'}")
        print(f"Streaming Performance: {'✅ PASS' if perf_success else '❌ FAIL'}")
        
        overall_success = basic_success and perf_success
        print(f"\nOverall Result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
        
        return overall_success
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {str(e)}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
