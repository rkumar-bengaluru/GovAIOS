"""One admin session: exactly 30 minutes on the monotonic clock, never extended."""
import secrets
import threading
import time

SESSION_S = 30 * 60


class Session:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._id = None
        self._opened = 0.0

    def _live(self) -> bool:
        return self._id is not None and self._clock() < self._opened + SESSION_S

    def open(self) -> str:
        with self._lock:
            if self._live():
                raise RuntimeError("session already open")
            self._id, self._opened = secrets.token_hex(8), self._clock()
            return self._id

    def active(self) -> bool:
        with self._lock:
            return self._live()

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._opened + SESSION_S - self._clock()) if self._id else 0.0

    @property
    def id(self) -> str | None:
        with self._lock:
            return self._id

    def end(self, reason: str) -> str | None:
        with self._lock:
            sid, self._id = self._id, None
            return sid
