import datetime
import pandas as pd
from collections import defaultdict
from functools import singledispatchmethod

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.indicators.base import Indicator

from mixin import DailyResetMixin
from schemas import SessionConfig
from indicator.field import TYPE_REGISTRY
from indicator.indicator import IndicatorMeta, INDICATOR_REGISTRY
from message import IntradayDataFrameResponse, IntradayDataFrameRequest


class ConsolidationAndBreakoutIndicatorManageActorConfig(ActorConfig, frozen=True):
    name: str
    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
    consolidation_end: (
        datetime.time
    )  # time point which decide when the consolidation period end
    session_config: SessionConfig
    msg_enpoint: str
    msg_outbound_endpoint: str


class ConsolidationAndBreakoutIndicatorManageActor(Actor, DailyResetMixin):
    def __init__(self, config: ConsolidationAndBreakoutIndicatorManageActorConfig):
        super().__init__(config)
        self.indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]] = (
            defaultdict(dict)
        )
        self._empty_dataframe = self._build_empty_dataframe()
        self._current_session_time: datetime.time | None = None

    def on_start(self):
        self._init_daily_reset()
        self._register_daily_reset(self._on_daily_reset)
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
        if bar.bar_type.spec.aggregation == BarAggregation.DAY:
            return

    def on_historical_data(self, data):
        pass

    def on_stop(self):
        print(self.indicator_instrument_map)
        pass

    def _register_indicator(self):
        # registry indicator
        for indm in self.config.indicator_meta_set:
            if indm is None:
                continue
            indi = INDICATOR_REGISTRY.get(indm.indicator_name)
            if indi is None:
                raise Exception("Not valid indicator")

            for iid, bts in self.config.bar_types.items():
                bts_spec = [f"{b.spec.step}-{b.spec.aggregation}" for b in bts]
                if set(bts_spec) in set(indm.bar_spec_requirements):
                    raise Exception(
                        "Bar type requirement not match, please add correct bar type"
                    )
                # too much loop, might have better work around
                t_bts = []
                for bt in bts:
                    if (
                        f"{bt.spec.step}-{bt.spec.aggregation}"
                        in indm.bar_spec_requirements
                    ):
                        t_bts.append(bt)
                t_ind = indi(
                    bar_types=t_bts,
                    snapshot_time=self.config.consolidation_end,
                    field_configs=indm.field_configs,
                )
                self.indicator_instrument_map[indm.name][iid] = t_ind
                self._register_daily_reset(
                    t_ind.reset
                )  # mixin method, register reset method for all indicator
                for bt in t_bts:
                    self.register_indicator_for_bars(bt, t_ind)

    def _build_empty_dataframe(self):
        fields = {"instrument_id": pd.Series(dtype="string")}
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
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

    def _build_dataframe(self, snapshot: bool = False):
        """
        Build a dataframe by collecting data from all indicator.
        """
        df = self._empty_dataframe.copy(deep=True)
        for v in self.indicator_instrument_map.values():
            for iid, ind in v.items():
                data = ind.get(snapshot=snapshot)
                if str(iid) in df["instrument_id"].values:
                    df.loc[df["instrument_id"] == str(iid), data.keys()] = data.values()
                else:
                    df.loc[len(df), "instrument_id"] = str(iid)
                    df.loc[df["instrument_id"] == str(iid), data.keys()] = data.values()
        return df

    @singledispatchmethod
    def _dispatch_msg(self, msg) -> None:
        self.log.warning(f"Unhandled custom data type: {type(msg).__name__}")

    @_dispatch_msg.register
    def _send_dataframe(self, msg: IntradayDataFrameRequest):
        if msg.snapshot:
            data = IntradayDataFrameResponse(
                data=self._build_dataframe(snapshot=msg.snapshot), snapshot=msg.snapshot
            )
        else:
            data = IntradayDataFrameResponse(
                data=self._build_dataframe(snapshot=msg.snapshot), snapshot=msg.snapshot
            )

        self.msgbus.send(endpoint=self.config.msg_outbound_endpoint, msg=data)

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
