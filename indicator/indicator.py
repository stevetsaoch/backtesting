import pandas as pd
import numpy as np
import datetime
from pydantic import BaseModel
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import BarType, Bar
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.core.datetime import unix_nanos_to_dt


class BaseIndicator(Indicator):
    def __init__(
        self,
        bar_types: list[BarType],
        data_model: BaseModel,
        snapshot_time: datetime.time | None = None,
    ):
        super().__init__(
            params=[
                "_".join(
                    [str(b) for b in bar_types],
                ),
                snapshot_time.isoformat() if snapshot_time is not None else None,
            ]
        )
        self.default_data = data_model()
        self.snapshot_time = snapshot_time


class IntradayIndicator(BaseIndicator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot_data: BaseModel | None = None
        self.latest_data = self.default_data.copy(deep=True)

    def handle_bar(self, bar: Bar):
        if bar.bar_type.spec.aggregation == BarAggregation.DAY:
            return
        if (
            bar.bar_type.spec.aggregation == BarAggregation.MINUTE
            and bar.bar_type.spec.step == 1
        ):
            self._update_date_and_open(bar)
            self._update_current_high_and_low(bar)
            self._update_trading_value(bar)
            self._update_snapshot(bar)
            self._update_amplitude()

    def get(self, snapshot: bool = False) -> None | BaseModel:
        if not snapshot:
            return self.latest_data.copy(deep=True)
        elif snapshot and self.snapshot_data is not None:
            return self.snapshot_data.copy(deep=True)
        else:
            return None

    def _update_snapshot(self, bar):
        bar_time = unix_nanos_to_dt(bar.ts_init).time()
        if bar_time == self.snapshot_time:
            self.snapshot_data = self.latest_data.copy(deep=True)

    def _update_current_high_and_low(self, bar):
        bar_high = bar.high.as_double()
        bar_low = bar.low.as_double()
        if self.latest_data.current_high is None:
            self.latest_data.current_high = bar_high
        elif bar_high > self.latest_data.current_high:
            self.latest_data.current_high = bar_high

        if self.latest_data.current_low is None:
            self.latest_data.current_low = bar_low
        elif bar_low < self.latest_data.current_low:
            self.latest_data.current_low = bar_low

    def _update_amplitude(self):
        print(self.latest_data)
        if (
            self.latest_data.current_high is None
            or self.latest_data.current_low is None
        ):
            return
        self.latest_data.amplitude = (
            self.latest_data.current_high - self.latest_data.current_low
        )

    def _update_trading_value(self, bar):
        price = (
            bar.high.as_double()
            + bar.low.as_double()
            + bar.open.as_double()
            + bar.close.as_double()
        ) / 4

        if self.latest_data.trading_value is None:
            self.latest_data.trading_value = price * bar.volume.as_double()
        else:
            self.latest_data.trading_value += price * bar.volume.as_double()

    def _update_date_and_open(self, bar):
        bar_date = unix_nanos_to_dt(bar.ts_init).date()
        if self.latest_data.current_date == bar_date:
            return
        if (
            self.latest_data.current_date is None
            or self.latest_data.current_date != bar_date
        ):
            self.latest_data.current_date = bar_date
            self.latest_data.open = bar.open.as_double()
            return

    def _reset(self):
        self.latest_data = self.default_data.copy(deep=True)
        self.snapshot_data = self.default_data.copy(deep=True)


class IndicatorHub:
    indicators = {"intraday": IntradayIndicator}

    @classmethod
    def get(cls, indicator_name: str):
        return cls.indicators.get(indicator_name, None)
