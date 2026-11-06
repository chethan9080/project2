"""
In-Process Push Event Bus for Live Portal Updates.

NiceGUI serves every browser tab over a persistent websocket. This module lets
services publish domain events (for example a new citizen registration) and lets
open pages receive them instantly through an asyncio queue instead of polling
the database.

Subscribers are registered per connected page. Publishing is loop-safe and can
be called from the NiceGUI event loop or from a worker thread.
"""

import asyncio
from typing import Any, Dict, Optional

_subscribers: Dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}


def subscribe() -> asyncio.Queue:
    """Register the current page as a listener and return its event queue."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers[queue] = loop
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    """Remove a listener queue (called when the page disconnects)."""
    _subscribers.pop(queue, None)


def _deliver(queue: asyncio.Queue, event: Dict[str, Any]) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        # A stalled client must never block or crash the publishing request. Drop the
        # oldest queued event instead of the new one so pages converge on current state.
        try:
            queue.get_nowait()
            queue.put_nowait(event)
        except asyncio.QueueEmpty:
            pass


def publish(event: Dict[str, Any]) -> None:
    """Push an event to every open subscriber queue."""
    for queue, loop in list(_subscribers.items()):
        try:
            loop.call_soon_threadsafe(_deliver, queue, event)
        except RuntimeError:
            _subscribers.pop(queue, None)


def subscriber_count() -> int:
    """Expose the number of live listeners for diagnostics."""
    return len(_subscribers)


def reset() -> None:
    """Clear all listeners (used by tests)."""
    _subscribers.clear()
