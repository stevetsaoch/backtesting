from decimal import Decimal
from pydantic import BaseModel
from abc import ABC, abstractmethod

from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.orders import Order
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce, PositionSide
from nautilus_trader.model.objects import Quantity
from nautilus_trader.core.datetime import unix_nanos_to_dt

from protocols.provider import (
    ORBSnapshotIntradayInfoProvider,
    ClockProvider,
    OrderFactoryMethodProvider,
    CacheInfoProvider,
)

from order.order import OrderTicket, OrderState, OrderRole
from trading_rule_manager import TradingRulesMutable


class OrderTicketGroup(BaseModel):
    parent: OrderTicket
    child: OrderTicket


class OrderTicketComposer(ABC):
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
    ):
        self._order_ticket_groups: list[OrderTicketGroup] = []
        self._trading_rule = trading_rule

    @property
    @abstractmethod
    def order_ticket_groups(self) -> list[OrderTicketGroup]:
        return self._order_ticket_groups

    @abstractmethod
    def compose(self, candidates: list[InstrumentId]): ...

    @abstractmethod
    def compose_forced_close_order_ticket(
        self, order_tickets: list[OrderTicket]
    ) -> list[OrderTicket]: ...

    @abstractmethod
    def reset(self) -> None: ...


class ORBOrderTicketComposer(OrderTicketComposer):
    def __init__(
        self,
        orb_snapshot_intraday_info_provider: ORBSnapshotIntradayInfoProvider,
        clock_provider: ClockProvider,
        order_factory_method_provider: OrderFactoryMethodProvider,
        cache_info_provider: CacheInfoProvider,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._order_side = OrderSide.BUY
        self._position_side = PositionSide.LONG
        self._parent_order_ticket: OrderTicket
        self._child_order_ticket: OrderTicket
        self._orb_snapshot_intraday_info_provider = orb_snapshot_intraday_info_provider
        self._clock_provider = clock_provider
        self._order_factory_method_provider = order_factory_method_provider
        self._cache_info_provider = cache_info_provider

    @property
    def order_ticket_groups(self):
        return self._order_ticket_groups

    def reset(self):
        self._parent_order_ticket: OrderTicket
        self._child_order_ticket: OrderTicket
        self._order_ticket_groups: list[OrderTicketGroup] = []

    def compose(self, candidates: list[InstrumentId]):
        candidates = candidates[0]
        self._create_child_order_ticket(candidates)
        self._create_parent_order_ticket(candidates)
        # risk price
        risk_price = self._calculate_risk_price(candidates)
        self._parent_order_ticket.order_risk_price = risk_price
        self._child_order_ticket.trigger_price = self._cache_info_provider.instrument(
            candidates
        ).make_price(risk_price)
        # quantity
        quantity = self._calculate_quantity(candidates)
        # happen when the bar.close is lower than stop loss price
        if quantity is None:
            return
        self._parent_order_ticket.quantity = self._cache_info_provider.instrument(
            candidates
        ).make_qty(quantity)
        self._child_order_ticket.quantity = self._cache_info_provider.instrument(
            candidates
        ).make_qty(quantity)
        # referencing
        self._parent_order_ticket.order_child_order_id = (
            self._child_order_ticket.order_client_order_id
        )
        self._child_order_ticket.order_parent_order_id = (
            self._parent_order_ticket.order_client_order_id
        )

        # order group
        order_ticket_group = OrderTicketGroup(
            parent=self._parent_order_ticket, child=self._child_order_ticket
        )
        self._order_ticket_groups.append(order_ticket_group)
        self._create_order()

    def _create_parent_order_ticket(self, instrument_id: InstrumentId):
        parent_order_ticket: OrderTicket = OrderTicket(instrument_id=instrument_id)
        parent_order_ticket.order_side = OrderSide.BUY
        parent_order_ticket.entry_order_type = OrderType.MARKET
        parent_order_ticket.time_in_force = TimeInForce.FOK
        parent_order_ticket.expire_time = self._clock_provider.utc_now().replace(
            hour=self._trading_rule.session_rule.forced_close_at.hour,
            minute=self._trading_rule.session_rule.forced_close_at.minute,
            second=self._trading_rule.session_rule.forced_close_at.second,
            tzinfo=None,
        )
        parent_order_ticket.order_reference_price = self._calculate_entry_price(
            instrument_id
        )
        parent_order_ticket.order_role = OrderRole.PARENT
        self._parent_order_ticket = parent_order_ticket

    def _create_child_order_ticket(self, instrument_id: InstrumentId):
        # child order
        child_order_ticket: OrderTicket = OrderTicket(instrument_id=instrument_id)
        child_order_ticket.order_role = OrderRole.CHILD
        child_order_ticket.order_side = OrderSide.SELL
        child_order_ticket.entry_order_type = OrderType.STOP_MARKET
        child_order_ticket.time_in_force = TimeInForce.GTD
        child_order_ticket.expire_time = self._clock_provider.utc_now().replace(
            hour=self._trading_rule.session_rule.forced_close_at.hour,
            minute=self._trading_rule.session_rule.forced_close_at.minute,
            second=self._trading_rule.session_rule.forced_close_at.second,
            tzinfo=None,
        )
        child_order_ticket.reduce_only = True
        child_order_ticket.order_reference_price = self._calculate_risk_price(
            instrument_id
        )
        self._child_order_ticket = child_order_ticket

    def _create_order(self):
        for otg in self._order_ticket_groups:
            # child order
            c_order = self._create_stop_market_order(otg.child)
            otg.child.order = c_order
            otg.child.order_client_order_id = c_order.client_order_id
            # parent order
            p_order = self._create_market_order(otg.parent)
            otg.parent.order = p_order
            otg.parent.order_client_order_id = p_order.client_order_id

            otg.child.order_parent_order_id = p_order.client_order_id
            otg.child.order_state = OrderState.CREATED
            otg.child.order_created_at = self._clock_provider.utc_now()
            otg.parent.order_child_order_id = c_order.client_order_id
            otg.parent.order_state = OrderState.CREATED
            otg.parent.order_created_at = self._clock_provider.utc_now()

    def _calculate_quantity(self, instrument_id: InstrumentId) -> Quantity:
        bar = self._get_last_bar(instrument_id)
        target_price = bar.close.as_decimal()

        sl_price = (
            self._get_intraday_low(instrument_id)
            - self._trading_rule.order_rule.stop_price_buffer
        )
        risk = bar.close.as_decimal() - sl_price
        if risk <= Decimal(str(0.0)):
            return
        budget = self._calculate_budget(instrument_id)
        theo_qty = budget / risk
        theo_cost = bar.close.as_decimal() * theo_qty

        qty: Decimal = Decimal(str(0.0))

        if theo_cost > budget:
            qty = budget / target_price
        elif theo_cost <= budget:
            qty = theo_qty

        if self._is_down_sizing_trigger(instrument_id=InstrumentId):
            qty = qty * self._trading_rule.order_rule.order_size_multiplier_ratio

        return self._cache_info_provider.instrument(instrument_id).make_qty(int(qty))

    def _is_down_sizing_trigger(self, instrument_id: InstrumentId) -> bool:
        current_pnl = (
            self._get_intraday_realized_profit()
            + self._get_intraday_unrealized_profit(instrument_id)
        )
        if current_pnl < 0:
            if (
                abs(current_pnl)
                > self._trading_rule.order_rule.order_size_multiplier_trigger_minimum
            ):
                return True
            else:
                return False
        else:
            return False

    def _calculate_budget(self, instrument_id: InstrumentId):
        deployed_balance = self._get_deployed_balance(instrument_id)
        budget = (
            Decimal(self._trading_rule.risk_rule.tradable_balance) - deployed_balance
        )
        if budget > self._trading_rule.order_rule.order_value_maximum:
            budget = self._trading_rule.order_rule.order_value_maximum
        return budget

    def _calculate_tp_price(self, instrument_id: InstrumentId) -> Decimal:
        bar = self._get_last_bar(instrument_id)
        price = bar.high.as_decimal() * Decimal(100)

        return price

    def _calculate_risk_price(self, instrument_id: InstrumentId) -> Decimal:
        price = Decimal(self._get_intraday_low(instrument_id)) - Decimal(
            self._trading_rule.order_rule.stop_price_buffer
        )
        return price

    def _calculate_entry_price(self, instrument_id: InstrumentId) -> Decimal:
        bar = self._get_last_bar(instrument_id)
        return bar.close.as_decimal()

    def _get_deployed_balance(self, instrument_id: InstrumentId) -> Decimal:
        balance_from_positions = sum(
            (
                (Decimal(str(p.avg_px_open)) * p.quantity.as_decimal())
                for p in self._cache_info_provider.positions_open(
                    side=self._position_side, instrument_id=instrument_id
                )
            ),
            start=Decimal(0),
        )

        reference_bar = self._get_last_bar(instrument_id)
        balance_from_pending_orders = sum(
            (
                (
                    (
                        (
                            reference_bar.high.as_decimal()
                            + reference_bar.low.as_decimal()
                        )
                        / Decimal(2)
                    )
                    * o.quantity.as_decimal()
                )
                for o in list(self._cache_info_provider.orders_inflight())
                + list(
                    self._cache_info_provider.orders_open(
                        side=self._order_side, instrument_id=instrument_id
                    )
                )
            ),
            start=Decimal(0),
        )

        balance_deployed = balance_from_positions + balance_from_pending_orders
        return balance_deployed

    def _get_last_bar(self, instrument_id: InstrumentId) -> Bar:
        bar_type = BarType.from_str(
            f"{str(instrument_id)}-{self._trading_rule.order_rule.trading_bar_type}"
        )
        bar = self._cache_info_provider.bars(bar_type)[0]
        return bar

    def _get_intraday_high(self, instrument_id: InstrumentId) -> Decimal:
        return Decimal(
            self._orb_snapshot_intraday_info_provider.get_snapshot_intraday_high(
                instrument_id
            )
        )

    def _get_intraday_low(self, instrument_id: InstrumentId) -> Decimal:
        return Decimal(
            self._orb_snapshot_intraday_info_provider.get_snapshot_intraday_low(
                instrument_id
            )
        )

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
            side=self._position_side
        )
        for p in open_positions:
            if unix_nanos_to_dt(p.ts_opened) == date:
                latest_bar = self._get_last_bar(instrument_id)
                pnl = p.unrealized_pnl(latest_bar.low)
                total += pnl.as_decimal()
        return total

    def _create_market_order(self, order_ticket: OrderTicket) -> Order:
        order = self._order_factory_method_provider.market(
            instrument_id=order_ticket.instrument_id,
            order_side=order_ticket.order_side,
            quantity=order_ticket.quantity,
            time_in_force=order_ticket.time_in_force,
        )
        return order

    def _create_stop_market_order(self, order_ticket: OrderTicket) -> Order:
        order = self._order_factory_method_provider.stop_market(
            instrument_id=order_ticket.instrument_id,
            order_side=order_ticket.order_side,
            quantity=order_ticket.quantity,
            trigger_price=order_ticket.trigger_price,
            time_in_force=order_ticket.time_in_force,
            expire_time=order_ticket.expire_time,
            reduce_only=True,
        )
        return order

    # force close
    def compose_forced_close_order_ticket(self, order_tickets: list[OrderTicket]):
        ots = []
        for ot in order_tickets:
            order_ticket = ForcedCloseOrderComposer().compose(ot)
            order = self._create_forced_close_market(order_ticket)
            order_ticket.order = order
            order_ticket.order_client_order_id = order.client_order_id
            order_ticket.order_state = OrderState.CREATED
            order_ticket.order_created_at = self._clock_provider.utc_now()
            order_ticket.is_forced_close_order = True
            ots.append(order_ticket)
        return ots

    def _create_forced_close_market(self, order_ticket: OrderTicket) -> Order:
        order = self._order_factory_method_provider.market(
            instrument_id=order_ticket.instrument_id,
            order_side=order_ticket.order_side,
            quantity=order_ticket.quantity,
            time_in_force=order_ticket.time_in_force,
            reduce_only=True,
        )
        return order


class ForcedCloseOrderComposer:
    def __init__(self):
        pass

    def compose(self, parent_order_ticket: OrderTicket):
        order_ticket: OrderTicket = OrderTicket(
            instrument_id=parent_order_ticket.instrument_id
        )
        order_ticket.order_side = (
            OrderSide.SELL
            if parent_order_ticket.order_side == OrderSide.BUY
            else OrderSide.BUY
        )
        order_ticket.entry_order_type = OrderType.MARKET
        order_ticket.time_in_force = TimeInForce.GTC
        order_ticket.order_role = OrderRole.PARENT
        order_ticket.reduce_only = True
        order_ticket.quantity = parent_order_ticket.quantity
        return order_ticket


ORDER_COMPOSER_REGISTRY: dict[str, type[OrderTicketComposer]] = {
    "orb_order_composer": ORBOrderTicketComposer
}


class OrderFactory:
    def __init__(self):
        pass
