import datetime
import duckdb
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.config import (
    BacktestRunConfig,
    BacktestEngineConfig,
    ImportableStrategyConfig,
    ImportableActorConfig,
    LoggingConfig,
    DataEngineConfig,
)
from schemas import (
    Operator,
    NautilusInstrumentId,
    DataConfig,
    NautilusBarType,
    NautilusInstrumentId,
    TradingRule,
    SessionConfig,
)
from indicator.field import IndicatorDataFieldConfig, IndicatorMeta
from strategy.factor import FactorConfig
from strategy.signal import SignalMeta
from config import NAUTILUS_CONFIG, VENUE_CONFIG

# global variables
catalog_path = NAUTILUS_CONFIG.catalog_path

# venue
venue = VENUE_CONFIG
venue.fee_model_path = "fee:IbkrTieredFeeModel"
venue.fee_model_config_path = "fee:IbkrTieredFeeConfig"
backtest_venue_config = venue.to_backtest_venue_config()

# data config
r = duckdb.sql(
    """
    SELECT DISTINCT(symbol) FROM read_parquet(?);
    """,
    params=[
        "/Volumes/backtesting_main/data/_missions/10_20_1min/2019-12-01 00:00:00|1|minute|23|day.parquet"
    ],
).df()

symbols = r["symbol"].to_list()
symbols = symbols[0:2]
# IIS/OS window
engine_start_time = datetime.datetime(2019, 12, 1, 0, 0, 0)
warmup_data_start_time = engine_start_time + datetime.timedelta(days=-5)
data_end_time = datetime.datetime(2019, 12, 4, 17, 0, 0)
dcfs = []

# preparing bar type
# bar type information
data_cls = "bar"
l1_type = "trade"
bar_types = {}
for s in symbols:
    instrument_id = NautilusInstrumentId(symbol=s, venue=venue.name)
    bar_type_1_min = NautilusBarType(
        instrument=instrument_id,
        external_bar_size=1,
        external_bar_unit="minute",
        l1_type=l1_type,
        external=True,
    )
    bar_type_5_min = NautilusBarType(
        instrument=instrument_id,
        external_bar_size=1,
        external_bar_unit="minute",
        l1_type=l1_type,
        external=False,
        internal_bar_size=5,
        internal_bar_unit="minute",
    )
    bar_type_1_day = NautilusBarType(
        instrument=instrument_id,
        external_bar_size=1,
        external_bar_unit="day",
        l1_type=l1_type,
        external=True,
    )
    bar_types[instrument_id.to_string()] = [
        bar_type_1_min.to_bar_type(),
        bar_type_5_min.to_bar_type(),
        bar_type_1_day.to_bar_type(),
    ]

    dcf_m = DataConfig(
        instrument=instrument_id,
        catalog_path=catalog_path,
        data_cls=data_cls,
        bar_types=[bar_type_1_min.to_bar_type()],  # hard code
        start_time=engine_start_time,
        end_time=data_end_time,
    ).to_backtest_data_config()

    dcf_d = DataConfig(
        instrument=instrument_id,
        catalog_path=catalog_path,
        data_cls=data_cls,
        bar_types=[bar_type_1_day.to_bar_type()],  # hard code
        start_time=warmup_data_start_time,
        end_time=data_end_time,
    ).to_backtest_data_config()
    dcfs.append(dcf_m)
    dcfs.append(dcf_d)

intraday_open = IndicatorDataFieldConfig(
    name="intraday_open",
    field_type="float",
    depends_on=(),
)
intraday_high = IndicatorDataFieldConfig(
    name="intraday_high",
    field_type="float",
    depends_on=(),
)
intraday_low = IndicatorDataFieldConfig(
    name="intraday_low",
    field_type="float",
    depends_on=(),
)
intraday_trading_value = IndicatorDataFieldConfig(
    name="intraday_trading_value",
    field_type="float",
    operator=Operator.GTE,
    threshold=10_000.0,
    depends_on=(),
)
intraday_high_updated_at = IndicatorDataFieldConfig(
    name="intraday_high_updated_at",
    field_type="datetime.time",
    depends_on=("intraday_high",),
)
intraday_low_updated_at = IndicatorDataFieldConfig(
    name="intraday_low_updated_at",
    field_type="datetime.time",
    depends_on=("intraday_low",),
)
intraday_amplitude = IndicatorDataFieldConfig(
    name="intraday_amplitude",
    field_type="float",
    operator=Operator.LTE,
    threshold=10.0,
    depends_on=(
        "intraday_high",
        "intraday_low",
        "intraday_open",
    ),
)
intraday_1_min = IndicatorMeta(
    name="intraday_1_min",
    indicator_name="intraday_short_period",
    bar_spec_requirements=[f"1-{BarAggregation.MINUTE}"],
    field_configs=[
        intraday_open,
        intraday_low,
        intraday_high,
        intraday_amplitude,
        intraday_trading_value,
        intraday_low_updated_at,
        intraday_high_updated_at,
    ],
)

# signal
clv_factor = FactorConfig(
    name="clv",
    operator=Operator.GTE,
    threshold=0.7,
    ascending=True,
    provider="factor_provider",
)
two_bar_higher_close = FactorConfig(
    name="two_bar_higher_close",
    operator=Operator.GTE,
    threshold=0.0,
    ascending=True,
    provider="factor_provider",
)
orb_entry_signal = SignalMeta(
    name="orb_entry_signal", factor_configs=[clv_factor, two_bar_higher_close]
)
# other
consolidation_end: datetime.time = datetime.time(10, 30, 0)
trading_rule: TradingRule = TradingRule(
    open_position_maximum=2,
    position_value_maximum=venue.starting_balances * 0.8,
    open_order_maximum=2,
    order_value_limit=800.0,
    forced_close_at=datetime.time(15, 30, 0, 0),
)
session_config = SessionConfig(
    market_open_at=datetime.time(9, 30, 0), market_close_at=datetime.time(16, 0, 0)
)

a = ImportableActorConfig(
    actor_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActor",
    config_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActorConfig",
    config={
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday_1_min],
        "consolidation_end": consolidation_end,
        "session_config": session_config,
        "msg_enpoint": "consolidation.actor",
        "msg_outbound_endpoint": "consolidation.strategy",
    },
)

s = ImportableStrategyConfig(
    strategy_path="strategy.intraday:ConsolidationAndBreakout",
    config_path="strategy.intraday:ConsolidationAndBreakoutConfig",
    config={
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday_1_min],
        "consolidation_end": consolidation_end,
        "session_config": session_config,
        "trading_rule": trading_rule,
        "signal_meta_set": [orb_entry_signal],
        # hard code
        "venue_currency_pair": {"SIM": "USD"},
        "msg_enpoint": "consolidation.strategy",
        "msg_outbound_endpoint": "consolidation.actor",
    },
)


btrc = BacktestRunConfig(
    engine=BacktestEngineConfig(
        actors=[a],
        strategies=[s],
        logging=LoggingConfig(log_level="INFO"),
        data_engine=DataEngineConfig(
            time_bars_timestamp_on_close=True,
            time_bars_build_with_no_updates=False,
            time_bars_skip_first_non_full_bar=True,
        ),
    ),
    data=dcfs,
    venues=[backtest_venue_config],
)


node = BacktestNode(configs=[btrc])
results = node.run()
