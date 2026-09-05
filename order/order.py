import enum
import datetime
from typing import Generic
from decimal import Decimal
from abc import ABC, abstractmethod
from collections import defaultdict
from decimal import Decimal
from pydantic import BaseModel, model_serializer, ConfigDict, Field
from pydantic_core.core_schema import SerializationInfo

from nautilus_trader.model.orders import Order
from nautilus_trader.model import InstrumentId, ClientOrderId, PositionId, Bar
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.objects import Price, Quantity, Money

from protocols.provider import ActorInfoProvider, PG

from schemas import TradingRulesMutable


# model
class OrderState(str, enum.Enum):
    REQUEST = "request"
    CREATED = "created"
    ACCEPTED = "accepted"
    SUBMITTED = "submitted"
    CANCELED = "canceled"
    FILLED = "filled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderRole(str, enum.Enum):
    PARENT = "parent"
    CHILD = "child"
    FORCED_CLOSE = "forced_close"


class PositionState(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class OrderTicket(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    is_forced_close_order: bool = False
    # for event log
    # time
    order_created_at: datetime.datetime | None = None
    order_accepted_at: datetime.datetime | None = None
    order_submitted_at: datetime.datetime | None = None
    order_rejected_at: datetime.datetime | None = None
    order_canceled_at: datetime.datetime | None = None
    order_expired_at: datetime.datetime | None = None
    order_filled_at: datetime.datetime | None = None
    # for event log
    order_state: OrderState = Field(default=OrderState.REQUEST)
    order_role: OrderRole | None = None
    order_client_order_id: ClientOrderId | None = None
    order_reference_price: float | None = None
    order_risk_price: float | None = None
    order_child_order_id: ClientOrderId | None = None
    order_parent_order_id: ClientOrderId | None = None
    order_filled_price_qty: list[tuple[float, float]] = []
    order: Order | None = None
    # position
    position_id: PositionId | None = None
    position_state: PositionState | None = None
    position_open_at: datetime.datetime | None = None
    position_closed_at: datetime.datetime | None = None
    position_realized_profit_and_loss: float | None = None
    position_maximum_favorable_excursion: float | None = None
    position_maximum_adverse_excursion: float | None = None
    # cost
    cost: float | None = None
    # for order factory
    instrument_id: InstrumentId | None = None
    order_side: OrderSide | None = None
    quantity: Quantity | None = None
    entry_order_type: OrderType | None = None
    entry_price: Price | None = None
    tp_price: Price | None = None
    trigger_price: Price | None = None
    sl_trigger_price: Price | None = None
    time_in_force: TimeInForce | None = None
    expire_time: datetime.datetime | None = None
    reduce_only: bool = False

    @model_serializer(mode="wrap")
    def convert_data_type(self, handler, info: SerializationInfo):
        readable = info.context.get("readable", False) if info.context else False
        data = handler(self)
        if not readable:
            data.pop("state", None)
            data.pop("role", None)
            data.pop("order", None)
            data.pop("risk_price", None)
            data.pop("client_order_id", None)
            data.pop("reference_price", None)
            data.pop("parent_order_ticket_id", None)
            data.pop("child_order_id", None)
            data.pop("parent_order_id", None)
            data.pop("position_id", None)
            data.pop("entry_order_type", None)
            return data

        for k, v in data.items():
            if isinstance(v, datetime.datetime):
                data[k] = v.isoformat(timespec="seconds")
            elif isinstance(v, Money):
                data[k] = v.as_float()
            elif isinstance(v, Price):
                data[k] = float(v)
            elif isinstance(v, Quantity):
                data[k] = float(v)
            elif isinstance(v, ClientOrderId):
                data[k] = str(v)
            elif isinstance(v, Order):
                data[k] = None
            elif isinstance(v, PositionId):
                data[k] = str(v)
            elif isinstance(v, InstrumentId):
                data[k] = str(v)
            elif isinstance(v, OrderType):
                if v == OrderType.MARKET:
                    data[k] = "market"
                elif v == OrderType.LIMIT:
                    data[k] = "limit"
                elif v == OrderType.STOP_LIMIT:
                    data[k] = "stop limit"
                elif v == OrderType.STOP_MARKET:
                    data[k] = "stop market"
                elif v == OrderType.MARKET_TO_LIMIT:
                    data[k] = "market to limit"
                elif v == OrderType.MARKET_IF_TOUCHED:
                    data[k] = "market if touch"
                elif v == OrderType.LIMIT_IF_TOUCHED:
                    data[k] = "limit if touch"
                elif v == OrderType.TRAILING_STOP_LIMIT:
                    data[k] = "trailing stop limit"
                elif v == OrderType.TRAILING_STOP_MARKET:
                    data[k] = "trailing stop market"
            elif isinstance(v, OrderSide):
                if v == OrderSide.BUY:
                    data[k] = "buy"
                elif v == OrderSide.SELL:
                    data[k] = "sell"
            elif isinstance(v, TimeInForce):
                if v == TimeInForce.DAY:
                    data[k] = "day order"
                elif v == TimeInForce.GTC:
                    data[k] = "good till canceled"
                elif v == TimeInForce.IOC:
                    data[k] = "immediate or cancel"
                elif v == TimeInForce.FOK:
                    data[k] = "fill or kill"
                elif v == TimeInForce.GTD:
                    data[k] = "good til date"
                elif v == TimeInForce.AT_THE_OPEN:
                    data[k] = "at the open"
                elif v == TimeInForce.AT_THE_CLOSE:
                    data[k] = "at the close"
        return data


class OrderTicketGroup(BaseModel):
    parent: OrderTicket
    child: OrderTicket


class OrderTicketManager:
    def __init__(self):
        self._books: dict[ClientOrderId, OrderTicket] = defaultdict()
        self._instrument_ids: set[InstrumentId] = set()

    @property
    def open_order_count(self):
        oot = 0
        for ot in self._books.values():
            if ot.order_state == OrderState.ACCEPTED:
                oot += 1

        return oot

    def get_tickets(self) -> dict[ClientOrderId, OrderTicket]:
        return self._books

    def get_ticket(self, client_order_id: ClientOrderId):
        return self._books.get(client_order_id)

    def get_child_order_ticket(self, client_order_id: ClientOrderId):
        ot = self._books.get(client_order_id)
        if not ot.order_role == OrderRole.PARENT:
            return
        cot = self._books.get(ot.order_child_order_id)
        return cot

    def register_ticket(
        self, client_order_id: ClientOrderId, order_ticket: OrderTicket
    ):
        self._books[client_order_id] = order_ticket
        self._instrument_ids.add(order_ticket.instrument_id)

    def update_on_order_submitted(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.SUBMITTED
        self._books[client_order_id].order_submitted_at = time

    def update_on_order_accepted(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.ACCEPTED
        self._books[client_order_id].order_accepted_at = time

    def update_on_order_rejected(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.REJECTED
        self._books[client_order_id].order_rejected_at = time

    def update_on_order_canceled(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.CANCELED
        self._books[client_order_id].order_canceled_at = time

    def update_on_order_expired(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.EXPIRED
        self._books[client_order_id].order_expired_at = time

    def update_on_order_filled(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.FILLED
        self._books[client_order_id].order_filled_at = time

    def update_position_id(
        self, client_order_id: ClientOrderId, position_id: PositionId
    ):
        self._books[client_order_id].position_id = position_id

    def update_position_state(
        self, client_order_id: ClientOrderId, position_state: PositionState
    ):
        self._books[client_order_id].position_state = position_state

    def update_position_open_time(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].position_open_at = time

    def update_position_close_time(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].position_closed_at = time

    def update_order_filled_price_qty(
        self, client_order_id: ClientOrderId, qty: Quantity, price: Price
    ):
        self._books[client_order_id].order_filled_price_qty.append(
            (price.as_decimal(), qty.as_decimal())
        )

    def update_cost(self, client_order_id: ClientOrderId, cost: Money):
        if self._books[client_order_id].cost is None:
            self._books[client_order_id].cost = cost
        else:
            self._books[client_order_id].cost += cost

    def update_position_realized_profit_and_loss(
        self, client_order_id: ClientOrderId, realized_profit_and_loss: Money
    ):

        self._books[client_order_id].position_realized_profit_and_loss = (
            realized_profit_and_loss
        )

    def upate_mae_mfe(self, bar: Bar):
        if not bar.bar_type.instrument_id in self._instrument_ids:
            return
        for v in self._books.values():
            if not v.instrument_id == bar.bar_type.instrument_id:
                continue
            if v.position_id is None:
                continue
            if v.order_role != OrderRole.PARENT:
                continue
            if v.is_forced_close_order:
                continue

            if v.order_side == OrderSide.BUY:
                tmp_mae = sum(
                    [(bar.low - fpq[0]) * fpq[1] for fpq in v.order_filled_price_qty]
                )
                tmp_mfe = sum(
                    [(bar.high - fpq[0]) * fpq[1] for fpq in v.order_filled_price_qty]
                )
            elif v.order_side == OrderSide.SELL:
                tmp_mfe = sum(
                    [(bar.low - fpq[0]) * fpq[1] for fpq in v.order_filled_price_qty]
                ) * Decimal(-1.0)
                tmp_mae = sum(
                    [(bar.high - fpq[0]) * fpq[1] for fpq in v.order_filled_price_qty]
                ) * Decimal(-1.0)

            if tmp_mfe > 0.0 and v.position_maximum_favorable_excursion is None:
                v.position_maximum_favorable_excursion = tmp_mfe
            elif tmp_mfe > 0.0 and tmp_mfe > v.position_maximum_favorable_excursion:
                v.position_maximum_favorable_excursion = tmp_mfe
            elif tmp_mae < 0.0 and v.position_maximum_adverse_excursion is None:
                v.position_maximum_adverse_excursion = tmp_mae
            elif tmp_mae < 0.0 and tmp_mae < v.position_maximum_adverse_excursion:
                v.position_maximum_adverse_excursion = tmp_mae


class OrderTicketComposer(ABC, Generic[PG]):
    def __init__(self, provider: PG, instrument_id: str):
        self._provider: PG = provider
        self._instrument_id = instrument_id
        self._order_ticket_groups: list[OrderTicketGroup] = []

    @property
    @abstractmethod
    def order_ticket_groups(self) -> list[OrderTicketGroup]:
        return self._order_ticket_groups

    @abstractmethod
    def compose(self): ...


class ORBOrderTicketComposer(OrderTicketComposer[ActorInfoProvider]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trading_rule: TradingRulesMutable = self._get_trading_rules()
        self._instrument = self._provider.get_instrument(self._instrument_id)
        self._parent_order_ticket: OrderTicket
        self._child_order_ticket: OrderTicket

    @property
    def order_ticket_groups(self):
        return self._order_ticket_groups

    def compose(self):
        self._create_child_order_ticket()
        self._create_parent_order_ticket()
        # risk price
        risk_price = self._calculate_risk_price()
        self._parent_order_ticket.order_risk_price = risk_price
        self._child_order_ticket.trigger_price = self._instrument.make_price(risk_price)
        # quantity
        quantity = self._calculate_quantity()
        # happen when the bar.close is lower than stop loss price
        if quantity is None:
            return
        self._parent_order_ticket.quantity = self._instrument.make_qty(quantity)
        self._child_order_ticket.quantity = self._instrument.make_qty(quantity)
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

    def _create_parent_order_ticket(self):
        parent_order_ticket: OrderTicket = OrderTicket(
            instrument_id=InstrumentId.from_str(self._instrument_id)
        )
        parent_order_ticket.order_side = OrderSide.BUY
        parent_order_ticket.entry_order_type = OrderType.MARKET
        parent_order_ticket.time_in_force = TimeInForce.FOK
        parent_order_ticket.expire_time = self._provider.get_current_datetime().replace(
            hour=self._trading_rule.session_rule.forced_close_at.hour,
            minute=self._trading_rule.session_rule.forced_close_at.minute,
            second=self._trading_rule.session_rule.forced_close_at.second,
            tzinfo=None,
        )
        parent_order_ticket.order_reference_price = self._calculate_entry_price()
        parent_order_ticket.order_role = OrderRole.PARENT
        self._parent_order_ticket = parent_order_ticket

    def _create_child_order_ticket(self):
        # child order
        child_order_ticket: OrderTicket = OrderTicket(
            instrument_id=InstrumentId.from_str(self._instrument_id)
        )
        child_order_ticket.order_role = OrderRole.CHILD
        child_order_ticket.order_side = OrderSide.SELL
        child_order_ticket.entry_order_type = OrderType.STOP_MARKET
        child_order_ticket.time_in_force = TimeInForce.GTD
        child_order_ticket.expire_time = self._provider.get_current_datetime().replace(
            hour=self._trading_rule.session_rule.forced_close_at.hour,
            minute=self._trading_rule.session_rule.forced_close_at.minute,
            second=self._trading_rule.session_rule.forced_close_at.second,
            tzinfo=None,
        )
        child_order_ticket.reduce_only = True
        child_order_ticket.order_reference_price = self._calculate_risk_price()
        self._child_order_ticket = child_order_ticket

    def _calculate_quantity(self) -> Quantity:
        bar = self._provider.get_latest_bar_with_trading_bar_type(self._instrument_id)
        target_price = bar.close.as_double()

        sl_price = (
            self._get_intraday_low() - self._trading_rule.order_rule.stop_price_buffer
        )
        risk = bar.close.as_double() - sl_price
        if risk <= 0.0:
            return
        budget = self._calculate_budget()
        theo_qty = budget / risk
        theo_cost = bar.close.as_double() * theo_qty

        qty: float = 0.0

        if theo_cost > budget:
            qty = budget / target_price
        elif theo_cost <= budget:
            qty = theo_qty

        if self._is_down_sizing_trigger():
            qty = qty * self._trading_rule.order_rule.order_size_multiplier_ratio

        return self._instrument.make_qty(int(qty))

    def _is_down_sizing_trigger(self) -> bool:
        current_pnl = (
            self._provider.get_realized_profit_and_loss()
            + self._provider.get_unrealized_profit_and_loss()
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

    def _calculate_budget(self):
        deployed_balance = self._provider.get_depolyed_balance(self._instrument_id)
        budget = self._trading_rule.risk_rule.tradable_balance - deployed_balance
        if budget > self._trading_rule.order_rule.order_value_maximum:
            budget = self._trading_rule.order_rule.order_value_maximum
        return budget

    def _calculate_tp_price(self):
        bar = self._provider.get_latest_bar_with_trading_bar_type(self._instrument_id)
        price = bar.high.as_double() * 100.0

        return price

    def _calculate_risk_price(self):
        price = (
            self._get_intraday_low() - self._trading_rule.order_rule.stop_price_buffer
        )
        return price

    def _calculate_entry_price(self):
        bar = self._provider.get_latest_bar_with_trading_bar_type(self._instrument_id)
        return bar.close.as_double()

    def _get_intraday_high(self):
        return self._provider.get_snapshot_intraday_high(self._instrument_id)

    def _get_intraday_low(self):
        return self._provider.get_snapshot_intraday_low(self._instrument_id)

    def _get_trading_rules(self):
        return self._provider.get_trading_rule()


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


ORDER_COMPOSER_REGISTRY = {"orb_order_composer": ORBOrderTicketComposer}


class OrderFactory:
    def __init__(self):
        pass
