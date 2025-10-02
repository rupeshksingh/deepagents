"""
Tender Analysis React Agent

A sophisticated React agent built using the Deep Agents library for comprehensive 
tender analysis and document processing. This agent provides intelligent analysis 
of tender documents, maintains conversation context, and uses multi-agent architecture 
for specialized tasks.
"""

import os
import logging
import time
from typing import Dict, List, Optional, Any
import json

# Defer ChatOpenAI import to avoid Pydantic issues
# from langchain_openai import ChatOpenAI
from prompts import (
                TENDER_ANALYSIS_SYSTEM_PROMPT,
                DOCUMENT_ANALYZER_PROMPT,
                RESEARCH_AGENT_PROMPT,
                COMPLIANCE_CHECKER_PROMPT
            )

from pymongo import MongoClient
from dotenv import load_dotenv
from src.deepagents.graph import async_create_deep_agent
from src.deepagents.logging import log_query_start, log_query_end, get_tool_logger, start_run, end_run, set_agent_context
from langgraph.checkpoint.memory import MemorySaver
from tools import REACT_TOOLS

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TenderAnalysisAgent:
    """
    A React agent for tender analysis that uses the deep agents library.
    This agent can analyze tender documents, search for relevant information,
    and maintain conversation context for iterative queries.
    """
    
    def __init__(self, org_id: int = 1):
        self.org_id = org_id
        try:
            mongodb_uri = os.environ.get("MONGODB_URL")
            self.mongo_client = MongoClient(mongodb_uri)
        except Exception as e:
            logger.warning(f"MongoDB connection failed: {e}")
            self.mongo_client = None
        
        self.current_tender_id = None
        self.conversation_history = []
        self.checkpointer = MemorySaver()
        # Defer model initialization to avoid Pydantic issues
        # self.model = ChatOpenAI(model="gpt-5")
        self.model = None
        self.tool_logger = get_tool_logger()
        
        # Initialize run tracking
        self.current_run_id = None
        self.run_start_time = None
        
        # Set agent context for this instance
        set_agent_context("react_agent", f"react_agent_{org_id}")
        
        self.agent = self._create_agent()
    
    def _create_agent(self):
        """Create the deep agent graph with custom tools and subagents."""
        try:
            from langchain_openai import ChatOpenAI
            self.model = ChatOpenAI(model="gpt-5")
            
            tools = REACT_TOOLS

            subagents = [
                {
                    "name": "document-analyzer",
                    "description": "Specialized agent for analyzing tender documents, extracting key information, and identifying compliance requirements.",
                    "prompt": DOCUMENT_ANALYZER_PROMPT,
                    "tools": tools
                },
                {
                    "name": "research-agent", 
                    "description": "Specialized agent for conducting research on tender-related topics, market analysis, and competitive intelligence.",
                    "prompt": RESEARCH_AGENT_PROMPT,
                    "tools": tools
                },
                {
                    "name": "compliance-checker",
                    "description": "Specialized agent for checking compliance requirements, identifying gaps, and ensuring tender submissions meet all criteria.",
                    "prompt": COMPLIANCE_CHECKER_PROMPT,
                    "tools": tools
                }
            ]

            agent_graph = async_create_deep_agent(
                tools=tools,
                instructions=TENDER_ANALYSIS_SYSTEM_PROMPT,
                subagents=subagents,
                model=self.model,
                checkpointer=self.checkpointer
            )
            
            configured_agent = agent_graph.with_config({
                "recursion_limit": 1000,
                "max_execution_time": 300
            })
            
            logger.info("Successfully created deep agent graph with subagents")
            return configured_agent
            
        except Exception as e:
            logger.error(f"Failed to create deep agent graph: {e}")
            return None
    
    async def chat(self, user_query: str, tender_id: Optional[str] = None) -> str:
        """
        Main chat interface for the tender analysis agent with tool monitoring.
        
        Args:
            user_query: The user's query
            tender_id: Optional tender ID to set as context
        
        Returns:
            Agent response
        """
        # Start query logging
        session_id = log_query_start(user_query)
        
        try:
            if self.agent is None:
                return "Agent is not properly initialized. Please check your configuration."
            
            if tender_id:
                self.current_tender_id = tender_id
                logger.info(f"Set tender ID: {tender_id}")
            
            self.conversation_history.append({
                "role": "user",
                "content": user_query,
                "tender_id": self.current_tender_id
            })
            
            if self.current_tender_id:
                enhanced_query = f"Tender ID: {self.current_tender_id}\n\nUser Query: {user_query}"
            else:
                enhanced_query = user_query
            
            messages = []
            if self.conversation_history:
                recent_history = self.conversation_history[-10:]
                for msg in recent_history:
                    if msg["role"] == "user":
                        messages.append({"role": "user", "content": msg["content"]})
                    elif msg["role"] == "assistant":
                        messages.append({"role": "assistant", "content": msg["content"]})
            
            messages.append({"role": "user", "content": enhanced_query})
            
            config = {
                "configurable": {
                    "thread_id": f"tender_analysis_{self.org_id}_{self.current_tender_id or 'general'}"
                }
            }
            
            response = await self.agent.ainvoke({
                "messages": messages
            }, config=config)
            
            if isinstance(response, dict) and "messages" in response:
                last_message = response["messages"][-1]
                if isinstance(last_message, dict):
                    agent_response = last_message.get("content", str(response))
                else:
                    agent_response = last_message.content
            else:
                agent_response = str(response)
            
            self.conversation_history.append({
                "role": "assistant",
                "content": agent_response,
                "tender_id": self.current_tender_id
            })
            
            logger.info("Successfully processed query with agent graph")
            
            # End query logging
            log_query_end(session_id, agent_response)
            
            return agent_response
            
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            error_response = f"I apologize, but I encountered an error while processing your request: {str(e)}"
            
            # Log query end with error
            log_query_end(session_id, error_response)
            
            return error_response
    
    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get the conversation history."""
        return self.conversation_history
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    def set_tender_id(self, tender_id: str):
        """Set the current tender ID."""
        self.current_tender_id = tender_id
        logger.info(f"Tender ID set to: {tender_id}")
    
    def get_current_tender_id(self) -> Optional[str]:
        """Get the current tender ID."""
        return self.current_tender_id
    
    def get_tool_call_stats(self) -> Dict[str, Any]:
        """Get tool call statistics from the log file."""
        try:
            log_file = "tool_calls.log"
            if not os.path.exists(log_file):
                return {"error": "Log file not found"}
            
            stats = {
                "total_tool_calls": 0,
                "tool_call_types": {},
                "execution_times": [],
                "errors": 0,
                "queries_processed": 0
            }
            
            with open(log_file, 'r') as f:
                for line in f:
                    if "TOOL_CALL_START:" in line:
                        stats["total_tool_calls"] += 1
                        try:
                            data = json.loads(line.split("TOOL_CALL_START: ")[1])
                            tool_name = data.get("tool_name", "unknown")
                            stats["tool_call_types"][tool_name] = stats["tool_call_types"].get(tool_name, 0) + 1
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                    elif "TOOL_CALL_END:" in line:
                        try:
                            data = json.loads(line.split("TOOL_CALL_END: ")[1])
                            exec_time = data.get("execution_time_ms", 0)
                            stats["execution_times"].append(exec_time)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
                    elif "TOOL_CALL_ERROR:" in line:
                        stats["errors"] += 1
                    elif "QUERY_START:" in line:
                        stats["queries_processed"] += 1

            if stats["execution_times"]:
                stats["avg_execution_time_ms"] = sum(stats["execution_times"]) / len(stats["execution_times"])
                stats["max_execution_time_ms"] = max(stats["execution_times"])
                stats["min_execution_time_ms"] = min(stats["execution_times"])
            
            return stats
            
        except Exception as e:
            return {"error": f"Failed to read tool call stats: {str(e)}"}
    
    def start_run(self, run_description: str = "Tender Analysis Session") -> str:
        """Start a new run session for tracking."""
        self.current_run_id = start_run(run_description)
        self.run_start_time = time.time()
        logger.info(f"Started new run: {self.current_run_id}")
        return self.current_run_id
    
    def end_run(self, run_summary: str = ""):
        """End the current run session."""
        if self.current_run_id:
            run_duration = time.time() - self.run_start_time if self.run_start_time else 0
            summary = f"Run completed in {run_duration:.2f}s. {run_summary}"
            end_run(summary)
            logger.info(f"Ended run: {self.current_run_id}")
            self.current_run_id = None
            self.run_start_time = None
    
    def get_run_stats(self) -> Dict[str, Any]:
        """Get comprehensive run statistics from log files."""
        try:
            import os
            import json
            import time
            
            stats = {
                "current_run_id": self.current_run_id,
                "total_runs": 0,
                "total_sessions": 0,
                "total_tool_calls": 0,
                "tool_call_types": {},
                "agent_calls": {},
                "subagent_calls": {},
                "execution_times": [],
                "errors": 0,
                "run_duration": 0
            }
            
            if self.run_start_time:
                stats["run_duration"] = time.time() - self.run_start_time
            
            # Check logs directory
            logs_dir = "logs"
            if os.path.exists(logs_dir):
                for log_file in os.listdir(logs_dir):
                    if log_file.startswith("run_") and log_file.endswith(".log"):
                        stats["total_runs"] += 1
                        
                        log_path = os.path.join(logs_dir, log_file)
                        with open(log_path, 'r') as f:
                            for line in f:
                                if "SESSION_START:" in line:
                                    stats["total_sessions"] += 1
                                elif "TOOL_CALL_START:" in line:
                                    stats["total_tool_calls"] += 1
                                    try:
                                        data = json.loads(line.split("TOOL_CALL_START: ")[1])
                                        tool_name = data.get("tool_name", "unknown")
                                        stats["tool_call_types"][tool_name] = stats["tool_call_types"].get(tool_name, 0) + 1
                                        
                                        # Track agent context
                                        agent_context = data.get("agent_context", {})
                                        agent_type = agent_context.get("agent_type", "unknown")
                                        stats["agent_calls"][agent_type] = stats["agent_calls"].get(agent_type, 0) + 1
                                        
                                        subagent_type = agent_context.get("subagent_type")
                                        if subagent_type:
                                            stats["subagent_calls"][subagent_type] = stats["subagent_calls"].get(subagent_type, 0) + 1
                                    except (json.JSONDecodeError, KeyError, IndexError):
                                        pass
                                elif "TOOL_CALL_END:" in line:
                                    try:
                                        data = json.loads(line.split("TOOL_CALL_END: ")[1])
                                        exec_time = data.get("execution_time_ms", 0)
                                        stats["execution_times"].append(exec_time)
                                    except (json.JSONDecodeError, KeyError, IndexError):
                                        pass
                                elif "TOOL_CALL_ERROR:" in line:
                                    stats["errors"] += 1
            
            # Calculate averages
            if stats["execution_times"]:
                stats["avg_execution_time_ms"] = sum(stats["execution_times"]) / len(stats["execution_times"])
                stats["max_execution_time_ms"] = max(stats["execution_times"])
                stats["min_execution_time_ms"] = min(stats["execution_times"])
            
            return stats
            
        except Exception as e:
            return {"error": f"Failed to read run stats: {str(e)}"}
    
    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about the agent configuration."""
        tool_stats = self.get_tool_call_stats()
        run_stats = self.get_run_stats()
        
        return {
            "org_id": self.org_id,
            "current_tender_id": self.current_tender_id,
            "conversation_length": len(self.conversation_history),
            "agent_initialized": self.agent is not None,
            "agent_type": "Async Deep Agent Graph with Subagents",
            "subagents": [
                "document-analyzer",
                "research-agent", 
                "compliance-checker"
            ],
            "memory_enabled": self.checkpointer is not None,
            "model": "gpt-5",
            "dependencies_available": True,
            "mongodb_connected": self.mongo_client is not None,
            "tools_available": len(REACT_TOOLS) if REACT_TOOLS else 0,
            "tool_monitoring_enabled": True,
            "enhanced_logging_enabled": True,
            "current_run_id": self.current_run_id,
            "tool_call_stats": tool_stats,
            "run_stats": run_stats
        }

async def main():
    """Example usage of the TenderAnalysisAgent."""

    agent = TenderAnalysisAgent(org_id=1)

    print("=== Tender Analysis Agent Demo with Enhanced Logging ===\n")

    # Start a new run session
    run_id = agent.start_run("Tender Analysis Demo Session")
    print(f"Started run: {run_id}\n")

    try:
        response1 = await agent.chat(
        user_query="""What is the specific financial penalty (bod) for submitting a monthly turnover report late to SKI?""",
        tender_id="68c99b8a10844521ad051544"
        )
        print("Response 1:", response1)
        print("\n" + "="*50 + "\n")
        
        response2 = await agent.chat(
            user_query=""": List all the sub-services (Ydelser) we must be able to provide under the
            mandatory service area "Ydelsesområde 4: It-sikkerhed, business continuity og
            it-compliance"."""
        )
        print("Response 2:", response2)
        print("\n" + "="*50 + "\n")
        
        response3 = await agent.chat(
            user_query="""A customer wants us to sign a Leveringsaftale (Bilag C). Where in this
    agreement do we specify the consultants who will work on the project, and which
    document defines the qualification levels for these consultants?"""
        )
        print("Response 3:", response3)
        print("\n" + "="*50 + "\n")
        
        print("Conversation History:")
        for i, msg in enumerate(agent.get_conversation_history(), 1):
            print(f"{i}. {msg['role']}: {msg['content'][:100]}...")
        
        print("\nAgent Info with Enhanced Logging:")
        info = agent.get_agent_info()
        for key, value in info.items():
            if key in ["tool_call_stats", "run_stats"]:
                print(f"{key}:")
                for stat_key, stat_value in value.items():
                    print(f"  {stat_key}: {stat_value}")
            else:
                print(f"{key}: {value}")
        
        print("\nEnhanced Run Statistics:")
        run_stats = agent.get_run_stats()
        for key, value in run_stats.items():
            print(f"{key}: {value}")
    
    finally:
        # End the run session
        agent.end_run("Demo completed successfully")
        print(f"\nRun {run_id} completed and logged.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())