import datetime
from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict
from decimal import Decimal

from nautilus_trader.model import Venue, Currency

from protocols.provider import AccountInfoProvider


class PortfolioInfoMutable(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    venue: Venue
    currency: Currency
    balance: Decimal


class FeeModelInfoMutable(BaseModel):
    fee_per_share: Decimal
    minimum_fee_per_order: Decimal
    maximum_fee_ratio_per_order: Decimal


class OrderRulesMutable(BaseModel):
    trading_bar_type: str
    stop_price_buffer: Decimal
    order_value_maximum: (
        Decimal  # tradable_balance / open_position_maximum, update frequence: daily
    )
    # down sizing
    order_size_multiplier_trigger_loss_ratio: Decimal
    order_size_multiplier_trigger_minimum: Decimal  # order_size_multiplier_trigger_loss_ratio * intraday_loss_limit, update frequence: daily
    order_size_multiplier_ratio: Decimal  # change order size when intraday loss / intraday_loss_limit > trigger_loss_ratio


class PositionRulesMutable(BaseModel):
    open_position_maximum: Decimal


class RiskRulesMutable(BaseModel):
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


class SessionRuleMutable(BaseModel):
    market_open_at: datetime.time
    market_close_at: datetime.time
    trading_start_at: datetime.time
    forced_close_at: datetime.time


class TradingRulesMutable(BaseModel):
    portfolio_info: PortfolioInfoMutable
    fee_model_info: FeeModelInfoMutable
    order_rule: OrderRulesMutable
    position_rule: PositionRulesMutable
    risk_rule: RiskRulesMutable
    session_rule: SessionRuleMutable


class TradingRuleManager(ABC):
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        account_info_provider: AccountInfoProvider,
    ):
        self._trading_rule: TradingRulesMutable = trading_rule
        self._account_info_provider: AccountInfoProvider = account_info_provider

    @abstractmethod
    def update(self): ...


class ORBTradingRuleManager(TradingRuleManager):
    def update(self):
        # balance
        last_balance = self._account_info_provider.balance_total(
            self._trading_rule.portfolio_info.currency
        ).as_decimal()

        self._trading_rule.portfolio_info.balance = last_balance

        # tradable balance
        self._trading_rule.risk_rule.tradable_balance = (
            self._trading_rule.portfolio_info.balance
            * self._trading_rule.risk_rule.tradable_balance_ratio
        )
        # order value maximum
        self._trading_rule.order_rule.order_value_maximum = (
            self._trading_rule.risk_rule.tradable_balance
            / self._trading_rule.position_rule.open_position_maximum
        )

        # intraday loss maximum
        self._trading_rule.risk_rule.intraday_loss_maximum = (
            self._trading_rule.portfolio_info.balance
            * self._trading_rule.risk_rule.intraday_risk_ratio
        )
        # cost estimated per trade
        self._trading_rule.risk_rule.cost_estimated_per_trade = (
            self._trading_rule.fee_model_info.minimum_fee_per_order
            if (
                self._trading_rule.order_rule.order_value_maximum
                / self._trading_rule.risk_rule.target_profit_minimum
            )
            * self._trading_rule.fee_model_info.fee_per_share
            < self._trading_rule.fee_model_info.maximum_fee_ratio_per_order
            * self._trading_rule.order_rule.order_value_maximum
            else self._trading_rule.fee_model_info.maximum_fee_ratio_per_order
            * self._trading_rule.order_rule.order_value_maximum
        ) * Decimal(str(2.0))

        # cost efficiency value minimum
        self._trading_rule.risk_rule.cost_efficiency_value_minimum = (
            self._trading_rule.risk_rule.cost_estimated_per_trade
            / self._trading_rule.risk_rule.cost_ratio_maximum
        )

        # risk value minimum
        self._trading_rule.risk_rule.risk_value_minimum = (
            self._trading_rule.portfolio_info.balance
            * self._trading_rule.risk_rule.risk_value_ratio_minimum
        )


TRADING_RULE_MANAGER_REGISTRY = {"orb_trading_rule_manager": ORBTradingRuleManager}
