"""
Test Agent - Streaming Testing Module

Tests for streaming responses, real-time communication, and performance monitoring.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List

from react_agent import ReactAgent
from src.deepagents.logging_utils import get_unified_logger, log_streaming_chunk
from pymongo import MongoClient


class StreamingTester:
    """Test class for streaming functionality and performance."""
    
    def __init__(self, mongo_client: MongoClient, org_id: int = 1):
        self.mongo_client = mongo_client
        self.org_id = org_id
        self.agent = ReactAgent(mongo_client, org_id)
        self.test_results = []
    
    async def test_streaming_performance(self, query: str, thread_id: str, iterations: int = 3) -> Dict[str, Any]:
        """Test streaming performance across multiple iterations."""
        print(f"\n⚡ Testing streaming performance: '{query[:50]}...'")
        print("=" * 60)
        
        performance_data = []
        
        for i in range(iterations):
            print(f"\n--- Iteration {i+1}/{iterations} ---")
            
            start_time = time.time()
            chunks = []
            chunk_times = []
            
            try:
                async for chunk in self.agent.chat_streaming(
                    user_query=query,
                    thread_id=f"{thread_id}_iter_{i+1}"
                ):
                    chunk_time = time.time()
                    chunks.append(chunk)
                    chunk_times.append(chunk_time - start_time)
                    
                    chunk_type = chunk.get("chunk_type", "unknown")
                    content = chunk.get("content", "")
                    
                    if chunk_type == "start":
                        print(f"🚀 Start: {chunk_time - start_time:.3f}s")
                    elif chunk_type == "content":
                        print(".", end="", flush=True)
                    elif chunk_type == "end":
                        print(f"\n✅ End: {chunk_time - start_time:.3f}s")
                    elif chunk_type == "error":
                        print(f"\n❌ Error: {content}")
                
                total_time = time.time() - start_time
                
                iteration_data = {
                    "iteration": i + 1,
                    "total_time": total_time,
                    "chunks_received": len(chunks),
                    "chunk_times": chunk_times,
                    "success": True,
                    "timestamp": datetime.now().isoformat()
                }
                
                performance_data.append(iteration_data)
                
            except Exception as e:
                error_data = {
                    "iteration": i + 1,
                    "error": str(e),
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                }
                performance_data.append(error_data)
                print(f"\n❌ Error in iteration {i+1}: {str(e)}")
        
        # Calculate performance metrics
        successful_iterations = [d for d in performance_data if d.get("success", False)]
        
        if successful_iterations:
            avg_time = sum(d["total_time"] for d in successful_iterations) / len(successful_iterations)
            avg_chunks = sum(d["chunks_received"] for d in successful_iterations) / len(successful_iterations)
            min_time = min(d["total_time"] for d in successful_iterations)
            max_time = max(d["total_time"] for d in successful_iterations)
        else:
            avg_time = avg_chunks = min_time = max_time = 0
        
        performance_test = {
            "test_type": "streaming_performance",
            "query": query,
            "iterations": iterations,
            "successful_iterations": len(successful_iterations),
            "performance_metrics": {
                "avg_time_seconds": avg_time,
                "avg_chunks": avg_chunks,
                "min_time_seconds": min_time,
                "max_time_seconds": max_time
            },
            "iteration_data": performance_data,
            "timestamp": datetime.now().isoformat()
        }
        
        self.test_results.append(performance_test)
        return performance_test
    
    async def test_streaming_chunk_analysis(self, query: str, thread_id: str) -> Dict[str, Any]:
        """Analyze streaming chunks in detail."""
        print(f"\n🔍 Testing streaming chunk analysis: '{query[:50]}...'")
        print("=" * 60)
        
        chunks = []
        chunk_types = {}
        content_lengths = []
        
        try:
            async for chunk in self.agent.chat_streaming(
                user_query=query,
                thread_id=thread_id
            ):
                chunks.append(chunk)
                
                chunk_type = chunk.get("chunk_type", "unknown")
                content = chunk.get("content", "")
                
                # Count chunk types
                chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
                
                # Track content lengths
                if content:
                    content_lengths.append(len(content))
                
                # Log streaming chunk
                log_streaming_chunk(
                    chunk_type=chunk_type,
                    content=content[:100] if content else None,
                    thread_id=thread_id,
                    metadata={"chunk_index": len(chunks)}
                )
                
                print(f"[{chunk_type}] {content[:50]}{'...' if len(content) > 50 else ''}")
            
            chunk_analysis = {
                "test_type": "streaming_chunk_analysis",
                "query": query,
                "thread_id": thread_id,
                "total_chunks": len(chunks),
                "chunk_types": chunk_types,
                "content_lengths": content_lengths,
                "avg_content_length": sum(content_lengths) / len(content_lengths) if content_lengths else 0,
                "max_content_length": max(content_lengths) if content_lengths else 0,
                "min_content_length": min(content_lengths) if content_lengths else 0,
                "chunks": chunks,
                "success": True,
                "timestamp": datetime.now().isoformat()
            }
            
            self.test_results.append(chunk_analysis)
            return chunk_analysis
            
        except Exception as e:
            error_result = {
                "test_type": "streaming_chunk_analysis",
                "query": query,
                "thread_id": thread_id,
                "error": str(e),
                "success": False,
                "timestamp": datetime.now().isoformat()
            }
            self.test_results.append(error_result)
            return error_result
    
    async def test_concurrent_streaming(self, queries: List[str], thread_id: str) -> Dict[str, Any]:
        """Test concurrent streaming requests."""
        print(f"\n🔄 Testing concurrent streaming with {len(queries)} queries")
        print("=" * 60)
        
        async def stream_single_query(query: str, query_id: int):
            """Stream a single query."""
            start_time = time.time()
            chunks = []
            
            try:
                async for chunk in self.agent.chat_streaming(
                    user_query=query,
                    thread_id=f"{thread_id}_concurrent_{query_id}"
                ):
                    chunks.append(chunk)
                
                total_time = time.time() - start_time
                
                return {
                    "query_id": query_id,
                    "query": query,
                    "chunks_received": len(chunks),
                    "total_time": total_time,
                    "success": True,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                return {
                    "query_id": query_id,
                    "query": query,
                    "error": str(e),
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                }
        
        # Run concurrent streaming
        start_time = time.time()
        tasks = [stream_single_query(query, i) for i, query in enumerate(queries)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        concurrent_test = {
            "test_type": "concurrent_streaming",
            "thread_id": thread_id,
            "queries_count": len(queries),
            "total_time": total_time,
            "successful_streams": sum(1 for r in results if isinstance(r, dict) and r.get("success", False)),
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
        self.test_results.append(concurrent_test)
        return concurrent_test
    
    async def test_streaming_error_handling(self, thread_id: str) -> Dict[str, Any]:
        """Test streaming error handling."""
        print(f"\n🚨 Testing streaming error handling")
        print("=" * 60)
        
        error_queries = [
            "",  # Empty query
            "x" * 10000,  # Very long query
            "SELECT * FROM users; DROP TABLE users;",  # SQL injection attempt
            "🚀" * 100,  # Emoji spam
        ]
        
        error_results = []
        
        for i, query in enumerate(error_queries):
            print(f"\n--- Error Test {i+1}: {query[:50]}{'...' if len(query) > 50 else ''} ---")
            
            chunks = []
            error_occurred = False
            
            try:
                async for chunk in self.agent.chat_streaming(
                    user_query=query,
                    thread_id=f"{thread_id}_error_{i+1}"
                ):
                    chunks.append(chunk)
                    
                    if chunk.get("chunk_type") == "error":
                        error_occurred = True
                        print(f"❌ Error chunk received: {chunk.get('content', '')}")
                
                error_results.append({
                    "test_query": query,
                    "chunks_received": len(chunks),
                    "error_occurred": error_occurred,
                    "success": True,
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                error_results.append({
                    "test_query": query,
                    "error": str(e),
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                })
                print(f"❌ Exception: {str(e)}")
        
        error_handling_test = {
            "test_type": "streaming_error_handling",
            "thread_id": thread_id,
            "error_tests": len(error_queries),
            "results": error_results,
            "timestamp": datetime.now().isoformat()
        }
        
        self.test_results.append(error_handling_test)
        return error_handling_test
    
    def get_streaming_test_summary(self) -> Dict[str, Any]:
        """Get summary of streaming test results."""
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
            "total_streaming_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": (successful_tests / total_tests * 100) if total_tests > 0 else 0,
            "test_types": test_types,
            "results": self.test_results,
            "timestamp": datetime.now().isoformat()
        }
    
    def print_streaming_test_summary(self):
        """Print a summary of streaming test results."""
        summary = self.get_streaming_test_summary()
        
        print("\n" + "="*60)
        print("⚡ STREAMING TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {summary['total_streaming_tests']}")
        print(f"Successful: {summary['successful_tests']}")
        print(f"Success Rate: {summary['success_rate']:.1f}%")
        
        print("\nStreaming Test Types:")
        for test_type, stats in summary['test_types'].items():
            print(f"  {test_type}: {stats['successful']}/{stats['total']} ({stats['successful']/stats['total']*100:.1f}%)")
        
        print("\nDetailed Results:")
        for i, result in enumerate(summary['results'], 1):
            status = "✅" if result.get("success", False) else "❌"
            print(f"  {i}. {status} {result.get('test_type', 'unknown')}")


async def run_streaming_tests(mongo_client: MongoClient, org_id: int = 1):
    """Run comprehensive streaming tests."""
    print("⚡ Starting Streaming Tests")
    print("="*60)
    
    tester = StreamingTester(mongo_client, org_id)
    
    # Test 1: Streaming performance
    print("\n1️⃣ Testing Streaming Performance")
    await tester.test_streaming_performance(
        "Analyze the tender requirements for cloud migration services including security, compliance, and performance aspects.",
        "perf_test_thread"
    )
    
    # Test 2: Chunk analysis
    print("\n2️⃣ Testing Streaming Chunk Analysis")
    await tester.test_streaming_chunk_analysis(
        "What are the key compliance requirements for GDPR and how do they apply to data processing?",
        "chunk_analysis_thread"
    )
    
    # Test 3: Concurrent streaming
    print("\n3️⃣ Testing Concurrent Streaming")
    concurrent_queries = [
        "What are the security requirements?",
        "Explain the compliance framework.",
        "Describe the performance metrics.",
        "What are the cost considerations?"
    ]
    await tester.test_concurrent_streaming(concurrent_queries, "concurrent_test_thread")
    
    # Test 4: Error handling
    print("\n4️⃣ Testing Streaming Error Handling")
    await tester.test_streaming_error_handling("error_test_thread")
    
    # Print summary
    tester.print_streaming_test_summary()
    
    return tester.get_streaming_test_summary()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Initialize MongoDB client
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        # Run streaming tests
        asyncio.run(run_streaming_tests(mongo_client))
    finally:
        mongo_client.close()
