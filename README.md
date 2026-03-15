# AgenticFlow: MCP + A2A Demo

A distributed agent orchestration system showcasing the **Agent-to-Agent (A2A)** and **Model Context Protocol (MCP)** standards using LangChain.

## Architecture
- **Dynamic Router**: Uses an LLM to route requests based on Agent Cards.
- **Data-Driven Agents**: Define agents via JSON in `/agents` and their MCP tools in `/implementations`.
- **Human-Backed News Agent**: A discoverable A2A News Specialist that pauses for a reply from the UI inbox panel.
- **Observability**: Real-time Event Inspector for raw JSON-RPC protocol traffic.

## Quick Start
1. Create a `.env` file with your `GEMINI_API_KEY`.
2. (Optional) Set `DEFAULT_MODEL` (defaults to `gemini-3-flash-preview`).
3. Start the stack with either Docker Compose or pure Python.

### Option A: Docker Compose

```bash
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000) to start.

### Option B: Python (No Docker)

Install dependencies:

```bash
uv sync
```

Run in 3 terminals from the repo root:

Terminal 1 (Orchestrator + UI):

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

This process also serves the embedded `NewsSpecialist` agent at `/api/news-agent` and its human-response inbox in the sidebar UI.

Terminal 2 (Math specialist):

```bash
uv run python -m backend.agent_server --agent math_specialist --port 8001
```

Terminal 3 (Weather specialist):

```bash
uv run python -m backend.agent_server --agent weather_specialist --port 8002
```

## Dynamic Agents
- **Agent Cards (`/agents`)**: Public A2A metadata (identity, skills).
- **Tool Sidecars (`/implementations`)**: Private MCP configurations (server paths).
