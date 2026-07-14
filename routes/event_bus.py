import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone


class EventBus:
    """
    In-process async event bus for real-time SSE streaming.
    
    The Discord bot publishes events here, and FastAPI SSE endpoints
    subscribe to receive them. Each SSE client gets its own asyncio.Queue.
    """

    def __init__(self):
        self._queues: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """Subscribe to events for a session. Returns a queue that receives events."""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            if session_id not in self._queues:
                self._queues[session_id] = []
            self._queues[session_id].append(queue)
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue):
        """Remove a subscriber queue."""
        async with self._lock:
            if session_id in self._queues:
                try:
                    self._queues[session_id].remove(queue)
                except ValueError:
                    pass
                if not self._queues[session_id]:
                    del self._queues[session_id]

    async def publish(self, session_id: str, event_type: str, data: Any = None):
        """
        Publish an event to all subscribers of a session.
        
        Args:
            session_id: The session (channel_id) to publish to
            event_type: Event name (e.g. "member_join", "drop_created")
            data: Event payload (will be JSON-serialized)
        """
        event = {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        message = json.dumps(event, default=str)

        async with self._lock:
            queues = list(self._queues.get(session_id, []))

        dead_queues = []
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead_queues.append(queue)

        if dead_queues:
            async with self._lock:
                for q in dead_queues:
                    if session_id in self._queues:
                        try:
                            self._queues[session_id].remove(q)
                        except ValueError:
                            pass

    def subscriber_count(self, session_id: str) -> int:
        """Get the number of active subscribers for a session."""
        return len(self._queues.get(session_id, []))
