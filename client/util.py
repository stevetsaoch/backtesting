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
