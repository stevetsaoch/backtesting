from abc import ABC
from schemas import TradingRulesMutable
from protocols.provider import ActorInfoProvider


class DefaultOrderValidator(ABC):
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        provider: ActorInfoProvider,
    ):
        self._trading_rule: TradingRulesMutable = trading_rule
        self._provider = provider


class ORBOrderValidator(DefaultOrderValidator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._metrics: dict[str, bool] = {}

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

    def _validate_daily_loss(self):
        pnl = self._provider.get_intraday_realized_pnl()
        if pnl < 0.0 and abs(pnl) > self._trading_rule.risk_rule.maximum_lose_per_day:
            self._metrics["daily_lose_validation"] = False
            return
        else:
            self._metrics["daily_lose_validation"] = True
            return

    def _validate_position_total_count(self):
        positions = self._provider.get_positions()
        position_n = len(positions)
        if position_n >= self._trading_rule.position_rule.position_total_count_maximum:
            self._metrics["position_total_count_validation"] = False
            return
        else:
            self._metrics["position_total_count_validation"] = True
            return

    def _validate_position_value(self):
        positions = self._provider.get_positions()

    def _validate_order_total_count(self):
        otb = self._provider.get_order_ticket_book()
        order_n = otb.open_order_count
        if order_n >= self._trading_rule.order_rule.order_total_count_maximum:
            self._metrics["order_total_count_validation"] = False
            return
        else:
            self._metrics["order_total_count_validation"] = True
            return

    def _validate_order_value(self):
        pass

    def validate(self) -> dict:
        self._validate_trading_session()
        self._validate_kill_switch()
        self._validate_daily_loss()
        self._validate_position_total_count()
        self._validate_position_value()
        self._validate_order_total_count()
        self._validate_order_value()

        return self._metrics


ORDER_VALIDATOR_REGISTRY = {"orb_order_validator": ORBOrderValidator}


ORDER_VALIDATOR_REGISTRY = {"orb_order_validator": ORBOrderValidator}
