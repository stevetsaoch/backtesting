import datetime
from collections import deque
from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar
from nautilus_trader.core.datetime import unix_nanos_to_dt

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
    ranking_config: RankingConfigs
    bar_buffer_size: int


class Factor(ABC):
    def __init__(
        self,
        name: str,
        operator: Operator,
        threshold: float,
        bar_buffer_size: int,
        bar_spec_requirement: str,
        established_at: datetime.datetime,
    ):
        self.name = name
        self.operator = operator
        self.threshold = threshold
        self.bar_buffer_size = bar_buffer_size
        self.bar_spec_requirement = bar_spec_requirement
        self._established_at = established_at

    @abstractmethod
    def update(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...

    @property
    @abstractmethod
    def value(self) -> float | int | dict: ...

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


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


class OneHourNoNewHigh(Factor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = 0
        self.bars = deque(maxlen=self.bar_buffer_size)
        self._highest_price: float = float("-inf")
        self._updated_at: datetime.datetime = self._established_at
        self._current_datetime: datetime.datetime

    @property
    def signal(self):
        exceed = (self._current_datetime - self._updated_at) > datetime.timedelta(
            hours=1
        )
        return exceed

    @property
    def value(self):
        return {
            "updated_at": f"{self._updated_at.replace(tzinfo=None)}",
            "current_datetime": f"{self._current_datetime.replace(tzinfo=None)}",
        }

    def update(self, bar: Bar):
        if not self._check_bar_spec(bar):
            return

        self.bars.append(bar)
        self._current_datetime = unix_nanos_to_dt(bar.ts_event)
        if bar.high.as_double() > self._highest_price:
            self._highest_price = bar.high.as_double()
            ts = unix_nanos_to_dt(bar.ts_event)
            self._updated_at = ts


FACTOR_REGISTRY: dict[str, type] = {
    "clv": CLVFactor,
    "two_bar_higher_close": TwoBarHigherCloseFactor,
    "one_hour_no_new_high": OneHourNoNewHigh,
}
