from typing import Any
from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar

from protocols.provider import Provider
from signal.factor import FactorConfig, FACTOR_REGISTRY
from schemas import AggregationMethod


@dataclass(frozen=True)
class SignalMeta:
    name: str
    factor_configs: list[FactorConfig]
    internal_aggregation_method: AggregationMethod


def build_factor(
    instrument_id: str,
    factor_configs: list[FactorConfig],
    provider: Provider,
):
    factors = []
    for c in factor_configs:
        fc = FACTOR_REGISTRY.get(c.name)
        f = fc(
            c.name,
            instrument_id=instrument_id,
            provider=provider,
            operator=c.operator,
            threshold=c.threshold,
            bar_buffer_size=c.bar_buffer_size,
        )
        factors.append(f)
    return factors


class BaseSignal(ABC):
    def __init__(
        self,
        name: str,
        instrument_id: str,
        factor_configs: list[FactorConfig],
        provider: Provider,
    ):
        self.name = name
        self.factor_configs = factor_configs
        self.instrument_id = instrument_id
        self.factors = build_factor(
            instrument_id=self.instrument_id,
            factor_configs=factor_configs,
            provider=provider,
        )

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
        for s in self.factors:
            s.update(bar)

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


SIGNAL_REGISTRY: dict[str, type] = {"orb_entry_signal": ORBEntrySignal}
