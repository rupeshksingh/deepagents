#!/bin/bash

# Start the FastAPI server with uvicorn
# Usage: ./start_api.sh

cd "$(dirname "$0")"
source venv/bin/activate

echo "Starting Proposal Assistant API with uvicorn..."
echo "API will be available at: http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo "Press Ctrl+C to stop"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8000 --reload

