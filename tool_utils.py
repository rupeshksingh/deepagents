import hashlib  # noqa: D100
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from bson import ObjectId  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever
from openai import OpenAI
from pydantic import Field
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO)


class CustomRetriever(BaseRetriever):
    """A custom retriever that combines multiple retrievers and implements reranking."""

    retrievers: List[BaseRetriever] = Field(default_factory=list)
    k: int = Field(default=10)
    p: int = Field(default=5)

    def __init__(self, retrievers: List[BaseRetriever], k: int = 10, p: int = 5) -> None:
        """Initialize the CustomRetriever.

        Args:
            retrievers: List of retrievers to use
            k: Number of documents to retrieve from each retriever
            p: Number of documents to return after reranking
        """
        super().__init__()
        self.__dict__["retrievers"] = retrievers
        self.__dict__["k"] = k
        self.__dict__["p"] = p

    def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for a list of texts using OpenAI's API.

        Args:
            texts: List of texts to get embeddings for

        Returns:
            List of embeddings
        """
        logging.info(f"Fetching embeddings for {len(texts)} texts...")
        try:
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.embeddings.create(input=texts, model="text-embedding-3-small")
            embeddings = [data.embedding for data in response.data]
            return embeddings
        except Exception as e:
            logging.error(f"Error getting embeddings: {e}")
            raise

    def _rerank_documents(self, query: str, documents: List[Document]) -> List[Document]:
        """Rerank documents based on their relevance to the query.

        Args:
            query: Query string
            documents: List of documents to rerank

        Returns:
            Reranked list of documents
        """
        if not documents:
            logging.info("No documents to rerank")
            return []

        try:
            # rerank_results = compressor.rerank(documents, query, top_n=self.p)
            rerank_results = []
        except Exception as e:
            logging.error(f"Error during reranking: {e}")
            logging.info("Falling back to first p documents")
            return documents[: self.p]

        sorted_documents = []
        for rerank in rerank_results:
            idx = rerank["index"]
            score = rerank["relevance_score"]

            if idx < 0 or idx >= len(documents):
                logging.error(f"Index {idx} is out of bounds for documents list")
                continue

            doc = documents[idx]
            doc.metadata["relevance_score"] = score
            sorted_documents.append(doc)

        return sorted_documents

    def remove_duplicates(self, documents: List[Document]) -> List[Document]:
        """Remove duplicate documents based on content hash.

        Args:
            documents: List of documents to deduplicate

        Returns:
            List of unique documents
        """
        logging.info(f"Removing duplicates from {len(documents)} documents")

        seen_identifiers = set()
        unique_documents = []

        for doc in documents:
            content_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
            identifier = f"hash:{content_hash}"

            if identifier not in seen_identifiers:
                seen_identifiers.add(identifier)
                unique_documents.append(doc)

        logging.info(f"Found {len(unique_documents)} unique documents")
        return unique_documents

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> List[Document]:
        """Get relevant documents for a query using multiple retrievers."""
        logging.info(f"Query: {query}...")
        documents = []
        for i, retriever in enumerate(self.retrievers):
            try:
                logging.info(f"Getting documents from retriever {i+1}")
                docs = retriever.invoke(query, config={"callbacks": run_manager.get_child(f"retriever_{i + 1}")})
                documents.extend(docs)
                logging.info(f"Retrieved {len(docs)} documents from retriever {i+1}")
            except Exception as e:
                logging.error(f"Error with retriever {i+1}: {e}")
                continue

        logging.info(f"Retrieved total of {len(documents)} documents before deduplication")
        for i, doc in enumerate(documents):
            logging.info(f"Document {i+1}: {doc.page_content[:100]}...")

        documents = self.remove_duplicates(documents)
        logging.info(f"Have {len(documents)} documents after deduplication")

        if documents:
            # reranked_documents = self._rerank_documents(query, documents)
            reranked_documents = documents
            logging.info(f"Reranked to {len(reranked_documents)} documents")
            return reranked_documents

        logging.info("No documents found")
        return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> List[Document]:
        """Async version of get_relevant_documents.

        Args:
            query: Query string
            run_manager: Callback manager for the retriever run

        Returns:
            List of relevant documents
        """
        return self._get_relevant_documents(query, run_manager=run_manager)

    def get_docs_without_callbacks(self, query: str, search_kwargs: Optional[Dict[str, Any]] = None) -> List[Document]:
        """Simplified version of document retrieval without callback manager.
        Useful for direct calls without LangChain's callback infrastructure.

        Args:
            query (str): The query string.
            search_kwargs (Optional[Dict[str, Any]]): Additional search parameters to override defaults.

        Returns:
            List[Document]: List of relevant, possibly reranked documents.
        """  # noqa: D205
        logging.info(f"Starting simple retrieval for query: {query} where k={self.k} and p={self.p}")
        documents: List[Document] = []

        try:
            final_search_kwargs = {"k": self.k}  # Start with default k
            if search_kwargs:
                final_search_kwargs.update(search_kwargs)  # Override with any provided kwargs

            for i, retriever in enumerate(self.retrievers):
                try:
                    logging.info(
                        f"Using sub-retriever {i+1}/{len(self.retrievers)} to get docs "
                        f"with k={final_search_kwargs.get('k', self.k)}"
                    )

                    if hasattr(retriever, "search_kwargs"):
                        original_kwargs = getattr(retriever, "search_kwargs", {}) or {}
                        setattr(
                            retriever,
                            "search_kwargs",
                            {
                                **original_kwargs,
                                **final_search_kwargs,
                            },
                        )

                    docs = retriever.invoke(query)
                    documents.extend(docs)
                    logging.info(f"Sub-retriever {i+1} returned {len(docs)} docs.")

                    if hasattr(retriever, "search_kwargs"):
                        setattr(retriever, "search_kwargs", original_kwargs)

                except Exception:
                    continue

            logging.info(f"Total docs from all sub-retrievers (before dedup): {len(documents)}")

            documents = self.remove_duplicates(documents)
            logging.info(f"Documents after deduplication: {len(documents)}")

            if documents:
                # reranked_documents = self._rerank_documents(query, documents)
                reranked_documents = documents
                logging.info(f"Returning top {min(len(reranked_documents), self.p)} reranked documents.")
                return reranked_documents[: self.p]

            logging.info("No documents found. Returning empty list.")
            return []

        except Exception:
            return []

def getVectorStore(collection_name):  # noqa: D103
    from langchain_openai import OpenAIEmbeddings
    from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
    
    sparse_embedding_model = FastEmbedSparse(model_name="Qdrant/bm25")
    dense_embedding_model = OpenAIEmbeddings(
        api_key=os.environ["OPENAI_API_KEY"], model="text-embedding-3-small"
    )

    vectorstore = QdrantVectorStore.from_existing_collection(
        embedding=dense_embedding_model,
        sparse_embedding=sparse_embedding_model,
        url=os.environ["QDRANT_HOST"],
        api_key=os.environ["QDRANT_API_KEY"],
        collection_name=collection_name,
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name="text-embedding-3-small",
        sparse_vector_name="bm25",
    )
    return vectorstore

def make_query(query: str) -> str:  # noqa: D103
    from langchain_openai import ChatOpenAI
    
    prompt = PromptTemplate(
        template="""
            You are an expert in query optimization. Your task is to **rewrite** a long query to fit within **50 words**, while keeping all essential details intact.

            **Guidelines:**
            - The **rewritten query must be self-sufficient**, meaning it should **contain all important information** from the original.
            - **No critical details should be lost**—restructure and rephrase concisely.
            - **All characters (letters, numbers, spaces, punctuation, etc.) count** towards the 300 limit.
            - If the original query is already **≤ 50 words**, return it unchanged.
            - Ensure **clarity** and **search optimization** while maintaining meaning.

            **Original Query:**
            {query}

            **Optimized Query (≤ 50 words):**
        """,
        input_variables=["query"],
    )
    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_tokens=50)

    chain = prompt | llm

    response = chain.invoke({"query": query})
    return response.content

def search(inputs: str) -> Tuple[str, List[str]]:  # noqa: D103
    max_results = 20
    query = inputs.get("orig_input", " ")
    tavily_query = make_query(query)

    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    if not TAVILY_API_KEY:
        raise ValueError("Tavily API key not found in environment variables")
 
    TAVILY_BASE_URL = "https://api.tavily.com"
    endpoint = f"{TAVILY_BASE_URL}/search"
    headers = {"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"}
    payload = {"query": tavily_query, "limit": max_results}
 
    response = requests.post(endpoint, json=payload, headers=headers)
    response.raise_for_status()
    data = response.json()
 
    results = data.get("results", [])
 
    context = "\n\n".join(
        f"{result.get('title', 'No Title')}\n{result.get('content', 'No Content')}" for result in results
    )
    tavily_links = [result["url"] for result in results if "url" in result and result["url"]]
    return context, tavily_links

def get_requirement_cluster_id(client: MongoClient, tender_id: str, org_id: int = 1) -> Optional[str]:
    """Get the requirement cluster id for a given tender id."""
    try:
        db = client[f"org_{org_id}"]
        proposals = db["proposals"]
        proposal = proposals.find_one({ "_id" : ObjectId(tender_id) })
        if proposal:
            return proposal.get("requirement_cluster_id")
        return None
    except Exception as e:
        logging.error(f"Error getting requirement cluster id: {e}")
        return None

def get_proposal_files(client: MongoClient, requirement_cluster_id: str, org_id: int = 1) -> Optional[List[Dict[str, Any]]]:
    """Get the proposal files from a given requirement cluster id."""
    try:
        db = client[f"org_{org_id}"]
        proposal_files = db["proposal_files"]
        files = proposal_files.find({ "cluster_id" : requirement_cluster_id })
        if files:
            return list(files)
        return None
    except Exception as e:
        logging.error(f"Error getting proposal files: {e}")
        return None

def get_proposal_summary(client: MongoClient, tender_id: str, org_id: int = 1) -> Optional[str]:
    """Get the proposal summary for a given tender id."""
    try:
        db = client[f"org_{org_id}"]
        proposals = db["proposals"]
        proposal = proposals.find_one({ "_id" : ObjectId(tender_id) })
        compliance_matrix_analysis = proposal["compliance_matrix_analysis"]
        if compliance_matrix_analysis is None:
            return None
        summary = ""
        for _, v in compliance_matrix_analysis.items():
            summary += f"{v}\n"
        return summary
    except Exception as e:
        logging.error(f"Error getting proposal summary: {e}")
        return None

def get_proposal_files_summary(client: MongoClient, tender_id: str, org_id: int = 1) -> Optional[List[Dict[str, Any]]]:
    """Get the proposal files summary for a given tender id."""
    try:
        db = client[f"org_{org_id}"]
        proposal_files = db["proposal_files"]
        proposals = db["proposals"]
        proposal = proposals.find_one({ "_id" : ObjectId(tender_id) })
        if proposal is None:
            return None
        file_id = proposal["requirement_cluster_id"]
        if file_id is None:
            return None
        files = proposal_files.find({ "cluster_id" : file_id })
        if files is None:
            return None
        return [
            {
                "file_id": doc.get("_id"),
                "file_name": doc.get("file_name"),
                "document_type": doc.get("file_extension"),
                "summary": doc.get("requirements_summary", {}).get("en") if doc.get("requirements_summary", {}).get("en") else list(doc.get("requirements_summary", {}).values())[0]
            }
            for doc in files
        ]
    except Exception as e:
        logging.error(f"Error getting proposal files summary: {e}")
        return None

def get_file_content_from_id(client: MongoClient, file_id: str, tender_id: str, org_id: int = 1) -> Optional[str]:
    """Get the file content from a given file id."""
    try:
        db = client[f"org_{org_id}"]
        proposal_files = db["proposal_files"]
        file = proposal_files.find_one({ "_id" : ObjectId(file_id) })
        if file:
            return file.get("extracted_markdown")
        return None
    except Exception as e:
        logging.error(f"Error getting file content from id: {e}")
        return None