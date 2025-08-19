# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Environment Setup
```bash
# Create virtual environment (if not exists)
/opt/homebrew/bin/python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Server
```bash
# Using the convenience script (recommended)
./run.sh

# Or using Python directly
python start_server.py

# Or using uvicorn directly
uvicorn web_server:app --host 0.0.0.0 --port 8081 --reload
```

### Testing
```bash
# Run tests
python test_server.py
```

## Architecture Overview

This is an AI Agent Web Server that acts as a bridge between:
- **Frontend** (localhost:3000) - Web-based chat interface
- **AI Agent Server** (localhost:8081) - This FastAPI server with OpenAI integration
- **Backend API** (localhost:8080) - User data and Notion data storage
- **MCP Server** - Notion API integration via FastMCP

### Key Components

- **`web_server.py`**: Main FastAPI application with chat endpoints and AI agent logic
- **`server.py`**: MCP server providing Notion API tools (search, page retrieval, etc.)
- **`start_server.py`**: Server startup script
- **`client.py`**: Legacy terminal-based client (reference only)

### Data Flow
1. Frontend sends chat messages to `/api/chat`
2. AI agent processes message using OpenAI API
3. If needed, calls MCP tools for Notion operations
4. Retrieves/stores user data via backend API
5. Returns processed response to frontend

## Environment Variables

Required `.env` file variables:
- `OPENAI_API_KEY`: OpenAI API key (required)
- `NOTION_TOKEN`: Notion integration token (required)
- `OPENAI_MODEL`: OpenAI model to use (default: gpt-4o-mini)
- `MCP_SERVER_PATH`: Path to MCP server (default: server.py)
- `BACKEND_BASE_URL`: Backend API base URL (default: http://localhost:8080)

## API Endpoints

- `POST /api/chat`: Main chat endpoint for AI agent interaction
- `GET /api/health`: Server health check with MCP connection status
- `GET /docs`: FastAPI automatic documentation
- `GET /redoc`: Alternative API documentation

## Backend API Schema

### Notion Data Storage
The `save_notion_data_to_backend` MCP tool uses a 5-parameter schema:
- `user_id`: User identifier
- `content`: Full Notion page text content 
- `notion_url`: Notion page URL (from search results)
- `notion_page_id`: Notion page ID
- `summary`: Concise 2-3 sentence summary of the page content

### Workflow for STEP 2: Content Analysis and Storage
1. Use `notion_search_with_user` to find pages (STEP 1)
2. Use `notion_page_content_with_user` to get full content for each page
3. Create 2-3 sentence summaries for each page
4. Use `save_notion_data_to_backend` with the 5-parameter schema to store
5. Log completion: "STEP 2 COMPLETE: Stored [X] pages with summaries in database"

## Development Notes

- Server runs on port 8081 by default
- Auto-reload is enabled in development mode
- CORS is configured for localhost:3000 frontend
- MCP client connects to local Notion API server
- Korean language support throughout the codebase
- MCP tools are designed with step-by-step workflow comments for AI agents