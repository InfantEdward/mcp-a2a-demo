import traceback
import uuid
import json
import logging
import httpx
import os
import contextvars
from dotenv import load_dotenv

load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool

from langchain.agents import create_agent

from a2a.server.agent_execution import (
    AgentExecutor as A2AAgentExecutor,
    RequestContext,
)
from a2a.types import (
    TaskStatusUpdateEvent,
    TaskStatus,
    TaskState,
    Message,
    TextPart,
)
from backend.event_logger import event_logger
from backend.token_tracker import token_tracker
from backend.token_usage import extract_tokens_from_response

logger = logging.getLogger("Orchestrator")
MODEL_NAME = os.getenv("DEFAULT_MODEL", "gemini-3-flash-preview")
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "Missing Gemini API key. Set GEMINI_API_KEY or GOOGLE_API_KEY."
    )


active_context_id_var = contextvars.ContextVar("active_context_id", default=None)
active_task_id_var = contextvars.ContextVar("active_task_id", default=None)
AGENT_CARD_PATH = "/.well-known/agent-card.json"


def get_discovery_hosts() -> list[str]:
    hosts = os.getenv(
        "DISCOVERY_HOSTS",
        "http://127.0.0.1:8001,http://127.0.0.1:8002,http://127.0.0.1:8000/api/news-agent",
    )
    return [host.strip() for host in hosts.split(",") if host.strip()]


def build_agent_card_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith(AGENT_CARD_PATH):
        return normalized
    return f"{normalized}{AGENT_CARD_PATH}"


@tool
async def discover_network_agents() -> str:
    """
    Fetches the profiles of available specialized agents on the network.
    Call this when you need to know who is available to help you solve a user's request.
    """
    known_hosts = get_discovery_hosts()
    found_agents = []
    context_id = active_context_id_var.get()
    task_id = active_task_id_var.get()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for host in known_hosts:
            card_url = build_agent_card_url(host)
            try:
                discovery_request = {
                    "method": "GET",
                    "base_url": host,
                    "url": card_url,
                    "purpose": "agent_card_discovery",
                    "context_id": context_id,
                    "task_id": task_id,
                }
                await event_logger.broadcast(
                    "A2A Discovery Client",
                    "Discovery Request",
                    discovery_request,
                )

                logger.info(f"Manager is pinging {card_url} for discovery...")
                resp = await client.get(card_url, timeout=3.0)
                discovery_response = {
                    "method": "GET",
                    "base_url": host,
                    "url": card_url,
                    "status_code": resp.status_code,
                    "context_id": context_id,
                    "task_id": task_id,
                    "body": (
                        resp.json() if resp.status_code == 200 else resp.text
                    ),
                }
                await event_logger.broadcast(
                    "A2A Discovery Client",
                    "Discovery Response",
                    discovery_response,
                )
                if resp.status_code == 200:
                    card = resp.json()
                    found_agents.append(
                        f"Agent Name: {card['name']}\nA2A Target URL: {card['url']}\nCapabilities: {card['description']}"
                    )
            except Exception as e:
                logger.warning(f"Failed to reach {host}: {e}")
                await event_logger.broadcast(
                    "A2A Discovery Client",
                    "Discovery Error",
                    {
                        "method": "GET",
                        "base_url": host,
                        "url": card_url,
                        "context_id": context_id,
                        "task_id": task_id,
                        "error": str(e),
                    },
                )
                continue

    if not found_agents:
        return "No agents found on the network right now."
    return "Available Agents:\n\n" + "\n---\n".join(found_agents)


@tool
async def delegate_a2a_task(target_url: str, task_description: str) -> str:
    """
    Sends a task to a specialized agent.
    Provide the exact 'target_url' of the agent and a clear 'task_description'.
    """
    logger.info(f"Manager is delegating task to {target_url}...")
    context_id = active_context_id_var.get()
    task_id = active_task_id_var.get()

    await event_logger.broadcast(
        "Manager",
        "Routing Decision",
        {
            "target_url": target_url,
            "task_preview": task_description[:180],
            "context_id": context_id,
            "task_id": task_id,
        },
    )

    a2a_payload = {
        "jsonrpc": "2.0",
        "id": f"msg-{uuid.uuid4()}",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": f"id-{uuid.uuid4()}",
                "contextId": context_id,
                "role": "user",
                "parts": [{"text": task_description}],
            }
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            await event_logger.broadcast(
                "A2A Delegation Client",
                "JSON-RPC Request",
                {
                    "target_url": target_url,
                    "context_id": context_id,
                    "task_id": task_id,
                    "payload": a2a_payload,
                },
            )
            response = await client.post(target_url, json=a2a_payload)
            response.raise_for_status()
            data = response.json()

            await event_logger.broadcast(
                "A2A Delegation Client",
                "JSON-RPC Response",
                {
                    "target_url": target_url,
                    "status_code": response.status_code,
                    "context_id": context_id,
                    "task_id": task_id,
                    "payload": data,
                },
            )

            parts = (
                data.get("result", {})
                .get("status", {})
                .get("message", {})
                .get("parts", [])
            )
            return (
                parts[0]["text"]
                if parts
                else "Task completed, but no text was returned."
            )
        except Exception as e:
            await event_logger.broadcast(
                "A2A Delegation Client",
                "JSON-RPC Error",
                {
                    "target_url": target_url,
                    "context_id": context_id,
                    "task_id": task_id,
                    "request_payload": a2a_payload,
                    "error": str(e),
                },
            )
            return f"Error delegating task to {target_url}: {str(e)}"


class AutonomousManager(A2AAgentExecutor):
    def __init__(self):
        super().__init__()

        self.llm = ChatGoogleGenerativeAI(
            model=MODEL_NAME, google_api_key=API_KEY, temperature=0
        )
        self.tools = [discover_network_agents, delegate_a2a_task]
        self.session_histories: dict[str, list[tuple[str, str]]] = {}

        system_prompt = (
            "You are the central Manager Agent of a network. "
            "You have general conversational abilities, but you must delegate specialized tasks "
            "(like Math, Weather, or News) to external agents. "
            "Use the 'discover_network_agents' tool to find out who is online, "
            "and the 'delegate_a2a_task' tool to send them work. "
            "If the user asks a general question, just answer it yourself."
        )

        self.agent = create_agent(
            model=self.llm, tools=self.tools, system_prompt=system_prompt
        )

    async def execute(self, context: RequestContext, event_queue):
        user_input = context.get_user_input()
        session_id = context.context_id or str(uuid.uuid4())
        ctx_token = active_context_id_var.set(session_id)
        task_token = active_task_id_var.set(context.task_id)
        message_history = self.session_histories.setdefault(session_id, [])

        await event_logger.broadcast(
            "A2A Server",
            "Task Status: Working",
            json.loads(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=session_id,
                    final=False,
                    status=TaskStatus(
                        state=TaskState.working,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role="agent",
                            parts=[
                                TextPart(
                                    text="[Manager] Analyzing request and checking network..."
                                )
                            ],
                        ),
                    ),
                ).model_dump_json()
            ),
        )

        try:
            message_history.append(("user", user_input))
            result = await self.agent.ainvoke(
                {"messages": message_history}
            )

            final_message = result["messages"][-1]
            raw_content = final_message.content

            in_tokens, out_tokens, total_tokens = extract_tokens_from_response(final_message)
            if total_tokens > 0:
                token_tracker.record("manager", in_tokens, out_tokens, total_tokens)
                await event_logger.broadcast(
                    "Token Tracker",
                    "Usage Update",
                    token_tracker.snapshot(),
                )

            if isinstance(raw_content, list):
                final_answer = "".join(
                    [
                        part.get("text", "")
                        for part in raw_content
                        if isinstance(part, dict)
                    ]
                )
            else:
                final_answer = str(raw_content)

            message_history.append(("assistant", final_answer))
            if len(message_history) > 20:
                self.session_histories[session_id] = message_history[-20:]

            completed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[TextPart(text=final_answer)],
                    ),
                ),
            )
            await event_queue.enqueue_event(completed_event)
            await event_logger.broadcast(
                "A2A Server",
                "Task Status: Completed",
                json.loads(completed_event.model_dump_json()),
            )

        except Exception as e:
            err_msg = f"Manager Error: {e}\n{traceback.format_exc()}"
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=session_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role="agent",
                            parts=[TextPart(text=err_msg)],
                        ),
                    ),
                )
            )
        finally:
            active_context_id_var.reset(ctx_token)
            active_task_id_var.reset(task_token)

    async def cancel(self, context: RequestContext, event_queue):
        pass


adk_executor = AutonomousManager()
