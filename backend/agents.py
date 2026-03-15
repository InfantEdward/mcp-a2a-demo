import os
import sys
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from backend.mcp_interceptor import apply_mcp_session_patch

apply_mcp_session_patch()

import mcp.client.stdio
from mcp import ClientSession, StdioServerParameters
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.tools import load_mcp_tools
from backend.token_usage import extract_tokens_from_response
from backend.token_tracker import token_tracker
from backend.event_logger import event_logger

load_dotenv()

MODEL_NAME = os.getenv("DEFAULT_MODEL", "gemini-3-flash-preview")
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME, google_api_key=API_KEY, temperature=0
)


@dataclass
class AgentRunResult:
    state: str
    message: str


@tool
async def request_clarification(question: str) -> str:
    """Request one concise follow-up question when the user's input is missing required information or is ambiguous."""
    return question


class A2AAgent:
    """A generic A2A Agent whose identity and tools are defined by data."""

    def __init__(self, name, instruction, mcp_config=None):
        self.name = name
        self.instruction = instruction
        self.mcp_params = None

        self.exit_stack = AsyncExitStack()
        self.session = None
        self.tools = None
        self.local_tools = []

        if mcp_config:
            python_exe = sys.executable
            cmd = (
                python_exe
                if mcp_config.get("command") == "python"
                else mcp_config.get("command")
            )
            mcp_args = mcp_config.get("args") or ["-m", "backend.mcp_server"]
            self.mcp_params = StdioServerParameters(command=cmd, args=mcp_args)
            logger.info(
                f"Agent {name} configured with MCP params: {self.mcp_params.command} {self.mcp_params.args}"
            )
        else:
            logger.info(f"Agent {name} initialized without MCP tools.")

        if self.name.lower() == "weatherspecialist":
            self.local_tools = [request_clarification]

    async def run(self, messages, session_id):
        logger.info(f"Agent {self.name} running for session: {session_id}")
        run_input_tokens = 0
        run_output_tokens = 0
        run_total_tokens = 0

        if self.mcp_params:
            if self.session is None:
                logger.info(
                    f"Starting persistent MCP connection for {self.name}..."
                )

                read, write = await self.exit_stack.enter_async_context(
                    mcp.client.stdio.stdio_client(self.mcp_params)
                )
                self.session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write)
                )

                await self.session.initialize()

                mcp_tools = await load_mcp_tools(self.session)
                self.tools = [*self.local_tools, *mcp_tools]
                logger.info(
                    f"MCP connection established and tools loaded for {self.name}."
                )

            llm_with_tools = llm.bind_tools(self.tools)

            system_msg = SystemMessage(content=self._system_instruction())
            all_messages = [system_msg] + list(messages)

            response = await llm_with_tools.ainvoke(all_messages)
            in_t, out_t, tot_t = extract_tokens_from_response(response)
            run_input_tokens += in_t
            run_output_tokens += out_t
            run_total_tokens += tot_t

            while response.tool_calls:
                all_messages.append(response)
                for tool_call in response.tool_calls:
                    if tool_call["name"] == request_clarification.name:
                        question = tool_call["args"].get("question", "").strip()
                        return AgentRunResult(
                            state="input_required",
                            message=question or "Could you clarify your request?",
                        )
                    tool = next(
                        (t for t in self.tools if t.name == tool_call["name"]),
                        None,
                    )
                    if tool:
                        result = await tool.ainvoke(tool_call["args"])
                        all_messages.append(
                            ToolMessage(
                                content=str(result),
                                tool_call_id=tool_call["id"],
                            )
                        )
                response = await llm_with_tools.ainvoke(all_messages)
                in_t, out_t, tot_t = extract_tokens_from_response(response)
                run_input_tokens += in_t
                run_output_tokens += out_t
                run_total_tokens += tot_t

            final_content = self._clean_content(response.content)
            self._record_token_usage(run_input_tokens, run_output_tokens, run_total_tokens)
            return final_content

        else:
            system_msg = SystemMessage(content=self._system_instruction())
            all_messages = [system_msg] + list(messages)
            llm_with_tools = llm.bind_tools(self.local_tools) if self.local_tools else llm
            response = await llm_with_tools.ainvoke(all_messages)
            in_t, out_t, tot_t = extract_tokens_from_response(response)
            run_input_tokens += in_t
            run_output_tokens += out_t
            run_total_tokens += tot_t

            while getattr(response, "tool_calls", None):
                all_messages.append(response)
                for tool_call in response.tool_calls:
                    if tool_call["name"] == request_clarification.name:
                        question = tool_call["args"].get("question", "").strip()
                        self._record_token_usage(
                            run_input_tokens, run_output_tokens, run_total_tokens
                        )
                        return AgentRunResult(
                            state="input_required",
                            message=question or "Could you clarify your request?",
                        )
                response = await llm_with_tools.ainvoke(all_messages)
                in_t, out_t, tot_t = extract_tokens_from_response(response)
                run_input_tokens += in_t
                run_output_tokens += out_t
                run_total_tokens += tot_t

            self._record_token_usage(
                run_input_tokens, run_output_tokens, run_total_tokens
            )
            return self._clean_content(response.content)

    async def close(self):
        await self.exit_stack.aclose()
        self.session = None

    def _system_instruction(self) -> str:
        if self.name.lower() != "weatherspecialist":
            return self.instruction

        return (
            f"{self.instruction}\n\n"
            "If the user's request is missing a required detail or is ambiguous, "
            "do not guess. Call the `request_clarification` tool with one concise follow-up question instead of answering."
        )

    def _clean_content(self, content):
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            return "".join(text_parts)
        return str(content)

    def _record_token_usage(self, input_tokens: int, output_tokens: int, total_tokens: int):
        if total_tokens <= 0:
            return
        agent_key = self.name.lower().replace(" ", "_")
        token_tracker.record(agent_key, input_tokens, output_tokens, total_tokens)
        try:
            import asyncio

            asyncio.create_task(
                event_logger.broadcast(
                    "Token Tracker",
                    "Usage Update",
                    token_tracker.snapshot(),
                )
            )
        except RuntimeError:
            pass
