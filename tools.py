"""MVP Toolset for Tender Analysis Agent"""

import os
from typing import Annotated, Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain.agents.tool_node import InjectedState
from pymongo import MongoClient
from qdrant_client.http import models as rest

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


def _targeted_hybrid_search(
    query: str,
    cluster_id: str,
    org_id: int = 1,
    file_id_filters: Optional[List[str]] = None,
):
    """Cluster-scoped hybrid retrieval for tender documents (Qdrant)."""
    try:
        if not cluster_id or cluster_id == "UNKNOWN":
            return {"error": "Cluster ID not available - cannot search"}

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
        return {"error": f"Chunk search failed: {str(e)}", "documents": []}


@tool
@log_tool_call
async def search_tender_corpus(
    query: str,
    state: Annotated[FilesystemState, InjectedState],
    file_ids: Optional[List[str]] = None,
    org_id: int = 1,
) -> str:
    """Semantic search across tender files with LLM synthesis to prevent context bloat."""
    try:
        # Get cluster_id from state (set during initialization)
        from react_agent import ReactAgent
        cluster_id = state.get("files", {}).get(ReactAgent.CONTEXT_CLUSTER_ID_PATH, "UNKNOWN")
        
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
            return "No relevant chunks found for this query."

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
        return f"Error in search_tender_corpus: {str(e)}"


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
            return {"error": f"No content found for {file_id}", "file_id": file_id}

        user_question = (
            question or "Provide a concise, structured summary of this document."
        )
        prompt = (
            f"Question: {user_question}\n\n"
            "Answer precisely using only the document. Use a table if requested.\n\n"
            "Document (markdown):\n" + content
        )

        llm = ChatOpenAI(model="gpt-4.1", temperature=temperature)
        resp = await llm.ainvoke(prompt)
        answer_text = getattr(resp, "content", str(resp))

        return {"file_id": file_id, "answer": answer_text}
    except Exception as e:  # noqa: BLE001
        return {"error": f"retrieve_full_document failed: {str(e)}", "file_id": file_id}


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
    
    ⚠️ WARNING: Returns large amounts of text (~40 pages). Only use when:
    - You need verbatim quotes from a specific known file
    - search_tender_corpus results reference a file repeatedly
    - You need to see complete document structure
    
    ALWAYS try search_tender_corpus first before using this tool."""
    try:
        content = get_file_content_from_id(
            mongo_client, file_id, tender_id or "", org_id
        )
        if not content:
            return ""

        # Truncate to approximately `max_pages` pages to avoid oversized returns
        max_chars = max(1, max_pages) * max(500, chars_per_page)
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... truncated to ~{max_pages} pages ...]"
        return content
    except Exception as e:  # noqa: BLE001
        return f"Error: get_file_content failed: {str(e)}"


@tool
@log_tool_call
def request_human_input(question: str, context: str = "") -> str:
    """Request clarification or a decision from a human reviewer."""
    prompt = "HITL REQUEST:\n" + question
    if context:
        prompt += "\n\nContext:\n" + context
    return prompt


@tool
@log_tool_call
async def web_search(query: str) -> Dict[str, Any]:
    """Web search for external context not present in tender docs."""
    try:
        context, links = search({"orig_input": query})
        return {"context": context, "links": links, "query": query, "success": True}
    except Exception:  # noqa: BLE001
        return {
            "context": "No context available",
            "links": [],
            "query": query,
            "success": False,
        }


REACT_TOOLS = [
    search_tender_corpus,
    get_file_content,
    web_search,
    request_human_input,
]

REACT_TOOLS_DOC = [search_tender_corpus, get_file_content, request_human_input]
REACT_TOOLS_WEB = [web_search, request_human_input]
