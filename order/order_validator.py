from typing import Generic
from abc import ABC

from nautilus_trader.model.enums import OrderSide, PositionSide


from schemas import TradingRulesMutable
from protocols.provider import PG, ActorInfoProvider
from order.order import OrderTicket


class DefaultOrderValidator(ABC, Generic[PG]):
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        provider: PG,
    ):
        self._trading_rule: TradingRulesMutable = trading_rule
        self._provider = provider


class ORBLongOrderValidator(DefaultOrderValidator[ActorInfoProvider]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._metrics: dict[str, bool] = {}
        self._order_side = OrderSide.BUY
        self._position_side = PositionSide.LONG

    def _validate_trading_session(self):
        if (
            self._provider.get_current_datetime().time()
            < self._trading_rule.session_rule.market_open_at
        ):
            self._metrics["trading_session_validation"] = False
            return
        elif (
            self._provider.get_current_datetime().time()
            < self._trading_rule.session_rule.trading_start_at
        ):
            self._metrics["trading_session_validation"] = False
            return
        elif (
            self._provider.get_current_datetime().time()
            > self._trading_rule.session_rule.market_close_at
        ):
            self._metrics["trading_session_validation"] = False
            return
        else:
            self._metrics["trading_session_validation"] = True
            return

    def _validate_kill_switch(self):
        if (
            self._provider.get_current_datetime().time()
            > self._trading_rule.session_rule.forced_close_at
        ):
            self._metrics["kill_switch_validation"] = False
            return
        else:
            self._metrics["kill_switch_validation"] = True
            return

    def _validate_available_chance(self, instrument_id: str):
        open_orders = self._provider.get_open_orders(
            side=self._order_side, instrument_id=instrument_id
        )

        open_positions = self._provider.get_open_positions(
            side=self._position_side, instrument_id=instrument_id
        )
        occupied_chance = len(open_positions) + len(open_orders)
        if occupied_chance >= self._trading_rule.position_rule.open_position_maximum:
            self._metrics["available_chance_validation"] = False
        else:
            self._metrics["available_chance_validation"] = True

    def _validate_instrument_id_not_present_in_open_orders(self, instrument_id: str):
        open_orders = self._provider.get_open_orders(
            side=self._order_side, instrument_id=instrument_id
        )
        if len(open_orders) > 0:
            self._metrics["instrument_id_not_present_in_open_order_validation"] = False
        else:
            self._metrics["instrument_id_not_present_in_open_order_validation"] = True

    def _validate_instrument_id_not_present_in_open_positions(self, instrument_id: str):
        open_positions = self._provider.get_open_positions(
            side=self._position_side, instrument_id=instrument_id
        )
        if len(open_positions) > 0:
            self._metrics["instrument_id_not_present_in_open_position_validation"] = (
                False
            )
        else:
            self._metrics["instrument_id_not_present_in_open_position_validation"] = (
                True
            )

    def _validate_intraday_profit_and_loss(self):
        unr_pnl = self._provider.get_unrealized_profit_and_loss()
        r_pnl = self._provider.get_realized_profit_and_loss()
        c_pnl = abs(unr_pnl + r_pnl)
        if c_pnl >= self._trading_rule.risk_rule.intraday_loss_maximum:
            self._metrics["intraday_profit_and_loss_validation"] = False
        elif c_pnl < self._trading_rule.risk_rule.intraday_loss_maximum:
            self._metrics["intraday_profit_and_loss_validation"] = True

    def _validate_cost_minimum_and_risk_value_minimum(self, order_ticket: OrderTicket):
        order_risk_value = order_ticket.quantity.as_double() * (
            order_ticket.order_reference_price - order_ticket.order_risk_price
        )

        opportunity_cost_minimum = max(
            self._trading_rule.risk_rule.cost_efficiency_value_minimum,
            self._trading_rule.risk_rule.risk_value_minimum,
        )
        if order_risk_value < opportunity_cost_minimum:
            self._metrics["cost_minimum_and_risk_value_minimum_validation"] = False
        elif order_risk_value >= opportunity_cost_minimum:
            self._metrics["cost_minimum_and_risk_value_minimum_validation"] = True

    def pre_order_validate(self, instrument_id: str):
        self._validate_trading_session()
        self._validate_kill_switch()
        self._validate_available_chance(instrument_id)
        self._validate_instrument_id_not_present_in_open_orders(instrument_id)
        self._validate_instrument_id_not_present_in_open_positions(instrument_id)
        self._validate_intraday_profit_and_loss()
        return self._metrics

    def post_order_validate(self, order_ticket: OrderTicket) -> dict:
        self._validate_cost_minimum_and_risk_value_minimum(order_ticket)
        return self._metrics


ORDER_VALIDATOR_REGISTRY = {"orb_long_order_validator": ORBLongOrderValidator}
