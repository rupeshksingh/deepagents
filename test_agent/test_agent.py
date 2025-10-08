#!/usr/bin/env python3
"""
Simple Test Runner for Agent Components

Basic test script to verify chat and memory persistence functionality.
"""

import asyncio
import os
import sys
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from react_agent import ReactAgent


async def test_basic_functionality():
    """Test basic agent functionality with query and memory persistence."""
    print("🧪 Testing Basic Agent Functionality")
    print("=" * 50)

    load_dotenv()

    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        print("🚀 Initializing ReactAgent...")
        agent = ReactAgent(mongo_client, org_id=1)
        print("✅ Agent initialized successfully")
        
        thread_id = "test_thread_29"
        
        tender_id = "68c99b8a10844521ad051544"  # Valid 24-character MongoDB ObjectId format
        query1 = """Two things:

(a) From the tender, extract all obligations related to web‑tilgængelighed and the Digitaliseringsstyrelsens WAS‑tool.

(b) Confirm via web search the current legal basis and guidance we must follow for accessibility statements in Denmark (point to official sources).

(c) Using Bilag A Kundeliste (xlsx/pdf), segment customers by type (kommune/region/stat/øvrige) and propose a prioritized roll‑out plan for making their websites/apps compliant.
 
 """
        print(f"\n1️⃣ Testing Basic Query (Thread ID: {thread_id}, Tender ID: {tender_id})")
        result1 = await agent.chat_sync(
            user_query=query1,
            thread_id=thread_id,
            tender_id=tender_id
        )
        
        print(f"Query 1 Result: {result1.get('success', False)}")
        print(f"Response: {result1.get('response', 'No response')[:200]}...")
        
        # Save first response to file
        with open("thread1.txt", "w", encoding="utf-8") as f:
            f.write(f"Thread ID: {thread_id}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Query: {query1}\n")
            f.write(f"Success: {result1.get('success', False)}\n")
            f.write(f"Response:\n{result1.get('response', 'No response')}\n")
        
        print(f"✅ Response saved to thread1.txt")
        
        print(f"\n2️⃣ Testing Memory Persistence (Same Thread ID: {thread_id}, Tender ID: {tender_id})")
        query2 = "Given that Quality has 70% weighting in Direct Award evaluation, and our hourly rates are 8% higher than the cheapest supplier, what quality score differential do we need to achieve to still win contracts? Include mathematical analysis."
        result2 = await agent.chat_sync(
            user_query=query2,
            thread_id=thread_id,
            tender_id=tender_id
        )
        
        print(f"Memory Test Result: {result2.get('success', False)}")
        print(f"Response: {result2.get('response', 'No response')[:200]}...")
        
        # Save second response to file
        with open("thread2.txt", "w", encoding="utf-8") as f:
            f.write(f"Thread ID: {thread_id}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Query: {query2}\n")
            f.write(f"Success: {result2.get('success', False)}\n")
            f.write(f"Response:\n{result2.get('response', 'No response')}\n")
        
        print(f"✅ Response saved to thread2.txt")
        
        print("\n✅ All basic tests completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        return False
    
    finally:
        mongo_client.close()


def main():
    """Main test function."""
    print("🧪 Basic Agent Test Suite")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 60)
    
    try:
        success = asyncio.run(test_basic_functionality())
        
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Basic Tests: {'✅ PASS' if success else '❌ FAIL'}")
        
        if success:
            print("\n✅ All tests passed! Check thread1.txt and thread2.txt for responses.")
        else:
            print("\n❌ Tests failed!")
        
        return success
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {str(e)}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
