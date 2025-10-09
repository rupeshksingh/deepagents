"""MVP Toolset for Tender Analysis Agent"""

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from pymongo import MongoClient
from qdrant_client.http import models as rest

from src.deepagents.logging_utils import log_tool_call

from tool_utils import (
    CustomRetriever,
    get_file_content_from_id,
    get_requirement_cluster_id,
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
    tender_id: str,
    org_id: int = 1,
    file_id_filters: Optional[List[str]] = None,
):
    """Cluster-scoped hybrid retrieval for tender documents (Qdrant)."""
    try:
        cluster_id = get_requirement_cluster_id(mongo_client, tender_id, org_id)
        if cluster_id is None:
            return {"error": f"Cluster ID not found for tender {tender_id}"}

        must_conditions: List[rest.Condition] = [
            rest.FieldCondition(key="metadata.type", match=rest.MatchValue(value="pc")),
            rest.FieldCondition(
                key="metadata.cluster_id", match=rest.MatchValue(value=cluster_id)
            ),
        ]
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
    tender_id: str,
    file_ids: Optional[List[str]] = None,
    org_id: int = 1,
) -> List[Dict[str, Any]]:
    """Semantic search across tender files (hybrid RAG)."""
    try:
        results = _targeted_hybrid_search(
            query, tender_id, org_id, file_id_filters=file_ids
        )
        if isinstance(results, dict) and "error" in results:
            return results  # type: ignore[return-value]

        chunks: List[Dict[str, Any]] = []
        for doc in results:  # type: ignore[assignment]
            meta = getattr(doc, "metadata", {}) or {}
            chunks.append(
                {
                    "content": getattr(doc, "page_content", ""),
                    "citation": {
                        "file_id": str(meta.get("file_id") or meta.get("_id") or ""),
                        "file_name": meta.get("file_name")
                        or meta.get("filename")
                        or "",
                    },
                }
            )
        return chunks
    except Exception as e:  # noqa: BLE001
        return {"error": f"search_tender_corpus failed: {str(e)}"}  # type: ignore[return-value]


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
    retrieve_full_document,
    web_search,
    request_human_input,
]

REACT_TOOLS_DOC = [search_tender_corpus, retrieve_full_document, request_human_input]
REACT_TOOLS_WEB = [web_search, request_human_input]
