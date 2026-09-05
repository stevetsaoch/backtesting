from typing import Protocol


class EventRecoder(Protocol):
    def record(self) -> None: ...
