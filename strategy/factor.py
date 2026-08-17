import operator
from collections import deque
from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar

from schemas import Operator
from strategy.provider_protocols import FactorProvider


@dataclass(frozen=True)
class FactorConfig:
    name: str
    operator: Operator
    threshold: float
    # for ranking,
    ascending: bool
    provider: str


class Factor(ABC):
    def __init__(
        self,
        name: str,
        instrument_id: str,
        operator: Operator,
        threshold: float,
        callback_provider: FactorProvider | None = None,
    ):
        self.name = name
        self.instrument_id = instrument_id
        self.callback_provider = callback_provider
        self.operator = operator
        self.threshold = threshold

    @abstractmethod
    def update(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...

    @property
    @abstractmethod
    def metric(self) -> float | int: ...


class CLVFactor(Factor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clv = 0.0
        self.stage = 0
        self.bars = deque(maxlen=2)

    @property
    def signal(self):
        exceed: bool = False
        if self.stage == 0:
            pass
        if self.stage == 1:
            exceed = True
        return exceed

    @property
    def metric(self):
        return self.clv

    def update(self, bar: Bar):
        self.bars.append(bar)
        if len(self.bars) == 2:
            high = self.bars[0].high.as_double()
            low = self.bars[0].low.as_double()
            close = self.bars[0].close.as_double()
            try:
                clv = ((close - low) - (high - close)) / (high - low)
            except:
                clv = 0.0

            self.clv = clv
            if self.operator.to_operator()(clv, self.threshold):
                self.stage = 1

            else:
                self.stage = 0


class TwoBarHigherCloseFactor(Factor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = 0
        self.bars = deque(maxlen=2)
        self.spread = float("-inf")

    @property
    def signal(self):
        trade: bool = False
        if self.stage == 0:
            pass
        if self.stage == 1:
            trade = True
        return trade

    @property
    def metric(self):
        return self.spread

    def update(self, bar: Bar):
        self.bars.append(bar)
        if len(self.bars) == 2:
            v = self.bars[1].close.as_double() - self.bars[0].close.as_double()
            self.callback_provider.get_snapshot_intraday_high(self.instrument_id)
            self.spread = v

            if self.operator.to_operator()(v, self.threshold):
                self.stage = 1

            else:
                self.stage = 0


FACTOR_REGISTRY: dict[str, type] = {
    "clv": CLVFactor,
    "two_bar_higher_close": TwoBarHigherCloseFactor,
}
