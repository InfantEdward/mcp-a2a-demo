# AgenticFlow: MCP + A2A Demo

A distributed agent orchestration system showcasing the **Agent-to-Agent (A2A)** and **Model Context Protocol (MCP)** standards using LangChain.

## Architecture
- **Dynamic Router**: Uses an LLM to route requests based on Agent Cards.
- **Data-Driven Agents**: Define agents via JSON in `/agents` and their MCP tools in `/implementations`.
- **Observability**: Real-time Event Inspector for raw JSON-RPC protocol traffic.

## Quick Start
1. Create a `.env` file with your `GEMINI_API_KEY`.
2. (Optional) Set `DEFAULT_MODEL` (defaults to `gemini-2.0-flash`).
3. Run the application:

```bash
docker build -t app . && docker run -p 8000:8000 app
```

Open [http://localhost:8000](http://localhost:8000) to start.

## Dynamic Agents
- **Agent Cards (`/agents`)**: Public A2A metadata (identity, skills).
- **Tool Sidecars (`/implementations`)**: Private MCP configurations (server paths).
