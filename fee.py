from nautilus_trader.config import StrategyConfig
from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.objects import Money


class IbkrTieredFeeConfig(StrategyConfig, frozen=True):
    fee_rate: float = 0.001
    fixed_fee: float = 1.0


class IbkrTieredFeeModel(FeeModel):
    def __init__(self, config: IbkrTieredFeeConfig):
        super().__init__()
        self.fee_rate = config.fee_rate
        self.fixed_fee = config.fixed_fee

    def get_commission(
        self, instrument, quantity, price, Instrument_instrument, *args, **kwargs
    ):
        fee: float = 0.0
        trade_value = float(quantity) * float(price)
        init_fee = float(quantity) * 0.005
        if init_fee >= trade_value * 0.01:
            fee = trade_value * 0.01
        elif init_fee <= 1.0:
            fee = 1.0
        else:
            fee = init_fee

        return Money(fee, Instrument_instrument.quote_currency)
