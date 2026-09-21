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
