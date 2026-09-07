import re
from decimal import Decimal
from functools import wraps
from typing import Callable, Literal
from abc import ABC, abstractmethod
from collections import defaultdict

from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model import InstrumentId, Bar, BarType


from schemas import TradingRulesMutable
from protocols.provider import ClockProvider, CacheInfoProvider
from order.order import OrderTicket


class OrderValidator(ABC):
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        cache_info_provider: CacheInfoProvider,
        clock_provider: ClockProvider,
    ):
        self._trading_rule: TradingRulesMutable = trading_rule
        self._cache_info_provider = cache_info_provider
        self._clock_provider = clock_provider
        self._pre_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )
        self._post_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )

    @property
    @abstractmethod
    def pre_order_validation_result(self) -> dict[InstrumentId, dict[str, bool]]: ...

    @property
    @abstractmethod
    def post_order_validation_result(self) -> dict[InstrumentId, dict[str, bool]]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def _validate_trading_session(self, instrument_id: InstrumentId) -> bool: ...

    @abstractmethod
    def _validate_kill_switch(self, instrument_id: InstrumentId) -> bool: ...

    @abstractmethod
    def _validate_available_chance(self, instrument_id: InstrumentId) -> bool: ...

    @abstractmethod
    def _validate_instrument_id_not_present_in_open_orders(
        self, instrument_id: InstrumentId
    ) -> bool: ...

    @abstractmethod
    def _validate_instrument_id_not_present_in_open_positions(
        self, instrument_id: InstrumentId
    ) -> bool: ...

    @abstractmethod
    def _validate_intraday_profit_and_loss(
        self, instrument_id: InstrumentId
    ) -> bool: ...

    @abstractmethod
    def _validate_cost_minimum_and_risk_value_minimum(
        self, order_ticket: OrderTicket
    ) -> bool: ...

    @abstractmethod
    def pre_order_validate(self, instrument_ids: list[InstrumentId]) -> None: ...

    @abstractmethod
    def post_order_validate(self, order_ticket: OrderTicket) -> None: ...

    @staticmethod
    def validation_result(
        target_attr: Literal[
            "_pre_order_validation_result", "_post_order_validation_result"
        ],
        key: str | None = None,
    ) -> Callable:
        if target_attr == "_pre_order_validation_result":
            f_look_up_key = lambda args, kwargs: (
                args[0] if args else kwargs["instrument_id"]
            )
        else:
            f_look_up_key = lambda args, kwargs: (
                args[0].instrument_id
                if args
                else kwargs["order_ticket"].order_client_order_id
            )

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(self, *args, **kwargs):
                result = func(self, *args, **kwargs)

                result_key = key
                if result_key is None:
                    name = func.__name__.lstrip("_")
                    name = re.sub(r"^validate_", "", name)
                    result_key = f"{name}_validation"

                look_up_key = f_look_up_key(args, kwargs)
                target_dict = getattr(self, target_attr)
                target_dict[look_up_key][result_key] = result
                return result

            return wrapper  # type: ignore[return-value]

        return decorator


class ORBLongOrderValidator(OrderValidator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._order_side = OrderSide.BUY
        self._position_side = PositionSide.LONG
        self._pre_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )
        self._post_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )

    @property
    def pre_order_validation_result(self) -> dict[InstrumentId, dict[str, bool]]:
        return self._pre_order_validation_result

    @property
    def post_order_validation_result(self) -> dict[InstrumentId, dict[str, bool]]:
        return self._post_order_validation_result

    def reset(self):
        self._pre_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )
        self._post_order_validation_result: dict[InstrumentId, dict[str, bool]] = (
            defaultdict(dict)
        )

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_trading_session(self, instrument_id: InstrumentId):
        if (
            self._clock_provider.utc_now().time()
            < self._trading_rule.session_rule.market_open_at
        ):
            return False
        elif (
            self._clock_provider.utc_now().time()
            < self._trading_rule.session_rule.trading_start_at
        ):
            return False
        elif (
            self._clock_provider.utc_now().time()
            > self._trading_rule.session_rule.market_close_at
        ):
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_kill_switch(self, instrument_id: InstrumentId):
        if (
            self._clock_provider.utc_now().time()
            > self._trading_rule.session_rule.forced_close_at
        ):
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_available_chance(self, instrument_id: InstrumentId):
        open_orders = self._cache_info_provider.orders_open(
            side=self._order_side, instrument_id=instrument_id
        )

        open_positions = self._cache_info_provider.positions_open(
            side=self._position_side, instrument_id=instrument_id
        )
        occupied_chance = len(open_positions) + len(open_orders)
        if occupied_chance >= self._trading_rule.position_rule.open_position_maximum:
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_instrument_id_not_present_in_open_orders(
        self, instrument_id: InstrumentId
    ):
        open_orders = self._cache_info_provider.orders_open(
            side=self._order_side, instrument_id=instrument_id
        )
        if len(open_orders) > 0:
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_instrument_id_not_present_in_open_positions(
        self, instrument_id: InstrumentId
    ):
        open_positions = self._cache_info_provider.positions_open(
            side=self._position_side, instrument_id=instrument_id
        )
        if len(open_positions) > 0:
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_pre_order_validation_result")
    def _validate_intraday_profit_and_loss(self, instrument_id: InstrumentId):
        unr_pnl = self._get_intraday_unrealized_profit(instrument_id)
        r_pnl = self._get_intraday_realized_profit()
        c_pnl = abs(unr_pnl + r_pnl)
        if c_pnl >= self._trading_rule.risk_rule.intraday_loss_maximum:
            return False
        else:
            return True

    @OrderValidator.validation_result(target_attr="_post_order_validation_result")
    def _validate_cost_minimum_and_risk_value_minimum(self, order_ticket: OrderTicket):
        order_risk_value = order_ticket.quantity * (
            order_ticket.order_reference_price - order_ticket.order_risk_price
        )

        opportunity_cost_minimum = max(
            self._trading_rule.risk_rule.cost_efficiency_value_minimum,
            self._trading_rule.risk_rule.risk_value_minimum,
        )
        if order_risk_value < opportunity_cost_minimum:
            return False
        else:
            return True

    def _get_intraday_realized_profit(self) -> Decimal:
        total = Decimal("0")
        date = self._clock_provider.utc_now().date()
        for position in self._cache_info_provider.positions_closed():
            if position.ts_closed is not None:
                closed_dt = unix_nanos_to_dt(position.ts_closed)
                if closed_dt.date() == date:
                    total += position.realized_pnl.as_decimal()
        return total

    def _get_intraday_unrealized_profit(self, instrument_id: InstrumentId) -> Decimal:
        total = Decimal("0")
        date = self._clock_provider.utc_now().date()
        open_positions = self._cache_info_provider.positions_open(
            side=self._position_side, instrument_id=instrument_id
        )
        for p in open_positions:
            if unix_nanos_to_dt(p.ts_opened) == date:
                latest_bar = self._get_last_bar(instrument_id)
                pnl = p.unrealized_pnl(latest_bar.low)
                total += pnl.as_decimal()
        return total

    def _get_last_bar(self, instrument_id: InstrumentId) -> Bar:
        bar_type = BarType.from_str(
            f"{str(instrument_id)}-{self._trading_rule.order_rule.trading_bar_type}"
        )
        bar = self._cache_info_provider.bars(bar_type)[0]
        return bar

    def pre_order_validate(self, instrument_ids: list[InstrumentId]):
        instrument_id = instrument_ids[0]
        for instrument_id in instrument_ids:
            self._validate_trading_session(instrument_id)
            self._validate_kill_switch(instrument_id)
            self._validate_available_chance(instrument_id)
            self._validate_instrument_id_not_present_in_open_orders(instrument_id)
            self._validate_instrument_id_not_present_in_open_positions(instrument_id)
            self._validate_intraday_profit_and_loss(instrument_id)

    def post_order_validate(self, order_ticket: OrderTicket):
        self._validate_cost_minimum_and_risk_value_minimum(order_ticket=order_ticket)


ORDER_VALIDATOR_REGISTRY = {"orb_long_order_validator": ORBLongOrderValidator}
