from typing import Callable


class DailyResetMixin:

    def _init_daily_reset(self):
        self._reset_callbacks: list[Callable[[], None]] = []

    def _register_daily_reset(self, callback: Callable[[], None]) -> None:
        self._reset_callbacks.append(callback)


class FileNameMixin:
    PRESETS_PARQUET = "presets.parquet"
    MISSIONS_PARQUET = "missions.parquet"
