import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Message,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from backend.event_logger import event_logger

logger = logging.getLogger("HumanNewsAgent")


@dataclass
class PendingNewsRequest:
    request_id: str
    task_id: str
    context_id: str
    prompt: str
    future: asyncio.Future[str]


class NewsAgentResponse(BaseModel):
    request_id: str
    response_text: str


class PendingNewsStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._pending_by_id: dict[str, PendingNewsRequest] = {}
        self._pending_order: list[str] = []

    async def create(self, task_id: str, context_id: str, prompt: str) -> PendingNewsRequest:
        async with self._lock:
            request_id = f"news-{uuid.uuid4()}"
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            pending = PendingNewsRequest(
                request_id=request_id,
                task_id=task_id,
                context_id=context_id,
                prompt=prompt,
                future=future,
            )
            self._pending_by_id[request_id] = pending
            self._pending_order.append(request_id)
            return pending

    async def resolve(self, request_id: str, response_text: str) -> Optional[PendingNewsRequest]:
        async with self._lock:
            pending = self._pending_by_id.get(request_id)
            if pending is None:
                return None
            if not pending.future.done():
                pending.future.set_result(response_text)
            return pending

    async def remove(self, request_id: str):
        async with self._lock:
            self._pending_by_id.pop(request_id, None)
            self._pending_order = [value for value in self._pending_order if value != request_id]

    async def latest_snapshot(self) -> Optional[dict]:
        async with self._lock:
            for request_id in reversed(self._pending_order):
                pending = self._pending_by_id.get(request_id)
                if pending is None:
                    continue
                if pending.future.done():
                    continue
                return {
                    "request_id": pending.request_id,
                    "task_id": pending.task_id,
                    "context_id": pending.context_id,
                    "prompt": pending.prompt,
                }
        return None


class HumanNewsExecutor(AgentExecutor):
    def __init__(self, pending_store: PendingNewsStore, agent_name: str):
        super().__init__()
        self.pending_store = pending_store
        self.agent_name = agent_name

    async def execute(self, context: RequestContext, event_queue):
        session_id = context.context_id or str(uuid.uuid4())
        user_input = context.get_user_input()

        await event_logger.broadcast(
            f"{self.agent_name} (A2A)",
            "Task Received",
            {
                "task_id": context.task_id,
                "context_id": session_id,
                "user_input": user_input,
            },
        )

        pending = await self.pending_store.create(
            task_id=context.task_id,
            context_id=session_id,
            prompt=user_input,
        )

        wait_event = TaskStatusUpdateEvent(
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
                            text=f"[{self.agent_name}] Waiting for a newsroom analyst to respond."
                        )
                    ],
                ),
            ),
        )
        await event_queue.enqueue_event(wait_event)
        await event_logger.broadcast(
            f"{self.agent_name} (A2A)",
            "Task Input Required",
            {
                "request_id": pending.request_id,
                "task_id": context.task_id,
                "context_id": session_id,
                "prompt": user_input,
                "instruction": "Reply with a news update that answers the manager's request.",
            },
        )

        try:
            response_text = await asyncio.wait_for(pending.future, timeout=900)
            completed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[TextPart(text=f"[{self.agent_name}] {response_text}")],
                    ),
                ),
            )
            await event_queue.enqueue_event(completed_event)
            await event_logger.broadcast(
                f"{self.agent_name} (A2A)",
                "Task Completed",
                json.loads(completed_event.model_dump_json()),
            )
        except asyncio.TimeoutError:
            failed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.failed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[
                            TextPart(
                                text=f"[{self.agent_name}] Timed out waiting for a human news reply."
                            )
                        ],
                    ),
                ),
            )
            await event_queue.enqueue_event(failed_event)
            await event_logger.broadcast(
                f"{self.agent_name} (A2A)",
                "Task Failed",
                json.loads(failed_event.model_dump_json()),
            )
        finally:
            await self.pending_store.remove(pending.request_id)

    async def cancel(self, context: RequestContext, event_queue):
        return None


def create_human_news_app(
    card_data: dict,
    pending_store: PendingNewsStore,
) -> FastAPI:
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
        agent_executor=HumanNewsExecutor(
            pending_store=pending_store,
            agent_name=card_data["name"],
        ),
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AFastAPIApplication(agent_card=card, http_handler=handler).build()
    app = FastAPI(title=card_data["name"])

    @app.get("/.well-known/agent-card.json")
    def serve_agent_card():
        return card.model_dump()

    @app.get("/pending")
    async def get_pending_request():
        pending = await pending_store.latest_snapshot()
        return {"pending": pending}

    @app.post("/respond")
    async def respond_to_pending_task(body: NewsAgentResponse):
        pending = await pending_store.resolve(
            request_id=body.request_id,
            response_text=body.response_text,
        )
        if pending is None:
            return {"ok": False, "error": "Unknown or expired request."}

        payload = {
            "request_id": pending.request_id,
            "task_id": pending.task_id,
            "context_id": pending.context_id,
            "response_text": body.response_text,
        }
        await event_logger.broadcast(
            f"{card_data['name']} (A2A)",
            "Human Reply Submitted",
            payload,
        )
        return {"ok": True, "pending": payload}

    app.mount("/a2a", a2a_app)
    return app
