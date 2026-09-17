from decimal import Decimal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.objects import Money


class IbkrTieredFeeConfig(StrategyConfig, frozen=True):
    fee_rate: Decimal = Decimal(str(0.001))
    fixed_fee: Decimal = Decimal(str(1.0))


class IbkrTieredFeeModel(FeeModel):
    def __init__(self, config: IbkrTieredFeeConfig):
        super().__init__()
        self.fee_rate = config.fee_rate
        self.fixed_fee = config.fixed_fee
        self.fee_per_share: Decimal = Decimal(str(0.005))

    def get_commission(
        self, instrument, quantity, price, Instrument_instrument, *args, **kwargs
    ):
        fee: Decimal = Decimal(str(0.0))
        max_fee_ratio: Decimal = Decimal(str(0.01))

        trade_value = quantity * price
        init_fee = quantity * self.fee_per_share
        if init_fee >= trade_value * max_fee_ratio:
            fee = trade_value * max_fee_ratio
        elif init_fee <= self.fixed_fee:
            fee = self.fixed_fee
        else:
            fee = init_fee

        return Money(fee, Instrument_instrument.quote_currency)
