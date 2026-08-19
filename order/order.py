from abc import ABC, abstractmethod
from pydantic import BaseModel, model_validator

from nautilus_trader.model import InstrumentId
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.objects import Price, Quantity

from protocols.provider import ActorInfoProvider
from schemas import TradingRulesMutable


# model
class OrderConfig(BaseModel):
    instrument_id: InstrumentId
    order_side: OrderSide
    quantity: Quantity
    entry_order_type: OrderType
    tp_price: Price
    sl_trigger_price: Price
    time_in_force: TimeInForce


class BracketOrderConfig(OrderConfig):
    tp_price: Price
    sl_trigger_price: Price


class BracketLongMarketOrderConfig(BracketOrderConfig):
    order_side: OrderSide = OrderSide.BUY
    entry_order_type: OrderType = OrderType.MARKET


# order info
class OrderInfo(BaseModel):
    instrument_id: str
    order_side: str
    quantity: float
    order_type: str
    entry_order_type: str
    time_in_force: str

    @model_validator(mode="before")
    def convert_data_type(cls, data):
        for k, v in data.items():
            if isinstance(v, Price):
                data[k] = float(v)
            elif isinstance(v, Quantity):
                data[k] = float(v)
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


class BracketOrderInfo(OrderInfo):
    tp_price: float
    sl_trigger_price: float


class OrderConfigFactory(ABC):
    def __init__(self, instrument_id: str, provider: ActorInfoProvider):
        self.provider = provider
        self.instrument_id = instrument_id

    @abstractmethod
    def making_order(self) -> OrderConfig:
        pass


class ORBLongBracketOrderConfigFactory(OrderConfigFactory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trading_rule: TradingRulesMutable = self.provider.get_trading_rule()

    def making_order(self) -> OrderConfig:
        bar = self.provider.get_latest_bar_with_trading_bar_type(self.instrument_id)
        stop_price = self.provider.get_snapshot_intraday_low(self.instrument_id)
        # calculate quantity
        entry_price = bar.high.as_double()
        qty = self._calculate_quantity(stop_price=stop_price, entry_price=entry_price)
        instrument = self.provider.get_instrument(self.instrument_id)
        # order config
        order_config = BracketLongMarketOrderConfig(
            instrument_id=InstrumentId.from_str(self.instrument_id),
            quantity=instrument.make_qty(qty),
            tp_price=Price(bar.high.as_double() * 100.0, instrument.price_precision),
            sl_trigger_price=Price(stop_price, instrument.price_precision),
            time_in_force=TimeInForce.DAY,
        )
        return order_config

    def _calculate_quantity(self, stop_price: float, entry_price: float):
        risk = entry_price - stop_price - self.trading_rule.risk_rule.stop_price_buffer
        theoretical_quantity = self.trading_rule.risk_rule.maximum_lose_per_day / risk
        theoretical_order_value = theoretical_quantity * entry_price
        if theoretical_order_value > self.trading_rule.order_rule.order_value_maximum:
            value = self.trading_rule.order_rule.order_value_maximum
            quantity = value / entry_price
        else:
            value = theoretical_order_value
            quantity = theoretical_quantity
        return quantity


ORDER_CONFIG_FACTOR_REGISTER = {
    "orb_long_bracket_order_config_factory": ORBLongBracketOrderConfigFactory
}
