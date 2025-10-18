"""
Streaming Query Test - Similar to run_query.py but uses streaming

Tests ReactAgent.chat_streaming() with a single query.
Pass query as command-line argument or edit THREAD_ID below.

Usage:
    python run_streaming_query.py "What is the deadline?"
    python run_streaming_query.py "Analyze the penalty clauses"
"""

import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

# Ensure we can import react_agent from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from react_agent import ReactAgent


async def run_streaming_query(query: str, tender_id: str):
    """Run a single streaming query and display results."""
    
    # Thread ID - edit this in the file to test different conversations
    # Use same thread_id for follow-up questions to test multi-turn
    thread_id = "sid-test-001"
    
    print(f"\n{'='*80}")
    print("🌊 STREAMING QUERY TEST")
    print(f"{'='*80}")
    print(f"📝 Query: {query}")
    print(f"🔖 Thread ID: {thread_id}")
    print(f"📋 Tender ID: {tender_id}")
    print(f"{'='*80}\n")
    
    load_dotenv()
    mongodb_uri = os.getenv("MONGODB_URL")
    if not mongodb_uri:
        print("❌ MONGODB_URL not found in environment")
        return {"success": False, "error": "Missing MONGODB_URL"}
    
    # Initialize agent (same as run_query.py)
    mongo_client = MongoClient(mongodb_uri)
    agent = ReactAgent(mongo_client, org_id=1)
    
    print(f"✅ Agent initialized: {agent.db_name} (org_id={agent.org_id})")
    print(f"💡 Testing streaming workflow with optimizations enabled\n")
    
    # Stream the response
    print(f"{'='*80}")
    print("🌊 STREAMING RESPONSE")
    print(f"{'='*80}\n")
    
    full_response = ""
    start_time = datetime.now()
    
    try:
        async for chunk in agent.chat_streaming(
            user_query=query,
            thread_id=thread_id,
            tender_id=tender_id,
            user_id="test_user"
        ):
            chunk_type = chunk.get("chunk_type")
            
            if chunk_type == "content":
                content = chunk.get("content", "")
                full_response += content + " "
                # Show streaming in real-time (this is what frontend sees)
                print(content, end=" ", flush=True)
            
            elif chunk_type == "end":
                duration_ms = chunk.get("processing_time_ms", 0)
                print(f"\n\n{'='*80}")
                print(f"✅ STREAMING COMPLETED")
                print(f"{'='*80}")
                print(f"⏱️  Processing time: {duration_ms}ms ({duration_ms/1000:.2f}s)")
                
                # Get final response
                final_response = chunk.get("total_response", full_response.strip())
                if final_response:
                    full_response = final_response
            
            elif chunk_type == "error":
                error = chunk.get("content", "Unknown error")
                print(f"\n\n❌ ERROR: {error}")
                return {"success": False, "error": error}
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Print response summary
        print(f"\n{'='*80}")
        print("📊 RESPONSE SUMMARY")
        print(f"{'='*80}")
        print(f"✓ Success: True")
        print(f"✓ Total duration: {duration:.2f}s")
        print(f"✓ Response length: {len(full_response.strip())} characters")
        print(f"{'='*80}\n")
        
        print("📝 FULL RESPONSE:")
        print("-" * 80)
        print(full_response.strip())
        print("-" * 80)
        
        print(f"\n💡 OPTIMIZATION INDICATORS:")
        print("   Look in the logs above for:")
        print("   📦 'Compacted get_file_content output' - File compaction working")
        print("   ✓  'Cache HIT' messages - Caching working")
        print("   🔧 'Applying tender-specific compression' - Smart compression")
        print(f"   💬 Context injection status (first message only)")
        
        return {
            "success": True,
            "response": full_response.strip(),
            "duration_seconds": duration,
            "thread_id": thread_id,
        }
    
    except Exception as e:
        print(f"\n\n{'='*80}")
        print(f"❌ EXCEPTION: {e}")
        print(f"{'='*80}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Get query from command line or use default
    query = " ".join(sys.argv[1:]).strip()
    
    # Load tender_id from environment
    load_dotenv()
    tender_id = os.getenv("TENDER_ID")
    
    if not query:
        print("\n" + "⚠️ " * 35)
        print("No query provided. Using default test query...")
        print("⚠️ " * 35)
        query = """
        What is the deadline for this tender?
        """
    
    if not tender_id:
        print("\n" + "❌" * 35)
        print("ERROR: TENDER_ID not found in environment variables!")
        print("Please set TENDER_ID in your .env file or as an environment variable.")
        print("Example: export TENDER_ID=68c99b8a10844521ad051544")
        print("❌" * 35)
        sys.exit(1)
    
    print("\n" + "🚀" * 35)
    print("STREAMING QUERY TEST - Testing ReactAgent.chat_streaming()")
    print("🚀" * 35)
    print(f"\n💡 This tests the STREAMING workflow with all optimizations:")
    print(f"   • Phase 1: Tool Output Compaction")
    print(f"   • Phase 2: Cache Monitoring")
    print(f"   • Phase 5: Domain-Aware Summarization")
    print(f"   • Memory Bloat Fix (context only on first message)")
    
    try:
        result = asyncio.run(run_streaming_query(query, tender_id))
        
        if result.get("success"):
            print(f"\n\n{'='*80}")
            print("✅ TEST COMPLETED SUCCESSFULLY")
            print(f"{'='*80}\n")
            sys.exit(0)
        else:
            print(f"\n\n{'='*80}")
            print("❌ TEST FAILED")
            print(f"{'='*80}")
            print(f"Error: {result.get('error', 'Unknown error')}\n")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

