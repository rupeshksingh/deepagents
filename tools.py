"""Foundational tools for the LangGraph react agent.

This module provides essential tools for deep research and analysis of tender documents
using a ReAct (Reasoning and Acting) agent pattern. The tools enable comprehensive
document analysis, targeted search, and external research capabilities.

Key Features:
- Tender manifest consultation for metadata and document inventory
- Hybrid search combining vector and keyword search for precise content retrieval
- Iterative document analysis using MapReduce strategy for large documents
- External web search for regulations, legal definitions, and market intelligence
- File mapping capabilities to resolve user references to specific document IDs

Usage:
    These tools are designed to be used by a LangGraph ReAct agent for automated
    tender analysis and research tasks. Each tool returns structured data that can
    be processed by the agent for decision-making and further analysis.

Example:
    The agent can use these tools in sequence:
    1. consult_tender_manifest() to get overview and document list
    2. targeted_hybrid_search() to find specific information
    3. iterative_document_analyzer() for detailed document analysis
    4. web_search() for external context and validation
"""

import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pymongo import MongoClient

# Add standalone logging decorator to avoid import issues
import logging
import json
import time
from datetime import datetime
from functools import wraps
import uuid

def log_tool_call(func):
    """Standalone tool call logging decorator."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        tool_call_id = str(uuid.uuid4())
        
        log_args = {}
        log_kwargs = {}
        
        for i, arg in enumerate(args):
            if not hasattr(arg, '__dict__') or not isinstance(arg, dict):
                log_args[f"arg_{i}"] = str(arg)[:200]
        
        excluded_params = {'state', 'tool_call_id'}
        for key, value in kwargs.items():
            if key not in excluded_params:
                log_kwargs[key] = str(value)[:200]
        
        start_time = time.time()
        
        try:
            # Log tool call start
            log_data = {
                "event": "tool_call_start",
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "timestamp": datetime.now().isoformat(),
                "args": log_args,
                "kwargs": log_kwargs
            }
            logging.info(f"TOOL_CALL_START: {json.dumps(log_data, default=str)}")
            
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            
            # Log tool call end
            log_data = {
                "event": "tool_call_end",
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "timestamp": datetime.now().isoformat(),
                "execution_time_ms": round(execution_time * 1000, 2),
                "result_type": type(result).__name__,
                "result_preview": str(result)[:500] if result is not None else None
            }
            logging.info(f"TOOL_CALL_END: {json.dumps(log_data, default=str)}")
            
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log_data = {
                "event": "tool_call_error",
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "timestamp": datetime.now().isoformat(),
                "execution_time_ms": round(execution_time * 1000, 2),
                "error_type": type(e).__name__,
                "error_message": str(e)
            }
            logging.error(f"TOOL_CALL_ERROR: {json.dumps(log_data, default=str)}")
            raise
    
    return wrapper

from tool_utils import (
    CustomRetriever,
    get_file_content_from_id,
    get_proposal_files,
    get_proposal_files_summary,
    get_proposal_summary,
    get_requirement_cluster_id,
    getVectorStore,
    search,
)

load_dotenv()

uri = os.getenv("MONGODB_URL")
mongo_client = MongoClient(uri)

# Defer model initialization to avoid Pydantic issues
# configurable_model = init_chat_model(
#     model="gpt-4.1",
# )

class TenderOverview(BaseModel):
    """Schema for tender overview data.
    
    Represents high-level information about a tender including its summary
    and document count. This is typically the first information retrieved
    when exploring a new tender.
    
    Attributes:
        tender_id: Unique identifier for the tender (e.g., "tender_123")
        summary: Comprehensive 10-page structured summary containing:
            - Project overview and objectives
            - Evaluation criteria and scoring methodology
            - Timeline and milestone requirements
            - Key technical and business requirements
        total_documents: Total number of documents in the tender package
    """
    
    tender_id: str = Field(description="Unique identifier for the tender")
    summary: str = Field(description="10-page structured summary with overview, evaluation criteria, and timelines")
    total_documents: int = Field(description="Total number of documents in the tender")


class DocumentInventoryItem(BaseModel):
    """Schema for a document in the tender inventory.
    
    Represents metadata for a single document within a tender package.
    This structure is used to catalog and organize all documents
    associated with a tender for easy reference and retrieval.
    
    Attributes:
        file_id: Primary key for document retrieval (e.g., "doc_001")
        file_name: Exact file name as stored (e.g., "01_Rammeaftale_Hovedaftale.pdf")
        document_type: Categorization of the document type:
            - "Rammeaftale": Main framework agreement
            - "Bilag": Technical annexes and appendices
            - "Pricing": Cost and pricing related documents
            - "Legal": Legal terms and conditions
            - "Technical": Technical specifications and requirements
        summary: Concise 10-line overview describing the document's
            purpose, key contents, and relevance to the tender
    """
    
    file_id: str = Field(description="Primary key for document retrieval")
    file_name: str = Field(description="Exact file name")
    document_type: str = Field(description="Type: Rammeaftale, Bilag, Pricing, etc.")
    summary: str = Field(description="10-line concise overview of document purpose")


class TenderManifest(BaseModel):
    """Complete tender manifest structure.
    
    Represents the full manifest of a tender package, combining the
    high-level overview with the complete inventory of documents.
    This is the primary data structure returned by the consult_tender_manifest
    tool when listing all tender information.
    
    Attributes:
        overview: High-level tender information including summary and document count
        documents: Complete list of all documents in the tender package
    """
    
    overview: TenderOverview
    documents: List[DocumentInventoryItem]


class SearchResult(BaseModel):
    """Result from targeted hybrid search.
    
    Represents a single search result from the targeted_hybrid_search tool.
    Each result contains the relevant content along with metadata about
    its source and relevance confidence.
    
    Attributes:
        content: The actual text content that matches the search query
        file_id: Unique identifier of the source document (e.g., "doc_001")
        file_name: Human-readable name of the source file
        confidence_score: Relevance confidence score between 0.0 and 1.0,
            where 1.0 indicates perfect match and 0.0 indicates no relevance
    """
    
    content: str = Field(description="Relevant content from the search")
    file_id: str = Field(description="Source file identifier")
    file_name: str = Field(description="Source file name")
    confidence_score: float = Field(description="Relevance confidence score")


class AnalysisResult(BaseModel):
    """Result from iterative document analysis.
    
    Represents the structured output from the iterative_document_analyzer tool.
    Contains the analysis results organized into summary, findings, and
    relevant sections for easy consumption by the agent.
    
    Attributes:
        summary: High-level summary of the analysis findings
        key_findings: List of specific findings extracted from the document,
            typically formatted as bullet points for clarity
        relevant_sections: List of document sections that support the analysis,
            including section numbers, titles, or page references
        file_id: Unique identifier of the analyzed document
    """
    
    summary: str = Field(description="Analysis summary")
    key_findings: List[str] = Field(description="Key findings extracted")
    relevant_sections: List[str] = Field(description="Relevant document sections")
    file_id: str = Field(description="Analyzed file identifier")


class FileMapping(BaseModel):
    """Schema for mapping user references to file IDs with confidence scores.
    
    Represents a single mapping between a user-provided file reference
    and the actual file in the tender document collection. This is used
    by the consult_tender_manifest tool when action='map_names_to_ids'.
    
    Attributes:
        user_reference: The original user-provided reference string
            (e.g., "main contract", "pricing.pdf", "technical requirements")
        file_id: The mapped file ID from the tender document collection
        file_name: The actual file name that was matched
        confidence: Confidence score between 0.0 and 1.0 indicating
            how well the user reference matches the file:
            - 1.0: Perfect match (exact filename match)
            - 0.8-0.9: Very good match (strong semantic similarity)
            - 0.6-0.7: Good match (partial filename or content match)
            - 0.4-0.5: Moderate match (some similarity)
            - 0.0-0.3: Poor match (minimal similarity)
        reasoning: Brief explanation of why this mapping was chosen,
            including the matching criteria used
    """
    
    user_reference: str = Field(description="The original user reference string")
    file_id: str = Field(description="The mapped file ID")
    file_name: str = Field(description="The mapped file name")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0", ge=0.0, le=1.0)
    reasoning: str = Field(description="Brief explanation of why this mapping was chosen")


class FileMappings(BaseModel):
    """Schema for the complete file mapping result.
    
    Represents the complete result from the file mapping process,
    containing all mappings between user references and file IDs.
    This is the structured output format used by the consult_tender_manifest
    tool when action='map_names_to_ids'.
    
    Attributes:
        mapped_files: List of FileMapping objects, each representing
            a single mapping between a user reference and a file ID
            with associated confidence scores and reasoning
    """
    
    mapped_files: List[FileMapping] = Field(description="List of file mappings with confidence scores")

@tool
@log_tool_call
async def consult_tender_manifest(
    action: str,
    tender_id: str,
    org_id: int = 1,
    user_references: List[str] | None = None
) -> Dict[str, Any]:
    """Consult the tender manifest for rapid access to metadata and summaries. This tool will be used to get ids and basic information about the tender and its associated files.
    
    This tool provides three main capabilities for tender document management:
    1. Get tender overview with summary and document count. Use it when you need to get basic information of the whole tender and number of files in it.
    2. List all documents in the tender with metadata. Use it if you need to go through all files for a particular tender and get there names, ids, along with summary.
    3. Map user-provided file references to actual file IDs with confidence scores. Use it if you need to directly read a file check and to get it you need a its particular id.
    
    The tool is essential for initial tender exploration and file identification.
    
    Args:
        action (str): Action to perform. Must be one of:
            - 'get_overview': Retrieve tender summary and total document count
            - 'list_documents': Get complete list of documents with metadata
            - 'map_names_to_ids': Map user references to file IDs with confidence scores
        tender_id (str): Unique identifier for the tender (e.g., "tender_123")
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.
        user_references (List[str], optional): List of user-provided file references
            to map to actual file IDs. Only used when action='map_names_to_ids'.
            Examples: ["main contract", "pricing.pdf", "technical requirements"]
    
    Returns:
        Dict[str, Any]: Response varies by action:
            - 'get_overview': {"tender_id": str, "summary": str, "total_documents": int}
            - 'list_documents': {"documents": List[Dict]} with file metadata
            - 'map_names_to_ids': {"mapped_files": List[Dict]} with confidence scores
            - Error cases: {"error": str} with error description
    
    Raises:
        Exception: Database connection or query errors are caught and returned as error dicts
    
    Example:
        # Get tender overview
        result = await consult_tender_manifest("get_overview", "tender_123")
        
        # List all documents
        result = await consult_tender_manifest("list_documents", "tender_123")
        
        # Map user references to file IDs
        result = await consult_tender_manifest(
            "map_names_to_ids", 
            "tender_123", 
            user_references=["main contract", "pricing structure"]
        )
    """
    if action == "get_overview":
        summary = get_proposal_summary(mongo_client, tender_id, org_id)
        if summary is None:
            summary = "Summary not found"

        file_id = get_requirement_cluster_id(mongo_client, tender_id, org_id)
        if file_id is None:
            files = []
        else:
            files = get_proposal_files(mongo_client, file_id, org_id)
            if files is None:
                files = []

        return {
            "tender_id": tender_id,
            "summary": summary,
            "total_documents": len(files)
        }
    
    elif action == "list_documents":
        try:
            documents = get_proposal_files_summary(mongo_client, tender_id, org_id)
            if documents is None:
                documents = []
                return documents
            return {"documents": documents}
        except Exception as e:
            return {"error": f"Error getting document list: {str(e)}"}
    
    elif action == "map_names_to_ids":
        if not user_references:
            return {"error": "No user references provided for mapping"}
        
        try:
            document_info = get_proposal_files_summary(mongo_client, tender_id, org_id)
            if isinstance(document_info, dict) and "error" in document_info:
                return document_info
        except Exception as e:
            return {"error": f"Error getting document info for mapping: {str(e)}"}

        prompt = f"""
You are tasked with mapping user reference strings to the most appropriate file IDs from a tender document collection.
User References to Map: {', '.join(user_references)}
Available Documents:
{chr(10).join([f"- ID: {doc['file_id']}, Name: {doc['file_name']}, Type: {doc['document_type']}, Summary: {doc['summary']}" for doc in document_info])}
For each user reference, find the best matching document and provide:
1. The exact file_id from the available documents
2. A confidence score between 0.0 and 1.0 (1.0 = perfect match, 0.0 = no match)
3. Brief reasoning for your choice
Consider matches based on:
- Exact filename matches
- Partial filename matches
- File extension matches
- Content summary relevance
- Semantic similarity
Return your response in the following JSON format:
{{
  "mapped_files": [
    {{
      "user_reference": "original reference string",
      "file_id": "matched_file_id",
      "file_name": "matched_file_name",
      "confidence": 0.95,
      "reasoning": "Brief explanation of why this mapping was chosen"
    }}
  ]
}}
"""  
        try:
            from langchain.chat_models import init_chat_model
            configurable_model = init_chat_model(model="gpt-4.1")
            model_with_structure = configurable_model.with_structured_output(FileMappings)
            message = HumanMessage(content=prompt)
            response = model_with_structure.invoke([message])
            
            mapped_results = []
            for mapping in response.mapped_files:
                mapped_results.append({
                    "user_reference": mapping.user_reference,
                    "file_id": mapping.file_id,
                    "file_name": mapping.file_name,
                    "confidence": mapping.confidence,
                    "reasoning": mapping.reasoning
                })
            
            return {"mapped_files": mapped_results}
            
        except Exception:
            mapped_results = []
            for ref in user_references:
                ref_lower = ref.lower()
                best_match = None
                best_confidence = 0.0
                
                for doc in document_info:
                    confidence = 0.0
                    
                    if ref_lower in doc['file_name'].lower():
                        confidence += 0.6
                    if ref_lower in doc['document_type'].lower():
                        confidence += 0.4
                    if any(word in doc['summary'].lower() for word in ref_lower.split()):
                        confidence += 0.3
                    
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = doc
                
                if best_match and best_confidence > 0.1:
                    mapped_results.append({
                        "user_reference": ref,
                        "file_id": str(best_match['file_id']),
                        "file_name": best_match['file_name'],
                        "confidence": min(best_confidence, 1.0),
                        "reasoning": f"Fallback matching based on filename/content similarity (confidence: {best_confidence:.2f})"
                    })
            
            return {"mapped_files": mapped_results}
    
    else:
        return {"error": f"Unknown action: {action}"}

@tool
@log_tool_call
async def targeted_hybrid_search(
    query: str,
    tender_id: str,
    org_id: int = 1,
    file_id_filters: List[str] | None = None
) -> List[Dict[str, Any]]:
    """Primary RAG workhorse for deep content extraction using hybrid search from Tender files.
    
    This tool performs sophisticated content retrieval by combining vector similarity
    search with keyword matching. It's the core tool for finding specific information
    within tender documents using natural language queries.
    
    The hybrid approach ensures both semantic relevance and keyword precision,
    making it ideal for finding specific clauses, requirements, or technical details
    within large document collections.
    
    Args:
        query (str): Natural language search query. Can be:
            - Specific questions: "What are the penalty clauses for downtime?"
            - Keywords: "SLA requirements uptime"
            - Technical terms: "ISO 27001 compliance requirements"
            - Document sections: "pricing structure payment terms"
        tender_id (str): Unique identifier for the tender to search within
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.
        file_id_filters (List[str], optional): List of specific file IDs to restrict
            search scope. If provided, only these files will be searched.
            Useful for targeted analysis of specific documents.
    
    Returns:
        Dict[str, Any]: Search results containing:
            - "context" (str): Concatenated relevant content from all matching documents
            - "documents" (List): List of matching document objects with metadata
            - "num_results" (int): Number of documents found
            - "error" (str, optional): Error message if search fails
    
    Raises:
        Exception: Database connection, vector store, or retrieval errors are caught
            and returned as error dicts
    
    Example:
        # Search for penalty clauses
        result = await targeted_hybrid_search(
            "penalty clauses downtime SLA breach",
            "tender_123"
        )
        
        # Search within specific files only
        result = await targeted_hybrid_search(
            "pricing structure payment terms",
            "tender_123",
            file_id_filters=["doc_003", "doc_004"]
        )
        
        # Find technical requirements
        result = await targeted_hybrid_search(
            "What are the security compliance requirements?",
            "tender_123"
        )
    """
    try:
        cluster_id = get_requirement_cluster_id(mongo_client, tender_id, org_id)
        if cluster_id is None:
            return {"error": f"Cluster ID not found for tender {tender_id}"}
        # current_filter = Filter(
        #     must=[
        #         FieldCondition(
        #             key="cluster_id",
        #             match=MatchValue(value=cluster_id)
        #         )
        #     ]
        # )
        vectorstore = getVectorStore("proposal_testing")
        retriever = CustomRetriever(
            [vectorstore.as_retriever(search_kwargs={"filter": {}})],
            k=50,
            p=10,
        )
        
        documents = retriever.get_docs_without_callbacks(query)
        
        return documents
    except Exception as e:
        return {"error": f"Chunk search failed: {str(e)}", "documents": []}

@tool
@log_tool_call
async def iterative_document_analyzer(
    file_id: str,
    analysis_objective: str,
    tender_id: str,
    org_id: int = 1
) -> Dict[str, Any]:
    """Analyze or summarize large documents using MapReduce strategy.
    
    This tool performs deep analysis of individual documents by breaking them into
    manageable chunks and processing them iteratively. It's designed for comprehensive
    document analysis tasks that require thorough examination of large files.
    
    The MapReduce approach ensures efficient processing of large documents while
    maintaining context and providing detailed, structured analysis results.
    
    Args:
        file_id (str): Unique identifier for the specific document to analyze.
            Must be a valid file ID from the tender document collection.
        analysis_objective (str): Clear description of what to extract or analyze.

    Examples:
            - "Extract all penalty clauses and their conditions"
            - "Summarize technical requirements and compliance standards"
            - "Identify all pricing structures and payment terms"
            - "Find all SLA requirements and performance metrics"
            - "Extract risk assessment criteria and mitigation strategies"
        tender_id (str): Unique identifier for the tender containing the document
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.

    Returns:
        Dict[str, Any]: Analysis results containing:
            - "summary" (str): High-level summary of findings related to the objective
            - "key_findings" (List[str]): Bullet-point list of specific findings
            - "relevant_sections" (List[str]): Document sections that support the analysis
            - "file_id" (str): The analyzed file identifier
            - "error" (str, optional): Error message if analysis fails

    Raises:
        Exception: Document not found, processing errors, or analysis failures are
            caught and returned as error dicts

    Examples:
        # Extract penalty clauses
        result = await iterative_document_analyzer(
            "doc_001",
            "Extract all penalty clauses and their specific conditions",
            "tender_123"
        )
        
        # Analyze technical requirements
        result = await iterative_document_analyzer(
            "doc_002",
            "Summarize all security compliance requirements and standards",
            "tender_123"
        )
        
        # Find pricing information
        result = await iterative_document_analyzer(
            "doc_003",
            "Identify all pricing structures, payment terms, and cost models",
            "tender_123"
        )
    """
    content = get_file_content_from_id(mongo_client, file_id, tender_id, org_id)
    
    if content == "No content available for this file":
        return {"error": f"File {file_id} not found"}

    analysis_prompt = f"""
    Analyze the following document content based on this objective: {analysis_objective}
    
    Document Content:
    {content}
    
    Please provide:
    1. A summary of findings related to the objective
    2. Key findings as bullet points
    3. Relevant sections that support the analysis
    """

    try:
        from langchain.chat_models import init_chat_model
        configurable_model = init_chat_model(model="gpt-4.1")
        model_with_structure = configurable_model.with_structured_output(AnalysisResult)
        message = HumanMessage(content=analysis_prompt)
        response = model_with_structure.invoke([message])
        return {"summary": response.summary, "key_findings": response.key_findings, "relevant_sections": response.relevant_sections, "file_id": response.file_id} 
    except Exception as e:
        logging.error(f"Error analyzing document: {e}")
        return {"error": f"Error analyzing document: {e}"}

@tool
@log_tool_call
async def web_search(query: str) -> Dict[str, Any]:
    """Search external sources for regulations, legal definitions, and market intelligence.
    
    This tool enables the agent to gather external information from web sources to
    provide context, validation, and additional insights for tender analysis.
    It's particularly useful for understanding regulations, industry standards,
    legal definitions, and market intelligence that may be relevant to the tender.
    
    The tool searches across multiple web sources and returns structured results
    that can be used to enhance the agent's understanding and analysis capabilities.
    
    Args:
        query (str): Search query for external information. Can be:
            - Regulatory queries: "ISO 27001 requirements Denmark"
            - Legal definitions: "penalty clause definition contract law"
            - Industry standards: "cloud security standards 2024"
            - Market intelligence: "IT infrastructure pricing trends Denmark"
            - Compliance requirements: "GDPR data protection requirements"
            - Technical specifications: "disaster recovery RTO RPO standards"
    
    Returns:
        Dict[str, Any]: Search results containing:
            - "context" (str): Relevant content extracted from web sources
            - "links" (List[str]): URLs of sources used for the information
            - "query" (str): The original search query
            - "success" (bool): Whether the search was successful
            - "error" (str, optional): Error message if search fails

    Raises:
        Exception: Network errors, search API failures, or content extraction
            errors are caught and returned as error dicts

    Examples:
        # Search for regulatory requirements
        result = await web_search("ISO 27001 security requirements Denmark")
        
        # Find legal definitions
        result = await web_search("penalty clause definition contract law")
        
        # Get market intelligence
        result = await web_search("cloud infrastructure pricing trends 2024")
        
        # Research compliance standards
        result = await web_search("GDPR data protection requirements IT services")
    """
    try:
        context, links = search({"orig_input": query})
        
        return {
            "context": context,
            "links": links,
            "query": query,
            "success": True
        }
    except Exception:
        return {
            "context": "No context available",
            "links": [],
            "query": query,
            "success": False,
        }

REACT_TOOLS = [
    consult_tender_manifest,
    targeted_hybrid_search,
    iterative_document_analyzer,
    web_search,
]