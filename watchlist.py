import datetime
import pandas as pd
from dataclasses import dataclass
from abc import ABC, abstractmethod
from collections import defaultdict

from nautilus_trader.model import InstrumentId
from nautilus_trader.indicators.base import Indicator

from indicator.indicator import IndicatorMeta
from indicator.field import IndicatorFieldConfig, TYPE_REGISTRY


@dataclass(frozen=True)
class WatchListManagerMeta:
    watchlist_manager_name: str
    indicator_meta_set: list[IndicatorMeta]
    snapshot_time: datetime.time | None = None


class WatchListManager(ABC):
    COL_INSTRUMENT_ID = "instrument_id"

    def __init__(
        self,
        indicator_meta_set: list[IndicatorMeta],
        snapshot_time: datetime.time,
        indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]],
    ):
        self._field_configs: dict[str, IndicatorFieldConfig] = {
            f.name: f
            for indicator_meta in indicator_meta_set
            for f in indicator_meta.field_configs
        }
        self._indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]] = (
            indicator_instrument_map
        )
        self._snapshot_time = snapshot_time
        self._snapshot_data: pd.DataFrame = pd.DataFrame()
        self._is_ready: bool = False
        self._data: pd.DataFrame = pd.DataFrame()
        self._watchlist: list[InstrumentId] = []

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        pass

    @property
    @abstractmethod
    def data(self) -> pd.DataFrame:
        pass

    @property
    @abstractmethod
    def snapshot_data(self) -> pd.DataFrame:
        pass

    @property
    @abstractmethod
    def watchlist(self) -> list[InstrumentId]:
        pass

    @abstractmethod
    def update(self, time: datetime.time):
        pass

    @abstractmethod
    def reset(self):
        pass

    @abstractmethod
    def _build_watchlist(self) -> list[InstrumentId]:
        pass

    @abstractmethod
    def _build_dataframe(self) -> pd.DataFrame:
        pass

    @abstractmethod
    def _build_empty_dataframe(self) -> pd.DataFrame:
        pass


class ORBWatchListManager(WatchListManager):

    @property
    def data(self):
        self._data = self._build_dataframe()
        return self._data

    @property
    def snapshot_data(self):
        return self._snapshot_data

    @property
    def is_ready(self):
        return self._is_ready

    @property
    def watchlist(self):
        return self._watchlist

    def update(self, time: datetime.time):
        if not self._snapshot_data.empty or self._snapshot_time is None:
            return

        if time >= self._snapshot_time:
            # build watchlist
            self._watchlist = self._build_watchlist()
            self._snapshot_data = self._build_dataframe()
            self._is_ready = True

    def reset(self):
        self._snapshot_data: pd.DataFrame = pd.DataFrame()
        self._is_ready: bool = False
        self._data: pd.DataFrame = pd.DataFrame()
        self._watchlist: list[InstrumentId] = []

    def _build_watchlist(self) -> list[InstrumentId]:
        wld = defaultdict(list)
        for ind_pair in self._indicator_instrument_map.values():
            for iid, ind in ind_pair.items():
                result = []
                for name, value in ind.get().items():
                    cfg: IndicatorFieldConfig = self._field_configs[name]
                    if cfg.threshold is None:
                        continue
                    result.append(cfg.operator.to_operator()(value, cfg.threshold))
                wld[iid].extend(result)

        wl = []
        for iid, results in wld.items():
            if all(results):
                wl.append(iid)
        return wl

    def _build_dataframe(self) -> pd.DataFrame:
        edf = self._build_empty_dataframe()
        for v in self._indicator_instrument_map.values():
            for iid, ind in v.items():
                data = ind.get()
                if str(iid) in edf[self.COL_INSTRUMENT_ID].values:
                    edf.loc[df[self.COL_INSTRUMENT_ID] == str(iid), data.keys()] = (
                        data.values()
                    )
                else:
                    edf.loc[len(edf), "instrument_id"] = str(iid)
                    edf.loc[edf[self.COL_INSTRUMENT_ID] == str(iid), data.keys()] = (
                        data.values()
                    )
        return edf

    def _build_empty_dataframe(self) -> pd.DataFrame:
        fields = {self.COL_INSTRUMENT_ID: pd.Series(dtype="string")}
        for cfg in self._field_configs.values():
            field_type = TYPE_REGISTRY[cfg.field_type]
            if field_type in (int, float, bool, str):
                dtype = field_type
            elif field_type is datetime.datetime:
                dtype = "datetime64[ns]"
            elif field_type in (
                datetime.time,
                datetime.date,
            ):
                dtype = "object"

            fields[cfg.name] = pd.Series(dtype=dtype)

        return pd.DataFrame(fields)


WATCHLIST_MANAGER_REGISTRY: dict[str, type] = {
    "orb_watchlist_manager": ORBWatchListManager
}
