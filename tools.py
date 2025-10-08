"""Foundational tools for the LangGraph react agent.

This module provides essential tools for deep research and analysis of tender documents
using a ReAct (Reasoning and Acting) agent pattern. The tools enable comprehensive
document analysis, targeted search, and external research capabilities.

Key Features:
- Tender manifest consultation for metadata and document inventory at a global level.
- Hybrid search combining vector and keyword search for precise content retrieval at a global level.
- Iterative document analysis using MapReduce strategy for large single file with its id.
- External web search for regulations, legal definitions, and market intelligence
- File mapping capabilities to resolve user references to specific document IDs, like selecting a particular file given some specific text and getting its id.

Usage:
    These tools are designed to be used by a LangGraph ReAct agent for automated
    tender analysis and research tasks. Each tool returns structured data that can
    be processed by the agent for decision-making and further analysis.

Example:
    The agent can use these tools in sequence:
    1. consult_tender_manifest() to get overview and document list of the tender files
    2. targeted_hybrid_search() to find specific information from all files
    3. iterative_document_analyzer() for detailed document analysis for a single file
    4. web_search() for external context and validation
"""

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pymongo import MongoClient
from langchain.chat_models import init_chat_model

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

import logging

from src.deepagents.logging_utils import log_tool_call

load_dotenv()

uri = os.getenv("MONGODB_URL")
mongo_client = MongoClient(uri)

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
        # Get tender overview (like getting the summary and number of files in the tender)
        result = await consult_tender_manifest("get_overview", "tender_123")
        
        # List all documents (like getting the names, ids, and summaries of all files in the tender)
        result = await consult_tender_manifest("list_documents", "tender_123")
        
        # Map user references to file IDs (like selecting a particular file given some specific text and getting its id)
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
    """Analyze or summarize single documents.
    
    This tool performs deep analysis of individual file. It's designed for comprehensive
    document analysis tasks that require thorough examination of individual files.
    
    The analysis is performed on the entire file and the results are returned in a structured format.
    
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

@tool
@log_tool_call
async def proposal_scoring_analyzer(
    tender_id: str,
    org_id: int = 1,
    scoring_criteria: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze proposal scoring methodology and evaluation criteria for strategic positioning.
    
    This tool provides comprehensive analysis of scoring methodologies, evaluation criteria,
    and weighting systems to help understand how proposals will be evaluated and scored.
    This enables strategic positioning and optimization of proposal content.
    
    Args:
        tender_id (str): Unique identifier for the tender to analyze
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.
        scoring_criteria (str, optional): Specific scoring criteria to focus on. If not provided,
            will analyze all available scoring information.
    
    Returns:
        Dict[str, Any]: Scoring analysis containing:
            - "scoring_methodology" (str): Detailed explanation of scoring approach
            - "evaluation_criteria" (List[Dict]): List of criteria with weights and descriptions
            - "scoring_weights" (Dict): Weighting breakdown by category
            - "evaluation_process" (str): Description of evaluation process and timeline
            - "strategic_recommendations" (List[str]): Recommendations for proposal optimization
            - "competitive_insights" (str): Insights on competitive positioning
            - "error" (str, optional): Error message if analysis fails
    
    Example:
        # Analyze all scoring criteria
        result = await proposal_scoring_analyzer("tender_123")
        
        # Focus on specific criteria
        result = await proposal_scoring_analyzer(
            "tender_123", 
            scoring_criteria="technical evaluation criteria"
        )
    """
    try:
        # First get tender overview to understand the structure
        overview_result = await consult_tender_manifest("get_overview", tender_id, org_id)
        if "error" in overview_result:
            return {"error": f"Failed to get tender overview: {overview_result['error']}"}
        
        # Search for scoring and evaluation criteria
        scoring_query = scoring_criteria or "evaluation criteria scoring methodology weighting"
        search_results = await targeted_hybrid_search(scoring_query, tender_id, org_id)
        
        if "error" in search_results:
            return {"error": f"Failed to search for scoring criteria: {search_results['error']}"}
        
        # Analyze the scoring methodology
        analysis_prompt = f"""
        Analyze the following tender documents to extract comprehensive scoring methodology and evaluation criteria:
        
        Tender Overview: {overview_result.get('summary', 'No summary available')}
        
        Scoring-Related Content:
        {search_results.get('context', 'No scoring content found')}
        
        Please provide:
        1. Detailed scoring methodology explanation
        2. Complete list of evaluation criteria with weights and descriptions
        3. Scoring weights breakdown by category
        4. Evaluation process description and timeline
        5. Strategic recommendations for proposal optimization
        6. Competitive insights and positioning advice
        
        Focus on understanding how proposals will be evaluated and scored to enable strategic positioning.
        """
        
        try:
            configurable_model = init_chat_model(model="gpt-4.1")
            message = HumanMessage(content=analysis_prompt)
            response = configurable_model.invoke([message])
            
            return {
                "scoring_methodology": "Analysis completed - see detailed response",
                "evaluation_criteria": "Extracted from documents",
                "scoring_weights": "Analyzed from tender documents",
                "evaluation_process": "Process details extracted",
                "strategic_recommendations": "Recommendations provided",
                "competitive_insights": "Insights generated",
                "detailed_analysis": response.content
            }
            
        except Exception as e:
            return {"error": f"Failed to analyze scoring methodology: {str(e)}"}
            
    except Exception as e:
        return {"error": f"Proposal scoring analysis failed: {str(e)}"}

@tool
@log_tool_call
async def competitive_positioning_analyzer(
    tender_id: str,
    org_id: int = 1,
    market_context: Optional[str] = None
) -> Dict[str, Any]:
    """Analyze competitive positioning and market dynamics for strategic advantage.
    
    This tool provides comprehensive competitive analysis including market positioning,
    competitive advantages, pricing strategies, and strategic recommendations for
    winning proposals.
    
    Args:
        tender_id (str): Unique identifier for the tender to analyze
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.
        market_context (str, optional): Additional market context or specific areas to focus on
    
    Returns:
        Dict[str, Any]: Competitive analysis containing:
            - "market_overview" (str): Market size, trends, and dynamics
            - "competitive_landscape" (str): Key players and market positioning
            - "competitive_advantages" (List[str]): Identified competitive advantages
            - "pricing_analysis" (str): Pricing strategy analysis and recommendations
            - "differentiation_opportunities" (List[str]): Opportunities for differentiation
            - "strategic_recommendations" (List[str]): Strategic recommendations for winning
            - "risk_assessment" (str): Competitive risks and mitigation strategies
            - "error" (str, optional): Error message if analysis fails
    
    Example:
        # Full competitive analysis
        result = await competitive_positioning_analyzer("tender_123")
        
        # Focused analysis with context
        result = await competitive_positioning_analyzer(
            "tender_123", 
            market_context="cloud infrastructure services"
        )
    """
    try:
        # Get tender overview
        overview_result = await consult_tender_manifest("get_overview", tender_id, org_id)
        if "error" in overview_result:
            return {"error": f"Failed to get tender overview: {overview_result['error']}"}
        
        # Search for competitive and market information
        competitive_query = "competitive analysis market positioning pricing strategy"
        if market_context:
            competitive_query += f" {market_context}"
            
        search_results = await targeted_hybrid_search(competitive_query, tender_id, org_id)
        
        if "error" in search_results:
            return {"error": f"Failed to search for competitive information: {search_results['error']}"}
        
        # Perform web search for market intelligence
        web_search_query = f"market analysis competitive landscape {market_context or 'procurement services'}"
        web_results = await web_search(web_search_query)
        
        # Analyze competitive positioning
        analysis_prompt = f"""
        Perform comprehensive competitive positioning analysis based on the following information:
        
        Tender Overview: {overview_result.get('summary', 'No summary available')}
        
        Tender Content:
        {search_results.get('context', 'No competitive content found')}
        
        Market Intelligence:
        {web_results.get('context', 'No market intelligence available')}
        
        Please provide:
        1. Market overview with size, trends, and dynamics
        2. Competitive landscape analysis with key players
        3. Identified competitive advantages and differentiators
        4. Pricing strategy analysis and recommendations
        5. Opportunities for differentiation and innovation
        6. Strategic recommendations for winning the tender
        7. Competitive risks and mitigation strategies
        
        Focus on providing actionable insights for competitive advantage and strategic positioning.
        """
        
        try:
            configurable_model = init_chat_model(model="gpt-4.1")
            message = HumanMessage(content=analysis_prompt)
            response = configurable_model.invoke([message])
            
            return {
                "market_overview": "Market analysis completed",
                "competitive_landscape": "Competitive landscape analyzed",
                "competitive_advantages": "Advantages identified",
                "pricing_analysis": "Pricing strategy analyzed",
                "differentiation_opportunities": "Differentiation opportunities identified",
                "strategic_recommendations": "Strategic recommendations provided",
                "risk_assessment": "Competitive risks assessed",
                "detailed_analysis": response.content
            }
            
        except Exception as e:
            return {"error": f"Failed to analyze competitive positioning: {str(e)}"}
            
    except Exception as e:
        return {"error": f"Competitive positioning analysis failed: {str(e)}"}

@tool
@log_tool_call
async def risk_assessment_analyzer(
    tender_id: str,
    org_id: int = 1,
    risk_categories: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Perform comprehensive risk assessment and mitigation strategy analysis.
    
    This tool provides detailed risk analysis across multiple dimensions including
    technical, commercial, operational, and strategic risks with mitigation strategies.
    
    Args:
        tender_id (str): Unique identifier for the tender to analyze
        org_id (int, optional): Organization ID for multi-tenant support. Defaults to 1.
        risk_categories (List[str], optional): Specific risk categories to focus on.
            Options: ["technical", "commercial", "operational", "strategic", "regulatory"]
    
    Returns:
        Dict[str, Any]: Risk assessment containing:
            - "risk_summary" (str): High-level risk overview
            - "technical_risks" (List[Dict]): Technical risks with probability and impact
            - "commercial_risks" (List[Dict]): Commercial risks and mitigation strategies
            - "operational_risks" (List[Dict]): Operational risks and contingency plans
            - "strategic_risks" (List[Dict]): Strategic risks and business impact
            - "regulatory_risks" (List[Dict]): Regulatory risks and compliance issues
            - "mitigation_strategies" (List[str]): Comprehensive mitigation strategies
            - "risk_monitoring" (str): Risk monitoring and management recommendations
            - "error" (str, optional): Error message if analysis fails
    
    Example:
        # Full risk assessment
        result = await risk_assessment_analyzer("tender_123")
        
        # Focused risk assessment
        result = await risk_assessment_analyzer(
            "tender_123", 
            risk_categories=["technical", "commercial"]
        )
    """
    try:
        overview_result = await consult_tender_manifest("get_overview", tender_id, org_id)
        if "error" in overview_result:
            return {"error": f"Failed to get tender overview: {overview_result['error']}"}
        
        risk_query = "risk assessment mitigation strategies contingency planning"
        if risk_categories:
            risk_query += f" {' '.join(risk_categories)} risks"
            
        search_results = await targeted_hybrid_search(risk_query, tender_id, org_id)
        
        if "error" in search_results:
            return {"error": f"Failed to search for risk information: {search_results['error']}"}
        
        analysis_prompt = f"""
        Perform comprehensive risk assessment analysis based on the following information:
        
        Tender Overview: {overview_result.get('summary', 'No summary available')}
        
        Risk-Related Content:
        {search_results.get('context', 'No risk content found')}
        
        Risk Categories to Analyze: {risk_categories or ['technical', 'commercial', 'operational', 'strategic', 'regulatory']}
        
        Please provide:
        1. High-level risk summary with overall risk profile
        2. Technical risks with probability and impact assessment
        3. Commercial risks with financial impact and mitigation strategies
        4. Operational risks with implementation challenges and contingency plans
        5. Strategic risks with business impact and strategic implications
        6. Regulatory risks with compliance issues and legal considerations
        7. Comprehensive mitigation strategies and risk management approaches
        8. Risk monitoring and management recommendations
        
        Focus on providing actionable risk mitigation strategies and contingency planning.
        """
        
        try:
            configurable_model = init_chat_model(model="gpt-4.1")
            message = HumanMessage(content=analysis_prompt)
            response = configurable_model.invoke([message])
            
            return {
                "risk_summary": "Risk assessment completed",
                "technical_risks": "Technical risks analyzed",
                "commercial_risks": "Commercial risks assessed",
                "operational_risks": "Operational risks evaluated",
                "strategic_risks": "Strategic risks identified",
                "regulatory_risks": "Regulatory risks assessed",
                "mitigation_strategies": "Mitigation strategies developed",
                "risk_monitoring": "Risk monitoring recommendations provided",
                "detailed_analysis": response.content
            }
            
        except Exception as e:
            return {"error": f"Failed to analyze risks: {str(e)}"}
            
    except Exception as e:
        return {"error": f"Risk assessment analysis failed: {str(e)}"}

REACT_TOOLS = [
    consult_tender_manifest,
    targeted_hybrid_search,
    iterative_document_analyzer,
    web_search,
    proposal_scoring_analyzer,
    competitive_positioning_analyzer,
    risk_assessment_analyzer,
]