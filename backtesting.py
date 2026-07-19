import datetime
import numpy as np
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestRunConfig,
    BacktestEngineConfig,
    ImportableStrategyConfig,
    LoggingConfig,
)
from schemas import NautilusInstrumentId, DataConfig
from config import NAUTILUS_CONFIG, VENUE_CONFIG

# global variables
catalog_path = NAUTILUS_CONFIG.catalog_path
venue = NAUTILUS_CONFIG.venue

# data config
symbols = ["AA", "AAAU", "ABR"]
data_cls = "bar"
start_time = datetime.datetime(2020, 12, 30, 0, 0, 0)
end_time = datetime.datetime(2021, 1, 7, 0, 0, 0)
dcfs = []
for s in symbols:
    dcf = DataConfig(
        instrument=NautilusInstrumentId(symbol=s, venue=venue),
        catalog_path=catalog_path,
        data_cls=data_cls,
        start_time=start_time,
        end_time=end_time,
    ).to_backtest_data_config()
    dcfs.append(dcf)


# venue
vc = VENUE_CONFIG
vc.fee_model_path = "fee:IbkrTieredFeeModel"
vc.fee_model_config_path = "fee:IbkrTieredFeeConfig"
vc = vc.to_backtest_venue_config()

# bar type information
bar_unit = "minute"
bar_size = 1
l1_type = "trade"
external = True
aggregated_bar_pair = [(5, "minute")]
extra_bar_pair = [(1, "day")]

# filter
prior_day_change = [yc for yc in np.arange(0.01, 0.03, 0.005)]
intraday_change_upper_limit = [c for c in np.arange(0.01, 0.012, 0.001)]
volatility_upper_limit = [v for v in np.arange(0.025, 0.035, 0.005)]
trading_volue_lower_limit = [l for l in np.arange(1000000.0, 2000000.0, 200000.0)]
filter_pacing = 2
filter_freeze_time = datetime.time(10, 30, 0)
filter_result_dir = "./data/filter_results/"

# trading
start_trading_time = datetime.time(10, 30, 0)
max_open_position_count = 1
max_order_value = 800.0
risk_ratio = 0.02
s = ImportableStrategyConfig(
    strategy_path="strategy.day_trade:ConsolidationAndBreakout",
    config_path="strategy.day_trade:ConsolidationAndBreakoutConfig",
    config={
        "symbols": symbols,
        "venue": venue,
        "bar_unit": bar_unit,
        "bar_size": bar_size,
        "extra_bar_pair": extra_bar_pair,
        "l1_type": l1_type,
        "external": external,
        "aggregated_bar_pair": aggregated_bar_pair,
        # filter
        "prior_day_change": float(prior_day_change[0]),
        "intraday_change_upper_limit": float(intraday_change_upper_limit[0]),
        "volatility_upper_limit": float(volatility_upper_limit[0]),
        "trading_value_lower_limit": float(trading_volue_lower_limit[0]),
        "filter_pacing": filter_pacing,
        "filter_freeze_time": filter_freeze_time,
        "filter_result_dir": filter_result_dir,
        # trading
        "start_trading_time": start_trading_time,
        "max_open_position_count": max_open_position_count,
        "max_order_value": max_order_value,
        "risk_ratio": risk_ratio,
    },
)


btrc = BacktestRunConfig(
    engine=BacktestEngineConfig(
        strategies=[s], logging=LoggingConfig(log_level="DEBUG")
    ),
    data=dcfs,
    venues=[vc],
)


node = BacktestNode(configs=[btrc])
results = node.run()
