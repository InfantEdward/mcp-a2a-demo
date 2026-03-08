import json
import anyio
import contextlib
import mcp.client.stdio
from backend.event_logger import event_logger
import asyncio
import logging

logger = logging.getLogger("MCP_INTERCEPTOR")

_original_stdio_client = mcp.client.stdio.stdio_client


def try_serialize(obj):
    """Helper to turn complex MCP/Pydantic objects into dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {
            k: try_serialize(v)
            for k, v in obj.__dict__.items()
            if not k.startswith("_")
        }
    if isinstance(obj, list):
        return [try_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: try_serialize(v) for k, v in obj.items()}
    return obj


class InterceptSendStream:
    def __init__(self, stream):
        self._stream = stream

    async def send(self, data):
        try:
            if not isinstance(
                data, (str, bytes, int, float, bool, type(None))
            ):
                payload = try_serialize(data)
                asyncio.create_task(
                    event_logger.broadcast(
                        "MCP Client (TX)", "Object", payload
                    )
                )
            else:
                raw_str = (
                    data.decode() if isinstance(data, bytes) else str(data)
                )
                for line in raw_str.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        payload = {"raw_text": line}
                    asyncio.create_task(
                        event_logger.broadcast(
                            "MCP Client (TX)", "Bytes/Str", payload
                        )
                    )
        except Exception as e:
            logger.error(f"Failed to intercept TX data: {e}")

        await self._stream.send(data)

    async def aclose(self):
        await self._stream.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()


class InterceptReceiveStream:
    def __init__(self, stream):
        self._stream = stream

    async def receive(self):
        data = await self._stream.receive()
        try:
            if not isinstance(
                data, (str, bytes, int, float, bool, type(None))
            ):
                payload = try_serialize(data)
                asyncio.create_task(
                    event_logger.broadcast(
                        "MCP Server (RX)", "Object", payload
                    )
                )
            else:
                raw_str = (
                    data.decode() if isinstance(data, bytes) else str(data)
                )
                for line in raw_str.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        payload = {"raw_text": line}
                    asyncio.create_task(
                        event_logger.broadcast(
                            "MCP Server (RX)", "Bytes/Str", payload
                        )
                    )
        except Exception as e:
            logger.error(f"Failed to intercept RX data: {e}")

        return data

    async def aclose(self):
        await self._stream.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration


@contextlib.asynccontextmanager
async def patched_stdio_client(*args, **kwargs):
    async with _original_stdio_client(*args, **kwargs) as (
        read_stream,
        write_stream,
    ):
        yield InterceptReceiveStream(read_stream), InterceptSendStream(
            write_stream
        )


def apply_mcp_session_patch():
    """Globally apply the stdio interception monkeypatch."""
    mcp.client.stdio.stdio_client = patched_stdio_client

    try:
        import google.adk.tools.mcp_tool.mcp_session_manager

        google.adk.tools.mcp_tool.mcp_session_manager.stdio_client = (
            patched_stdio_client
        )
    except (ImportError, AttributeError):
        pass

    print("MCP stdio client monkeypatched for stream interception globally.")
