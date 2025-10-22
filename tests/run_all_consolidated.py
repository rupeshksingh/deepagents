"""
Run All Tests with Consolidated Output
Executes all 30 test cases sequentially and stores everything in a single comprehensive file.
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from react_agent import ReactAgent
from src.deepagents.logging_utils import (
    start_run,
    end_run,
    get_tool_call_stats,
)


class ConsolidatedTestRunner:
    """Runs all tests and consolidates output into single file"""
    
    def __init__(self, mongo_client: MongoClient, tender_id: str, org_id: int = 1):
        self.agent = ReactAgent(mongo_client, org_id=org_id)
        self.tender_id = tender_id
        self.test_cases_file = Path(__file__).parent / "test_cases.json"
        self.test_cases = self._load_test_cases()
        self.results = []
        
    def _load_test_cases(self) -> dict:
        """Load test cases from JSON file"""
        with open(self.test_cases_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _get_latest_session_log(self) -> str:
        """Get the latest session log content"""
        try:
            logs_dir = project_root / "logs"
            if not logs_dir.exists():
                return "(No logs directory found)"
            
            session_logs = sorted(
                [f for f in logs_dir.glob("session_*.log")],
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if session_logs:
                with open(session_logs[0], 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            return f"(Could not read session log: {e})"
        
        return "(No session log found)"
    
    async def run_single_test(self, test_case: dict, test_number: int, total_tests: int, output_file) -> dict:
        """Run a single test and write to consolidated file"""
        test_id = test_case["id"]
        test_name = test_case["name"]
        
        # Use English query if available, otherwise Danish
        query = test_case.get("query_en", test_case.get("query_da", ""))
        
        thread_id = f"test_{test_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Write test header to file
        output_file.write("\n" + "=" * 120 + "\n")
        output_file.write(f"TEST {test_number}/{total_tests}: {test_id} - {test_name}\n")
        output_file.write("=" * 120 + "\n\n")
        
        output_file.write(f"Test ID:          {test_id}\n")
        output_file.write(f"Test Name:        {test_name}\n")
        output_file.write(f"Category:         {test_case['category']}\n")
        output_file.write(f"Persona:          {test_case['persona']}\n")
        output_file.write(f"Complexity:       {test_case['complexity']}\n")
        output_file.write(f"Thread ID:        {thread_id}\n")
        output_file.write(f"Tender ID:        {self.tender_id}\n")
        output_file.write(f"Timestamp:        {datetime.now().isoformat()}\n\n")
        
        output_file.write(f"Query:            {query}\n")
        if test_case.get("query_da") and test_case.get("query_en"):
            other_query = test_case.get("query_da") if query == test_case.get("query_en") else test_case.get("query_en")
            output_file.write(f"Alt Query:        {other_query}\n")
        output_file.write(f"\nExpected Routing: {test_case.get('expected_routing', 'N/A')}\n")
        output_file.write(f"Architecture:     {', '.join(test_case.get('architecture_focus', []))}\n")
        
        output_file.write("\nSuccess Criteria:\n")
        for criterion in test_case.get('success_criteria', []):
            output_file.write(f"  - {criterion}\n")
        
        if test_case.get('must_cite'):
            output_file.write(f"\nMust Cite:        {', '.join(test_case['must_cite'])}\n")
        
        output_file.write("\n" + "-" * 120 + "\n")
        output_file.write("EXECUTION\n")
        output_file.write("-" * 120 + "\n\n")
        output_file.flush()
        
        # Console output
        complexity_emoji = {
            "Simple": "🟢",
            "Moderate": "🟡",
            "Advanced": "🟠",
            "Research+": "🔴"
        }.get(test_case["complexity"], "⚪")
        
        print(f"\n{complexity_emoji} [{test_number}/{total_tests}] Running {test_id}: {test_name}")
        print(f"   Category: {test_case['category']} | Complexity: {test_case['complexity']}")
        
        start_time = datetime.now()
        
        try:
            # Run the test
            result = await self.agent.chat_sync(
                user_query=query,
                thread_id=thread_id,
                tender_id=self.tender_id
            )
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            response_text = result.get("response", "No response")
            processing_time_ms = result.get("processing_time_ms", 0)
            success = result.get("success", False)
            
            # Get statistics
            stats = get_tool_call_stats()
            
            # Get session log
            session_log_content = self._get_latest_session_log()
            
            # Write execution summary
            output_file.write("EXECUTION SUMMARY\n")
            output_file.write("-" * 120 + "\n")
            output_file.write(f"Success:          {success}\n")
            output_file.write(f"Duration:         {duration:.2f}s\n")
            output_file.write(f"Processing Time:  {processing_time_ms}ms\n")
            
            if "error" not in stats:
                output_file.write(f"Total Tool Calls: {stats.get('total_tool_calls', 0)}\n")
                output_file.write(f"Tool Errors:      {stats.get('errors', 0)}\n")
                output_file.write(f"Queries Proc:     {stats.get('queries_processed', 0)}\n")
                
                if stats.get('execution_times'):
                    output_file.write(f"Avg Exec Time:    {stats.get('avg_execution_time_ms', 0):.2f}ms\n")
                    output_file.write(f"Max Exec Time:    {stats.get('max_execution_time_ms', 0):.2f}ms\n")
                    output_file.write(f"Min Exec Time:    {stats.get('min_execution_time_ms', 0):.2f}ms\n")
                
                if stats.get('tool_call_types'):
                    output_file.write("\nTool Usage Breakdown:\n")
                    for tool, count in stats['tool_call_types'].items():
                        output_file.write(f"  - {tool}: {count} calls\n")
            else:
                output_file.write(f"Statistics Error: {stats.get('error')}\n")
            
            # Write agent thinking
            output_file.write("\n" + "-" * 120 + "\n")
            output_file.write("AGENT THINKING (Step-by-Step Trace)\n")
            output_file.write("-" * 120 + "\n\n")
            output_file.write(session_log_content)
            output_file.write("\n")
            
            # Write final response
            output_file.write("\n" + "-" * 120 + "\n")
            output_file.write("FINAL RESPONSE\n")
            output_file.write("-" * 120 + "\n\n")
            output_file.write(response_text)
            output_file.write("\n\n")
            
            output_file.flush()
            
            # Console output
            status_emoji = "✅" if success else "❌"
            print(f"   {status_emoji} Completed in {duration:.2f}s | Tool Calls: {stats.get('total_tool_calls', 0)} | Response: {len(response_text)} chars")
            
            return {
                "test_id": test_id,
                "test_name": test_name,
                "category": test_case["category"],
                "complexity": test_case["complexity"],
                "success": success,
                "duration_seconds": duration,
                "tool_calls": stats.get('total_tool_calls', 0),
                "errors": stats.get('errors', 0),
                "response_length": len(response_text)
            }
            
        except Exception as e:
            error_msg = f"ERROR: {str(e)}"
            output_file.write(f"\n{error_msg}\n\n")
            
            import traceback
            error_trace = traceback.format_exc()
            output_file.write("TRACEBACK:\n")
            output_file.write(error_trace)
            output_file.write("\n\n")
            output_file.flush()
            
            print(f"   ❌ CRASHED: {str(e)}")
            
            return {
                "test_id": test_id,
                "test_name": test_name,
                "category": test_case["category"],
                "complexity": test_case["complexity"],
                "success": False,
                "error": str(e)
            }
    
    async def run_all_tests(self):
        """Run all tests and save to consolidated file"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f"all_tests_consolidated_{timestamp}.txt"
        output_path = Path(__file__).parent / output_filename
        
        test_cases = self.test_cases["test_cases"]
        total_tests = len(test_cases)
        
        print("\n" + "🚀" * 60)
        print("DEEP AGENTS - COMPREHENSIVE TEST SUITE (CONSOLIDATED)")
        print("🚀" * 60)
        print(f"\nTimestamp:        {timestamp}")
        print(f"Total Tests:      {total_tests}")
        print(f"Tender ID:        {self.tender_id}")
        print(f"Output File:      {output_filename}")
        print(f"Estimated Time:   ~45-60 minutes")
        print("\n" + "=" * 120 + "\n")
        
        run_id = start_run(f"Consolidated Test Suite - {timestamp}")
        
        with open(output_path, 'w', encoding='utf-8') as output_file:
            # Write file header
            output_file.write("=" * 120 + "\n")
            output_file.write("DEEP AGENTS - COMPREHENSIVE TEST SUITE RESULTS (CONSOLIDATED)\n")
            output_file.write("=" * 120 + "\n\n")
            
            output_file.write(f"Run ID:           {run_id}\n")
            output_file.write(f"Timestamp:        {timestamp}\n")
            output_file.write(f"Tender ID:        {self.tender_id}\n")
            output_file.write(f"Total Tests:      {total_tests}\n")
            output_file.write(f"Test Framework:   LangChain Deep Agents\n")
            output_file.write(f"Architecture:     Main Agent + Subagents (Document Analyzer, Web Researcher)\n")
            output_file.write(f"Test Focus:       L1/L2/L3 Progressive Disclosure, Language Adaptation, Subagents, HITL\n\n")
            
            output_file.write("TEST CATEGORIES:\n")
            categories = {}
            for test in test_cases:
                cat = test["category"]
                categories[cat] = categories.get(cat, 0) + 1
            for cat, count in sorted(categories.items()):
                output_file.write(f"  - {cat}: {count} tests\n")
            
            output_file.write("\n" + "=" * 120 + "\n")
            output_file.write("BEGIN TEST EXECUTION\n")
            output_file.write("=" * 120 + "\n")
            output_file.flush()
            
            # Run each test
            for idx, test_case in enumerate(test_cases, 1):
                result = await self.run_single_test(test_case, idx, total_tests, output_file)
                self.results.append(result)
                
                # Small delay between tests
                await asyncio.sleep(2)
            
            # Write summary at the end
            output_file.write("\n" + "=" * 120 + "\n")
            output_file.write("TEST SUITE SUMMARY\n")
            output_file.write("=" * 120 + "\n\n")
            
            successful_tests = sum(1 for r in self.results if r.get("success", False))
            failed_tests = total_tests - successful_tests
            total_duration = sum(r.get("duration_seconds", 0) for r in self.results)
            total_tool_calls = sum(r.get("tool_calls", 0) for r in self.results)
            total_errors = sum(r.get("errors", 0) for r in self.results)
            
            output_file.write(f"Total Tests:      {total_tests}\n")
            output_file.write(f"Successful:       {successful_tests} ✅\n")
            output_file.write(f"Failed:           {failed_tests} ❌\n")
            output_file.write(f"Success Rate:     {(successful_tests/total_tests*100) if total_tests > 0 else 0:.1f}%\n\n")
            
            output_file.write(f"Total Duration:   {total_duration:.2f}s ({total_duration/60:.1f} minutes)\n")
            output_file.write(f"Avg Duration:     {(total_duration/total_tests) if total_tests > 0 else 0:.2f}s\n")
            output_file.write(f"Total Tool Calls: {total_tool_calls}\n")
            output_file.write(f"Avg Tool Calls:   {(total_tool_calls/total_tests) if total_tests > 0 else 0:.1f}\n")
            output_file.write(f"Total Errors:     {total_errors}\n\n")
            
            # Breakdown by category
            output_file.write("RESULTS BY CATEGORY:\n")
            output_file.write("-" * 120 + "\n\n")
            
            by_category = {}
            for result in self.results:
                cat = result["category"]
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(result)
            
            for category, results in sorted(by_category.items()):
                cat_passed = sum(1 for r in results if r.get("success", False))
                cat_total = len(results)
                output_file.write(f"\n{category} ({cat_passed}/{cat_total} passed)\n")
                output_file.write("-" * 120 + "\n")
                
                for result in results:
                    status = "✅ PASS" if result.get("success") else "❌ FAIL"
                    duration = result.get("duration_seconds", 0)
                    tools = result.get("tool_calls", 0)
                    
                    output_file.write(f"{status}  {result['test_id']:12}  {result['test_name']:50}  ")
                    output_file.write(f"{duration:6.1f}s  {tools:3} tools\n")
                    
                    if "error" in result:
                        output_file.write(f"       Error: {result['error']}\n")
            
            # Breakdown by complexity
            output_file.write("\n\nRESULTS BY COMPLEXITY:\n")
            output_file.write("-" * 120 + "\n\n")
            
            by_complexity = {}
            for result in self.results:
                comp = result["complexity"]
                if comp not in by_complexity:
                    by_complexity[comp] = []
                by_complexity[comp].append(result)
            
            complexity_order = ["Simple", "Moderate", "Advanced", "Research+"]
            for complexity in complexity_order:
                if complexity in by_complexity:
                    results = by_complexity[complexity]
                    comp_passed = sum(1 for r in results if r.get("success", False))
                    comp_total = len(results)
                    comp_avg_duration = sum(r.get("duration_seconds", 0) for r in results) / comp_total if comp_total > 0 else 0
                    
                    output_file.write(f"{complexity}: {comp_passed}/{comp_total} passed, ")
                    output_file.write(f"avg {comp_avg_duration:.1f}s\n")
            
            output_file.write("\n" + "=" * 120 + "\n")
            output_file.write(f"END OF TEST SUITE - {datetime.now().isoformat()}\n")
            output_file.write("=" * 120 + "\n")
        
        end_run(f"Consolidated test suite completed: {successful_tests}/{total_tests} tests passed")
        
        # Console summary
        print("\n" + "=" * 120)
        print("TEST SUITE COMPLETED")
        print("=" * 120)
        print(f"Output File:      {output_path}")
        print(f"Total Tests:      {total_tests}")
        print(f"Successful:       {successful_tests} ✅")
        print(f"Failed:           {failed_tests} ❌")
        print(f"Success Rate:     {(successful_tests/total_tests*100) if total_tests > 0 else 0:.1f}%")
        print(f"Total Duration:   {total_duration:.2f}s ({total_duration/60:.1f} minutes)")
        print(f"Total Tool Calls: {total_tool_calls}")
        print("=" * 120)
        print(f"\n📄 Complete consolidated results saved to:")
        print(f"   {output_path}")
        print(f"\n💡 All {total_tests} test results are in a single file for easy review!")
        print("=" * 120 + "\n")


async def main():
    """Main entry point"""
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URL")
    tender_id = os.getenv("TENDER_ID")
    
    if not mongodb_uri:
        print("❌ MONGODB_URL not found in environment")
        sys.exit(1)
    
    if not tender_id:
        print("❌ TENDER_ID not found in environment")
        sys.exit(1)
    
    # Initialize runner
    mongo_client = MongoClient(mongodb_uri)
    runner = ConsolidatedTestRunner(mongo_client, tender_id)
    
    # Run all tests
    await runner.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())

