import traceback
import uuid
import json
import logging
import os
import numpy as np
from backend.agents import A2AAgent
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.types import (
    TaskStatusUpdateEvent,
    TaskStatus,
    TaskState,
    Message,
    TextPart,
)
from backend.event_logger import event_logger

logger = logging.getLogger("Orchestrator")

# Global memory store
session_histories = {}


def get_session_history(session_id: str) -> ChatMessageHistory:
    if session_id not in session_histories:
        session_histories[session_id] = ChatMessageHistory()
    return session_histories[session_id]


def cosine_similarity(v1, v2):
    vec1 = np.array(v1)
    vec2 = np.array(v2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return float(np.dot(vec1, vec2) / (norm1 * norm2))


class DynamicRouter(AgentExecutor):
    def __init__(self, agents_dir="agents", impl_dir="implementations"):
        super().__init__()
        self.agents_dir = agents_dir
        self.impl_dir = impl_dir
        self.agents = {}

        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001"
        )

        self._load_agents()

    def _load_agents(self):
        if not os.path.exists(self.agents_dir):
            return

        for filename in os.listdir(self.agents_dir):
            if filename.endswith(".json"):
                try:
                    with open(
                        os.path.join(self.agents_dir, filename), "r"
                    ) as f:
                        card = json.load(f)
                        name = card["name"]

                        mcp_config = None
                        impl_path = os.path.join(
                            self.impl_dir, f"{name}.mcp.json"
                        )
                        if os.path.exists(impl_path):
                            with open(impl_path, "r") as ifile:
                                mcp_config = json.load(ifile)

                        agent_instance = A2AAgent(
                            name=name,
                            instruction=card["description"],
                            mcp_config=mcp_config,
                        )

                        skills_text = ", ".join(
                            [s["name"] for s in card.get("skills", [])]
                        )
                        profile_text = f"Agent: {name}. Description: {card['description']} Skills: {skills_text}"  # noqa: E501

                        logger.info(
                            f"Generating embedding vector for {name}..."
                        )
                        agent_embedding = self.embeddings.embed_query(
                            profile_text
                        )

                        self.agents[name] = {
                            "card": card,
                            "instance": agent_instance,
                            "embedding": agent_embedding,
                        }
                        logger.info(f"Registered local agent: {name}")
                except Exception as e:
                    logger.error(f"Error loading agent from {filename}: {e}")

    async def execute(self, context: RequestContext, event_queue):
        try:
            user_input = context.get_user_input()
            session_id = context.context_id or str(uuid.uuid4())
            history = get_session_history(session_id)

            orchestrator_event = TaskStatusUpdateEvent(
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
                                text="[Orchestrator] Computing semantic similarity..."  # noqa: E501
                            )
                        ],
                    ),
                ),
            )
            await event_queue.enqueue_event(orchestrator_event)
            await event_logger.broadcast(
                "A2A Server",
                "Task Status: Working",
                json.loads(orchestrator_event.model_dump_json()),
            )

            input_embedding = await self.embeddings.aembed_query(user_input)

            best_agent = None
            best_score = -1.0

            CONFIDENCE_THRESHOLD = 0.55

            for agent_name, agent_info in self.agents.items():
                score = cosine_similarity(
                    input_embedding, agent_info["embedding"]
                )
                logger.info(f"Similarity for {agent_name}: {score:.3f}")

                if score > best_score:
                    best_score = score
                    best_agent = agent_name

            if best_score >= CONFIDENCE_THRESHOLD:
                agent_name = best_agent
                reason = (
                    f"Selected via vector similarity (score: {best_score:.2f})"
                )
            else:
                agent_name = "GeneralAssistant"
                reason = f"No agent met the threshold of {CONFIDENCE_THRESHOLD} (best was {best_score:.2f}). Falling back to general."  # noqa: E501

            selected_info = self.agents[agent_name]
            target_agent = selected_info["instance"]

            router_event = TaskStatusUpdateEvent(
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
                                text=f"[Router] Routing to {agent_name}. {reason}"  # noqa: E501
                            )
                        ],
                    ),
                ),
            )
            await event_queue.enqueue_event(router_event)
            await event_logger.broadcast(
                "A2A Server",
                "Task Status: Working",
                json.loads(router_event.model_dump_json()),
            )

            history.add_user_message(user_input)
            response_text = await target_agent.run(
                history.messages, session_id
            )
            history.add_ai_message(response_text)

            completed_event = TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=session_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role="agent",
                        parts=[
                            TextPart(text=f"[{agent_name}] {response_text}")
                        ],
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
            err_msg = f"Router Error: {e}\n{traceback.format_exc()}"
            failed_event = TaskStatusUpdateEvent(
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
            await event_queue.enqueue_event(failed_event)
            await event_logger.broadcast(
                "A2A Server",
                "Task Status: Failed",
                json.loads(failed_event.model_dump_json()),
            )

    async def cancel(self, context: RequestContext, event_queue):
        pass


adk_executor = DynamicRouter()
