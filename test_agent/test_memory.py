"""
Test Agent - Memory Testing Module

Tests for MongoDB checkpointer memory persistence and conversation state management.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List

from react_agent import ReactAgent
from src.deepagents.logging_utils import get_unified_logger, log_memory_operation
from pymongo import MongoClient


class MemoryTester:
    """Test class for memory persistence and conversation state management."""

    def __init__(self, mongo_client: MongoClient, org_id: int = 1):
        self.mongo_client = mongo_client
        self.org_id = org_id
        self.agent = ReactAgent(mongo_client, org_id)
        self.test_results = []

    async def test_conversation_persistence(self, thread_id: str) -> Dict[str, Any]:
        """Test conversation persistence across multiple sessions."""
        print(f"\n🧠 Testing conversation persistence for thread: {thread_id}")
        print("=" * 60)

        # First conversation
        print("--- First Conversation ---")
        result1 = await self._test_query(
            "My name is Alice and I'm analyzing tender #12345 for cloud services.",
            thread_id,
        )

        await asyncio.sleep(2)  # Simulate time gap

        # Second conversation (should remember context)
        print("\n--- Second Conversation (should remember context) ---")
        result2 = await self._test_query(
            "What's my name and which tender am I analyzing?", thread_id
        )

        await asyncio.sleep(2)  # Simulate time gap

        # Third conversation (should maintain full context)
        print("\n--- Third Conversation (should maintain full context) ---")
        result3 = await self._test_query(
            "Can you summarize our conversation and provide analysis recommendations?",
            thread_id,
        )

        persistence_test = {
            "test_type": "conversation_persistence",
            "thread_id": thread_id,
            "conversations": [result1, result2, result3],
            "context_maintained": self._check_context_maintenance(
                [result1, result2, result3]
            ),
            "timestamp": datetime.now().isoformat(),
        }

        self.test_results.append(persistence_test)
        return persistence_test

    async def test_multi_thread_isolation(self) -> Dict[str, Any]:
        """Test that different threads maintain separate conversations."""
        print(f"\n🔀 Testing multi-thread isolation")
        print("=" * 60)

        thread1_id = "test_thread_1"
        thread2_id = "test_thread_2"

        # Set up different contexts in each thread
        print("--- Setting up Thread 1 context ---")
        await self._test_query(
            "I'm working on tender #11111 for infrastructure services.", thread1_id
        )

        print("\n--- Setting up Thread 2 context ---")
        await self._test_query(
            "I'm working on tender #22222 for software development.", thread2_id
        )

        # Test isolation
        print("\n--- Testing Thread 1 isolation ---")
        result1 = await self._test_query("Which tender am I working on?", thread1_id)

        print("\n--- Testing Thread 2 isolation ---")
        result2 = await self._test_query("Which tender am I working on?", thread2_id)

        isolation_test = {
            "test_type": "multi_thread_isolation",
            "thread1_id": thread1_id,
            "thread2_id": thread2_id,
            "thread1_result": result1,
            "thread2_result": result2,
            "isolation_maintained": self._check_thread_isolation(result1, result2),
            "timestamp": datetime.now().isoformat(),
        }

        self.test_results.append(isolation_test)
        return isolation_test

    async def test_memory_operations(self, thread_id: str) -> Dict[str, Any]:
        """Test memory operations and checkpointer interactions."""
        print(f"\n💾 Testing memory operations for thread: {thread_id}")
        print("=" * 60)

        # Log memory operations
        log_memory_operation("checkpoint_save", thread_id, "save", {"step": 1})

        # First query
        result1 = await self._test_query(
            "I need to analyze compliance requirements for GDPR.", thread_id
        )

        log_memory_operation("checkpoint_save", thread_id, "save", {"step": 2})

        # Second query
        result2 = await self._test_query(
            "What compliance requirements did I mention?", thread_id
        )

        log_memory_operation("checkpoint_load", thread_id, "load", {"step": 3})

        # Third query
        result3 = await self._test_query(
            "Can you provide a detailed analysis of GDPR compliance?", thread_id
        )

        log_memory_operation("checkpoint_save", thread_id, "save", {"step": 4})

        memory_ops_test = {
            "test_type": "memory_operations",
            "thread_id": thread_id,
            "operations_logged": 4,
            "queries": [result1, result2, result3],
            "timestamp": datetime.now().isoformat(),
        }

        self.test_results.append(memory_ops_test)
        return memory_ops_test

    async def test_conversation_history_retrieval(
        self, thread_id: str
    ) -> Dict[str, Any]:
        """Test conversation history retrieval."""
        print(f"\n📚 Testing conversation history retrieval for thread: {thread_id}")
        print("=" * 60)

        # Add some conversation history
        queries = [
            "I'm starting a new tender analysis project.",
            "The tender is for cloud migration services.",
            "I need to focus on security and compliance aspects.",
            "What are the key areas I should analyze?",
        ]

        for query in queries:
            await self._test_query(query, thread_id)
            await asyncio.sleep(1)

        # Test history retrieval
        print("\n--- Testing History Retrieval ---")
        history_result = await self._test_query(
            "Can you summarize our conversation history?", thread_id
        )

        history_test = {
            "test_type": "conversation_history_retrieval",
            "thread_id": thread_id,
            "queries_added": len(queries),
            "history_retrieval_result": history_result,
            "timestamp": datetime.now().isoformat(),
        }

        self.test_results.append(history_test)
        return history_test

    async def _test_query(self, query: str, thread_id: str) -> Dict[str, Any]:
        """Helper method to test a single query."""
        print(f"Query: {query}")

        start_time = time.time()

        try:
            result = await self.agent.chat_sync(user_query=query, thread_id=thread_id)

            processing_time = int((time.time() - start_time) * 1000)

            print(f"Response: {result.get('response', 'No response')[:100]}...")
            print(f"Time: {processing_time}ms")

            return {
                "query": query,
                "response": result.get("response", ""),
                "success": result.get("success", False),
                "processing_time_ms": processing_time,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            print(f"Error: {str(e)}")
            return {
                "query": query,
                "error": str(e),
                "success": False,
                "timestamp": datetime.now().isoformat(),
            }

    def _check_context_maintenance(self, results: List[Dict[str, Any]]) -> bool:
        """Check if context was maintained across conversations."""
        if len(results) < 2:
            return False

        # Check if later responses reference earlier context
        later_responses = " ".join([r.get("response", "") for r in results[1:]])
        early_context = results[0].get("response", "")

        # Simple check: if later responses contain references to early context
        context_keywords = ["Alice", "tender", "12345", "cloud services"]
        context_found = any(
            keyword.lower() in later_responses.lower() for keyword in context_keywords
        )

        return context_found

    def _check_thread_isolation(
        self, result1: Dict[str, Any], result2: Dict[str, Any]
    ) -> bool:
        """Check if threads maintain separate contexts."""
        response1 = result1.get("response", "").lower()
        response2 = result2.get("response", "").lower()

        # Check if each response contains its respective tender ID
        tender1_found = "11111" in response1 and "infrastructure" in response1
        tender2_found = "22222" in response2 and "software" in response2

        return tender1_found and tender2_found

    def get_memory_test_summary(self) -> Dict[str, Any]:
        """Get summary of memory test results."""
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
            "total_memory_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": (
                (successful_tests / total_tests * 100) if total_tests > 0 else 0
            ),
            "test_types": test_types,
            "results": self.test_results,
            "timestamp": datetime.now().isoformat(),
        }

    def print_memory_test_summary(self):
        """Print a summary of memory test results."""
        summary = self.get_memory_test_summary()

        print("\n" + "=" * 60)
        print("🧠 MEMORY TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {summary['total_memory_tests']}")
        print(f"Successful: {summary['successful_tests']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")

        print("\nMemory Test Types:")
        for test_type, stats in summary["test_types"].items():
            print(
                f"  {test_type}: {stats['successful']}/{stats['total']} ({stats['successful']/stats['total']*100:.1f}%)"
            )

        print("\nDetailed Results:")
        for i, result in enumerate(summary["results"], 1):
            status = "✅" if result.get("success", False) else "❌"
            print(f"  {i}. {status} {result.get('test_type', 'unknown')}")


async def run_memory_tests(mongo_client: MongoClient, org_id: int = 1):
    """Run comprehensive memory tests."""
    print("🧠 Starting Memory Persistence Tests")
    print("=" * 60)

    tester = MemoryTester(mongo_client, org_id)

    # Test 1: Conversation persistence
    print("\n1️⃣ Testing Conversation Persistence")
    await tester.test_conversation_persistence("memory_test_thread_1")

    # Test 2: Multi-thread isolation
    print("\n2️⃣ Testing Multi-Thread Isolation")
    await tester.test_multi_thread_isolation()

    # Test 3: Memory operations
    print("\n3️⃣ Testing Memory Operations")
    await tester.test_memory_operations("memory_ops_thread")

    # Test 4: Conversation history retrieval
    print("\n4️⃣ Testing Conversation History Retrieval")
    await tester.test_conversation_history_retrieval("history_test_thread")

    # Print summary
    tester.print_memory_test_summary()

    return tester.get_memory_test_summary()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Initialize MongoDB client
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)

    try:
        # Run memory tests
        asyncio.run(run_memory_tests(mongo_client))
    finally:
        mongo_client.close()
