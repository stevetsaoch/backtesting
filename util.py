import threading
import time


class PacingController:
    def __init__(self, cooldown: int = 10):
        self._cooldown = cooldown
        self._deadline = 0.0
        self._lock = threading.Lock()

    @property
    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._deadline - time.monotonic())

    @property
    def ready(self) -> bool:
        return self.remaining == 0

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now >= self._deadline:
                self._deadline = now + self._cooldown
                return True
            return False

    def reset(self):
        with self._lock:
            self._deadline = time.monotonic() + self._cooldown


class RequestIdManager:
    def __init__(self):
        self.request_id = 1
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            request_id = self.request_id
            self.request_id += 1
            return request_id

        pass
