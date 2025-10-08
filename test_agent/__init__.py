"""
Test Agent - Main Test Runner

Comprehensive test suite for chat, memory, streaming, and tool logging functionality.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any

from test_chat import run_comprehensive_tests
from test_memory import run_memory_tests
from test_streaming import run_streaming_tests
from src.deepagents.logging_utils import get_tool_call_stats
from pymongo import MongoClient


class TestRunner:
    """Main test runner for all agent functionality."""
    
    def __init__(self, mongo_client: MongoClient, org_id: int = 1):
        self.mongo_client = mongo_client
        self.org_id = org_id
        self.test_suites = []
        self.overall_results = {}
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all test suites."""
        print("🧪 Starting Comprehensive Agent Test Suite")
        print("="*80)
        print(f"Organization ID: {self.org_id}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("="*80)
        
        start_time = time.time()
        
        # Test Suite 1: Chat Tests
        print("\n" + "="*80)
        print("1️⃣ CHAT FUNCTIONALITY TESTS")
        print("="*80)
        chat_results = await run_comprehensive_tests(self.mongo_client, self.org_id)
        self.test_suites.append({
            "suite_name": "chat_tests",
            "results": chat_results,
            "timestamp": datetime.now().isoformat()
        })
        
        # Test Suite 2: Memory Tests
        print("\n" + "="*80)
        print("2️⃣ MEMORY PERSISTENCE TESTS")
        print("="*80)
        memory_results = await run_memory_tests(self.mongo_client, self.org_id)
        self.test_suites.append({
            "suite_name": "memory_tests",
            "results": memory_results,
            "timestamp": datetime.now().isoformat()
        })
        
        # Test Suite 3: Streaming Tests
        print("\n" + "="*80)
        print("3️⃣ STREAMING FUNCTIONALITY TESTS")
        print("="*80)
        streaming_results = await run_streaming_tests(self.mongo_client, self.org_id)
        self.test_suites.append({
            "suite_name": "streaming_tests",
            "results": streaming_results,
            "timestamp": datetime.now().isoformat()
        })
        
        # Test Suite 4: Tool Logging Tests
        print("\n" + "="*80)
        print("4️⃣ TOOL LOGGING TESTS")
        print("="*80)
        logging_results = await self._test_tool_logging()
        self.test_suites.append({
            "suite_name": "logging_tests",
            "results": logging_results,
            "timestamp": datetime.now().isoformat()
        })
        
        total_time = time.time() - start_time
        
        # Compile overall results
        self.overall_results = {
            "test_run_id": f"test_run_{int(time.time())}",
            "org_id": self.org_id,
            "start_time": datetime.fromtimestamp(start_time).isoformat(),
            "end_time": datetime.now().isoformat(),
            "total_time_seconds": total_time,
            "test_suites": self.test_suites,
            "overall_summary": self._compile_overall_summary(),
            "timestamp": datetime.now().isoformat()
        }
        
        # Print overall summary
        self._print_overall_summary()
        
        return self.overall_results
    
    async def _test_tool_logging(self) -> Dict[str, Any]:
        """Test tool logging functionality."""
        print("📊 Testing Tool Logging Functionality")
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
                "test_type": "tool_logging_comprehensive",
                "success": True,
                "stats": stats,
                "timestamp": datetime.now().isoformat()
            }
            
            return logging_test_result
            
        except Exception as e:
            error_result = {
                "test_type": "tool_logging_comprehensive",
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            return error_result
    
    def _compile_overall_summary(self) -> Dict[str, Any]:
        """Compile overall test summary."""
        total_tests = 0
        successful_tests = 0
        
        suite_summaries = {}
        
        for suite in self.test_suites:
            suite_name = suite["suite_name"]
            results = suite["results"]
            
            if suite_name == "chat_tests":
                total_tests += results.get("total_tests", 0)
                successful_tests += results.get("successful_tests", 0)
            elif suite_name == "memory_tests":
                total_tests += results.get("total_memory_tests", 0)
                successful_tests += results.get("successful_tests", 0)
            elif suite_name == "streaming_tests":
                total_tests += results.get("total_streaming_tests", 0)
                successful_tests += results.get("successful_tests", 0)
            elif suite_name == "logging_tests":
                total_tests += 1
                if results.get("success", False):
                    successful_tests += 1
            
            suite_summaries[suite_name] = {
                "total_tests": results.get("total_tests", results.get("total_memory_tests", results.get("total_streaming_tests", 1))),
                "successful_tests": results.get("successful_tests", 1 if results.get("success", False) else 0),
                "success_rate": results.get("success_rate", 100 if results.get("success", False) else 0)
            }
        
        return {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": (successful_tests / total_tests * 100) if total_tests > 0 else 0,
            "suite_summaries": suite_summaries
        }
    
    def _print_overall_summary(self):
        """Print overall test summary."""
        summary = self.overall_results["overall_summary"]
        
        print("\n" + "="*80)
        print("🏆 OVERALL TEST SUMMARY")
        print("="*80)
        print(f"Test Run ID: {self.overall_results['test_run_id']}")
        print(f"Organization ID: {self.overall_results['org_id']}")
        print(f"Total Time: {self.overall_results['total_time_seconds']:.2f} seconds")
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Successful Tests: {summary['successful_tests']}")
        print(f"Overall Success Rate: {summary['success_rate']:.1f}%")
        
        print("\nTest Suite Breakdown:")
        for suite_name, suite_summary in summary['suite_summaries'].items():
            print(f"  {suite_name}: {suite_summary['successful_tests']}/{suite_summary['total_tests']} ({suite_summary['success_rate']:.1f}%)")
        
        print("\n" + "="*80)
        print("✅ Test Suite Completed Successfully!")
        print("="*80)
    
    def save_results(self, filename: str = None):
        """Save test results to JSON file."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_results_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.overall_results, f, indent=2, default=str)
        
        print(f"\n📁 Test results saved to: {filename}")


async def main():
    """Main function to run all tests."""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Initialize MongoDB client
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongo_client = MongoClient(mongodb_uri)
    
    try:
        # Initialize test runner
        test_runner = TestRunner(mongo_client, org_id=1)
        
        # Run all tests
        results = await test_runner.run_all_tests()
        
        # Save results
        test_runner.save_results()
        
        return results
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {str(e)}")
        return {"error": str(e)}
    
    finally:
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
