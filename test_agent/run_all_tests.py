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

# NEW COMPREHENSIVE TEST CASES (Bilag F focused)
TEST_CASES = {
    "A. Sanity & Quick-RAG Tests (No Subagent)": [
        {
            "id": "A1",
            "name": "Obligatoriske ydelsesområder lookup",
            "query": "Hvilke obligatoriske ydelsesområder indgår i Rammeaftale 02.15?",
            "english": "Which mandatory service areas are included in Framework Agreement 02.15?",
            "expected_routing": "Orchestrator direct (search_tender_corpus)",
            "success_criteria": "Mentions 1-7 (It-strategier, Forretningsbehov, It-udbud, It-sikkerhed, It-arkitektur, It-governance, Projekt-/programledelse). Cite Bilag F page 3."
        },
        {
            "id": "A2",
            "name": "Ydelsesområde 3 details",
            "query": "Hvad dækker Ydelsesområde 3: It-udbud (delområder og ydelser)?",
            "english": "What does Service Area 3: IT Procurement cover (sub-areas and services)?",
            "expected_routing": "Orchestrator direct (search_tender_corpus)",
            "success_criteria": "Refers to 2.3.1 and 2.3.2. Cite Bilag F pp. 9-11."
        },
        {
            "id": "A3",
            "name": "Konsulentkategori 3 requirements",
            "query": "Angiv kravene for Konsulentkategori 3 (seniorkonsulent/specialist) kort.",
            "english": "Briefly state the requirements for Consultant Category 3 (senior consultant/specialist).",
            "expected_routing": "Orchestrator direct (search_tender_corpus)",
            "success_criteria": "Five headings (A-E: Education/experience, Independence, Influence, Complexity, Business skills). Cite Bilag F.2 pp. 5/6."
        },
        {
            "id": "A4",
            "name": "WAS-tool reference",
            "query": "Hvor nævnes WAS-tool (Digitaliseringsstyrelsens Web Accessibility Statement Tool)?",
            "english": "Where is the WAS-tool (Danish Digitalization Agency's Web Accessibility Statement Tool) mentioned?",
            "expected_routing": "Orchestrator direct (search_tender_corpus)",
            "success_criteria": "Identifies mentions under 3.5.1 and 3.5.2 UX services. Cite relevant pages (~pp. 31 & 33 in Bilag F)."
        },
        {
            "id": "A5",
            "name": "Purpose of system adaptation",
            "query": "Hvad er formålet med Tilpasning af eksisterende it-systemer?",
            "english": "What is the purpose of Adaptation of existing IT systems?",
            "expected_routing": "Orchestrator direct (search_tender_corpus)",
            "success_criteria": "Protecting prior IT investments via changes/maintenance/error correction. Cite Bilag F 3.6 intro and 3.6.1."
        }
    ],
    
    "B. Exact Citation / File Retrieval Tests": [
        {
            "id": "B1",
            "name": "Exact citation of BC planning",
            "query": "Citer præcist delområdet 'Business continuity planlægning og afprøvning'.",
            "english": "Quote precisely the sub-area 'Business continuity planning and testing'.",
            "expected_routing": "Orchestrator: search_tender_corpus → get_file_content",
            "success_criteria": "Quotes 2.4.2 subsection accurately with quote block and page ref."
        },
        {
            "id": "B2",
            "name": "Full section retrieval",
            "query": "Vis hele sektionen 2.7.3 Ledelse af agile projekter (ingen sammenfatning).",
            "english": "Show the entire section 2.7.3 Management of agile projects (no summary).",
            "expected_routing": "Orchestrator: get_file_content",
            "success_criteria": "Full 2.7.3 text as excerpt, exact heading visible, page span included."
        }
    ],
    
    "C. Multi-Snippet Synthesis (No Subagent)": [
        {
            "id": "C1",
            "name": "Compare security and compliance",
            "query": "Sammenlign It-sikkerhed (2.4.1) og It-compliance (2.4.3): nøgleforskelle og leverancer.",
            "english": "Compare IT security (2.4.1) and IT compliance (2.4.3): key differences and deliverables.",
            "expected_routing": "Orchestrator: 2x search_tender_corpus + synthesis",
            "success_criteria": "Comparison table/list with citations to both sections. Clear contrast between policy/process vs. legal compliance."
        },
        {
            "id": "C2",
            "name": "IT architecture sub-areas list",
            "query": "Lav en punktopstilling over delområder og ydelser under 2.5.1 Etablering af en it-arkitektur.",
            "english": "Create a bullet list of sub-areas and services under 2.5.1 Establishment of an IT architecture.",
            "expected_routing": "Orchestrator: search_tender_corpus + structuring",
            "success_criteria": "Captures data models, dataflow, platform selection, security design, environments, cloud/shared components, standard applications. Cite 2.5.1."
        }
    ],
    
    "D. Internal Deep Analysis (Requires advanced_tender_analyst)": [
        {
            "id": "D1",
            "name": "Find all backup references",
            "query": "Find alle steder i materialet hvor backup (eller genopretning) omtales, og lav anbefalinger til vores leveranceplan.",
            "english": "Find all places in the material where backup (or recovery) is mentioned, and make recommendations for our delivery plan.",
            "expected_routing": "Delegate to advanced_tender_analyst",
            "success_criteria": "Mentions backup/recovery under 2.4.1 and 3.7.1. Cites Bilag F pages. Returns structured recommendations."
        },
        {
            "id": "D2",
            "name": "Map procurement activities to business case",
            "query": "Udtræk alle aktiviteter under 'Gennemførelse af udbud' og map dem til påvirkning af business case.",
            "english": "Extract all activities under 'Execution of procurement' and map them to business case impact.",
            "expected_routing": "Delegate to advanced_tender_analyst",
            "success_criteria": "2-column overview (Activity → BC impact). Includes prequalification, evaluation, award, contract, complaints. Cites 2.3.2 and 2.2.x."
        },
        {
            "id": "D3",
            "name": "Cross-reference agile vs waterfall",
            "query": "Lav en krydsreference mellem agil og vandfald for både test og udvikling (sektioner 3.4 & 3.5).",
            "english": "Create a cross-reference between agile and waterfall for both test and development (sections 3.4 & 3.5).",
            "expected_routing": "Delegate to advanced_tender_analyst",
            "success_criteria": "Matrix with phases/roles/artifacts, key differences. Covers test strategy, agile testing, regression, UX/WAS requirements. Cites 3.4 & 3.5."
        },
        {
            "id": "D4",
            "name": "Extract all personal data compliance requirements",
            "query": "Udtræk samtlige persondata/compliance-krav og strukturer dem i en tjekliste.",
            "english": "Extract all personal data/compliance requirements and structure them into a checklist.",
            "expected_routing": "Delegate to advanced_tender_analyst",
            "success_criteria": "Checklist with guidelines/monitoring/escalation/anchoring + test data handling from 2.5.1. Citations included."
        }
    ],
    
    "E. Parallel Internal Analyses (Concurrency)": [
        {
            "id": "E1",
            "name": "Summarize all 7 service areas",
            "query": "Opsummer for hvert ydelsesområde 1-7: 3 vigtigste leverancer og et konkret eksempel.",
            "english": "Summarize for each service area 1-7: 3 most important deliverables and a concrete example.",
            "expected_routing": "Orchestrator: 7 parallel advanced_tender_analyst tasks",
            "success_criteria": "Seven rows populated with deliverables and examples. All within Bilag F's mandatory areas."
        },
        {
            "id": "E2",
            "name": "Deliverables checklist for 3 areas",
            "query": "Lav en 'hvad-skal-leveres' checkliste for: 2.3 It-udbud, 2.4 It-sikkerhed/BC/compliance, 2.7 Programledelse.",
            "english": "Create a 'what-to-deliver' checklist for: 2.3 IT procurement, 2.4 IT security/BC/compliance, 2.7 Program management.",
            "expected_routing": "Orchestrator: 3 parallel advanced_tender_analyst tasks",
            "success_criteria": "Merged checklist with artifacts (point models, policies, contingency plans, program standards) with citations."
        }
    ],
    
    "F. Writer Workflow (Analysis → Drafting)": [
        {
            "id": "F1",
            "name": "Draft IT procurement approach",
            "query": "Skriv på dansk et kort afsnit 'Tilgang til It-udbud (Ydelsesområde 3)' baseret på bilagets leverancer.",
            "english": "Write in Danish a brief section 'Approach to IT Procurement (Service Area 3)' based on the annex deliverables.",
            "expected_routing": "Sequential: advanced_tender_analyst → bid_writer_assistant",
            "success_criteria": "Danish, 150-200 words, persuasive, tethered to Bilag F 2.3 with inline citations."
        },
        {
            "id": "F2",
            "name": "Draft IT security approach",
            "query": "Skriv en udkaststekst (200-300 ord) om vores It-sikkerhed-tilgang.",
            "english": "Write a draft text (200-300 words) about our IT security approach.",
            "expected_routing": "Sequential: advanced_tender_analyst → bid_writer_assistant",
            "success_criteria": "References IT security policy, monitoring/escalation, encryption, logging, virus protection. Danish. Cites 2.4.1."
        },
        {
            "id": "F3",
            "name": "Executive summary for municipal client",
            "query": "Lav en Executive Summary (max 250 ord) for obligatoriske ydelsesområder til en kommunal kunde.",
            "english": "Create an Executive Summary (max 250 words) for mandatory service areas for a municipal client.",
            "expected_routing": "Parallel analysis of 2.1-2.7 → bid_writer_assistant",
            "success_criteria": "Brief, coherent, covers all 7 areas. Cites Bilag F overview table page 3."
        }
    ],
    
    "G. Web Search by Orchestrator": [
        {
            "id": "G1",
            "name": "GDPR changes affecting compliance",
            "query": "Er der seneste ændringer i GDPR som påvirker 'It-compliance' for kommuner?",
            "english": "Are there recent changes in GDPR that affect 'IT compliance' for municipalities?",
            "expected_routing": "Orchestrator: web_search",
            "success_criteria": "Clear separation of external info from tender content. No hallucinated tender facts. Optional crosswalk to 2.4.3."
        }
    ],
    
    "H. Cross-File Tasks": [
        {
            "id": "H1",
            "name": "Show customer list from Bilag A",
            "query": "Vis kundelisten fra Bilag A.",
            "english": "Show the customer list from Annex A.",
            "expected_routing": "Orchestrator: read file_index → get_file_content(Bilag A)",
            "success_criteria": "Picks correct file. Returns list or explains if redacted."
        },
        {
            "id": "H2",
            "name": "Direct award rules from Bilag B",
            "query": "Hvornår og hvordan kan Direkte tildeling anvendes (Bilag B)?",
            "english": "When and how can Direct Award be used (Annex B)?",
            "expected_routing": "Orchestrator: get_file_content(Bilag B) + quotes",
            "success_criteria": "Summarizes rules with exact quotes for critical definitions."
        },
        {
            "id": "H3",
            "name": "Reporting requirements from Bilag D",
            "query": "Hvilke rapporteringskrav har leverandøren (Bilag D)?",
            "english": "What reporting requirements does the supplier have (Annex D)?",
            "expected_routing": "Orchestrator: get_file_content(Bilag D)",
            "success_criteria": "Summarizes obligations, deliverables, cadence with short quotes."
        },
        {
            "id": "H4",
            "name": "CSR obligations from Bilag E",
            "query": "Hvad er vores CSR-forpligtelser (Bilag E)?",
            "english": "What are our CSR obligations (Annex E)?",
            "expected_routing": "Orchestrator: get_file_content(Bilag E)",
            "success_criteria": "Bullet summary with mandatory clause quotes."
        }
    ],
    
    "I. Robustness / Edge Cases": [
        {
            "id": "I1",
            "name": "Ambiguous request",
            "query": "Kan vi levere dette?",
            "english": "Can we deliver this?",
            "expected_routing": "Orchestrator: clarifying follow-up question",
            "success_criteria": "Asks clarification about which service area/requirement. No premature RAG."
        },
        {
            "id": "I2",
            "name": "Non-existent deadline",
            "query": "Find deadline for tilbudsafgivelse.",
            "english": "Find the deadline for bid submission.",
            "expected_routing": "Orchestrator: search_tender_corpus → check summary → 'not found'",
            "success_criteria": "Honest 'not found', no hallucination. Suggests where it might be (procurement notice)."
        },
        {
            "id": "I3",
            "name": "Top 10 passages on program management",
            "query": "Returnér de 10 mest relevante passager om 'Programledelse' (citeret).",
            "english": "Return the 10 most relevant passages about 'Program Management' (cited).",
            "expected_routing": "Orchestrator: search_tender_corpus(top_k=50) → deduplicate → top 10",
            "success_criteria": "Shows top 10 chunks with inline quotes and references to Bilag F 2.7.4."
        }
    ]
}

# OLD TEST CASES (Commented out - already run)
OLD_TEST_CASES_COMMENTED = """
{
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
"""


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
    if "expected_routing" in test_case:
        output_file.write(f"Expected Routing: {test_case['expected_routing']}\n")
    if "success_criteria" in test_case:
        output_file.write(f"Success Criteria: {test_case['success_criteria']}\n")
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
        output_file.write(f"Agent Architecture: Main Agent + Subagents (advanced_tender_analyst, bid_writer_assistant)\n")
        output_file.write(f"Test Focus: Bilag F (Service Areas 1-7) + Cross-file operations (Bilag A-E)\n")
        output_file.write(f"Total Test Categories: 9 (A-I)\n")
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

