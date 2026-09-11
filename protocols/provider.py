import datetime
from typing import Protocol
from nautilus_trader.model import Bar, Quantity, Price, Venue, Money, Currency
from nautilus_trader.model.enums import OrderSide, PositionSide, TimeInForce
from nautilus_trader.model.position import Position
from nautilus_trader.model.orders import Order
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.instruments import Instrument

from watchlist import WatchListManager
from order.order import OrderTicket


class OrderTicketInfoProvider(Protocol):
    def get_open_position_tickets_with_instrument_id(
        self, instrument_id: InstrumentId
    ) -> list[OrderTicket]: ...


class WatchlistManagerProvider(Protocol):
    def get_watchlist_manager(self) -> WatchListManager: ...


class ORBSnapshotIntradayInfoProvider(Protocol):
    def get_snapshot_intraday_high(self, instrument_id: InstrumentId) -> float: ...
    def get_snapshot_intraday_low(self, instrument_id: InstrumentId) -> float: ...


class AccountInfoProvider(Protocol):
    def balance_total(self, currency: Currency) -> Money: ...


class ClockProvider(Protocol):
    def utc_now(self) -> datetime.datetime: ...


class OrderFactoryMethodProvider(Protocol):
    def market(
        self,
        instrument_id: InstrumentId,
        order_side: OrderSide,
        quantity: Quantity,
        time_in_force: TimeInForce,
    ) -> Order: ...
    def stop_market(
        self,
        instrument_id: InstrumentId,
        order_side: OrderSide,
        quantity: Quantity,
        trigger_price: Price,
        time_in_force: TimeInForce,
        expire_time: datetime.datetime,
        reduce_only: bool,
    ) -> Order: ...


class CacheInfoProvider(Protocol):
    def bars(self, BarType) -> list[Bar]: ...
    def instrument(self, instrument_id: InstrumentId) -> Instrument: ...
    def positions_open(
        self, side: PositionSide, instrument_id: InstrumentId | None = None
    ) -> list[Position]: ...
    def positions_closed(self) -> list[Position]: ...
    def orders_open(
        self, side: OrderSide, instrument_id: InstrumentId | None = None
    ) -> list[Order]: ...
    def orders_inflight(
        self, side: OrderSide, instrument_id: InstrumentId | None = None
    ) -> list[Order]: ...


class OrderInfoProvider(Protocol):
    pass


class PositionInfoProvider(Protocol):
    pass


class OrderCreationMethodProvider(Protocol):
    def create_order(self, order_ticket: OrderTicket) -> Order: ...


PROVIDER_REGISTRY = {}
