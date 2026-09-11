import datetime
from abc import ABC, abstractmethod
from typing import TypeVar
from collections import defaultdict
from pydantic import BaseModel, ConfigDict

from nautilus_trader.model import Bar, InstrumentId, ClientOrderId

from trading_signal.signal import BaseSignal, SignalMeta, SIGNAL_REGISTRY


class InstrumentSignal(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    instrument_id: InstrumentId
    signals: list[BaseSignal]


class OrderTicketSignal(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    instrument_id: InstrumentId
    client_order_id: ClientOrderId
    signals: list[BaseSignal]


class SignalManager(ABC):
    def __init__(self, signal_meta_set: list[SignalMeta]):
        self._entry_signal_map: dict[InstrumentId, InstrumentSignal] = defaultdict()
        self._exit_signal_map: dict[ClientOrderId, OrderTicketSignal] = defaultdict()
        self._signal_meta_set: list[SignalMeta] = signal_meta_set
        self._is_instrument_ids_fixed = False

    @property
    @abstractmethod
    def entry_signal_map(self) -> dict[InstrumentId, InstrumentSignal]: ...

    @property
    @abstractmethod
    def exit_signal_map(self) -> dict[ClientOrderId, OrderTicketSignal]: ...

    @property
    @abstractmethod
    def signal_meta_set(self) -> list[SignalMeta]: ...

    @abstractmethod
    def register_entry_signal(
        self, instrument_ids: list[InstrumentId], established_at: datetime.datetime
    ): ...

    @abstractmethod
    def register_exit_signal(
        self,
        client_order_id: ClientOrderId,
        instrument_id: InstrumentId,
        established_at: datetime.datetime,
    ): ...

    @abstractmethod
    def update_signals(self, bars: list[Bar]): ...

    @abstractmethod
    def reset_entry_signal(self) -> None: ...

    @abstractmethod
    def reset_exit_signal(self) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    def _build_entry_signals(self, established_at: datetime.datetime):
        sl = []
        for signal_config in self._signal_meta_set:
            if signal_config.is_entry_signal:
                s = SIGNAL_REGISTRY.get(signal_config.name)
                sl.append(
                    s(
                        name=signal_config.name,
                        factor_configs=signal_config.factor_configs,
                        is_entry_signal=signal_config.is_entry_signal,
                        is_exit_signal=signal_config.is_exit_signal,
                        established_at=established_at,
                    )
                )
        return sl

    def _build_exit_signals(self, established_at: datetime.datetime):
        sl = []
        for signal_config in self._signal_meta_set:
            if signal_config.is_exit_signal:
                s = SIGNAL_REGISTRY.get(signal_config.name)
                sl.append(
                    s(
                        name=signal_config.name,
                        factor_configs=signal_config.factor_configs,
                        is_entry_signal=signal_config.is_entry_signal,
                        is_exit_signal=signal_config.is_exit_signal,
                        established_at=established_at,
                    )
                )
        return sl


SIGNAL_MANAGER = TypeVar("SIGNAL_MANAGER", bound=SignalManager)


class ORBSignalManager(SignalManager):
    @property
    def entry_signal_map(self) -> dict[InstrumentId, InstrumentSignal]:
        return self._entry_signal_map

    @property
    def exit_signal_map(self) -> dict[ClientOrderId, OrderTicketSignal]:
        return self._exit_signal_map

    @property
    def signal_meta_set(self) -> list[SignalMeta]:
        return self._signal_meta_set

    def register_entry_signal(
        self, instrument_ids: list[InstrumentId], established_at: datetime.datetime
    ):
        if self._is_instrument_ids_fixed:
            return

        for iid in instrument_ids:
            if self._entry_signal_map.get(iid, None) is None:
                self._entry_signal_map[iid] = InstrumentSignal(
                    instrument_id=iid,
                    signals=self._build_entry_signals(established_at=established_at),
                )
        self._is_instrument_ids_fixed = True

    def register_exit_signal(
        self,
        client_order_id: ClientOrderId,
        instrument_id: InstrumentId,
        established_at: datetime.datetime,
    ):
        self._exit_signal_map[client_order_id] = OrderTicketSignal(
            client_order_id=client_order_id,
            instrument_id=instrument_id,
            signals=self._build_exit_signals(established_at=established_at),
        )

    def update_signals(self, bars: list[Bar]):
        for bar in bars:
            if self._entry_signal_map.get(bar.bar_type.instrument_id, None) is None:
                pass
            else:
                for s in self._entry_signal_map[bar.bar_type.instrument_id].signals:
                    s.update(bar)
                for exs in self._exit_signal_map.values():
                    if bar.bar_type.instrument_id == exs.instrument_id:
                        continue
                    else:
                        for s in exs.signals:
                            s.update(bar)

    def reset_entry_signal(self):
        self._is_instrument_ids_fixed = False
        self._entry_signal_map: dict[InstrumentId, InstrumentSignal] = defaultdict()

    def reset_exit_signal(self):
        self._exit_signal_map: dict[ClientOrderId, OrderTicketSignal] = defaultdict()

    def reset(self):
        self._is_instrument_ids_fixed = False
        self._entry_signal_map: dict[InstrumentId, InstrumentSignal] = defaultdict()
        self._exit_signal_map: dict[ClientOrderId, OrderTicketSignal] = defaultdict()


SIGNAL_MANAGER_REGISTRY: dict[str, type] = {"orb_signal_manager": ORBSignalManager}
