import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

from nautilus_trader.model import Venue, Currency

from schemas import SweepConfig


class PortfolioInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    venue: Venue
    currency: Currency
    balance: Decimal


class FeeModelInfo(BaseModel):
    fee_per_share: Decimal
    minimum_fee_per_order: Decimal
    maximum_fee_ratio_per_order: Decimal


class OrderRule(BaseModel):
    trading_bar_type: str
    stop_price_buffer: Decimal
    order_value_maximum: (
        Decimal  # tradable_balance / open_position_maximum, update frequence: daily
    )
    # down sizing
    order_size_multiplier_trigger_loss_ratio: Decimal
    order_size_multiplier_trigger_minimum: Decimal  # order_size_multiplier_trigger_loss_ratio * intraday_loss_limit, update frequence: daily
    order_size_multiplier_ratio: Decimal  # change order size when intraday loss / intraday_loss_limit > trigger_loss_ratio


class PositionRule(BaseModel):
    open_position_maximum: Decimal


class RiskRule(BaseModel):
    # balance
    tradable_balance_ratio: Decimal
    tradable_balance: (
        Decimal  # balance * tradabel_balance_raito, update frequence: daily
    )
    # loss
    intraday_risk_ratio: Decimal
    intraday_loss_maximum: (
        Decimal  # balance * intraday_risk_ratio, update frequence: daily
    )
    # opportunity cost, actual risk value > max(cost_efficiency_minimum, risk_value_minimum)
    target_profit_minimum: Decimal
    cost_ratio_maximum: Decimal
    cost_estimated_per_trade: Decimal
    cost_efficiency_value_minimum: (
        Decimal  # cost estimated / cost ratio, prevent cost drag
    )
    risk_value_ratio_minimum: Decimal
    risk_value_minimum: Decimal  # risk_value_ratio * balance, update frequence: daily
    remaining_trade: Decimal


class SessionRule(BaseModel):
    market_open_at: datetime.time
    market_close_at: datetime.time
    trading_start_at: datetime.time
    forced_close_at: datetime.time


class TradingRule(BaseModel):
    portfolio_info: PortfolioInfo
    fee_model_info: FeeModelInfo
    order_rule: OrderRule
    position_rule: PositionRule
    risk_rule: RiskRule
    session_rule: SessionRule


class TradingRulePresetInbound(BaseModel):
    # portfolio
    venue: str
    currency: str
    balance: str

    # fee model info
    fee_per_share: str
    minimum_fee_per_order: str
    maximum_fee_ratio_per_order: str

    # position
    open_position_maximum: str

    # order
    trading_bar_type: str
    stop_price_buffer: str
    order_size_multiplier_ratio: str
    order_size_multiplier_trigger_loss_ratio: str

    # risk
    tradable_balance_ratio: str
    remaining_trade: str
    intraday_risk_ratio: str
    target_profit_minimum: str
    cost_ratio_maximum: str
    risk_value_ratio_minimum: str

    # session
    market_open_at: datetime.time
    market_close_at: datetime.time
    trading_start_at: datetime.time
    forced_close_at: datetime.time


class TradingRulePresetOutbound(BaseModel):
    # portfolio
    venue: str
    currency: str
    balance: str

    # fee model info
    fee_per_share: str
    minimum_fee_per_order: str
    maximum_fee_ratio_per_order: str

    # position
    open_position_maximum: str

    # order
    trading_bar_type: str
    stop_price_buffer: str
    order_size_multiplier_ratio: str
    order_size_multiplier_trigger_loss_ratio: str

    # risk
    tradable_balance_ratio: str
    remaining_trade: str
    intraday_risk_ratio: str
    target_profit_minimum: str
    cost_ratio_maximum: str
    risk_value_ratio_minimum: str

    # session
    market_open_at: datetime.time
    market_close_at: datetime.time
    trading_start_at: datetime.time
    forced_close_at: datetime.time

    # grid
    sweep: SweepConfig | None
