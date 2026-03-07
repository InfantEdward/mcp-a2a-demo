import json
import logging

logger = logging.getLogger(__name__)


class EventLogger:
    def __init__(self):
        self.connections = set()

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
