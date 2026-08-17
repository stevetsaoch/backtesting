from abc import ABC, abstractmethod
from dataclasses import dataclass

from nautilus_trader.model import Bar

from strategy.provider_protocols import Provider
from strategy.factor import FactorConfig, FACTOR_REGISTRY
from schemas import Operator


@dataclass(frozen=True)
class SignalMeta:
    name: str
    factor_configs: list[FactorConfig]


def build_factor(
    instrument_id: str,
    factor_configs: list[FactorConfig],
    callback_provider: Provider,
):
    factors = []
    for c in factor_configs:
        fc = FACTOR_REGISTRY.get(c.name)
        f = fc(
            c.name,
            instrument_id=instrument_id,
            callback_provider=callback_provider,
            operator=c.operator,
            threshold=c.threshold,
        )
        factors.append(f)
    return factors


class BaseSignal(ABC):
    def __init__(
        self,
        name: str,
        instrument_id: str,
        factor_configs: list[FactorConfig],
        callback_provider: Provider,
    ):
        self.name = name
        self.factor_configs = factor_configs
        self.instrument_id = instrument_id
        self.factors = build_factor(
            instrument_id=self.instrument_id,
            factor_configs=factor_configs,
            callback_provider=callback_provider,
        )

    @abstractmethod
    def update(self, *args, **kwargs): ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...


class ORBEntrySignal(BaseSignal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update(self, bar: Bar):
        for s in self.factors:
            s.update(bar)

    @property
    def signal(self):
        tradeable = True
        for s in self.factors:
            if not s.signal:
                return False
        return tradeable


SIGNAL_REGISTRY: dict[str, type] = {"orb_entry_signal": ORBEntrySignal}
