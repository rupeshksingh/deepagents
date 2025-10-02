# Tender Analysis React Agent

A sophisticated React agent built using the Deep Agents library for comprehensive tender analysis and document processing. This agent provides intelligent analysis of tender documents, maintains conversation context, and uses multi-agent architecture for specialized tasks.

## Features

### 🤖 **Multi-Agent Architecture**
- **Document Analyzer**: Specialized agent for analyzing tender documents and extracting key information
- **Research Agent**: Conducts market research and competitive intelligence
- **Compliance Checker**: Verifies compliance requirements and identifies gaps

### 🧠 **Memory Management**
- Maintains conversation context across multiple queries
- Remembers tender ID throughout the conversation
- Builds upon previous analysis in subsequent interactions
- Tracks conversation history for context-aware responses

### 🔧 **Custom Tools**
- **Tender Search**: Search for relevant documents within a specific tender
- **Document Analysis**: Analyze specific documents by file ID
- **Web Search**: Search the web for additional information
- **File Content Retrieval**: Get full content of specific files
- **Tender Summary**: Get comprehensive summaries of tenders and their files

### 📊 **Advanced Capabilities**
- Vector-based document search using Qdrant
- MongoDB integration for tender data
- Web search integration via Tavily API
- Document reranking using Cohere
- Custom retriever with deduplication

## Installation

### Prerequisites
```bash
pip install pymongo python-dotenv langchain langchain-openai langchain-qdrant langchain-cohere tavily-python
```

### Environment Variables
Create a `.env` file with the following variables:
```env
MONGODB_URI=mongodb://localhost:27017
OPENAI_API_KEY=your_openai_api_key
QDRANT_HOST=your_qdrant_host
QDRANT_API_KEY=your_qdrant_api_key
TAVILY_API_KEY=your_tavily_api_key
COHERE_API_KEY=your_cohere_api_key
```

## Usage

### Basic Usage

```python
from react_agent import TenderAnalysisAgent

# Initialize the agent
agent = TenderAnalysisAgent(org_id=1)

# First query with tender ID
response = agent.chat(
    user_query="Can you analyze this tender and tell me about the main requirements?",
    tender_id="507f1f77bcf86cd799439011"
)

# Follow-up queries (tender ID is remembered)
response2 = agent.chat("What are the compliance requirements for this tender?")
response3 = agent.chat("Can you research similar tenders in the market?")
```

### Advanced Usage

```python
# Set tender ID explicitly
agent.set_tender_id("507f1f77bcf86cd799439011")

# Get conversation history
history = agent.get_conversation_history()

# Clear conversation history
agent.clear_history()
```

### Interactive Demo

Run the interactive demo:
```bash
python test_react_agent.py
```

## Architecture

### Agent Structure
```
TenderAnalysisAgent
├── Main Agent (Deep Agent)
│   ├── Custom Tools
│   │   ├── search_tender_documents
│   │   ├── analyze_document
│   │   ├── web_search
│   │   ├── get_file_content
│   │   └── get_tender_summary
│   └── Subagents
│       ├── document-analyzer
│       ├── research-agent
│       └── compliance-checker
└── Memory Management
    ├── Conversation History
    ├── Tender ID Context
    └── State Persistence
```

### Tool Integration

The agent integrates with several external services:

1. **MongoDB**: Stores tender documents and metadata
2. **Qdrant**: Vector database for document search
3. **OpenAI**: Language model and embeddings
4. **Tavily**: Web search API
5. **Cohere**: Document reranking

## Customization

### Adding New Tools

```python
from langchain_core.tools import tool

@tool
def custom_tool(query: str) -> str:
    """Custom tool description."""
    # Your tool implementation
    return result

# Add to agent tools list
tools.append(custom_tool)
```

### Creating Custom Subagents

```python
custom_subagent = {
    "name": "custom-analyzer",
    "description": "Description of what this subagent does",
    "prompt": "Detailed prompt for the subagent",
    "tools": [custom_tool]  # Optional: specific tools for this subagent
}
```

### Modifying System Prompts

The agent uses custom system prompts for different components:

- **Main Agent**: Comprehensive tender analysis instructions
- **Document Analyzer**: Specialized document analysis prompt
- **Research Agent**: Research-focused prompt
- **Compliance Checker**: Compliance verification prompt

## Testing

### Running Tests
```bash
python test_react_agent.py
```

### Test Coverage
- Basic functionality
- Chat functionality
- Tools and subagents
- Memory management
- Interactive demo

## Error Handling

The agent includes comprehensive error handling:

- Graceful degradation when dependencies are missing
- Error logging for debugging
- User-friendly error messages
- Fallback mechanisms for tool failures

## Performance Considerations

- **Vector Search**: Optimized with hybrid retrieval (dense + sparse)
- **Document Reranking**: Uses Cohere for relevance scoring
- **Deduplication**: Removes duplicate documents based on content hash
- **Caching**: Implements prompt caching for efficiency
- **Parallel Processing**: Supports concurrent subagent execution

## Limitations

- Requires MongoDB with specific schema
- Depends on external APIs (OpenAI, Tavily, Cohere, Qdrant)
- Memory is not persisted across application restarts
- Limited to English language processing

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions and support, please open an issue in the repository or contact the development team.

---

**Note**: This agent is designed for tender analysis and document processing. Ensure you have the necessary permissions and access to the required databases and APIs before deployment.
