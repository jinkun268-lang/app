"""Per-process bounded work; deployment intentionally runs one API process."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
import os
import threading
import time

import anyio

from .common import DomainError


@dataclass(frozen=True)
class ServiceLimits:
    upload_concurrency: int = 4
    export_concurrency: int = 1
    export_requests_per_minute: int = 6
    export_max_images: int = 5000
    export_max_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self):
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.upload_concurrency > 16 or self.export_concurrency > 4:
            raise ValueError('Work concurrency exceeds the supported single-process limit')

    @classmethod
    def from_env(cls):
        return cls(**{name: int(os.environ.get('APP_' + name.upper(), value))
                      for name, value in vars(cls()).items()})


def busy(scope, seconds=2):
    return DomainError(429, 'RATE_LIMITED', '处理繁忙，请稍后重试', {
        'scope': scope, 'retry_after_seconds': seconds})


class UploadWork:
    def __init__(self, limit):
        self._slots = threading.BoundedSemaphore(limit)
        self._threads = anyio.CapacityLimiter(limit)

    @contextmanager
    def admit(self):
        # Reject before reading the body; do not accumulate whole-image waiters in memory.
        if not self._slots.acquire(blocking=False):
            raise busy('uploads')
        try:
            yield
        finally:
            self._slots.release()

    async def run(self, function, *args):
        # Default cancellation shielding keeps the admission slot until sync work finishes.
        return await anyio.to_thread.run_sync(partial(function, *args), limiter=self._threads)


class _ExportTicket:
    def __init__(self, owner, user_id):
        self.owner = owner
        self.user_id = user_id
        self.submitted = False

    def submit(self, function, *args):
        with self.owner._lock:
            if self.owner._closed:
                raise DomainError(503, 'UNAVAILABLE', '导出服务正在停止')
            future = self.owner._executor.submit(function, *args)
            self.submitted = True
            self.owner._recent.setdefault(self.user_id, deque()).append(time.monotonic())
        future.add_done_callback(lambda _: self.owner._slots.release())


class ExportWork:
    def __init__(self, limits):
        self._limits = limits
        self._slots = threading.BoundedSemaphore(limits.export_concurrency)
        self._executor = ThreadPoolExecutor(max_workers=limits.export_concurrency,
                                            thread_name_prefix='citrus-export')
        self._lock = threading.Lock()
        self._recent = {}
        self._closed = False

    @contextmanager
    def reserve(self, user_id):
        if not self._slots.acquire(blocking=False):
            raise busy('exports')
        ticket = _ExportTicket(self, user_id)
        try:
            with self._lock:
                if self._closed:
                    raise DomainError(503, 'UNAVAILABLE', '导出服务正在停止')
                now = time.monotonic()
                for key, times in list(self._recent.items()):
                    while times and times[0] <= now - 60:
                        times.popleft()
                    if not times:
                        del self._recent[key]
                times = self._recent.get(user_id, ())
                if len(times) >= self._limits.export_requests_per_minute:
                    raise busy('exports', max(1, int(60 - (now - times[0])) + 1))
            yield ticket
        finally:
            if not ticket.submitted:
                self._slots.release()

    def close(self):
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True)
