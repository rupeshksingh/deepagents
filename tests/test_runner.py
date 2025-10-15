"""
Test Runner for Danish Tender Analysis Agent
Runs selected test cases by ID with comprehensive reporting.
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
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
    get_unified_logger,
)


class TestRunner:
    """Runs and validates test cases from test_cases.json"""
    
    def __init__(self, mongo_client: MongoClient, tender_id: str, org_id: int = 1):
        self.agent = ReactAgent(mongo_client, org_id=org_id)
        self.tender_id = tender_id
        self.test_cases_file = Path(__file__).parent / "test_cases.json"
        self.test_cases = self._load_test_cases()
        self.results = []
        
    def _load_test_cases(self) -> Dict:
        """Load test cases from JSON file"""
        with open(self.test_cases_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def list_tests(self, category: Optional[str] = None) -> None:
        """List all available tests, optionally filtered by category"""
        print("\n" + "=" * 100)
        print("AVAILABLE TEST CASES")
        print("=" * 100 + "\n")
        
        if category:
            print(f"Category Filter: {category}\n")
        
        current_category = None
        for test in self.test_cases["test_cases"]:
            if category and test["category"] != category:
                continue
                
            if test["category"] != current_category:
                current_category = test["category"]
                print(f"\n{current_category}")
                print("-" * 100)
            
            complexity_emoji = {
                "Simple": "🟢",
                "Moderate": "🟡",
                "Advanced": "🟠",
                "Research+": "🔴"
            }.get(test["complexity"], "⚪")
            
            print(f"  {complexity_emoji} {test['id']:12} | {test['name']:60} | {test['persona']}")
        
        print("\n" + "=" * 100)
        print(f"Total Tests: {len([t for t in self.test_cases['test_cases'] if not category or t['category'] == category])}")
        print("=" * 100 + "\n")
    
    def get_test_by_id(self, test_id: str) -> Optional[Dict]:
        """Get a single test case by ID"""
        for test in self.test_cases["test_cases"]:
            if test["id"] == test_id:
                return test
        return None
    
    async def run_single_test(self, test_case: Dict, output_dir: Path) -> Dict:
        """Run a single test case and return results"""
        test_id = test_case["id"]
        test_name = test_case["name"]
        
        # Use English query if available, otherwise Danish
        query = test_case.get("query_en", test_case.get("query_da", ""))
        
        thread_id = f"test_{test_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Print test header
        print("\n" + "=" * 100)
        print(f"TEST {test_id}: {test_name}")
        print("=" * 100)
        print(f"Persona:     {test_case['persona']}")
        print(f"Category:    {test_case['category']}")
        print(f"Complexity:  {test_case['complexity']}")
        print(f"Query:       {query}")
        print(f"Thread ID:   {thread_id}")
        print("-" * 100)
        
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
            
            # Validate against success criteria
            validation_results = self._validate_test(test_case, response_text, session_log_content, stats)
            
            # Save detailed output
            test_output_file = output_dir / f"{test_id}_output.txt"
            self._save_test_output(test_output_file, test_case, response_text, session_log_content, stats, validation_results, duration)
            
            # Print summary
            validation_passed = validation_results["overall_pass"]
            status_emoji = "✅" if validation_passed else "❌"
            print(f"\n{status_emoji} Test {test_id}: {'PASSED' if validation_passed else 'FAILED'}")
            print(f"   Duration: {duration:.2f}s | Tool Calls: {stats.get('total_tool_calls', 0)} | Response: {len(response_text)} chars")
            
            if not validation_passed:
                print(f"   Failed Criteria: {', '.join(validation_results['failed_criteria'])}")
            
            return {
                "test_id": test_id,
                "test_name": test_name,
                "success": success,
                "validation_passed": validation_passed,
                "duration_seconds": duration,
                "processing_time_ms": processing_time_ms,
                "tool_calls": stats.get('total_tool_calls', 0),
                "errors": stats.get('errors', 0),
                "validation_results": validation_results,
                "output_file": str(test_output_file)
            }
            
        except Exception as e:
            print(f"❌ Test {test_id} CRASHED: {str(e)}")
            
            import traceback
            error_trace = traceback.format_exc()
            
            return {
                "test_id": test_id,
                "test_name": test_name,
                "success": False,
                "validation_passed": False,
                "error": str(e),
                "error_trace": error_trace
            }
    
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
    
    def _validate_test(self, test_case: Dict, response: str, log: str, stats: Dict) -> Dict:
        """Validate test results against success criteria"""
        validation = {
            "overall_pass": True,
            "passed_criteria": [],
            "failed_criteria": [],
            "details": {}
        }
        
        success_criteria = test_case.get("success_criteria", [])
        
        for criterion in success_criteria:
            # Simple string matching for now (can be enhanced with regex, semantic checks, etc.)
            if self._check_criterion(criterion, response, log, stats):
                validation["passed_criteria"].append(criterion)
            else:
                validation["failed_criteria"].append(criterion)
                validation["overall_pass"] = False
        
        # Check must_cite
        if "must_cite" in test_case:
            for required_citation in test_case["must_cite"]:
                if required_citation.lower() in response.lower():
                    validation["passed_criteria"].append(f"Citation: {required_citation}")
                else:
                    validation["failed_criteria"].append(f"Missing citation: {required_citation}")
                    validation["overall_pass"] = False
        
        # Check must_not
        if "must_not" in test_case:
            for forbidden_item in test_case["must_not"]:
                if forbidden_item.lower() in response.lower() or forbidden_item.lower() in log.lower():
                    validation["failed_criteria"].append(f"Forbidden: {forbidden_item}")
                    validation["overall_pass"] = False
                else:
                    validation["passed_criteria"].append(f"Avoided: {forbidden_item}")
        
        # Check validation regex if present
        if "validation" in test_case:
            val_rules = test_case["validation"]
            
            if "regex_must_not_match" in val_rules:
                import re
                for pattern in val_rules["regex_must_not_match"]:
                    if re.search(pattern, response):
                        validation["failed_criteria"].append(f"Regex matched (should not): {pattern}")
                        validation["overall_pass"] = False
            
            if "regex_must_match" in val_rules:
                import re
                for pattern in val_rules["regex_must_match"]:
                    if not re.search(pattern, response):
                        validation["failed_criteria"].append(f"Regex not matched (should): {pattern}")
                        validation["overall_pass"] = False
            
            if "log_must_contain" in val_rules:
                for required_log_item in val_rules["log_must_contain"]:
                    if required_log_item not in log:
                        validation["failed_criteria"].append(f"Log missing: {required_log_item}")
                        validation["overall_pass"] = False
        
        # Check performance threshold
        if "performance_threshold_seconds" in test_case:
            threshold = test_case["performance_threshold_seconds"]
            actual_time = stats.get('execution_times', [0])
            if actual_time and max(actual_time) / 1000 > threshold:
                validation["failed_criteria"].append(f"Performance: exceeded {threshold}s")
                validation["overall_pass"] = False
        
        return validation
    
    def _check_criterion(self, criterion: str, response: str, log: str, stats: Dict) -> bool:
        """Check if a single criterion is met (basic implementation)"""
        # This is a simple heuristic check - can be enhanced
        criterion_lower = criterion.lower()
        
        # Check for keywords in response
        if "no file_id" in criterion_lower:
            import re
            return not re.search(r'[0-9a-f]{24}', response)
        
        if "response time" in criterion_lower or "under" in criterion_lower:
            # Performance check handled separately
            return True
        
        # General keyword matching
        keywords = [word for word in criterion.lower().split() if len(word) > 4]
        if keywords:
            matches = sum(1 for kw in keywords if kw in response.lower())
            return matches >= len(keywords) * 0.5  # At least 50% of keywords
        
        return True  # Default pass for criteria without clear validation logic
    
    def _save_test_output(self, output_file: Path, test_case: Dict, response: str, 
                          log: str, stats: Dict, validation: Dict, duration: float) -> None:
        """Save detailed test output to file"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 100 + "\n")
            f.write(f"TEST CASE {test_case['id']}: {test_case['name']}\n")
            f.write("=" * 100 + "\n\n")
            
            f.write(f"Persona:          {test_case['persona']}\n")
            f.write(f"Category:         {test_case['category']}\n")
            f.write(f"Complexity:       {test_case['complexity']}\n")
            f.write(f"Query:            {test_case.get('query_en', test_case.get('query_da', ''))}\n")
            f.write(f"Architecture:     {', '.join(test_case.get('architecture_focus', []))}\n")
            f.write(f"Expected Routing: {test_case.get('expected_routing', 'N/A')}\n\n")
            
            f.write("EXECUTION SUMMARY\n")
            f.write("-" * 100 + "\n")
            f.write(f"Duration:         {duration:.2f}s\n")
            f.write(f"Tool Calls:       {stats.get('total_tool_calls', 0)}\n")
            f.write(f"Errors:           {stats.get('errors', 0)}\n")
            f.write(f"Validation:       {'PASSED ✅' if validation['overall_pass'] else 'FAILED ❌'}\n\n")
            
            if stats.get('tool_call_types'):
                f.write("Tool Usage:\n")
                for tool, count in stats['tool_call_types'].items():
                    f.write(f"  - {tool}: {count}\n")
                f.write("\n")
            
            f.write("VALIDATION RESULTS\n")
            f.write("-" * 100 + "\n")
            f.write(f"Passed Criteria ({len(validation['passed_criteria'])}):\n")
            for criterion in validation['passed_criteria']:
                f.write(f"  ✅ {criterion}\n")
            f.write(f"\nFailed Criteria ({len(validation['failed_criteria'])}):\n")
            for criterion in validation['failed_criteria']:
                f.write(f"  ❌ {criterion}\n")
            f.write("\n")
            
            f.write("SUCCESS CRITERIA (Expected)\n")
            f.write("-" * 100 + "\n")
            for criterion in test_case.get('success_criteria', []):
                f.write(f"  - {criterion}\n")
            f.write("\n")
            
            f.write("AGENT THINKING (Session Log)\n")
            f.write("-" * 100 + "\n")
            f.write(log)
            f.write("\n\n")
            
            f.write("FINAL RESPONSE\n")
            f.write("-" * 100 + "\n")
            f.write(response)
            f.write("\n\n")
            
            f.write("=" * 100 + "\n")
            f.write("END OF TEST OUTPUT\n")
            f.write("=" * 100 + "\n")
    
    async def run_tests(self, test_ids: List[str]) -> None:
        """Run multiple tests by ID"""
        # Create output directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = Path(__file__).parent / "results" / f"run_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print("\n" + "🚀" * 50)
        print("DEEP AGENTS TEST SUITE - EXECUTION")
        print("🚀" * 50)
        print(f"\nRun Timestamp: {timestamp}")
        print(f"Output Directory: {output_dir}")
        print(f"Tests Selected: {len(test_ids)}")
        print(f"Tender ID: {self.tender_id}\n")
        
        run_id = start_run(f"Test Suite Run - {timestamp}")
        
        # Run each test
        for test_id in test_ids:
            test_case = self.get_test_by_id(test_id)
            
            if not test_case:
                print(f"❌ Test ID not found: {test_id}")
                continue
            
            result = await self.run_single_test(test_case, output_dir)
            self.results.append(result)
            
            # Small delay between tests
            await asyncio.sleep(2)
        
        # Generate summary report
        self._generate_summary_report(output_dir, run_id)
        
        end_run(f"Test suite completed: {len(self.results)} tests")
    
    def _generate_summary_report(self, output_dir: Path, run_id: str) -> None:
        """Generate a summary report of all test results"""
        summary_file = output_dir / "summary_report.txt"
        
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.get("validation_passed", False))
        failed_tests = total_tests - passed_tests
        total_duration = sum(r.get("duration_seconds", 0) for r in self.results)
        total_tool_calls = sum(r.get("tool_calls", 0) for r in self.results)
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("=" * 100 + "\n")
            f.write("DEEP AGENTS TEST SUITE - SUMMARY REPORT\n")
            f.write("=" * 100 + "\n\n")
            
            f.write(f"Run ID:           {run_id}\n")
            f.write(f"Timestamp:        {datetime.now().isoformat()}\n")
            f.write(f"Tender ID:        {self.tender_id}\n")
            f.write(f"Output Directory: {output_dir}\n\n")
            
            f.write("OVERALL RESULTS\n")
            f.write("-" * 100 + "\n")
            f.write(f"Total Tests:      {total_tests}\n")
            f.write(f"Passed:           {passed_tests} ✅\n")
            f.write(f"Failed:           {failed_tests} ❌\n")
            f.write(f"Success Rate:     {(passed_tests/total_tests*100) if total_tests > 0 else 0:.1f}%\n\n")
            
            f.write(f"Total Duration:   {total_duration:.2f}s\n")
            f.write(f"Avg Duration:     {(total_duration/total_tests) if total_tests > 0 else 0:.2f}s\n")
            f.write(f"Total Tool Calls: {total_tool_calls}\n")
            f.write(f"Avg Tool Calls:   {(total_tool_calls/total_tests) if total_tests > 0 else 0:.1f}\n\n")
            
            f.write("TEST RESULTS BREAKDOWN\n")
            f.write("-" * 100 + "\n\n")
            
            # Group by category
            by_category = {}
            for result in self.results:
                test_case = self.get_test_by_id(result["test_id"])
                category = test_case["category"] if test_case else "Unknown"
                if category not in by_category:
                    by_category[category] = []
                by_category[category].append(result)
            
            for category, results in sorted(by_category.items()):
                f.write(f"\n{category}\n")
                f.write("-" * 100 + "\n")
                for result in results:
                    status = "✅ PASS" if result.get("validation_passed") else "❌ FAIL"
                    f.write(f"{status}  {result['test_id']:12}  {result['test_name']:50}  ")
                    f.write(f"{result.get('duration_seconds', 0):.1f}s  ")
                    f.write(f"{result.get('tool_calls', 0)} tools\n")
                    
                    if not result.get("validation_passed") and "validation_results" in result:
                        failed = result["validation_results"].get("failed_criteria", [])
                        if failed:
                            f.write(f"     Failed: {', '.join(failed[:3])}\n")
            
            f.write("\n" + "=" * 100 + "\n")
            f.write("END OF SUMMARY REPORT\n")
            f.write("=" * 100 + "\n")
        
        # Console summary
        print("\n" + "=" * 100)
        print("TEST SUITE COMPLETED")
        print("=" * 100)
        print(f"Total Tests:  {total_tests}")
        print(f"Passed:       {passed_tests} ✅")
        print(f"Failed:       {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests*100) if total_tests > 0 else 0:.1f}%")
        print(f"Duration:     {total_duration:.2f}s")
        print(f"Tool Calls:   {total_tool_calls}")
        print("=" * 100)
        print(f"\n📄 Summary Report: {summary_file}")
        print(f"📁 Test Outputs:   {output_dir}")
        print("=" * 100 + "\n")


async def main():
    """Main entry point for test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Deep Agents Test Runner")
    parser.add_argument("test_ids", nargs="*", help="Test IDs to run (e.g., L1-01 L2-01)")
    parser.add_argument("--list", action="store_true", help="List all available tests")
    parser.add_argument("--category", type=str, help="Filter by category when listing")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--complexity", type=str, choices=["Simple", "Moderate", "Advanced", "Research+"], 
                       help="Run all tests of a specific complexity")
    
    args = parser.parse_args()
    
    # Load environment
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
    runner = TestRunner(mongo_client, tender_id)
    
    # List tests if requested
    if args.list:
        runner.list_tests(category=args.category)
        return
    
    # Determine which tests to run
    test_ids_to_run = []
    
    if args.all:
        test_ids_to_run = [t["id"] for t in runner.test_cases["test_cases"]]
    elif args.complexity:
        test_ids_to_run = [t["id"] for t in runner.test_cases["test_cases"] 
                          if t["complexity"] == args.complexity]
    elif args.test_ids:
        test_ids_to_run = args.test_ids
    else:
        print("❌ No tests specified. Use test IDs, --all, --complexity, or --list")
        parser.print_help()
        sys.exit(1)
    
    # Run tests
    await runner.run_tests(test_ids_to_run)


if __name__ == "__main__":
    asyncio.run(main())

