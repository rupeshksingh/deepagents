"""
Comprehensive Test Suite for Bid Management Agent
Executes all test cases from Level 0-4 and saves complete results to a single file.
"""

import os
import sys
import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

# Ensure we can import react_agent from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from react_agent import ReactAgent
from src.deepagents.logging_utils import (
    start_run,
    end_run,
    get_tool_call_stats,
    get_unified_logger,
)

# Test cases organized by level
TEST_CASES = {
    "Level 0: Initialization and Context Awareness": [
        {
            "id": "0.1",
            "name": "Context Verification",
            "query": "Hvad handler dette udbud (02.15) om, og hvilke hoveddokumenter har du adgang til?",
            "english": "What is this tender (02.15) about, and what main documents do you have access to?",
        }
    ],
    "Level 1: Simple Arbitration - Direct Tool Use": [
        {
            "id": "1.1",
            "name": "Known-Item Search (Specific Value)",
            "query": "Hvor stor en procentdel (SKI's andel) skal leverandøren betale til SKI af omsætningen?",
            "english": "What percentage fee (SKI's share) must the supplier pay to SKI of the turnover?",
        },
        {
            "id": "1.2",
            "name": "Definition Lookup",
            "query": "Hvad er definitionen af 'Arbejdsdag' i rammeaftalen?",
            "english": "What is the definition of 'Working Day' in the framework agreement?",
        }
    ],
    "Level 2: Complex Analysis & Simple Drafting": [
        {
            "id": "2.1",
            "name": "Analyzing Procedures and Requirements (Analyst)",
            "query": "Beskriv detaljeret processen for 'Direkte tildeling'. Hvilke trin (Trin 1-6) skal kunden følge ifølge Bilag B, og hvilken dokumentation kræves?",
            "english": "Describe the process for 'Direct award' in detail. What steps (Trin 1-6) must the customer follow according to Bilag B, and what documentation is required?",
        },
        {
            "id": "2.2",
            "name": "Cross-Document Consequence Analysis (Analyst)",
            "query": "Hvad er de fulde konsekvenser, hvis en leverandør gentagne gange undlader at rapportere omsætning rettidigt? Inkluder bod, renter og risiko for ophævelse.",
            "english": "What are the full consequences if a supplier repeatedly fails to report turnover on time? Include penalties (bod), interest, and risk of termination.",
        },
        {
            "id": "2.3",
            "name": "Simple Drafting (Writer)",
            "query": "Skriv en kort, professionel introduktion til vores virksomhed som leverandør på rammeaftale 02.15 It-rådgivning.",
            "english": "Write a short, professional introduction to our company as a supplier on framework agreement 02.15 IT Consulting.",
        }
    ],
    "Level 3: Sequential Workflow (Analysis → Drafting)": [
        {
            "id": "3.1",
            "name": "Research and Draft Compliance Response",
            "query": "Vi skal svare på kravene vedrørende 'CSR' (Bilag E). Undersøg hvilke internationale principper (f.eks. FN's Global Compact, OECD) der henvises til i Afsnit 2, og skriv derefter et udkast til vores erklæring om overholdelse på dansk.",
            "english": "We need to respond to the requirements regarding 'CSR' (Bilag E). Investigate which international principles (e.g., UN Global Compact, OECD) are referred to in Section 2, and then write a draft of our compliance statement in Danish.",
        }
    ],
    "Level 4: Parallel Execution": [
        {
            "id": "4.1",
            "name": "Comprehensive Risk Analysis Across Multiple Domains",
            "query": "Identificer de væsentligste risici for os som leverandør i denne rammeaftale. Opdel analysen i tre områder: (A) Misligholdelse og bod (Rammeaftale/Bilag C), (B) Krav til CSR (Bilag E), og (C) Regler omkring revision (Bilag D).",
            "english": "Identify the most significant risks for us as a supplier in this framework agreement. Divide the analysis into three areas: (A) Breach and penalties (Rammeaftale/Bilag C), (B) Requirements for CSR (Bilag E), and (C) Rules regarding auditing (Bilag D).",
        }
    ]
}


async def run_single_test(agent: ReactAgent, test_case: dict, tender_id: str, output_file) -> dict:
    """Run a single test case and write results to file."""
    test_id = test_case["id"]
    test_name = test_case["name"]
    query = test_case["query"]
    english = test_case.get("english", "")
    
    thread_id = f"test_{test_id.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Write test header
    output_file.write("\n" + "=" * 100 + "\n")
    output_file.write(f"TEST CASE {test_id}: {test_name}\n")
    output_file.write("=" * 100 + "\n\n")
    output_file.write(f"Query (Danish): {query}\n")
    if english:
        output_file.write(f"Query (English): {english}\n")
    output_file.write(f"\nThread ID: {thread_id}\n")
    output_file.write(f"Tender ID: {tender_id}\n")
    output_file.write(f"Timestamp: {datetime.now().isoformat()}\n")
    output_file.write("\n" + "-" * 100 + "\n")
    output_file.write("EXECUTION\n")
    output_file.write("-" * 100 + "\n\n")
    
    # Console output
    print(f"\n{'=' * 100}")
    print(f"Running Test {test_id}: {test_name}")
    print(f"{'=' * 100}")
    print(f"Query: {query}")
    
    # Run the test
    try:
        result = await agent.chat_sync(
            user_query=query,
            thread_id=thread_id,
            tender_id=tender_id
        )
        
        response_text = result.get("response", "No response")
        duration_ms = result.get("processing_time_ms", 0)
        success = result.get("success", False)
        
        # Get statistics
        stats = get_tool_call_stats()
        
        # Get session log
        session_log_path = None
        session_log_content = ""
        try:
            logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            session_logs = [
                os.path.join(logs_dir, f)
                for f in os.listdir(logs_dir)
                if f.startswith("session_") and f.endswith(".log")
            ]
            session_logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            if session_logs:
                session_log_path = session_logs[0]
                with open(session_log_path, "r", encoding="utf-8") as s:
                    session_log_content = s.read()
        except Exception as e:
            session_log_content = f"(Could not read session log: {e})"
        
        # Write execution summary
        output_file.write("EXECUTION SUMMARY\n")
        output_file.write("-" * 100 + "\n")
        output_file.write(f"Success: {success}\n")
        output_file.write(f"Duration: {duration_ms/1000:.2f}s\n")
        output_file.write(f"Processing Time: {duration_ms}ms\n")
        
        if "error" not in stats:
            output_file.write(f"Total Tool Calls: {stats.get('total_tool_calls', 0)}\n")
            output_file.write(f"Tool Call Errors: {stats.get('errors', 0)}\n")
            output_file.write(f"Queries Processed: {stats.get('queries_processed', 0)}\n")
            
            if stats.get('execution_times'):
                output_file.write(f"Avg Execution Time: {stats.get('avg_execution_time_ms', 0):.2f}ms\n")
                output_file.write(f"Max Execution Time: {stats.get('max_execution_time_ms', 0):.2f}ms\n")
                output_file.write(f"Min Execution Time: {stats.get('min_execution_time_ms', 0):.2f}ms\n")
            
            output_file.write("\nTool Usage Breakdown:\n")
            for tool, count in stats.get('tool_call_types', {}).items():
                output_file.write(f"  - {tool}: {count} calls\n")
        else:
            output_file.write(f"Statistics Error: {stats.get('error')}\n")
        
        # Write agent thinking (narrative log)
        output_file.write("\n" + "-" * 100 + "\n")
        output_file.write("AGENT THINKING (Step-by-Step Trace)\n")
        output_file.write("-" * 100 + "\n\n")
        output_file.write(session_log_content)
        
        # Write final response
        output_file.write("\n" + "-" * 100 + "\n")
        output_file.write("FINAL RESPONSE\n")
        output_file.write("-" * 100 + "\n\n")
        output_file.write(response_text)  # Complete response, no truncation
        output_file.write("\n\n")
        
        # Console output
        print(f"✓ Test {test_id} completed in {duration_ms/1000:.2f}s")
        print(f"  Tool Calls: {stats.get('total_tool_calls', 0)}, Errors: {stats.get('errors', 0)}")
        print(f"  Response Length: {len(response_text)} characters")
        
        return {
            "test_id": test_id,
            "success": success,
            "duration_ms": duration_ms,
            "tool_calls": stats.get('total_tool_calls', 0),
            "errors": stats.get('errors', 0),
        }
        
    except Exception as e:
        error_msg = f"ERROR: {str(e)}"
        output_file.write(f"\n{error_msg}\n\n")
        print(f"✗ Test {test_id} failed: {e}")
        
        import traceback
        output_file.write("TRACEBACK:\n")
        output_file.write(traceback.format_exc())
        output_file.write("\n\n")
        
        return {
            "test_id": test_id,
            "success": False,
            "error": str(e),
        }


async def run_all_tests():
    """Run all test cases and save results to a single file."""
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URL")
    tender_id = os.getenv("TENDER_ID")
    
    if not mongodb_uri:
        print("❌ MONGODB_URL not found in environment")
        return
    
    if not tender_id:
        print("❌ TENDER_ID not found in environment")
        return
    
    # Initialize agent
    run_id = start_run(f"Complete Test Suite - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mongo_client = MongoClient(mongodb_uri)
    agent = ReactAgent(mongo_client, org_id=1)
    
    # Create output file
    output_filename = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    print("\n" + "🚀" * 50)
    print("BID MANAGEMENT AGENT - COMPREHENSIVE TEST SUITE")
    print("🚀" * 50)
    print(f"\nRun ID: {run_id}")
    print(f"Tender ID: {tender_id}")
    print(f"Output File: {output_filename}")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    test_results = []
    
    with open(output_filename, "w", encoding="utf-8") as output_file:
        # Write header
        output_file.write("=" * 100 + "\n")
        output_file.write("BID MANAGEMENT AGENT - COMPREHENSIVE TEST RESULTS\n")
        output_file.write("=" * 100 + "\n\n")
        output_file.write(f"Run ID: {run_id}\n")
        output_file.write(f"Tender ID: {tender_id}\n")
        output_file.write(f"Timestamp: {datetime.now().isoformat()}\n")
        output_file.write(f"Test Framework: LangChain Deep Agents\n")
        output_file.write(f"Agent Architecture: Main Agent + Subagents (document-analyzer, web-researcher)\n")
        output_file.write("\n")
        
        # Run all test cases
        for level_name, test_cases in TEST_CASES.items():
            output_file.write("\n" + "=" * 100 + "\n")
            output_file.write(f"{level_name}\n")
            output_file.write("=" * 100 + "\n")
            
            print(f"\n{'=' * 100}")
            print(f"{level_name}")
            print(f"{'=' * 100}")
            
            for test_case in test_cases:
                result = await run_single_test(agent, test_case, tender_id, output_file)
                test_results.append(result)
                
                # Small delay between tests
                await asyncio.sleep(2)
        
        # Write summary
        output_file.write("\n" + "=" * 100 + "\n")
        output_file.write("TEST SUITE SUMMARY\n")
        output_file.write("=" * 100 + "\n\n")
        
        total_tests = len(test_results)
        successful_tests = sum(1 for r in test_results if r.get("success", False))
        failed_tests = total_tests - successful_tests
        total_duration = sum(r.get("duration_ms", 0) for r in test_results)
        total_tool_calls = sum(r.get("tool_calls", 0) for r in test_results)
        total_errors = sum(r.get("errors", 0) for r in test_results)
        
        output_file.write(f"Total Tests: {total_tests}\n")
        output_file.write(f"Successful: {successful_tests}\n")
        output_file.write(f"Failed: {failed_tests}\n")
        output_file.write(f"Success Rate: {(successful_tests/total_tests*100):.1f}%\n")
        output_file.write(f"\nTotal Execution Time: {total_duration/1000:.2f}s\n")
        output_file.write(f"Average Test Duration: {total_duration/total_tests/1000:.2f}s\n")
        output_file.write(f"\nTotal Tool Calls: {total_tool_calls}\n")
        output_file.write(f"Average Tool Calls per Test: {total_tool_calls/total_tests:.1f}\n")
        output_file.write(f"Total Tool Errors: {total_errors}\n")
        
        output_file.write("\n\nDetailed Results:\n")
        output_file.write("-" * 100 + "\n")
        for result in test_results:
            status = "✓ PASS" if result.get("success") else "✗ FAIL"
            test_id = result["test_id"]
            duration = result.get("duration_ms", 0) / 1000
            tool_calls = result.get("tool_calls", 0)
            errors = result.get("errors", 0)
            
            output_file.write(f"{status} Test {test_id}: {duration:.2f}s, {tool_calls} tools, {errors} errors\n")
            if "error" in result:
                output_file.write(f"      Error: {result['error']}\n")
        
        output_file.write("\n" + "=" * 100 + "\n")
        output_file.write(f"End Time: {datetime.now().isoformat()}\n")
        output_file.write("=" * 100 + "\n")
    
    end_run(f"Test suite completed: {successful_tests}/{total_tests} tests passed")
    
    # Console summary
    print("\n" + "=" * 100)
    print("TEST SUITE COMPLETED")
    print("=" * 100)
    print(f"Output File: {output_filename}")
    print(f"Total Tests: {total_tests}")
    print(f"Successful: {successful_tests}")
    print(f"Failed: {failed_tests}")
    print(f"Success Rate: {(successful_tests/total_tests*100):.1f}%")
    print(f"Total Duration: {total_duration/1000:.2f}s")
    print(f"Total Tool Calls: {total_tool_calls}")
    print("=" * 100)
    
    print(f"\n📄 Complete results saved to: {output_filename}")
    print(f"📊 Review the file for full agent traces and responses")


if __name__ == "__main__":
    asyncio.run(run_all_tests())

