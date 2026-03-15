from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import json
from backend.event_logger import event_logger
from backend.a2a_orchestrator import adk_executor
from backend.human_news_agent import PendingNewsStore, create_human_news_app
from backend.token_tracker import token_tracker
from dotenv import load_dotenv
from typing import Any
from pydantic import BaseModel
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities

load_dotenv()
card = AgentCard(
    name="LangChain-MCP-A2A Demo Agent",
    description="A demonstration of A2A and MCP protocols using LangChain.",
    url="http://127.0.0.1:8000/api/a2a/",
    version="1.1.0",
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(),
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=adk_executor, task_store=InMemoryTaskStore()
)

a2a_app = A2AFastAPIApplication(agent_card=card, http_handler=handler).build()

app = FastAPI()

app.mount("/api/a2a", a2a_app)


class RemoteLog(BaseModel):
    source: str
    type: str
    payload: Any


def _load_agent_card(path: str) -> dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


news_pending_store = PendingNewsStore()
news_card = _load_agent_card("agents/news_specialist.json")
app.mount(
    "/api/news-agent",
    create_human_news_app(news_card, news_pending_store),
)


@app.get("/api/demo/network")
async def get_demo_network_metadata():
    math_card = _load_agent_card("agents/math_specialist.json")
    weather_card = _load_agent_card("agents/weather_specialist.json")
    news_card = _load_agent_card("agents/news_specialist.json")

    return {
        "nodes": {
            "browser": {
                "title": "Browser Client",
                "description": "Sends JSON-RPC A2A requests to the orchestrator.",
                "kind": "client",
            },
            "manager": {
                "title": card.name,
                "description": card.description,
                "kind": "manager",
                "agent_card": card.model_dump(),
            },
            "math": {
                "title": math_card["name"],
                "description": math_card["description"],
                "kind": "specialist",
                "agent_card": math_card,
                "tool_schema": {
                    "server": "MathTools",
                    "tools": [
                        {
                            "name": "add",
                            "description": "Add two numbers.",
                            "arguments": {"a": "float", "b": "float"},
                        },
                        {
                            "name": "subtract",
                            "description": "Subtract two numbers.",
                            "arguments": {"a": "float", "b": "float"},
                        },
                        {
                            "name": "multiply",
                            "description": "Multiply two numbers.",
                            "arguments": {"a": "float", "b": "float"},
                        },
                        {
                            "name": "divide",
                            "description": "Divide two numbers.",
                            "arguments": {"a": "float", "b": "float"},
                        },
                        {
                            "name": "get_current_time",
                            "description": "Get the current time.",
                            "arguments": {},
                        },
                    ],
                },
            },
            "weather": {
                "title": weather_card["name"],
                "description": weather_card["description"],
                "kind": "specialist",
                "agent_card": weather_card,
                "tool_schema": {
                    "server": "WeatherTools",
                    "tools": [
                        {
                            "name": "get_current_weather",
                            "description": "Return hardcoded current weather for a city.",
                            "arguments": {"city": "string"},
                        },
                        {
                            "name": "get_three_day_forecast",
                            "description": "Return hardcoded three-day forecast.",
                            "arguments": {"city": "string"},
                        },
                        {
                            "name": "get_weather_alerts",
                            "description": "Return hardcoded weather alerts.",
                            "arguments": {"city": "string"},
                        },
                        {
                            "name": "compare_weather",
                            "description": "Compare weather conditions between two cities.",
                            "arguments": {"city_a": "string", "city_b": "string"},
                        },
                        {
                            "name": "plan_outdoor_activity",
                            "description": "Suggest activity plans based on weather conditions.",
                            "arguments": {"city": "string"},
                        },
                    ],
                },
            },
            "news": {
                "title": news_card["name"],
                "description": news_card["description"],
                "kind": "specialist",
                "agent_card": news_card,
                "tool_schema": {
                    "server": "HumanInbox",
                    "tools": [
                        {
                            "name": "request_news_update",
                            "description": "Queues a news request for a human analyst and returns the typed response as the agent output.",
                            "arguments": {"query": "string"},
                        }
                    ],
                },
            },
            "mcp": {
                "title": "MCP Tool Servers",
                "description": "FastMCP servers accessed over stdio by specialist agents.",
                "kind": "tools",
                "servers": [
                    {
                        "name": "MathTools",
                        "module": "backend.mcp_server",
                    },
                    {
                        "name": "WeatherTools",
                        "module": "backend.weather_mcp_server",
                    },
                ],
            },
        }
    }


@app.post("/api/log")
async def receive_remote_log(log: RemoteLog):
    if log.source == "Token Tracker" and log.type == "Usage Update":
        if isinstance(log.payload, dict):
            token_tracker.merge_snapshot(log.payload)
        merged = token_tracker.snapshot()
        await event_logger.broadcast("Token Tracker", "Usage Update", merged)
        return {"status": "ok", "merged": True}

    await event_logger.broadcast(log.source, log.type, log.payload)
    return {"status": "ok"}


@app.get("/api/metrics/tokens")
async def get_token_metrics():
    return token_tracker.snapshot()


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await event_logger.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        event_logger.disconnect(websocket)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
