"""In-memory event bus for real-time dashboard events."""

import asyncio
from fnmatch import fnmatch
from typing import Any, AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]]]] = set()

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish an event to all active async subscribers."""
        dead_queues = set()
        for q in self._subscribers:
            try:
                q.put_nowait((topic, payload))
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_queues.add(q)
        self._subscribers.difference_update(dead_queues)

    async def subscribe(self, topic_pattern: str = "*") -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Subscribe to events matching a pattern (e.g. 'callback.*', 'case.*', '*')."""
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        try:
            while True:
                topic, payload = await q.get()
                if fnmatch(topic, topic_pattern):
                    yield topic, payload
        finally:
            self._subscribers.discard(q)


# Default global event bus for the process
event_bus = EventBus()
