import datetime
from typing import Literal

import pandas as pd
from sortedcontainers import SortedList

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, BarAggregation, PositionSide

from schemas import NautilusBarType, NautilusInstrumentId


class ConsolidationAndBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for trading equities which consolidating in the morning and breakout the highest point in the period of consolidation
    """

    # information for building bar type and instrument_id
    symbols: list[str]
    venue: str
    bar_unit: str
    bar_size: int
    l1_type: str
    external: bool
    extra_bar_pair: list[
        tuple[
            int,
            Literal["year", "month", "day", "minute"],
        ]
    ]
    aggregated_bar_pair: list[
        tuple[
            int,
            Literal["year", "month", "day", "minute"],
        ]
    ]

    # filter
    prior_day_change: float
    intraday_change_upper_limit: float
    volatility_upper_limit: float
    trading_value_lower_limit: float
    filter_pacing: int
    filter_freeze_time: datetime.time
    filter_result_dir: str

    # trading
    start_trading_time: datetime.time
    max_open_position_count: int
    max_order_value: float
    risk_ratio: float


class ConsolidationAndBreakout(Strategy):
    def __init__(self, config: ConsolidationAndBreakoutConfig):
        super().__init__(config)
        self.instrument_ids = [
            NautilusInstrumentId(symbol=s, venue=self.config.venue)
            for s in self.config.symbols
        ]

        self.bar_types = [
            NautilusBarType(
                instrument=inid,
                bar_unit=self.config.bar_unit,
                bar_size=self.config.bar_size,
                l1_type=self.config.l1_type,
                external=self.config.external,
                extra_bar_pair=self.config.extra_bar_pair,
                aggregated_bar_pair=self.config.aggregated_bar_pair,
            )
            for inid in self.instrument_ids
        ]

        self.instrument_info_default = {
            "gap": 0.0,
            "trading_value": 0.0,
            "intraday_change": 0.0,
            "volatility": 0.0,
            "prior_day_change": 0.0,
            "current_high": 0.0,
            "latest_day_bar": None,
            "latest_date": datetime.date,
        }

        self.instruments_info = pd.DataFrame(
            data=self.instrument_info_default,
            index=[
                InstrumentId.from_str(inid.to_string()) for inid in self.instrument_ids
            ],
        )
        self.start_datetime: pd.Timestamp
        self.freezed_filter_result: pd.DataFrame

    def on_start(self) -> None:
        self.start_datetime = self.clock.utc_now()
        self.instruments_info["latest_date"] = self.start_datetime.date()

        # subscribe data
        for bt in self.bar_types:
            for abt in bt.to_aggregator_string():
                bar_type = BarType.from_str(abt)
                self.subscribe_bars(bar_type)
            for bbt in bt.to_extra_string():
                bar_type = BarType.from_str(bbt)
                self.subscribe_bars(bar_type)

        # data which required repeatly calc for filtering
        self.clock.set_timer(
            name="daily_info_calc",
            interval=datetime.timedelta(days=1),
            callback=self._daily_info_calc,
        )
        self.clock.set_timer(
            name="minute_info_calc",
            interval=datetime.timedelta(minutes=self.config.filter_pacing),
            callback=self._minute_info_calc,
        )
        # freeze the report
        self.clock.set_time_alert(
            name=f"save_filtered_results",
            alert_time=self.clock.utc_now().normalize()
            + pd.Timedelta(
                hours=self.config.filter_freeze_time.hour,
                minutes=self.config.filter_freeze_time.minute,
            ),
            callback=self._save_filtered_results,
        )
        self.handlers = {
            "minute_info_calc": self._minute_info_calc,
            "daily_info_calc": self._daily_info_calc,
        }

    def on_bar(self, bar: Bar):
        if bar.bar_type.spec.aggregation == BarAggregation.DAY:
            return
        if self.clock.utc_now().time() < self.config.start_trading_time:
            return

        if not self._check_position():
            return
        else:
            # trade
            pass

    def on_order_filled(self, event):
        return

    def on_stop(self) -> None:
        print(self.instruments_info)
        pass

    def on_event(self, event):
        # calc yesterday stock price change
        handler = self.handlers.get(event.name)
        if handler:
            handler(event)

    def _daily_info_calc(self, event):
        self._reset_info()
        for bt in self.cache.bar_types():
            if bt.spec.aggregation == BarAggregation.DAY:
                bars = self.cache.bars(bt)

                self._update_latest_date(
                    bt.instrument_id,
                    pd.Timestamp(
                        self.cache.bars(bt)[0].ts_event, unit="ns", tz="UTC"
                    ).date(),
                )
                self._update_latest_bar(
                    bt.instrument_id, bars[0]
                )  # record latest day bar for gap calculation
                if not bars or len(bars) < 2:
                    continue
                prior_day_change = (
                    float(bars[0].close) - float(bars[1].close)
                ) / float(bars[1].close)

                self._update_prior_day_change(bt.instrument_id, prior_day_change)

    def _minute_info_calc(self, event):
        # hard coded
        for bt in self.cache.bar_types():
            if bt.spec.aggregation == BarAggregation.MINUTE and bt.spec.step == 5:
                current_date = pd.Timestamp(
                    self.cache.bars(bt)[0].ts_event, unit="ns", tz="UTC"
                ).date()
                bars = [
                    b
                    for b in self.cache.bars(bt)
                    if pd.Timestamp(b.ts_event, unit="ns", tz="UTC").date()
                    == current_date
                    and pd.Timestamp(b.ts_event, unit="ns", tz="UTC").time()
                    > datetime.time(9, 30, 0)  # hard code
                ]
                if not bars:
                    continue

                # calc trading value
                trading_value = sum(
                    float(b.volume * ((b.high + b.low) / 2)) for b in bars
                )
                # calc intraday change
                intraday_change = float(
                    abs((bars[0].close - bars[-1].open) / bars[-1].open)
                )
                # calc volatility
                volatility = (
                    max(float(b.high) for b in bars) - min(float(b.low) for b in bars)
                ) / bars[-1].open

                self._update_trading_value(bt.instrument_id, trading_value)
                self._update_intraday_change(bt.instrument_id, intraday_change)
                self._update_volatility(bt.instrument_id, volatility)

                # update current high
                if (
                    bars[0].high
                    > self.instruments_info.loc[bt.instrument_id, "current_high"]
                ):
                    self._update_current_high(bt.instrument_id, float(bars[0].high))

                # update gap
                if self.instruments_info.loc[
                    bt.instrument_id, "latest_day_bar"
                ] is not None and pd.Timestamp(
                    bars[0].ts_event, unit="ns", tz="UTC"
                ).time() == datetime.time(
                    9, 35, 0
                ):
                    gap = float(bars[-1].open) - float(
                        self.instruments_info.loc[
                            bt.instrument_id, "latest_day_bar"
                        ].close
                    )
                    self._update_gap(bt.instrument_id, gap)

                # freeze the filter result
                if (
                    pd.Timestamp(bars[0].ts_event, unit="ns", tz="UTC").time()
                    == self.config.filter_freeze_time
                ):
                    self.freezed_filter_result = self.instruments_info.copy(deep=True)

    def _ranking(self):
        pass

    def _filtering(self):
        pass

    def _reset_info(self):
        for k, v in self.instrument_info_default.items():
            self.instruments_info[k] = v

    def _update_latest_date(self, index, value):
        self.instruments_info.loc[index, "latest_date"] = value

    def _update_latest_bar(self, index, value):
        self.instruments_info.loc[index, "latest_day_bar"] = value

    def _update_prior_day_change(self, index, value):
        self.instruments_info.loc[index, "prior_day_change"] = value

    def _update_trading_value(self, index, value):
        self.instruments_info.loc[index, "trading_value"] = value

    def _update_intraday_change(self, index, value):
        self.instruments_info.loc[index, "intraday_change"] = value

    def _update_volatility(self, index, value):
        self.instruments_info.loc[index, "volatility"] = value

    def _update_gap(self, index, value):
        self.instruments_info.loc[index, "gap"] = value

    def _update_current_high(self, index, value):
        self.instruments_info.loc[index, "current_high"] = value

    def _check_position(self):
        open_long_count = self.cache.positions_open_count(
            side=PositionSide.LONG,
        )
        if open_long_count + 1 > self.config.max_open_position_count:
            return False
        else:
            return True

    def _save_filtered_results(self, event):
        tmp = self.instruments_info.copy(deep=True)
        tmp = tmp.reset_index()
        tmp = tmp.drop(columns=["latest_day_bar"])
        tmp["index"] = tmp["index"].map(lambda x: x.value)

        tmp.to_parquet(f"{self.config.filter_result_dir}{self.clock.utc_now()}.parquet")
        # setting up a time event
        self.clock.set_time_alert(
            name=f"save_filtered_results",
            alert_time=self.clock.utc_now().normalize()
            + pd.Timedelta(
                days=1,  # hard code, because this is a daily event
                hours=self.config.filter_freeze_time.hour,
                minutes=self.config.filter_freeze_time.minute,
            ),
            callback=self._save_filtered_results,
        )
