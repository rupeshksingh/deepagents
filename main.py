import os
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import MongoClient

from api.router import create_query_routers

app = FastAPI(
    title="Proposal Assistant API", 
    version="1.0.0",
    description="API for managing queries and responses using Deep Agents library"
)

env = os.getenv("ENV", "dev")
dotenv_file = f".env.{env}"
load_dotenv(dotenv_file)

os.environ["LANGCHAIN_TRACING_V2"] = os.getenv("LANGCHAIN_TRACING_V2", "false")
os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "")
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGCHAIN_API_KEY", "")
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

def get_mongo_client() -> MongoClient:
    """Get MongoDB client instance"""
    mongodb_uri = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    try:
        client = MongoClient(mongodb_uri)
        client.admin.command('ping')
        return client
    except Exception as e:
        raise Exception(f"Failed to connect to MongoDB: {str(e)}")

try:
    mongo_client = get_mongo_client()
except Exception as e:
    print(f"Warning: MongoDB connection failed: {e}")
    mongo_client = None

if mongo_client:
    query_routers = create_query_routers(mongo_client)
    app.include_router(query_routers.query_router)
else:
    print("Warning: Query endpoints will not be available due to MongoDB connection failure")

@app.get("/health")
def health_check():
    """Health check endpoint"""
    mongodb_status = "connected" if mongo_client else "disconnected"
    return {
        "status": "healthy" if mongodb_status == "connected" else "degraded",
        "timestamp": datetime.now().isoformat(),
        "mongodb": mongodb_status,
        "api": "1.0.0"
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for unhandled exceptions"""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "path": str(request.url)
        }
    )

@app.on_event("startup")
async def startup_event():
    """Application startup event"""
    print("Starting Proposal Assistant API...")
    if mongo_client:    
        print("MongoDB connection established")
    else:
        print("Warning: MongoDB connection not available")

@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event"""
    print("Shutting down Proposal Assistant API...")
    if mongo_client:
        mongo_client.close()
        print("MongoDB connection closed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
