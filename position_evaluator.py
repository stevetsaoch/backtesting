from abc import ABC, abstractmethod

from nautilus_trader.model.enums import PositionSide, OrderSide
from nautilus_trader.model import Position, InstrumentId, ClientOrderId
from nautilus_trader.model.orders import Order

from trading_rule_manager import TradingRulesMutable
from trading_signal.signal import BaseSignal
from trading_signal.signal_manager import SignalManager
from protocols.provider import ClockProvider, CacheInfoProvider


class PositionEvaluator(ABC):
    """
    Monitoring on position to decide whether submit an order to close the position base on signal
    """

    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        signal_manager: SignalManager,
        cache_info_provider: CacheInfoProvider,
        clock_provider: ClockProvider,
    ):
        self._signal_manager: SignalManager = signal_manager
        self._cache_info_provider: CacheInfoProvider = cache_info_provider
        self._trading_rule: TradingRulesMutable = trading_rule
        self._clock_provider = clock_provider
        self._is_forced_close_triggered: bool = False
        self._is_exit_signal_triggered: bool = False
        self._client_order_ids: list[ClientOrderId] = []

    @property
    @abstractmethod
    def client_order_ids(self) -> list[ClientOrderId]: ...

    @property
    @abstractmethod
    def is_exit_signal_triggered(self) -> bool: ...

    @property
    @abstractmethod
    def is_forced_close_triggered(self) -> bool: ...

    @abstractmethod
    def evaluate_forced_close_triggered(self) -> bool: ...

    @abstractmethod
    def evaluate_exit_signal_triggered(self) -> bool: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def _get_open_positions(self) -> list[Position]: ...

    @abstractmethod
    def _get_open_orders(self) -> list[Order]: ...

    @abstractmethod
    def _get_exit_signals(
        self, client_order_id: ClientOrderId
    ) -> list[BaseSignal] | None: ...

    @abstractmethod
    def _get_signals(self, instrument_id: InstrumentId) -> list[BaseSignal] | None: ...

    @abstractmethod
    def _check_forced_close_time_trigger(self) -> bool: ...


class ORBPositionEvaluator(PositionEvaluator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._position_side = PositionSide.LONG
        self._order_side = OrderSide.BUY

    @property
    def client_order_ids(self):
        return self._client_order_ids

    @property
    def is_forced_close_triggered(self) -> bool:
        return self._is_forced_close_triggered

    @property
    def is_exit_signal_triggered(self) -> bool:
        return self._is_exit_signal_triggered

    def evaluate_forced_close_triggered(self) -> bool:
        if (
            self._clock_provider.utc_now().time()
            >= self._trading_rule.session_rule.forced_close_at
        ):
            self._is_forced_close_triggered = True
            open_position_client_order_ids = [
                oop.opening_order_id for oop in self._get_open_positions()
            ]
            self._client_order_ids += open_position_client_order_ids
        return self._is_forced_close_triggered

    def evaluate_exit_signal_triggered(self):
        open_positions = self._get_open_positions()

        for p in open_positions:
            sigs = self._get_exit_signals(p.opening_order_id)
            if sigs is None:
                return False

            for s in sigs:
                if not s.is_exit_signal:
                    continue
                if s.signal:
                    self._client_order_ids.append(p.opening_order_id)

        if len(self._client_order_ids) > 0:
            self._is_exit_signal_triggered = True

        return self._is_exit_signal_triggered

    def reset(self):
        self._is_forced_close_triggered: bool = False
        self._is_exit_signal_triggered: bool = False
        self._client_order_ids: list[ClientOrderId] = []

    def _get_open_positions(self):
        return self._cache_info_provider.positions_open(side=self._position_side)

    def _get_open_orders(self):
        orders_inflight = self._cache_info_provider.orders_inflight(
            side=self._order_side
        )
        orders_open = self._cache_info_provider.orders_open(side=self._order_side)
        return orders_inflight + orders_open

    def _get_signals(self, instrument_id: InstrumentId):
        try:
            sigs = self._signal_manager.entry_signal_map[instrument_id].signals
            return sigs
        except:
            pass
        finally:
            return

    def _get_exit_signals(self, client_order_id: ClientOrderId):
        try:
            sigs = self._signal_manager.exit_signal_map[client_order_id].signals
            return sigs
        except:
            pass

    def _check_forced_close_time_trigger(self):
        return (
            self._clock_provider.utc_now().time()
            >= self._trading_rule.session_rule.forced_close_at
        )


POSITION_EVALUATOR_REGISTRY = {"orb_position_evaluator": ORBPositionEvaluator}
