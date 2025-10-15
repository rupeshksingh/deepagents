"""
Test script for ReactAgent with clean console output showing agent's thinking process.
"""

import asyncio
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
import logging  # noqa: F401
import json  # noqa: F401

# Add parent directory to path to import react_agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from react_agent import ReactAgent  # noqa: E402

# Suppress ALL noisy loggers completely
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("root").setLevel(logging.ERROR)
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("anthropic").setLevel(logging.ERROR)
logging.getLogger("react_agent").setLevel(logging.ERROR)


class AgentThinkingMonitor:
    """Monitor agent actions and display clean thinking process."""

    def __init__(self):
        self.step_counter = 0
        self.current_phase = "Initializing"

    def parse_and_display(self, log_message: str):
        """Parse log message and display thinking step."""
        try:
            # Only process if it contains JSON-like structure
            if "{" not in log_message:
                return

            # Try to extract the JSON part
            json_start = log_message.find("{")
            json_str = log_message[json_start:]
            data = json.loads(json_str)

            event_type = data.get("event")

            if event_type == "SESSION_START":
                print(f"\n🧠 Agent received query and loading context...")

            elif event_type == "TOOL_CALL_START":
                self.step_counter += 1
                tool_name = data.get("tool_name", "")
                kwargs = data.get("kwargs", {})

                print(f"\n{'─'*70}")
                print(f"🤔 STEP {self.step_counter}: ", end="")

                if tool_name == "search_tender_corpus":
                    query = kwargs.get("query", "")
                    file_ids = kwargs.get("file_ids")
                    print(f"Searching tender documents")
                    print(f"   💭 Thinking: Let me search for '{query}'")
                    if file_ids:
                        print(f"   🎯 Focusing on {len(file_ids)} specific file(s)")
                    else:
                        print(f"   🌐 Searching across all tender files")

                elif tool_name == "retrieve_full_document":
                    file_id = kwargs.get("file_id", "")
                    print(f"Reading full document")
                    print(
                        f"   💭 Thinking: I need the complete content of this document"
                    )
                    print(f"   📄 File ID: {file_id}...")

                elif tool_name == "web_search":
                    query = kwargs.get("query", "")
                    print(f"Searching the web")
                    print(f"   💭 Thinking: Let me find external information")
                    print(f"   🔍 Query: '{query}'")

                elif tool_name == "request_human_input":
                    print(f"Requesting human input")
                    print(f"   💭 Thinking: I need clarification from the user")

                elif tool_name == "task":
                    agent_type = kwargs.get("agent_type", "")
                    description = kwargs.get("description", "")
                    print(f"Delegating to subagent: {agent_type}")
                    print(f"   💭 Thinking: This requires specialized analysis")
                    print(f"   📋 Task: {description}")

                elif tool_name == "read_file":
                    target = kwargs.get("target_file", "")
                    print(f"Reading context file")
                    print(f"   📂 File: {target}")

                else:
                    print(f"Using tool: {tool_name}")

            elif event_type == "TOOL_CALL_END":
                result = data.get("result", {})
                exec_time = data.get("execution_time_ms", 0)

                # Brief confirmation (don't print full results)
                if isinstance(result, dict):
                    if "error" in result:
                        print(f"   ❌ Error: {result.get('error', 'Unknown')}")
                    else:
                        print(f"   ✓ Completed in {exec_time/1000:.1f}s")
                else:
                    print(f"   ✓ Completed in {exec_time/1000:.1f}s")

            elif event_type == "SESSION_END":
                print(f"\n{'─'*70}")
                print(f"💡 Synthesizing final response...")

        except json.JSONDecodeError:
            pass
        except Exception as e:
            # Silently ignore parsing errors
            pass


class CleanLogHandler(logging.Handler):
    """Filter and format logs to show only agent thinking."""

    def __init__(self, monitor: AgentThinkingMonitor):
        super().__init__()
        self.monitor = monitor

    def emit(self, record):
        try:
            msg = record.getMessage()
            # Only process deepagents_unified logs with event data
            if record.name == "deepagents_unified":
                self.monitor.parse_and_display(msg)
        except Exception:
            pass


# Global monitor instance
monitor = AgentThinkingMonitor()

# Configure logging
clean_handler = CleanLogHandler(monitor)
clean_handler.setLevel(logging.INFO)

# Configure deepagents logger
deepagents_logger = logging.getLogger("deepagents_unified")
deepagents_logger.handlers = []  # Clear existing handlers
deepagents_logger.addHandler(clean_handler)
deepagents_logger.setLevel(logging.INFO)
deepagents_logger.propagate = False


async def test_basic_functionality():
    """Test basic agent functionality with enhanced console output."""

    print("\n" + "=" * 70)
    print("🧪 DANISH TENDER ANALYSIS AGENT - TEST")
    print("=" * 70)
    print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    load_dotenv()

    mongodb_uri = os.getenv("MONGODB_URL")
    if not mongodb_uri:
        print("❌ Error: MONGODB_URL not found in environment variables")
        return False

    mongo_client = MongoClient(mongodb_uri)

    try:
        print("\n🚀 Initializing Agent...")
        agent = ReactAgent(mongo_client, org_id=1)
        print("✅ Agent initialized successfully\n")

        # Generate unique thread ID for this test run
        thread_id = f"test_thread_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tender_id = "68c99b8a10844521ad051544"

        print(f"📝 Thread ID: {thread_id}")
        print(f"📄 Tender ID: {tender_id}")

        # Test query about corporate social responsibility
        query1 = "What are the sub‑areas in “It‑sikkerhed, business continuity og it‑compliance”"

        print("\n" + "=" * 70)
        print(f"🔍 USER QUERY:")
        print(f"   {query1}")
        print("=" * 70)

        start_time = datetime.now()

        result1 = await agent.chat_sync(
            user_query=query1, thread_id=thread_id, tender_id=tender_id
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print("\n" + "=" * 70)
        print(f"✅ AGENT COMPLETED")
        print(f"⏱️  Total Time: {duration:.2f}s")
        print("=" * 70)

        # Show response preview
        response_text = result1.get("response", "No response")
        print("\n📝 RESPONSE PREVIEW :")
        print("─" * 70)
        print(response_text)
        print("─" * 70)

        # Save full response to file
        output_file = f"test_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write("DANISH TENDER ANALYSIS AGENT - TEST OUTPUT\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Thread ID: {thread_id}\n")
            f.write(f"Tender ID: {tender_id}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Duration: {duration:.2f}s\n")
            f.write(f"Success: {result1.get('success', False)}\n")
            f.write("\n" + "=" * 70 + "\n")
            f.write("USER QUERY:\n")
            f.write("=" * 70 + "\n")
            f.write(f"{query1}\n")
            f.write("\n" + "=" * 70 + "\n")
            f.write("AGENT RESPONSE:\n")
            f.write("=" * 70 + "\n\n")
            f.write(response_text)
            f.write("\n\n" + "=" * 70 + "\n")
            f.write("END OF OUTPUT\n")
            f.write("=" * 70 + "\n")

        print(f"\n💾 Full response saved to: {output_file}")
        print("\n✅ Test completed successfully!")

        return True

    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Main entry point."""
    print("\n" + "=" * 70)
    print("🧪 Basic Agent Test Suite")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    success = await test_basic_functionality()

    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    if success:
        print("Basic Tests: ✅ PASS")
        print("✅ All tests passed!")
    else:
        print("Basic Tests: ❌ FAIL")
        print("❌ Some tests failed. Check output above.")
    print("=" * 70 + "\n")

    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
