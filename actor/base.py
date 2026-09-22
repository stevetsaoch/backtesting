import datetime
from typing import Callable, Generic
from abc import ABC, abstractmethod
from collections import defaultdict

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model import Bar, BarType, InstrumentId

from indicator.schemas import IndicatorMeta
from event.manager import EventManager
from watchlist.interfaces import T_WL_CO
from watchlist.registry import WATCHLIST_MANAGER_REGISTRY
from indicator.indicator_registry import INDICATOR_REGISTRY


class BaseCustomActorConfig(ActorConfig, frozen=True):
    pass


class BaseCustomActor(Actor, ABC, Generic[T_WL_CO]):
    def __init__(
        self,
        config: BaseCustomActorConfig,
        event_manager: EventManager,
        warmup_data_start_datetime: datetime.datetime,
        data_start_datetime: datetime.datetime,
        bar_types: dict[InstrumentId, list[BarType]],
        indicator_meta_set: list[IndicatorMeta],
        snapshot_time: datetime.time | None,
        watchlist_manager_name: str,
    ):
        super().__init__(config)
        self._reset_callbacks: list[Callable[[], None]] = []
        self._current_session_datetime: datetime.datetime | None = None
        # indicator
        self._indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]] = (
            defaultdict(dict)
        )
        self._indicator_meta_set: list[IndicatorMeta] = indicator_meta_set
        self._snapshot_time: datetime.time | None = snapshot_time
        # data
        self._warmup_data_start_datetime: datetime.datetime = warmup_data_start_datetime
        self._data_start_datetime: datetime.datetime = data_start_datetime
        self._bar_types = bar_types
        # manager
        self._event_manager = event_manager
        self._watchlist_manager_name = watchlist_manager_name
        self._watchlist_manager: T_WL_CO

    def on_start(self):
        for bts in self._bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        # watchlist manager
        self._watchlist_manager: T_WL_CO = WATCHLIST_MANAGER_REGISTRY[
            self._watchlist_manager_name
        ](
            indicator_meta_set=self._indicator_meta_set,
            snapshot_time=self._snapshot_time,
            indicator_instrument_map=self._indicator_instrument_map,
            event_manager=self._event_manager,
            clock_provider=self.clock,
        )

        # event
        self.clock.set_timer(
            name="daily_reset",
            start_time=self._data_start_datetime.replace(
                hour=23, minute=59, second=59, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._daily_reset,
        )
        # reset
        self._register_daily_reset(self._watchlist_manager.reset)
        self._register_indicator()

    def on_bar(self, bar: Bar):
        current_datetime = self.clock.utc_now()
        if (
            self._current_session_datetime == None
            or self._current_session_datetime < current_datetime
        ):

            self._current_session_datetime = current_datetime
            self.clock.set_time_alert(
                name="post_on_bar",
                alert_time=current_datetime + datetime.timedelta(seconds=2),
                callback=self._post_on_bar,
            )

    def get_watchlist_manager(self) -> T_WL_CO:
        return self._watchlist_manager

    def _register_indicator(self):
        # registry indicator
        for indm in self._indicator_meta_set:
            if indm is None:
                continue
            indi = INDICATOR_REGISTRY.get(indm.indicator_name)
            if indi is None:
                raise Exception("Not valid indicator")
            bar_spec_requirement_from_fields = set(
                [bs.bar_spec_requirement for bs in indm.field_configs]
            )
            for iid, bts in self._bar_types.items():
                bts_spec = [f"{b.spec.step}-{b.spec.aggregation}" for b in bts]
                if set(bts_spec) in bar_spec_requirement_from_fields:
                    raise Exception(
                        "Bar type requirement not match, please add correct bar type"
                    )
                # too much loop, might have better work around
                t_bts = []
                for bt in bts:
                    if (
                        f"{bt.spec.step}-{bt.spec.aggregation}"
                        in bar_spec_requirement_from_fields
                    ):
                        t_bts.append(bt)
                t_ind = indi(
                    bar_types=t_bts,
                    field_configs=indm.field_configs,
                )
                self._indicator_instrument_map[indm.name][iid] = t_ind
                self._register_daily_reset(
                    t_ind.reset
                )  # mixin method, register reset method for all indicator
                for bt in t_bts:
                    self.register_indicator_for_bars(bt, t_ind)

    @abstractmethod
    def _post_on_bar(self, event): ...

    @abstractmethod
    def _register_daily_reset(self, callback: Callable[[], None]) -> None: ...

    @abstractmethod
    def _daily_reset(self, event): ...
