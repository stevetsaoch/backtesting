from collections import deque
from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar

from protocols.provider import ActorInfoProvider
from schemas import (
    Operator,
    RankingConfigs,
)


@dataclass(frozen=True)
class FactorConfig:
    name: str
    operator: Operator
    threshold: float
    bar_spec_requirement: str
    # for ranking,
    ascending: bool
    provider: str
    ranking_config: RankingConfigs
    bar_buffer_size: int


class Factor(ABC):
    def __init__(
        self,
        name: str,
        instrument_id: str,
        operator: Operator,
        threshold: float,
        bar_buffer_size: int,
        bar_spec_requirement: str,
        provider: ActorInfoProvider | None = None,
    ):
        self.name = name
        self.instrument_id = instrument_id
        self.provider = provider
        self.operator = operator
        self.threshold = threshold
        self.bar_buffer_size = bar_buffer_size
        self.bar_spec_requirement = bar_spec_requirement

    @abstractmethod
    def update(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...

    @property
    @abstractmethod
    def value(self) -> float | int: ...

    @abstractmethod
    def _check_bar_spec(self, bar: Bar) -> bool: ...


class CLVFactor(Factor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clv = 0.0
        self.stage = 0
        self.bars = deque(maxlen=self.bar_buffer_size)

    @property
    def signal(self):
        exceed: bool = False
        if len(self.bars) < self.bar_buffer_size:
            pass
        elif self.stage == 0:
            pass
        elif self.stage == 1:
            exceed = True
        return exceed

    @property
    def value(self):
        return self.clv

    def update(self, bar: Bar):
        if not self._check_bar_spec(bar):
            return

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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class TwoBarHigherCloseFactor(Factor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = 0
        self.bars = deque(maxlen=self.bar_buffer_size)
        self.spread = float("-inf")

    @property
    def signal(self):
        exceed: bool = False
        if len(self.bars) < self.bar_buffer_size:
            pass
        if self.stage == 0:
            pass
        if self.stage == 1:
            exceed = True
        return exceed

    @property
    def value(self):
        return self.spread

    def update(self, bar: Bar):
        if not self._check_bar_spec(bar):
            return

        self.bars.append(bar)
        if len(self.bars) == 2:
            v = self.bars[1].close.as_double() - self.bars[0].close.as_double()
            self.spread = v

            if self.operator.to_operator()(v, self.threshold):
                self.stage = 1

            else:
                self.stage = 0

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


FACTOR_REGISTRY: dict[str, type] = {
    "clv": CLVFactor,
    "two_bar_higher_close": TwoBarHigherCloseFactor,
}
