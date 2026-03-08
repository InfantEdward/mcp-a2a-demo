import os
import sys
import logging
from contextlib import AsyncExitStack
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from backend.mcp_interceptor import apply_mcp_session_patch

apply_mcp_session_patch()

import mcp.client.stdio
from mcp import ClientSession, StdioServerParameters
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools

load_dotenv()

MODEL_NAME = os.getenv("DEFAULT_MODEL", "gemini-3-flash-preview")
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME, google_api_key=API_KEY, temperature=0
)


class A2AAgent:
    """A generic A2A Agent whose identity and tools are defined by data."""

    def __init__(self, name, instruction, mcp_config=None):
        self.name = name
        self.instruction = instruction
        self.mcp_params = None

        self.exit_stack = AsyncExitStack()
        self.session = None
        self.tools = None

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

    async def run(self, messages, session_id):
        logger.info(f"Agent {self.name} running for session: {session_id}")

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

                self.tools = await load_mcp_tools(self.session)
                logger.info(
                    f"MCP connection established and tools loaded for {self.name}."
                )

            llm_with_tools = llm.bind_tools(self.tools)

            system_msg = SystemMessage(content=self.instruction)
            all_messages = [system_msg] + list(messages)

            response = await llm_with_tools.ainvoke(all_messages)

            while response.tool_calls:
                all_messages.append(response)
                for tool_call in response.tool_calls:
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

            return self._clean_content(response.content)

        else:
            system_msg = SystemMessage(content=self.instruction)
            all_messages = [system_msg] + list(messages)
            response = await llm.ainvoke(all_messages)
            return self._clean_content(response.content)

    async def close(self):
        await self.exit_stack.aclose()
        self.session = None

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
