from abc import ABC, abstractmethod
from typing import Any, TypeVar
from collections import defaultdict
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict

from nautilus_trader.model import Bar, InstrumentId

from trading_signal.factor import FactorConfig, FACTOR_REGISTRY
from schemas import AggregationMethod


@dataclass(frozen=True)
class SignalMeta:
    name: str
    factor_configs: list[FactorConfig]
    internal_aggregation_method: AggregationMethod
    is_entry_signal: bool
    is_exit_signal: bool


def build_factor(
    factor_configs: list[FactorConfig],
):
    factors = []
    for c in factor_configs:
        fc = FACTOR_REGISTRY.get(c.name)
        f = fc(
            c.name,
            operator=c.operator,
            threshold=c.threshold,
            bar_buffer_size=c.bar_buffer_size,
            bar_spec_requirement=c.bar_spec_requirement,
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
    ):
        self.name = name
        self.factor_configs = factor_configs
        self.factors = build_factor(
            factor_configs=factor_configs,
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


SIGNAL_REGISTRY: dict[str, type] = {"orb_entry_signal": ORBEntrySignal}


class InstrumentSignal(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    instrument_id: InstrumentId
    signals: list[BaseSignal]


class SignalManager(ABC):
    def __init__(self, signal_meta_set: list[SignalMeta]):
        self._signal_map: dict[InstrumentId, InstrumentSignal] = defaultdict()
        self._signal_meta_set: list[SignalMeta] = signal_meta_set
        self._is_instrument_ids_fixed = False

    @property
    @abstractmethod
    def signal_map(self) -> dict[InstrumentId, InstrumentSignal]:
        pass

    @property
    @abstractmethod
    def signal_meta_set(self) -> list[SignalMeta]:
        pass

    @abstractmethod
    def register(self, instrument_ids: list[InstrumentId]):
        pass

    @abstractmethod
    def update_signals(self, bars: list[Bar]):
        pass

    @abstractmethod
    def _build_signals(self) -> list[BaseSignal]:
        pass


SIGNAL_MANAGER = TypeVar("SIGNAL_MANAGER", bound=SignalManager)


class ORBSignalManager(SignalManager):
    @property
    def signal_map(self) -> dict[InstrumentId, InstrumentSignal]:
        return self._signal_map

    @property
    def signal_meta_set(self) -> list[SignalMeta]:
        return self._signal_meta_set

    def register(self, instrument_ids: list[InstrumentId]):
        if self._is_instrument_ids_fixed:
            return

        for iid in instrument_ids:
            if self._signal_map.get(iid, None) is None:
                self._signal_map[iid] = InstrumentSignal(
                    instrument_id=iid, signals=self._build_signals()
                )
        self._is_instrument_ids_fixed = True

    def update_signals(self, bars: list[Bar]):
        for bar in bars:
            if self._signal_map.get(bar.bar_type.instrument_id, None) is None:
                continue
            else:
                for s in self._signal_map[bar.bar_type.instrument_id].signals:
                    s.update(bar)

    def _build_signals(self):
        sl = []
        for signal_config in self._signal_meta_set:
            s = SIGNAL_REGISTRY.get(signal_config.name)
            sl.append(
                s(
                    name=signal_config.name,
                    factor_configs=signal_config.factor_configs,
                    is_entry_signal=signal_config.is_entry_signal,
                    is_exit_signal=signal_config.is_exit_signal,
                )
            )
        return sl


SIGNAL_MANAGER_REGISTRY: dict[str, type] = {"orb_signal_manager": ORBSignalManager}
