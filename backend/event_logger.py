import json
import logging
import httpx

logger = logging.getLogger(__name__)


class EventLogger:
    def __init__(self):
        self.connections = set()
        self.remote_url = None

    def set_remote_logger(self, url: str):
        """If set, this logger will forward events over HTTP instead of WebSockets."""
        self.remote_url = url

    async def connect(self, websocket):
        await websocket.accept()
        self.connections.add(websocket)
        logger.info(
            f"New WebSocket connection. Total: {len(self.connections)}"
        )

    def disconnect(self, websocket):
        self.connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.connections)}")

    async def broadcast(self, source, event_type, payload):
        if self.remote_url:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        self.remote_url,
                        json={
                            "source": source,
                            "type": event_type,
                            "payload": payload,
                        },
                    )
            except Exception as e:
                logger.error(f"Failed to forward log to Orchestrator: {e}")
            return

        if not self.connections:
            return

        message = json.dumps(
            {"source": source, "type": event_type, "payload": payload}
        )

        disconnected = set()
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.add(ws)

        for ws in disconnected:
            self.connections.remove(ws)


event_logger = EventLogger()
