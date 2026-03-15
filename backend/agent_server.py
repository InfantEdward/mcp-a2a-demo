import argparse
import json
import os
import logging
import uvicorn
import uuid
from fastapi import FastAPI

from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.types import (
    AgentCard,
    TaskStatusUpdateEvent,
    TaskStatus,
    TaskState,
    Message,
    TextPart,
    AgentCapabilities,
)

from backend.agents import A2AAgent, AgentRunResult
from backend.event_logger import event_logger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AgentServer")
class SingleAgentExecutor(AgentExecutor):
    def __init__(self, agent_instance):
        super().__init__()
        self.agent = agent_instance
        self.histories_by_session = {}

    async def execute(self, context: RequestContext, event_queue):
        try:
            user_input = context.get_user_input()
            session_id = context.context_id or str(uuid.uuid4())
            await event_logger.broadcast(
                f"{self.agent.name} (A2A)",
                "Task Received",
                {
                    "task_id": context.task_id,
                    "context_id": session_id,
                    "user_input": user_input,
                },
            )

            from langchain_core.messages import HumanMessage, AIMessage

            history = self.histories_by_session.setdefault(session_id, [])
            history.append(HumanMessage(content=user_input))

            response = await self.agent.run(history, session_id)
            if isinstance(response, AgentRunResult) and response.state == "input_required":
                history.append(AIMessage(content=response.message))
                if len(history) > 20:
                    self.histories_by_session[session_id] = history[-20:]

                clarification_event = TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=session_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.input_required,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role="agent",
                            parts=[
                                TextPart(
                                    text=f"[{self.agent.name}] {response.message}"
                                )
                            ],
                        ),
                    ),
                )
                await event_queue.enqueue_event(clarification_event)
                await event_logger.broadcast(
                    f"{self.agent.name} (A2A)",
                    "Task Input Required",
                    json.loads(clarification_event.model_dump_json()),
                )
                return
            response_text = response
            history.append(AIMessage(content=response_text))
            if len(history) > 20:
                self.histories_by_session[session_id] = history[-20:]

            completed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[TextPart(text=f"[{self.agent.name}] {response_text}")],
                    ),
                ),
            )
            await event_queue.enqueue_event(completed_event)
            await event_logger.broadcast(
                f"{self.agent.name} (A2A)",
                "Task Completed",
                json.loads(completed_event.model_dump_json()),
            )
        except Exception as e:
            failed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.failed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[TextPart(text=str(e))],
                    ),
                ),
            )
            await event_queue.enqueue_event(failed_event)
            await event_logger.broadcast(
                f"{self.agent.name} (A2A)",
                "Task Failed",
                json.loads(failed_event.model_dump_json()),
            )

    async def cancel(self, context: RequestContext, event_queue):
        pass


def create_app(agent_filename: str):
    event_logger.set_remote_logger(
        os.getenv("ORCHESTRATOR_LOG_URL", "http://127.0.0.1:8000/api/log")
    )

    card_path = f"agents/{agent_filename}.json"
    impl_basename = "".join(part.capitalize() for part in agent_filename.split("_"))
    impl_path = f"implementations/{impl_basename}.mcp.json"

    with open(card_path, "r") as f:
        card_data = json.load(f)

    card_url_override = os.getenv("A2A_CARD_URL")
    if card_url_override:
        card_data["url"] = card_url_override

    mcp_config = None
    if os.path.exists(impl_path):
        with open(impl_path, "r") as f:
            mcp_config = json.load(f)

    agent_instance = A2AAgent(
        name=card_data["name"],
        instruction=card_data["description"],
        mcp_config=mcp_config,
    )

    card = AgentCard(
        name=card_data["name"],
        description=card_data["description"],
        url=card_data["url"],
        version=card_data.get("version", "1.0.0"),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(),
        skills=[],
    )

    handler = DefaultRequestHandler(
        agent_executor=SingleAgentExecutor(agent_instance),
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AFastAPIApplication(
        agent_card=card, http_handler=handler
    ).build()
    app = FastAPI(title=card_data["name"])

    @app.get("/")
    def serve_agent_card():
        return card.model_dump()

    app.mount("/api/a2a", a2a_app)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--agent",
        required=True,
        help="Filename of the agent without .json (e.g., math_specialist)",
    )
    parser.add_argument(
        "--port", type=int, required=True, help="Port to run on"
    )
    args = parser.parse_args()

    app = create_app(args.agent)
    logger.info(f"Starting {args.agent} on port {args.port}...")
    uvicorn.run(app, host=os.getenv("AGENT_HOST", "127.0.0.1"), port=args.port)
