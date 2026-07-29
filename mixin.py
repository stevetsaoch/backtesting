import datetime
from typing import Callable
from nautilus_trader.core.datetime import unix_nanos_to_dt


class DailyResetMixin:

    def _init_daily_reset(self):
        self._current_session_date: datetime.date | None = None
        self._reset_callbacks: list[Callable[[], None]] = []

    def register_daily_reset(self, callback: Callable[[], None]) -> None:
        self._reset_callbacks.append(callback)
