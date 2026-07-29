import datetime
from functools import singledispatchmethod

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.data import Data
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import InstrumentId, BarType
from nautilus_trader.model.enums import (
    PositionSide,
    OrderSide,
    OrderType,
)
from schemas import IndicatorMeta, CustomDataMeta
from custom_data.custom_data import PublishableData, IntradayDataFrame


class ConsolidationAndBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for trading equities which consolidating in the morning and breakout the highest point in the period of consolidation
    """

    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
    consolidation_end: (
        datetime.time
    )  # time point which decide when the consolidation period end


class ConsolidationAndBreakout(Strategy):
    def __init__(self, config: ConsolidationAndBreakoutConfig):
        super().__init__(config)

    def on_start(self):
        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        for data_cls in PublishableData._registry:
            self.subscribe_data(data_cls.subscription_type())

    def on_data(self, data: PublishableData) -> None:
        self._dispatch(data)

    @singledispatchmethod
    def _dispatch(self, data) -> None:
        self.log.warning(f"Unhandled custom data type: {type(data).__name__}")

    @_dispatch.register
    def _(self, data: IntradayDataFrame) -> None:
        pass
