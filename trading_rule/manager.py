from decimal import Decimal
from abc import ABC, abstractmethod

from trading_rule.schemas import TradingRule
from protocols.provider import AccountInfoProvider


class TradingRuleManager(ABC):
    def __init__(
        self,
        trading_rule: TradingRule,
        account_info_provider: AccountInfoProvider,
    ):
        self._trading_rule: TradingRule = trading_rule
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
