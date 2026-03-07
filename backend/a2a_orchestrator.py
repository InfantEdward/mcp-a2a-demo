import traceback
import uuid
import json
import logging
import os
from backend.agents import A2AAgent, llm
from langchain_core.messages import get_buffer_string
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
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


class RouteDecision(BaseModel):
    agent: str = Field(description="The name of the agent to route to.")
    reason: str = Field(description="Brief reason for the routing decision.")


class DynamicRouter(AgentExecutor):
    def __init__(self, agents_dir="agents", impl_dir="implementations"):
        super().__init__()
        self.agents_dir = agents_dir
        self.impl_dir = impl_dir
        self.agents = {}
        self._load_agents()

        agent_descriptions = "\n".join(
            [
                f"{name}: {info['card']['description']} Skills: {', '.join([s['name'] for s in info['card'].get('skills', [])])}"  # noqa: E501
                for name, info in self.agents.items()
            ]
        )

        parser = JsonOutputParser(pydantic_object=RouteDecision)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"""You are an A2A Router. Your job is to route user requests to the most appropriate specialized agent based on their Agent Card metadata and the conversation history.
            
            AVAILABLE AGENTS:
            {agent_descriptions}
            
            CONVERSATION HISTORY:
            {{history}}
            
            Based on the history and the new input, decide who should handle the request.
            Respond with a JSON object containing 'agent' and 'reason'.
            {{format_instructions}}
            """,  # noqa: E501
                ),
                ("human", "{input}"),
            ]
        ).partial(format_instructions=parser.get_format_instructions())

        self.router_chain = prompt | llm | parser

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

                        self.agents[name] = {
                            "card": card,
                            "instance": agent_instance,
                        }
                        logger.info(f"Registered local agent: {name}")
                except Exception as e:
                    logger.error(f"Error loading agent from {filename}: {e}")

    async def execute(self, context: RequestContext, event_queue):
        try:
            user_input = context.get_user_input()
            session_id = context.context_id or str(uuid.uuid4())
            history = get_session_history(session_id)

            # Format history for the router
            history_str = get_buffer_string(history.messages)

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
                                text="[Orchestrator] Deciding destination..."
                            )
                        ],
                    ),
                ),
            )
            await event_queue.enqueue_event(orchestrator_event)
            await event_logger.broadcast(
                source="A2A Server",
                event_type="Task Status: Working",
                payload=json.loads(orchestrator_event.model_dump_json()),
            )

            decision = await self.router_chain.ainvoke(
                {"input": user_input, "history": history_str}
            )
            agent_name = decision["agent"]
            reason = decision["reason"]

            selected_info = self.agents.get(agent_name)
            if not selected_info:
                for k in self.agents.keys():
                    if k.lower() in agent_name.lower():
                        selected_info = self.agents[k]
                        agent_name = k
                        break
                if not selected_info:
                    agent_name = next(iter(self.agents.keys()))
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
                source="A2A Server",
                event_type="Task Status: Working",
                payload=json.loads(router_event.model_dump_json()),
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
                source="A2A Server",
                event_type="Task Status: Completed",
                payload=json.loads(completed_event.model_dump_json()),
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
                source="A2A Server",
                event_type="Task Status: Failed",
                payload=json.loads(failed_event.model_dump_json()),
            )

    async def cancel(self, context: RequestContext, event_queue):
        pass


adk_executor = DynamicRouter()
