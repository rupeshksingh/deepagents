"""
FastAPI application entry point for Proposal Assistant API.
Clean, ChatGPT-like API with user → chat → message hierarchy.
"""

import os
import logging
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient
import uvicorn

from api.streaming_router import create_streaming_router
from api.models import ApiInfoResponse, HealthResponse
from api.store import ApiStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

env = os.getenv("ENV", "dev")
dotenv_file = f".env.{env}"
load_dotenv(dotenv_file)

os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "false")
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "")
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGCHAIN_API_KEY", "")
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

app = FastAPI(
    title="Proposal Assistant API",
    version="2.0.0",
    description="AI-powered proposal assistant with chat interface and streaming responses",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# MongoDB Connection
# ============================================================================

def get_mongo_client() -> MongoClient:
    """
    Create and validate MongoDB client connection.
    
    Returns:
        MongoClient: Connected MongoDB client
        
    Raises:
        Exception: If connection fails
    """
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    try:
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        logger.info(f"MongoDB connected successfully: {mongodb_uri}")
        return client
    except Exception as e:
        logger.error(f"MongoDB connection failed: {str(e)}")
        raise Exception(f"Failed to connect to MongoDB: {str(e)}")


try:
    mongo_client = get_mongo_client()
    mongodb_status = "connected"
except Exception as e:
    logger.warning(f"MongoDB initialization failed: {e}")
    mongo_client = None
    mongodb_status = "disconnected"


# ============================================================================
# Register API Router
# ============================================================================

if mongo_client:
    try:
        # Register streaming API router (MVP)
        streaming_router = create_streaming_router(mongo_client, db_name="proposal_assistant")
        app.include_router(streaming_router)
        logger.info("Streaming API router registered successfully")
    except Exception as e:
        logger.error(f"Failed to register streaming router: {e}")
        mongodb_status = "error"
else:
    logger.warning("API endpoints not available due to MongoDB connection failure")


# ============================================================================
# Root Endpoints
# ============================================================================

@app.get("/", response_model=dict, tags=["Root"])
async def root():
    """
    API root endpoint with basic information.
    """
    return {
        "name": "Proposal Assistant API",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "info": "/info"
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint to monitor API and service status.
    
    Returns:
        HealthResponse: Health status of various components
    """
    mongodb_health = "disconnected"
    if mongo_client:
        try:
            mongo_client.admin.command('ping')
            mongodb_health = "connected"
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            mongodb_health = "error"
    
    agent_health = "unknown"
    if mongo_client:
        try:
            store = ApiStore(mongo_client)  # noqa: F841
            agent_health = "ready"
        except Exception as e:
            logger.error(f"Agent health check failed: {e}")
            agent_health = "error"
    
    overall_status = "healthy"
    if mongodb_health != "connected":
        overall_status = "degraded"
    if mongodb_health == "error" or agent_health == "error":
        overall_status = "unhealthy"
    
    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now().isoformat(),
        mongodb=mongodb_health,
        agent=agent_health
    )


@app.get("/info", response_model=ApiInfoResponse, tags=["System"])
async def api_info():
    """
    Get API information including version, features, and endpoints.
    
    Returns:
        ApiInfoResponse: API metadata and information
    """
    return ApiInfoResponse(
        name="Proposal Assistant API",
        version="2.0.0",
        description="AI-powered proposal assistant with multi-agent support, streaming responses, and MongoDB persistence",
        endpoints=10,
        features=[
            "User management (auto-creation)",
            "Chat sessions with UUID",
            "Streaming AI responses (SSE)",
            "MongoDB persistence",
            "Multi-agent architecture",
            "LangGraph integration",
            "Conversation history",
            "RESTful design",
            "Pagination support",
            "Error handling"
        ]
    )


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for unhandled exceptions.
    
    Args:
        request: The FastAPI request
        exc: The exception that occurred
        
    Returns:
        JSONResponse: Error response
    """
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "path": str(request.url.path)
        }
    )


# ============================================================================
# Lifecycle Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """
    Application startup event handler.
    Logs startup information and verifies connections.
    """
    logger.info("=" * 60)
    logger.info("Starting Proposal Assistant API v2.0.0")
    logger.info("=" * 60)
    
    if mongo_client:
        logger.info("✓ MongoDB connection: OK")
        logger.info("✓ API endpoints: Registered")
        logger.info("✓ Agent service: Ready")
    else:
        logger.warning("✗ MongoDB connection: FAILED")
        logger.warning("✗ API endpoints: Not available")
    
    logger.info("=" * 60)
    logger.info("API is ready to accept requests")
    logger.info("Documentation: http://localhost:8000/docs")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Application shutdown event handler.
    Cleans up resources and closes connections.
    """
    logger.info("Shutting down Proposal Assistant API...")
    
    if mongo_client:
        try:
            mongo_client.close()
            logger.info("MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing MongoDB connection: {e}")
    
    logger.info("API shutdown complete")


# ============================================================================
# Run Application
# ============================================================================

if __name__ == "__main__":
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"Starting server on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
