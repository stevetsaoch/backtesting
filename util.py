import os
import re
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


def find_files(root_dir, pattern):
    regex = re.compile(pattern)
    result = []
    stack = [root_dir]

    while stack:
        current_dir = stack.pop()
        try:
            entries = os.listdir(current_dir)
        except PermissionError:
            continue
        except FileNotFoundError as e:
            continue

        for entry in entries:
            full_path = os.path.join(current_dir, entry)

            if os.path.isdir(full_path):
                stack.append(full_path)
            elif os.path.isfile(full_path):
                if regex.search(entry):
                    result.append(full_path)

    return result
