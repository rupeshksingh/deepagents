"""MVP Toolset for Tender Analysis Agent"""

import os
from typing import Annotated, Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool, InjectedToolArg
from pymongo import MongoClient
from qdrant_client.http import models as rest
from langchain.tools.tool_node import InjectedState
from src.deepagents.logging_utils import log_tool_call
from src.deepagents.state import FilesystemState

from tool_utils import (
    CustomRetriever,
    get_file_content_from_id,
    getVectorStore,
    search,
)

# OpenAI Chat for answer-only analysis (1.1M context: GPT-4.1)
from langchain_openai import ChatOpenAI

load_dotenv()

uri = os.getenv("MONGODB_URL")
mongo_client = MongoClient(uri)


def _fix_injected_params_schema(tool_obj):
    """Remove injected params from tool schema to prevent validation errors."""
    if hasattr(tool_obj, 'args_schema') and tool_obj.args_schema is not None:
        schema = tool_obj.args_schema
        if hasattr(schema, 'model_fields'):
            for param_name in ['state', 'tool_call_id']:
                if param_name in schema.model_fields:
                    field = schema.model_fields[param_name]
                    field.default = None
                    field.default_factory = None
                    # Remove from required set if present (Pydantic v2)
                    if hasattr(schema, '__pydantic_required__'):
                        schema.__pydantic_required__.discard(param_name)
            # Rebuild the model to regenerate the schema
            if hasattr(schema, 'model_rebuild'):
                schema.model_rebuild(force=True)
    return tool_obj


def _targeted_hybrid_search(
    query: str,
    cluster_id: str,
    org_id: int = 1,
    file_id_filters: Optional[List[str]] = None,
):
    """Cluster-scoped hybrid retrieval for tender documents (Qdrant)."""
    try:
        if not cluster_id or cluster_id == "UNKNOWN":
            return {
                "error": "CLUSTER_ID_MISSING",
                "message": "Cannot perform search without a valid tender cluster_id",
                "cause": "cluster_id is either missing from state or set to 'UNKNOWN'",
                "suggestions": [
                    "This is likely a system configuration issue, not your fault",
                    "Check if cluster_id was set during agent initialization",
                    "Verify /workspace/context/cluster_id.txt exists and has valid content",
                    "As a fallback, try web_search if you need external information"
                ],
                "action_required": "Use request_human_input to resolve tender context configuration",
                "technical_details": f"cluster_id={cluster_id}, org_id={org_id}"
            }

        # ALWAYS filter by cluster_id (required for proper scoping)
        must_conditions: List[rest.Condition] = [
            rest.FieldCondition(key="metadata.type", match=rest.MatchValue(value="pc")),
            rest.FieldCondition(
                key="metadata.cluster_id", match=rest.MatchValue(value=cluster_id)
            ),
        ]
        
        # OPTIONALLY filter by specific file IDs (if provided)
        if file_id_filters:
            must_conditions.append(
                rest.FieldCondition(
                    key="metadata.file_id",
                    match=rest.MatchAny(any=[str(fid) for fid in file_id_filters]),
                )
            )
        
        qdrant_filter = rest.Filter(must=must_conditions)

        vectorstore = getVectorStore("org_1_v2")
        retriever = CustomRetriever(
            [vectorstore.as_retriever(search_kwargs={"filter": qdrant_filter})],
            k=50,
            p=10,
        )

        return retriever.get_docs_without_callbacks(query)
    except Exception as e:  # noqa: BLE001
        error_message = str(e)
        return {
            "error": "VECTOR_SEARCH_FAILED",
            "message": f"Hybrid vector search failed: {error_message}",
            "suggestions": [
                "This is likely a Qdrant vector database connection issue",
                "Check if Qdrant service is running and accessible",
                "Verify QDRANT_HOST and QDRANT_API_KEY environment variables",
                "Try again in a moment if this is a temporary network issue",
                "Use request_human_input if error persists"
            ],
            "technical_details": error_message,
            "query": query,
            "cluster_id": cluster_id,
            "documents": []
        }


@tool
@log_tool_call
async def search_tender_corpus(
    query: str,
    state: Annotated[FilesystemState, InjectedState, InjectedToolArg] = None,
    file_ids: Optional[List[str]] = None,
    org_id: int = 1,
) -> str:
    """Semantic search across tender documents with LLM synthesis - your PRIMARY tool for finding information.
    
    BEST PRACTICES FOR TENDER SEARCH:
    - **Language Adaptation**: If documents are in Danish, use Danish keywords for better recall
      * English: "penalties breach termination" → Danish: "bod sanktioner misligholdelse ophævelse"
      * English: "requirements obligations" → Danish: "krav forpligtelser"
      * English: "reporting turnover" → Danish: "rapportering omsætning"
    
    - **Use file_ids to scope searches**: When analyzing specific Bilag or Rammeaftale sections
      * Example: file_ids=["bilag_e_id"] to search only CSR appendix
    
    - **This returns SYNTHESIZED answers with citations** - not raw chunks
      * You get structured information ready to use, not document fragments
      * Always includes [Source: filename] citations
    
    - **ALWAYS prefer this over get_file_content** for initial exploration
      * get_file_content returns 40 pages of raw text (slow, expensive)
      * search_tender_corpus returns targeted answers (fast, precise)
    
    EXAMPLE QUERIES:
    - "Find all reporting obligations" → Returns structured list with section citations
    - "What are CSR documentation requirements?" → Returns requirements with sources
    - "Identify termination triggers misligholdelse" → Returns contract clauses with risk analysis
    - "SKI andel omsætning procent" → Returns fee percentage with citation"""
    
    # Parameter validation
    if not query or query.strip() == "":
        return """ERROR: EMPTY_QUERY

        search_tender_corpus requires a non-empty query parameter.

        CORRECT USAGE:
        search_tender_corpus(query="CSR requirements Bilag E")

        SUGGESTION:
        Provide specific search terms related to what you want to find in the tender documents."""
    
    if file_ids is not None and not isinstance(file_ids, list):
        return """ERROR: INVALID_PARAMETER
                The file_ids parameter must be a list of strings, not a single string.

                WRONG: file_ids="abc123"
                CORRECT: file_ids=["abc123", "def456"]

                SUGGESTION:
                If you have a single file_id, wrap it in a list: file_ids=[your_id]"""
    
    try:
        # Get cluster_id from state (set during initialization)
        from react_agent import ReactAgent
        files = state.get("files", {}) if state else {}
        # Prefer explicit cluster_id in state, then context file, then hard default
        cluster_id = (
            (state.get("cluster_id") if state else None)
            or files.get(ReactAgent.CONTEXT_CLUSTER_ID_PATH)
            or "68c99b8a10844521ad051543"
        )
        
        results = _targeted_hybrid_search(
            query, cluster_id, org_id, file_id_filters=file_ids
        )
        if isinstance(results, dict) and "error" in results:
            return str(results)

        # Collect chunks with citations
        chunks_with_citations = []
        for doc in results:  # type: ignore[assignment]
            meta = getattr(doc, "metadata", {}) or {}
            content = getattr(doc, "page_content", "")
            file_name = meta.get("file_name") or meta.get("filename") or "Unknown"
            file_id = str(meta.get("file_id") or meta.get("_id") or "")
            chunks_with_citations.append(f"[Source: {file_name} (ID: {file_id})]\n{content}")

        if not chunks_with_citations:
            return f"""NO RESULTS FOUND for query: "{query}"

            SUGGESTIONS TO IMPROVE YOUR SEARCH:
            1. **Try broader terms**: Instead of "CSR violations in Bilag E Section 3.2", try just "CSR obligations"
            2. **Adapt to document language**: If tender is Danish, use Danish keywords:
            • "penalties" → "bod" or "sanktioner"
            • "requirements" → "krav"
            • "reporting" → "rapportering"
            • "breach" → "misligholdelse"
            • "termination" → "ophævelse"
            3. **Check file scope**: Review /workspace/context/file_index.json to see which files cover this topic
            4. **Use file_ids parameter**: Narrow search to specific files if you know which documents are relevant
            5. **Try synonyms**: "backup" vs "sikkerhedskopiering" vs "genopretning"

            WHAT WAS SEARCHED: Entire tender corpus (cluster_id: {cluster_id})
            {f"FILE SCOPE: Limited to {len(file_ids)} file(s)" if file_ids else "FILE SCOPE: All tender files"}

            NEXT STEPS:
            • If this is a complex multi-document question, delegate to advanced_tender_analyst subagent
            • Check file_index.json to understand which documents exist: read_file("/workspace/context/file_index.json")
            • Try alternative search terms or break down your question into smaller searches"""

        # Synthesize with LLM to prevent context explosion
        combined_chunks = "\n\n---\n\n".join(chunks_with_citations)
        
        synthesis_prompt = f"""You are a tender document analyst providing information to an AI agent working on a bid management task.

        **Agent's Query**: {query}

        **Retrieved Document Chunks**:
        {combined_chunks}

        **Your Task**: 
        Synthesize the above chunks into a clear, actionable answer that the agent can directly use. The agent needs facts, requirements, and context—not vague summaries.

        **Output Requirements**:
        1. **Direct Answer First**: Lead with the specific information requested (values, dates, requirements, procedures)
        2. **Complete Context**: Include all relevant details the agent needs to act on this information (who, what, when, where, how)
        3. **Source Citations**: ALWAYS cite sources as [Source: filename] after each fact or requirement
        4. **Structured Format**: Use bullets, numbered lists, or tables when presenting multiple items
        5. **Exact Quotes**: When citing specific clauses, obligations, or criteria, preserve exact wording in quotes
        6. **Cross-References**: If information spans multiple files, explicitly note relationships and dependencies
        7. **Completeness Check**: If chunks are incomplete or contradictory, explicitly state what's missing or unclear

        **If chunks don't contain relevant information**: State clearly "No relevant information found in the searched documents" and suggest what might be searched instead.

        **Agent-Optimized Answer**:"""

        llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
        response = await llm.ainvoke(synthesis_prompt)
        return response.content if hasattr(response, 'content') else str(response)
        
    except Exception as e:  # noqa: BLE001
        error_message = str(e)
        return f"""ERROR: TOOL_EXECUTION_FAILED

        Tool: search_tender_corpus
        Message: {error_message}

        SUGGESTIONS:
        1. **Try a different search strategy**: Use broader or narrower search terms
        2. **Check if this is a network/database issue**: Try again in a moment
        3. **Consider alternative approaches**:
        • Use web_search for external/market information
        • Delegate to advanced_tender_analyst subagent for complex analysis
        • Try get_file_content if you know the exact file you need
        4. **If error persists**: Use request_human_input to report the issue

        TECHNICAL DETAILS:
        Error: {error_message}
        Parameters: query="{query}", file_ids={file_ids}, org_id={org_id}

        ACTION: If this error repeats, it may be a system configuration issue. Request human assistance."""


# Apply schema fix to remove injected params from validation
search_tender_corpus = _fix_injected_params_schema(search_tender_corpus)


@tool
@log_tool_call
async def retrieve_full_document(
    file_id: str,
    tender_id: Optional[str] = None,
    org_id: int = 1,
    question: Optional[str] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Fetch the full markdown content of a tender file and return a concise analysis (answer-only)."""
    try:
        content = get_file_content_from_id(
            mongo_client, file_id, tender_id or "", org_id
        )
        if not content:
            return {
                "error": "FILE_NOT_FOUND",
                "file_id": file_id,
                "message": f"No content found for file_id: {file_id}",
                "suggestions": [
                    "Verify the file_id exists in /workspace/context/file_index.json",
                    "Check if tender_id context is correct",
                    "Use search_tender_corpus to discover which files contain relevant information",
                    "Try get_file_content instead for raw file access"
                ],
                "note": "retrieve_full_document attempts to analyze the file with an LLM - if file is missing, no analysis is possible"
            }

        user_question = (
            question or "Provide a concise, structured summary of this document."
        )
        prompt = (
            f"Question: {user_question}\n\n"
            "Answer precisely using only the document. Use a table if requested.\n\n"
            "Document (markdown):\n" + content
        )

        llm = ChatOpenAI(model="gpt-4o", temperature=temperature)
        resp = await llm.ainvoke(prompt)
        answer_text = getattr(resp, "content", str(resp))

        return {"file_id": file_id, "answer": answer_text}
    except Exception as e:  # noqa: BLE001
        error_message = str(e)
        return {
            "error": "TOOL_EXECUTION_FAILED",
            "tool": "retrieve_full_document",
            "file_id": file_id,
            "message": f"Document retrieval and analysis failed: {error_message}",
            "suggestions": [
                "Try get_file_content instead for raw file access without LLM analysis",
                "Use search_tender_corpus for targeted information extraction",
                "If this is an LLM API issue, try again in a moment",
                "Check if file_id and tender_id are valid"
            ],
            "technical_details": error_message,
            "parameters": {
                "file_id": file_id,
                "tender_id": tender_id or "None",
                "org_id": org_id,
                "question": question or "default summary"
            }
        }


@tool
@log_tool_call
async def get_file_content(
    file_id: str,
    tender_id: Optional[str] = None,
    org_id: int = 1,
    max_pages: int = 40,
    chars_per_page: int = 2000,
) -> str:
    """Return the raw markdown content of a tender file by file_id (no analysis).
    
    ⚠️ PERFORMANCE WARNING: Returns large amounts of text (~40 pages). Processing is SLOW and expensive.
    
    ONLY USE WHEN:
    - You need EXACT verbatim quotes from a specific known file (e.g., for legal compliance language)
    - search_tender_corpus results reference the SAME file 5+ times, indicating you need full context
    - You need to see complete document structure/flow (e.g., understanding full procedure sequence in Bilag B)
    - You're analyzing a single known document in depth (e.g., "Summarize complete Bilag E")
    
    WHEN NOT TO USE:
    - General information lookups → Use search_tender_corpus instead
    - Multi-file analysis → Delegate to advanced_tender_analyst subagent
    - Initial exploration → ALWAYS search first, never retrieve full files blindly
    - Finding specific clauses → search_tender_corpus returns targeted results faster
    
    WORKFLOW:
    1. Try search_tender_corpus with 2-3 targeted searches first
    2. If search results consistently point to one file, then consider retrieving it
    3. Get file_id from /workspace/context/file_index.json
    4. Call this tool with that file_id
    
    TIP: Use file_index.json summaries to understand what each file contains before retrieving."""
    
    # Parameter validation
    if not file_id or file_id.strip() == "":
        return """ERROR: MISSING_FILE_ID

        get_file_content requires a valid file_id parameter.

        CORRECT USAGE:
        First: read_file("/workspace/context/file_index.json")
        Then: get_file_content(file_id="abc123...")

        SUGGESTION:
        Get file IDs from /workspace/context/file_index.json first. This file lists all available tender documents with their IDs and summaries.

        EXAMPLE WORKFLOW:
        1. read_file("/workspace/context/file_index.json")
        2. Find the file you need (e.g., "Bilag E" about CSR)
        3. Extract its file_id from the JSON
        4. get_file_content(file_id="that_id_here")"""
    
    try:
        content = get_file_content_from_id(
            mongo_client, file_id, tender_id or "", org_id
        )
        if not content:
            return f"""ERROR: FILE_NOT_FOUND

        No content available for file_id: {file_id}

        SUGGESTIONS:
        1. **Verify the file_id exists**: Check /workspace/context/file_index.json for valid file IDs
        2. **Check tender context**: Ensure you're using the correct tender_id (if multiple tenders)
        3. **Try search instead**: Use search_tender_corpus first to discover which files contain relevant information
        4. **Check file name**: If searching for a specific document (e.g., 'Bilag E'), check file_index.json for the correct ID

        NEXT STEPS:
        • Use read_file("/workspace/context/file_index.json") to see all available files and their IDs
        • Verify the file_id you're using matches an entry in file_index.json
        • If you don't know the file_id, use search_tender_corpus to find relevant information first

        TECHNICAL DETAILS:
        file_id: {file_id}
        tender_id: {tender_id or 'not specified'}
        org_id: {org_id}"""

        # Truncate to approximately `max_pages` pages to avoid oversized returns
        max_chars = max(1, max_pages) * max(500, chars_per_page)
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... truncated to ~{max_pages} pages ...]"
        return content
    except Exception as e:  # noqa: BLE001
        error_message = str(e)
        return f"""ERROR: TOOL_EXECUTION_FAILED

        Tool: get_file_content
        Message: {error_message}

        SUGGESTIONS:
        1. **Verify file_id format**: Ensure it's a valid MongoDB ObjectId or file identifier
        2. **Check database connection**: This might be a temporary network/database issue - try again
        3. **Use alternative approach**: Try search_tender_corpus instead for targeted information
        4. **Check tender context**: Verify tender_id is correct if working with multiple tenders
        5. **If error persists**: Use request_human_input to report the database issue

        TECHNICAL DETAILS:
        Error: {error_message}
        Parameters: file_id="{file_id}", tender_id="{tender_id or 'None'}", org_id={org_id}

        ACTION: If this error repeats, it may be a database configuration or permissions issue."""


@tool
@log_tool_call
def request_human_input(question: str, context: str = "") -> str:
    """Request clarification or a decision from a human reviewer (bid team member).
    
    USE WHEN:
    - Ambiguous tender clauses requiring legal interpretation
    - Business decisions needed (pricing strategy, resource allocation, go/no-go)
    - Contradictions in tender docs that need procurement office clarification
    - Missing information that only the user/client can provide
    - Risk assessment requires human judgment on severity/acceptability
    
    DO NOT USE:
    - Before exhausting searches (search thoroughly first!)
    - For information that's findable in documents (keep searching)
    - For simple clarifications the agent can infer from context
    
    EXAMPLES:
    - "Clause 8.5 contradicts Section 12.3 regarding penalty amounts - which takes precedence?"
    - "Should we commit to 24/7 support or negotiate for business hours only?"
    - "Risk identified: 3-strike termination rule. Is this acceptable for our delivery model?"
    - "Tender doesn't specify max response time for support. What should we propose?"
    
    The question will be presented to the user for their input before proceeding."""
    prompt = "HITL REQUEST:\n" + question
    if context:
        prompt += "\n\nContext:\n" + context
    return prompt


@tool
@log_tool_call
async def web_search(query: str) -> Dict[str, Any]:
    """Web search for external intelligence not present in tender documents.
    
    USE FOR:
    - **Competitor intelligence**: Who bids on similar tenders, their capabilities, past SKI wins
    - **Market data**: Pricing benchmarks, consultant rates in Denmark, industry salary ranges
    - **Regulatory research**: Danish GDPR updates, EU procurement law changes, SKI framework policies
    - **Technical standards**: ISO requirements, Danish IT security standards, framework comparisons
    - **CSR compliance**: Danish supply chain due diligence requirements, EU CSR directives
    - **Company research**: Client background, industry position, past procurement patterns
    
    DO NOT USE FOR:
    - Information that should be in tender documents (search tender corpus first!)
    - Danish company registry lookups (CVR numbers) - that's in tender docs
    - Tender-specific facts (deadlines, contacts, requirements) - use tender search
    
    BEST PRACTICES:
    - Prioritize Danish sources for Danish market context (.dk domains, Danish language)
    - Include "Denmark" or "Danish" in queries for local context
    - For competitors, search "SKI framework IT consulting [Company Name]"
    - For regulations, search official sources (datatilsynet.dk for GDPR, konkurrence-styrelsen.dk)
    
    EXAMPLES:
    - "Danish GDPR compliance requirements for IT suppliers 2024"
    - "Average senior IT consultant hourly rate Copenhagen Denmark"
    - "Company X SKI framework contracts IT consulting"
    - "ISO 27001 certification requirements Denmark"
    - "Danish CSR supply chain due diligence requirements"
    
    Returns: {"context": "...", "links": [...], "query": "...", "success": true/false}"""
    try:
        context, links = search({"orig_input": query})
        
        # Check if we got meaningful results
        if not context or not links or (isinstance(context, str) and len(context.strip()) < 10):
            return {
                "context": "",
                "links": [],
                "query": query,
                "success": False,
                "error": "NO_RESULTS",
                "message": f"Web search returned no results for query: '{query}'",
                "suggestions": [
                    "Try broader search terms (remove very specific details)",
                    "Use alternative phrasings or synonyms",
                    "For Danish topics, try both English and Danish terms",
                    "Consider if this information exists publicly (some tender details may not be online)",
                    "Try breaking down complex queries into simpler searches"
                ],
                "examples": [
                    f"Instead of '{query}', try removing specific company names or dates",
                    "Add 'Denmark' or 'Danish' to queries for local context",
                    "Use industry-standard terminology rather than company-specific jargon"
                ]
            }
        
        return {"context": context, "links": links, "query": query, "success": True}
    except Exception as e:  # noqa: BLE001
        error_message = str(e)
        return {
            "context": "",
            "links": [],
            "query": query,
            "success": False,
            "error": "SEARCH_FAILED",
            "message": f"Web search failed with error: {error_message}",
            "suggestions": [
                "This might be a temporary network or API issue - try again in a moment",
                "Check if your query contains special characters that might cause issues",
                "Try a simpler version of your query",
                "If error persists, use request_human_input to report the issue"
            ],
            "technical_details": error_message
        }


REACT_TOOLS = [
    search_tender_corpus,
    get_file_content,
    web_search,
    request_human_input,
]

REACT_TOOLS_DOC = [search_tender_corpus, get_file_content, request_human_input]
REACT_TOOLS_WEB = [web_search, request_human_input]
