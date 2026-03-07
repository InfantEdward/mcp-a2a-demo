import os
import sys
import logging
from dotenv import load_dotenv

# Configure logging
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

MODEL_NAME = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")
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

        if mcp_config:
            python_exe = sys.executable
            cmd = (
                python_exe
                if mcp_config.get("command") == "python"
                else mcp_config.get("command")
            )
            self.mcp_params = StdioServerParameters(
                command=cmd, args=["-m", "backend.mcp_server"]
            )
            logger.info(
                f"Agent {name} initialized with MCP: {self.mcp_params.command} {self.mcp_params.args}"  # noqa: E501
            )
        else:
            logger.info(f"Agent {name} initialized without MCP tools.")

    async def run(self, messages, session_id):
        logger.info(f"Agent {self.name} running for session: {session_id}")

        if self.mcp_params:
            async with mcp.client.stdio.stdio_client(self.mcp_params) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await load_mcp_tools(session)
                    llm_with_tools = llm.bind_tools(tools)

                    system_msg = SystemMessage(content=self.instruction)
                    all_messages = [system_msg] + list(messages)

                    response = await llm_with_tools.ainvoke(all_messages)

                    while response.tool_calls:
                        all_messages.append(response)
                        for tool_call in response.tool_calls:
                            tool = next(
                                (
                                    t
                                    for t in tools
                                    if t.name == tool_call["name"]
                                ),
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
