import datetime
from collections import defaultdict
from functools import singledispatchmethod

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.indicators.base import Indicator

from mixin import DailyResetMixin
from watchlist import WATCHLIST_MANAGER_REGISTRY
from indicator.indicator import IndicatorMeta, INDICATOR_REGISTRY
from message import WatchListRequest, WatchListResponse


class ConsolidationAndBreakoutIndicatorManageActorConfig(ActorConfig, frozen=True):
    name: str
    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
    snapshot_time: (
        datetime.time
    )  # time point which decide when the consolidation period end
    watchlist_manager: str
    msg_enpoint: str
    msg_outbound_endpoint: str


class ConsolidationAndBreakoutIndicatorManageActor(Actor, DailyResetMixin):
    def __init__(self, config: ConsolidationAndBreakoutIndicatorManageActorConfig):
        super().__init__(config)
        self._indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]] = (
            defaultdict(dict)
        )
        self._current_session_datetime: datetime.datetime | None = None
        self._watchlist_manager = WATCHLIST_MANAGER_REGISTRY[
            self.config.watchlist_manager
        ](
            indicator_meta_set=self.config.indicator_meta_set,
            snapshot_time=self.config.snapshot_time,
            indicator_instrument_map=self._indicator_instrument_map,
        )

    def on_start(self):
        self._init_daily_reset()
        self._register_daily_reset(self._on_daily_reset)
        self._register_daily_reset(self._watchlist_manager.reset)
        self._register_indicator()
        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)
        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self.config.data_start_datetime.replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._check_and_reset,
        )
        # request / response register
        self.msgbus.register(
            endpoint=self.config.msg_enpoint,
            handler=self._send_dataframe,
        )

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

    def on_historical_data(self, data):
        pass

    def on_stop(self):
        print(self._indicator_instrument_map)
        pass

    def _post_on_bar(self, event):
        """
        excute something after every round of on_bar finished
        """
        self._watchlist_manager.update(self._current_session_datetime.time())

    def _register_indicator(self):
        # registry indicator
        for indm in self.config.indicator_meta_set:
            if indm is None:
                continue
            indi = INDICATOR_REGISTRY.get(indm.indicator_name)
            if indi is None:
                raise Exception("Not valid indicator")
            bar_spec_requirement_from_fields = set(
                [bs.bar_spec_requirement for bs in indm.field_configs]
            )
            for iid, bts in self.config.bar_types.items():
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

    @singledispatchmethod
    def _dispatch_msg(self, msg) -> None:
        self.log.warning(f"Unhandled custom data type: {type(msg).__name__}")

    @_dispatch_msg.register
    def _send_watchlist(self, msg: WatchListRequest):
        res = WatchListResponse(
            is_ready=self._watchlist_manager.is_ready,
            payload=self._watchlist_manager.watchlist,
        )
        self.msgbus.send(endpoint=self.config.msg_outbound_endpoint, msg=res)

    def _check_and_reset(self, event) -> bool:
        date = self.clock.utc_now().date()
        if self._current_session_date is None:
            self._current_session_date = date
            return False

        if date != self._current_session_date:
            self._current_session_date = date
            for cb in self._reset_callbacks:
                cb()
            return True
        return False

    def _on_daily_reset(self):
        self._current_session_time = None
