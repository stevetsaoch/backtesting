import enum
import datetime
from decimal import Decimal
from collections import defaultdict
from pydantic import BaseModel, model_serializer, ConfigDict, Field
from pydantic_core.core_schema import SerializationInfo

from nautilus_trader.model.orders import Order
from nautilus_trader.model import InstrumentId, ClientOrderId, PositionId, Bar
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.objects import Price, Quantity, Money


# model
class OrderState(str, enum.Enum):
    REQUEST = "request"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_SUCCESSED = "validation_succeed"
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
    order_validation_failed_at: datetime.datetime | None = None
    order_validation_succeed_at: datetime.datetime | None = None
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
    order_reference_price: Decimal | None = None
    order_risk_price: Decimal | None = None
    order_child_order_id: ClientOrderId | None = None
    order_parent_order_id: ClientOrderId | None = None
    order_filled_price_qty: list[tuple[Decimal, Decimal]] = []
    order: Order | None = None
    # position
    position_id: PositionId | None = None
    position_state: PositionState | None = None
    position_open_at: datetime.datetime | None = None
    position_closed_at: datetime.datetime | None = None
    position_realized_profit_and_loss: Decimal | None = None
    position_maximum_favorable_excursion: Decimal | None = None
    position_maximum_adverse_excursion: Decimal | None = None
    # cost
    cost: Decimal | None = None
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

    def reset(self):
        self._books: dict[ClientOrderId, OrderTicket] = defaultdict()
        self._instrument_ids: set[InstrumentId] = set()

    def get_tickets(self) -> dict[ClientOrderId, OrderTicket]:
        return self._books

    def get_tickets_with_specific_state(
        self, order_state: OrderState
    ) -> dict[ClientOrderId, OrderTicket]:
        r = {k: v for k, v in self._books.items() if v.order_state == order_state}

        return r

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

    def update_on_validation_failed(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.VALIDATION_FAILED
        self._books[client_order_id].order_validation_failed_at = time

    def update_on_validation_succeed(
        self, client_order_id: ClientOrderId, time: datetime.time
    ):
        self._books[client_order_id].order_state = OrderState.VALIDATION_SUCCESSED
        self._books[client_order_id].order_validation_succeed_at = time

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
