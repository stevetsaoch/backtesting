import datetime
import pandas as pd
from collections import defaultdict

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.core.datetime import unix_nanos_to_dt

from mixin import DailyResetMixin
from indicator.indicator import IndicatorHub
from custom_data.custom_data import PublishableData, IntradayDataFrame
from schemas import IndicatorMeta


class ConsolidationAndBreakoutIndicatorManageActorConfig(ActorConfig, frozen=True):
    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
    consolidation_end: (
        datetime.time
    )  # time point which decide when the consolidation period end


class ConsolidationAndBreakoutIndicatorManageActor(Actor, DailyResetMixin):
    def __init__(self, config: ConsolidationAndBreakoutIndicatorManageActorConfig):
        super().__init__(config)
        self.indicator_instrument_map: dict[str, dict[InstrumentId, Indicator]] = (
            defaultdict(dict)
        )
        self._current_session_time: datetime.time | None = None

    def on_start(self):
        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self.config.data_start_datetime.replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._check_and_reset,
        )

        self._init_daily_reset()
        self.register_daily_reset(self._reset)
        self._registry_indicator()
        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

    def on_bar(self, bar: Bar):
        if bar.bar_type.spec.aggregation == BarAggregation.DAY:
            pass
        if self._should_publish_dataframe(bar):
            latest_data = self._build_dataframe()
            self._publish(
                data=IntradayDataFrame(
                    data=latest_data,
                    ts_event=bar.ts_event,
                    ts_init=self.clock.timestamp_ns(),
                    snapshot=False,
                )
            )
            snapshot_data = self._build_dataframe(snapshot=True)
            self._publish(
                data=IntradayDataFrame(
                    data=snapshot_data,
                    ts_event=bar.ts_event,
                    ts_init=self.clock.timestamp_ns(),
                    snapshot=True,
                )
            )
        else:
            pass

    def on_historical_data(self, data):
        pass

    def on_stop(self):
        print(self.indicator_instrument_map)
        print(self._build_dataframe())

    def _registry_indicator(self):
        # registry indicator
        for indm in self.config.indicator_meta_set:
            if indm is None:
                continue
            indi = IndicatorHub.get(indm.name)
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
                    data_model=indm.data_model,
                )
                self.indicator_instrument_map[indm.name][iid] = t_ind
                self.register_daily_reset(
                    t_ind.reset
                )  # mixin method, register reset method for all indicator
                for bt in t_bts:
                    self.register_indicator_for_bars(bt, t_ind)

    def _build_dataframe(self, snapshot: bool = False):
        """
        Build a dataframe by collecting data from all indicator.
        Return None when any one of indicator return None
        """
        df = pd.DataFrame({"instrument_id": pd.Series(dtype="string")})
        for v in self.indicator_instrument_map.values():
            for iid, ind in v.items():
                data = ind.get(
                    snapshot=snapshot
                )  # indicator method, return None or a BaseModel
                if data is not None:
                    data = data.dict()
                    if str(iid) in df["instrument_id"].values:
                        df.loc[df["instrument_id"] == str(iid), data.keys()] = (
                            data.values()
                        )
                    else:
                        df.loc[len(df), "instrument_id"] = str(iid)
                        df.loc[df["instrument_id"] == str(iid), data.keys()] = (
                            data.values()
                        )
                else:
                    return None
        return df

    def _should_publish_dataframe(self, bar) -> bool:
        bar_time = unix_nanos_to_dt(bar.ts_init).time()
        if bar_time < self.config.data_start_datetime.time():
            return False
        if self._current_session_time is None:
            self._current_session_time = bar_time
            return False
        elif self._current_session_time == bar_time:
            return False
        elif self._current_session_time != bar_time:
            # reset current time
            self._current_session_time = bar_time
            # publish data
            return True
        return False

    def _publish(self, data: PublishableData) -> None:
        self.publish_data(data.data_type, data)

    def _reset(self):
        pass

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
