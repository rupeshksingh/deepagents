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
    get_session_stats,
    get_unified_logger,
)


async def run_query(query: str, tender_id: str) -> dict:
    load_dotenv()
    mongodb_uri = os.getenv("MONGODB_URL")
    if not mongodb_uri:
        print("❌ MONGODB_URL not found in environment")
        return {"success": False, "response": "Missing MONGODB_URL"}

    # Initialize logging
    run_id = start_run(f"CLI Test Run - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    mongo_client = MongoClient(mongodb_uri)
    agent = ReactAgent(mongo_client, org_id=1)

    thread_id = f"test_thread_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("\n" + "=" * 70)
    print("🔍 USER QUERY:")
    print(f"   {query}")
    print(f"📋 Tender ID: {tender_id}")
    print(f"🔖 Thread ID: {thread_id}")
    print(f"🆔 Run ID: {run_id}")
    print("=" * 70)

    # Run the agent
    result = await agent.chat_sync(
        user_query=query, thread_id=thread_id, tender_id=tender_id
    )

    response_text = result.get("response", "No response")
    duration_ms = result.get("processing_time_ms", 0)
    
    # Get session ID from result metadata if available
    session_id = result.get("session_id")

    # Get tool call statistics (session-specific if available)
    if session_id:
        stats = get_session_stats(session_id)
    else:
        stats = get_tool_call_stats()  # Fallback to cumulative stats
    
    # End run and get summary
    end_run(f"Completed query in {duration_ms/1000:.2f}s")

    # Attempt to discover the latest session narrative log
    session_log_path = None
    try:
        logs_dir = os.path.join(os.getcwd(), "logs")
        # Pick the most recent session_<id>.log
        session_logs = [
            os.path.join(logs_dir, f)
            for f in os.listdir(logs_dir)
            if f.startswith("session_") and f.endswith(".log")
        ]
        session_logs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        session_log_path = session_logs[0] if session_logs else None
    except Exception:
        session_log_path = None

    # Save consolidated output
    out_file = f"run_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("BID MANAGEMENT AGENT - RUN OUTPUT\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Run ID:      {run_id}\n")
        f.write(f"Thread ID:   {thread_id}\n")
        f.write(f"Tender ID:   {tender_id}\n")
        f.write(f"Timestamp:   {datetime.now().isoformat()}\n")
        f.write(f"Duration:    {duration_ms/1000:.2f}s\n")
        f.write(f"Success:     {result.get('success', False)}\n")
        
        # Add statistics
        f.write("\n" + "=" * 70 + "\n")
        f.write("EXECUTION STATISTICS\n")
        f.write("=" * 70 + "\n\n")
        if "error" not in stats:
            f.write(f"Total Tool Calls:     {stats.get('total_tool_calls', 0)}\n")
            f.write(f"Tool Call Errors:     {stats.get('errors', 0)}\n")
            f.write(f"Queries Processed:    {stats.get('queries_processed', 0)}\n")
            if stats.get('execution_times'):
                f.write(f"Avg Execution Time:   {stats.get('avg_execution_time_ms', 0):.2f}ms\n")
                f.write(f"Max Execution Time:   {stats.get('max_execution_time_ms', 0):.2f}ms\n")
                f.write(f"Min Execution Time:   {stats.get('min_execution_time_ms', 0):.2f}ms\n")
            f.write("\nTool Usage Breakdown:\n")
            for tool, count in stats.get('tool_call_types', {}).items():
                f.write(f"  - {tool}: {count}\n")
        else:
            f.write(f"(Could not retrieve stats: {stats.get('error')})\n")
        
        f.write("\n" + "=" * 70 + "\n")
        f.write("AGENT THINKING (Narrative)\n")
        f.write("=" * 70 + "\n\n")
        if session_log_path and os.path.exists(session_log_path):
            try:
                with open(session_log_path, "r", encoding="utf-8") as s:
                    f.write(s.read())
            except Exception:
                f.write("(Could not read session narrative log)\n")
        else:
            f.write("(No session narrative log found)\n")
        
        f.write("\n" + "=" * 70 + "\n")
        f.write("FINAL RESPONSE\n")
        f.write("=" * 70 + "\n\n")
        f.write(response_text)
        f.write("\n\n" + "=" * 70 + "\n")
        f.write("END OF OUTPUT\n")
        f.write("=" * 70 + "\n")

    print("\n" + "=" * 70)
    print("📊 EXECUTION SUMMARY")
    print("=" * 70)
    print(f"✓ Output File:    {out_file}")
    print(f"✓ Session Log:    {session_log_path if session_log_path else 'N/A'}")
    print(f"✓ Success:        {result.get('success')}")
    print(f"✓ Duration:       {duration_ms/1000:.2f}s")
    if "error" not in stats:
        print(f"✓ Tool Calls:     {stats.get('total_tool_calls', 0)}")
        print(f"✓ Errors:         {stats.get('errors', 0)}")
    print("=" * 70)

    print("\n📝 RESPONSE PREVIEW:")
    print("-" * 70)
    print(response_text[:500])
    if len(response_text) > 500:
        print(f"\n... ({len(response_text) - 500} more characters)")
    print("-" * 70)
    
    print("\n💡 Logs available in:")
    print(f"   - Main log:      logs/tool_calls.log")
    print(f"   - Narrative log: logs/narrative.log")
    if session_log_path:
        print(f"   - Session log:   {session_log_path}")
    
    return result


if __name__ == "__main__":
    # Check if query provided via args or use default
    query = " ".join(sys.argv[1:]).strip()
    
    # Load tender_id from environment
    load_dotenv()
    tender_id = os.getenv("TENDER_ID")
    
    if not query:
        print("\n" + "⚠" * 35)
        print("No query provided. Using default test query...")
        print("⚠" * 35)
        query = "Use the advanced_tender_analyst subagent to list all available context files using the ls tool and then read the cluster_id.txt file. Report exactly what files are visible to the subagent and what the cluster_id value is."
    
    if not tender_id:
        print("\n" + "❌" * 35)
        print("ERROR: TENDER_ID not found in environment variables!")
        print("Please set TENDER_ID in your .env file or as an environment variable.")
        print("Example: export TENDER_ID=68c99b8a10844521ad051544")
        print("❌" * 35)
        sys.exit(1)
    
    print("\n" + "🚀" * 35)
    print("STARTING BID MANAGEMENT AGENT TEST")
    print("🚀" * 35)
    
    asyncio.run(run_query(query, tender_id))
