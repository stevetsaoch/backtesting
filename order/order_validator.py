from protocols.provider import ActorInfoProvider
from schemas import TradingRulesMutable


class OrderValidator:
    def __init__(
        self,
        trading_rule: TradingRulesMutable,
        provider: ActorInfoProvider,
    ):
        self.trading_rule = trading_rule
        self.provider = provider
