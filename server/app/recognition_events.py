"""Transient admin refresh events; persisted records remain the source of truth."""
from __future__ import annotations

import asyncio
import threading


class RecognitionEvents:
    def __init__(self):
        self._lock = threading.Lock()
        self._listeners = {}
        self._sequence = 0

    def subscribe(self):
        queue = asyncio.Queue(maxsize=16)
        with self._lock:
            self._listeners[queue] = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, queue):
        with self._lock:
            self._listeners.pop(queue, None)

    @staticmethod
    def _put(queue, event):
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(event)

    def publish(self, record_id):
        with self._lock:
            self._sequence += 1
            event = {'record_id': record_id, 'sequence': self._sequence}
            listeners = list(self._listeners.items())
        for queue, loop in listeners:
            try:
                loop.call_soon_threadsafe(self._put, queue, event)
            except RuntimeError:
                self.unsubscribe(queue)
