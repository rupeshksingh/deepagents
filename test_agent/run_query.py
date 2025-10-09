import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

# Ensure we can import react_agent from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from react_agent import ReactAgent


async def run_query(query: str, tender_id: str) -> dict:
    load_dotenv()
    mongodb_uri = os.getenv("MONGODB_URL")
    if not mongodb_uri:
        print("❌ MONGODB_URL not found in environment")
        return {"success": False, "response": "Missing MONGODB_URL"}

    mongo_client = MongoClient(mongodb_uri)
    agent = ReactAgent(mongo_client, org_id=1)

    thread_id = f"test_thread_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("\n" + "=" * 70)
    print("🔍 USER QUERY:")
    print(f"   {query}")
    print("=" * 70)

    # Run the agent
    result = await agent.chat_sync(
        user_query=query, thread_id=thread_id, tender_id=tender_id
    )

    response_text = result.get("response", "No response")
    duration_ms = result.get("processing_time_ms", 0)

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
        f.write("DANISH TENDER ANALYSIS AGENT - RUN OUTPUT\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Thread ID: {thread_id}\n")
        f.write(f"Tender ID: {tender_id}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Duration: {duration_ms/1000:.2f}s\n")
        f.write(f"Success: {result.get('success', False)}\n")
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
    print("OUTPUT FILE:", out_file)
    print("SUCCESS:", result.get("success"))
    print("DURATION(s):", f"{duration_ms/1000:.2f}")
    print("=" * 70)

    print("\nRESPONSE PREVIEW:\n", response_text[:600])
    return result


if __name__ == "__main__":
    query = (
        " ".join(sys.argv[1:]).strip()
        or "Extract all mandatory obligations related to persondata and it‑security and put them into a 5‑column table (Clause | Obligation | Who | Evidence | Source)."
    )
    tender_id = os.getenv("TENDER_ID", "68c99b8a10844521ad051544")
    asyncio.run(run_query(query, tender_id))
