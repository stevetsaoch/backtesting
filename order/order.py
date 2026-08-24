import enum
import datetime
from typing import TypeVar, Generic
from abc import ABC, abstractmethod
from pydantic import BaseModel, model_serializer, ConfigDict, Field
from pydantic_core.core_schema import SerializationInfo

from nautilus_trader.model import InstrumentId, ClientOrderId, PositionId
from nautilus_trader.model.orders import Order
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.objects import Price, Quantity

from protocols.provider import Provider, ActorInfoProvider
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


class OrderTicket(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    # for event log
    state: OrderState = Field(default=OrderState.REQUEST)
    role: OrderRole | None = None
    client_order_id: ClientOrderId | None = None
    reference_price: float | None = None
    risk_price: float | None = None
    child_order_id: str | None = None
    parent_order_id: str | None = None
    position_id: PositionId | None = None
    order: Order | None = None
    #
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
            if isinstance(v, Price):
                data[k] = float(v)
            elif isinstance(v, Quantity):
                data[k] = float(v)
            elif isinstance(v, ClientOrderId):
                data[k] = str(v)
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


class OrderTicketBook:
    def __init__(self):
        self._books: dict[str, OrderTicket] = {}

    @property
    def open_order_count(self):
        oot = 0
        for ot in self._books.values():
            if ot.state == OrderState.ACCEPTED:
                oot += 1

        return oot

    def get_tickets(self):
        return self._books

    def get_ticket(self, client_order_id: ClientOrderId):
        return self._books.get(client_order_id)

    def get_child_order_ticket(self, client_order_id: ClientOrderId):
        ot = self._books.get(client_order_id)
        if not ot.role == OrderRole.PARENT:
            return
        cot = self._books.get(ot.child_order_id)
        return cot

    def register_ticket(self, client_order_id: str, order_ticket: OrderTicket):
        self._books[client_order_id] = order_ticket

    def update_on_order_submitted(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.SUBMITTED

    def update_on_order_accepted(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.ACCEPTED

    def update_on_order_rejected(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.REJECTED

    def update_on_order_canceled(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.CANCELED

    def update_on_order_expired(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.EXPIRED

    def update_on_order_filled(self, client_order_id: ClientOrderId):
        self._books[client_order_id].state = OrderState.FILLED

    def update_position_id(
        self, client_order_id: ClientOrderId, position_id: PositionId
    ):
        self._books[client_order_id].position_id = position_id


P = TypeVar("P", bound=Provider)


class OrderTicketComposer(ABC, Generic[P]):
    def __init__(self, provider: P, instrument_id: str):
        self.provider: P = provider
        self.instrument_id = instrument_id
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
        self.trading_rule: TradingRulesMutable = self._get_trading_rules()
        self.instrument = self.provider.get_instrument(self.instrument_id)
        self._parent_order_ticket: OrderTicket
        self._child_order_ticket: OrderTicket

    @property
    def order_ticket_groups(self):
        return self._order_ticket_groups

    def compose(self):
        self._create_child_order_ticket()
        self._create_parent_order_ticket()
        order_ticket_group = OrderTicketGroup(
            parent=self._parent_order_ticket, child=self._child_order_ticket
        )
        self._order_ticket_groups.append(order_ticket_group)

    def _create_parent_order_ticket(self):
        parent_order_ticket: OrderTicket = OrderTicket(
            instrument_id=InstrumentId.from_str(self.instrument_id)
        )
        parent_order_ticket.order_side = OrderSide.BUY
        parent_order_ticket.entry_order_type = OrderType.MARKET
        parent_order_ticket.time_in_force = TimeInForce.FOK
        parent_order_ticket.expire_time = self.provider.get_current_datetime().replace(
            hour=self.trading_rule.session_rule.forced_close_at.hour,
            minute=self.trading_rule.session_rule.forced_close_at.minute,
            second=self.trading_rule.session_rule.forced_close_at.second,
        )
        parent_order_ticket.quantity = self.instrument.make_qty(
            self._calculate_quantity()
        )
        parent_order_ticket.reference_price = self._calculate_entry_price()
        parent_order_ticket.risk_price = self._calculate_risk_price()
        parent_order_ticket.role = OrderRole.PARENT
        self._parent_order_ticket = parent_order_ticket

    def _create_child_order_ticket(self):
        # child order
        child_order_ticket: OrderTicket = OrderTicket(
            instrument_id=InstrumentId.from_str(self.instrument_id)
        )
        child_order_ticket.role = OrderRole.CHILD
        child_order_ticket.order_side = OrderSide.SELL
        child_order_ticket.entry_order_type = OrderType.STOP_MARKET
        child_order_ticket.time_in_force = TimeInForce.GTD
        child_order_ticket.expire_time = self.provider.get_current_datetime().replace(
            hour=self.trading_rule.session_rule.forced_close_at.hour,
            minute=self.trading_rule.session_rule.forced_close_at.minute,
            second=self.trading_rule.session_rule.forced_close_at.second,
        )
        child_order_ticket.trigger_price = self.instrument.make_price(
            self._calculate_risk_price()
        )
        child_order_ticket.reduce_only = True
        child_order_ticket.quantity = self._calculate_quantity()
        child_order_ticket.reference_price = self._calculate_risk_price()
        self._child_order_ticket = child_order_ticket

    def _calculate_quantity(self) -> Quantity:
        bar = self.provider.get_latest_bar_with_trading_bar_type(self.instrument_id)
        target_price = bar.close.as_double()

        sl_price = (
            self._get_intraday_low() - self.trading_rule.risk_rule.stop_price_buffer
        )
        risk = bar.close.as_double() - sl_price
        budget = self.trading_rule.order_rule.order_value_maximum
        theo_qty = budget / risk
        theo_cost = bar.close.as_double() * theo_qty

        qty: float = 0.0

        if theo_cost > budget:
            qty = budget / target_price
        elif theo_cost <= budget:
            qty = theo_qty

        return self.instrument.make_qty(int(qty))

    def _calculate_tp_price(self):
        bar = self.provider.get_latest_bar_with_trading_bar_type(self.instrument_id)
        price = bar.high.as_double() * 100.0

        return price

    def _calculate_risk_price(self):
        price = self._get_intraday_low() - self.trading_rule.risk_rule.stop_price_buffer
        return price

    def _calculate_entry_price(self):
        bar = self.provider.get_latest_bar_with_trading_bar_type(self.instrument_id)
        return bar.close.as_double()

    def _get_intraday_high(self):
        return self.provider.get_snapshot_intraday_high(self.instrument_id)

    def _get_intraday_low(self):
        return self.provider.get_snapshot_intraday_low(self.instrument_id)

    def _get_trading_rules(self):
        return self.provider.get_trading_rule()


ORDER_COMPOSER_REGISTRY = {"orb_order_composer": ORBOrderTicketComposer}


class OrderFactory:
    def __init__(self):
        pass
