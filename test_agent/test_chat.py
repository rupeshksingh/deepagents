"""
Test Agent - Chat Testing Module

Tests for chat functionality, memory persistence, and streaming responses.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List

from react_agent import ReactAgent
from src.deepagents.logging_utils import get_unified_logger, get_tool_call_stats, get_session_stats
from pymongo import MongoClient


class ChatTester:
    """Test class for chat functionality with streaming and memory."""
    
    def __init__(self, mongo_client: MongoClient, org_id: int = 1):
        self.mongo_client = mongo_client
        self.org_id = org_id
        self.agent = ReactAgent(mongo_client, org_id)
        self.test_results = []
    
    async def test_streaming_chat(self, query: str, thread_id: str, tender_id: str = None) -> Dict[str, Any]:
        """Test streaming chat functionality."""
        print(f"\n🔄 Testing streaming chat: '{query}'")
        print("=" * 60)
        
        start_time = time.time()
        chunks = []
        full_response = ""
        
        try:
            async for chunk in self.agent.chat_streaming(
                user_query=query,
                thread_id=thread_id,
                tender_id=tender_id
            ):
                chunks.append(chunk)
                chunk_type = chunk.get("chunk_type", "unknown")
                content = chunk.get("content", "")
                
                if chunk_type == "start":
                    print(f"🚀 {content}")
                elif chunk_type == "content":
                    print(content, end="", flush=True)
                    full_response += content + " "
                elif chunk_type == "end":
                    end_time = time.time()
                    processing_time = chunk.get("processing_time_ms", 0)
                    print(f"\n\n✅ {content}")
                    print(f"⏱️  Processing time: {processing_time}ms")
                    print(f"⏱️  Total time: {(end_time - start_time)*1000:.0f}ms")
                elif chunk_type == "error":
                    print(f"\n❌ Error: {content}")
            
            result = {
                "test_type": "streaming_chat",
                "query": query,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "success": True,
                "chunks_received": len(chunks),
                "full_response": full_response.strip(),
                "processing_time_ms": int((time.time() - start_time) * 1000),
                "timestamp": datetime.now().isoformat()
            }
            
            self.test_results.append(result)
            return result
            
        except Exception as e:
            error_result = {
                "test_type": "streaming_chat",
                "query": query,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self.test_results.append(error_result)
            return error_result
    
    async def test_sync_chat(self, query: str, thread_id: str, tender_id: str = None) -> Dict[str, Any]:
        """Test synchronous chat functionality."""
        print(f"\n📝 Testing sync chat: '{query}'")
        print("=" * 60)
        
        start_time = time.time()
        
        try:
            result = await self.agent.chat_sync(
                user_query=query,
                thread_id=thread_id,
                tender_id=tender_id
            )
            
            end_time = time.time()
            total_time = int((end_time - start_time) * 1000)
            
            print(f"✅ Response: {result.get('response', 'No response')[:200]}...")
            print(f"⏱️  Total time: {total_time}ms")
            print(f"📊 Success: {result.get('success', False)}")
            
            test_result = {
                "test_type": "sync_chat",
                "query": query,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "success": result.get("success", False),
                "response": result.get("response", ""),
                "processing_time_ms": result.get("processing_time_ms", 0),
                "total_time_ms": total_time,
                "timestamp": datetime.now().isoformat()
            }
            
            self.test_results.append(test_result)
            return test_result
            
        except Exception as e:
            error_result = {
                "test_type": "sync_chat",
                "query": query,
                "thread_id": thread_id,
                "tender_id": tender_id,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self.test_results.append(error_result)
            return error_result
    
    async def test_memory_persistence(self, thread_id: str) -> Dict[str, Any]:
        """Test memory persistence across multiple queries."""
        print(f"\n🧠 Testing memory persistence for thread: {thread_id}")
        print("=" * 60)
        
        queries = [
            "My name is John and I'm working on tender analysis.",
            "What's my name?",
            "What am I working on?",
            "Can you summarize our conversation so far?"
        ]
        
        results = []
        
        for i, query in enumerate(queries, 1):
            print(f"\n--- Query {i}: {query} ---")
            
            result = await self.test_streaming_chat(query, thread_id)
            results.append(result)
            
            # Small delay between queries
            await asyncio.sleep(1)
        
        memory_test_result = {
            "test_type": "memory_persistence",
            "thread_id": thread_id,
            "queries_count": len(queries),
            "successful_queries": sum(1 for r in results if r.get("success", False)),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
        self.test_results.append(memory_test_result)
        return memory_test_result
    
    async def test_tool_logging(self) -> Dict[str, Any]:
        """Test tool logging functionality."""
        print(f"\n📊 Testing tool logging")
        print("=" * 60)
        
        try:
            # Get tool call stats
            stats = get_tool_call_stats()
            
            print("Tool Call Statistics:")
            print(f"  Total tool calls: {stats.get('total_tool_calls', 0)}")
            print(f"  Tool types: {stats.get('tool_call_types', {})}")
            print(f"  Agent calls: {stats.get('agent_calls', {})}")
            print(f"  Subagent calls: {stats.get('subagent_calls', {})}")
            print(f"  Queries processed: {stats.get('queries_processed', 0)}")
            print(f"  Errors: {stats.get('errors', 0)}")
            
            if stats.get('execution_times'):
                print(f"  Avg execution time: {stats.get('avg_execution_time_ms', 0):.2f}ms")
                print(f"  Max execution time: {stats.get('max_execution_time_ms', 0):.2f}ms")
                print(f"  Min execution time: {stats.get('min_execution_time_ms', 0):.2f}ms")
            
            logging_test_result = {
                "test_type": "tool_logging",
                "success": True,
                "stats": stats,
                "timestamp": datetime.now().isoformat()
            }
            
            self.test_results.append(logging_test_result)
            return logging_test_result
            
        except Exception as e:
            error_result = {
                "test_type": "tool_logging",
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self.test_results.append(error_result)
            return error_result
    
    def get_test_summary(self) -> Dict[str, Any]:
        """Get summary of all test results."""
        total_tests = len(self.test_results)
        successful_tests = sum(1 for r in self.test_results if r.get("success", False))
        
        test_types = {}
        for result in self.test_results:
            test_type = result.get("test_type", "unknown")
            if test_type not in test_types:
                test_types[test_type] = {"total": 0, "successful": 0}
            test_types[test_type]["total"] += 1
            if result.get("success", False):
                test_types[test_type]["successful"] += 1
        
        return {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": (successful_tests / total_tests * 100) if total_tests > 0 else 0,
            "test_types": test_types,
            "results": self.test_results,
            "timestamp": datetime.now().isoformat()
        }
    
    def print_test_summary(self):
        """Print a summary of test results."""
        summary = self.get_test_summary()
        
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Successful: {summary['successful_tests']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        
        print("\nTest Types:")
        for test_type, stats in summary['test_types'].items():
            print(f"  {test_type}: {stats['successful']}/{stats['total']} ({stats['successful']/stats['total']*100:.1f}%)")
        
        print("\nDetailed Results:")
        for i, result in enumerate(summary['results'], 1):
            status = "✅" if result.get("success", False) else "❌"
            print(f"  {i}. {status} {result.get('test_type', 'unknown')} - {result.get('query', 'N/A')[:50]}...")


async def run_comprehensive_tests(mongo_client: MongoClient, org_id: int = 1):
    """Run comprehensive tests for chat, memory, and tool logging."""
    print("🧪 Starting Comprehensive Agent Tests")
    print("="*60)
    
    tester = ChatTester(mongo_client, org_id)
    
    # Test 1: Basic streaming chat
    print("\n1️⃣ Testing Basic Streaming Chat")
    await tester.test_streaming_chat(
        "What are the key requirements for tender analysis?",
        "test_thread_1",
        "test_tender_123"
    )
    
    # Test 2: Synchronous chat
    print("\n2️⃣ Testing Synchronous Chat")
    await tester.test_sync_chat(
        "Can you explain the compliance requirements?",
        "test_thread_2",
        "test_tender_123"
    )
    
    # Test 3: Memory persistence
    print("\n3️⃣ Testing Memory Persistence")
    await tester.test_memory_persistence("test_memory_thread")
    
    # Test 4: Tool logging
    print("\n4️⃣ Testing Tool Logging")
    await tester.test_tool_logging()
    
    # Print summary
    tester.print_test_summary()
    
    return tester.get_test_summary()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Initialize MongoDB client
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        # Run tests
        asyncio.run(run_comprehensive_tests(mongo_client))
    finally:
        mongo_client.close()
