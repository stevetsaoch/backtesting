import datetime
import pandas as pd
from abc import abstractmethod
from typing import Protocol, TypeVar

from nautilus_trader.model import InstrumentId


class WatchlistManagerBaseInterface(Protocol):
    @property
    def is_watchlist_ready(self) -> bool: ...

    @property
    def data(self) -> pd.DataFrame: ...

    @property
    def snapshot_data(self) -> pd.DataFrame: ...

    @property
    def watchlist(self) -> list[InstrumentId]: ...

    def update(self, time: datetime.time): ...

    def reset(self): ...


class ORBWatchlistManagerInterface(WatchlistManagerBaseInterface, Protocol):
    def get_snapshot_intraday_high(self, instrument_id: InstrumentId) -> float: ...
    def get_snapshot_intraday_low(self, instrument_id: InstrumentId) -> float: ...


T_WL_CO = TypeVar("T_WL_CO", bound=WatchlistManagerBaseInterface, covariant=True)


class WatchlistManagerProvider(Protocol[T_WL_CO]):
    def get_watchlist_manager(self) -> T_WL_CO: ...
