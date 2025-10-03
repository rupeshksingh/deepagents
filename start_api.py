#!/usr/bin/env python3
"""
Startup script for the Proposal Assistant API

This script starts the FastAPI server with proper configuration.
"""

import os
import uvicorn
from dotenv import load_dotenv

def main():
    """Start the API server"""
    load_dotenv()
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    workers = int(os.getenv("API_WORKERS", "1"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    
    print(f"Starting Proposal Assistant API on {host}:{port}")
    print(f"Workers: {workers}, Reload: {reload}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_level="info"
    )

if __name__ == "__main__":
    main()
