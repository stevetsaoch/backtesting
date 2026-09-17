from watchlist.manager import ORBWatchListManager

WATCHLIST_MANAGER_REGISTRY: dict[str, type] = {
    "orb_watchlist_manager": ORBWatchListManager
}
