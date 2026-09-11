import datetime
from typing import Any
from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar

from trading_signal.factor import FactorConfig, FACTOR_REGISTRY
from schemas import AggregationMethod


@dataclass(frozen=True)
class SignalMeta:
    name: str
    factor_configs: list[FactorConfig]
    internal_aggregation_method: AggregationMethod
    is_entry_signal: bool
    is_exit_signal: bool


def build_factor(factor_configs: list[FactorConfig], established_at: datetime.datetime):
    factors = []
    for c in factor_configs:
        fc = FACTOR_REGISTRY.get(c.name)
        f = fc(
            c.name,
            operator=c.operator,
            threshold=c.threshold,
            bar_buffer_size=c.bar_buffer_size,
            bar_spec_requirement=c.bar_spec_requirement,
            established_at=established_at,
        )
        factors.append(f)
    return factors


class BaseSignal(ABC):
    def __init__(
        self,
        name: str,
        factor_configs: list[FactorConfig],
        is_entry_signal: bool,
        is_exit_signal: bool,
        established_at: datetime.datetime,
    ):
        self.name = name
        self.factor_configs = factor_configs
        self.factors = build_factor(
            factor_configs=factor_configs, established_at=established_at
        )
        self.is_entry_signal = is_entry_signal
        self.is_exit_signal = is_exit_signal

    @abstractmethod
    def update(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...

    @property
    @abstractmethod
    def metric(self) -> dict[Any, Any]: ...


class ORBEntrySignal(BaseSignal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, bar: Bar):
        for f in self.factors:
            f.update(bar)

    @property
    def signal(self):
        tradeable = True
        for f in self.factors:
            if not f.signal:
                return False
        return tradeable

    @property
    def metric(self):
        metric = {}
        for f in self.factors:
            metric[f.name] = f.value
        return metric


class ORBExitSignal(BaseSignal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, bar: Bar):
        for f in self.factors:
            f.update(bar)

    @property
    def signal(self):
        tradeable = True
        for f in self.factors:
            if not f.signal:
                return False
        return tradeable

    @property
    def metric(self):
        metric = {}
        for f in self.factors:
            metric[f.name] = f.value
        return metric


SIGNAL_REGISTRY: dict[str, type] = {
    "orb_entry_signal": ORBEntrySignal,
    "orb_exit_signal": ORBExitSignal,
}
