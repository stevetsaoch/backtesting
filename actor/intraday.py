from typing import Callable
from actor.base import BaseCustomActor, BaseCustomActorConfig
from watchlist.interfaces import ORBWatchlistManagerInterface


class ConsolidationAndBreakoutIndicatorManageActorConfig(
    BaseCustomActorConfig, frozen=True
):
    pass


class ConsolidationAndBreakoutIndicatorManageActor(
    BaseCustomActor[ORBWatchlistManagerInterface]
):
    def _post_on_bar(self, event):
        """
        excute something after every round of on_bar finished
        """
        self._watchlist_manager.update(self._current_session_datetime.time())

    def _register_daily_reset(self, callback: Callable[[], None]) -> None:
        self._reset_callbacks.append(callback)

    def _daily_reset(self, event):
        for cb in self._reset_callbacks:
            cb()
        self._current_session_time = None

    def on_stop(self):
        pass
