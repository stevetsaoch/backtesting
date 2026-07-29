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
)
from schemas import (
    NautilusInstrumentId,
    DataConfig,
    NautilusBarType,
    NautilusInstrumentId,
    IndicatorMeta,
    IndicatorDataField,
    CustomDataMeta,
)
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
symbols = symbols[0:3]
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
    bar_type_1_day = NautilusBarType(
        instrument=instrument_id,
        external_bar_size=1,
        external_bar_unit="day",
        l1_type=l1_type,
        external=True,
    )
    bar_types[instrument_id.to_string()] = [
        bar_type_1_min.to_bar_type(),
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

# fields and indicator
current_high = IndicatorDataField(name="current_high", default=None, field_type="float")
current_low = IndicatorDataField(name="current_low", default=None, field_type="float")
current_date = IndicatorDataField(
    name="current_date", default=None, field_type="datetime.date"
)
trading_value = IndicatorDataField(
    name="trading_value", default=None, field_type="float"
)
amplitude = IndicatorDataField(name="amplitude", default=None, field_type="float")
open = IndicatorDataField(name="open", default=None, field_type="float")

intraday = IndicatorMeta(
    name="intraday",
    bar_spec_requirements=[f"1-{BarAggregation.MINUTE}"],
    fields=[current_high, current_low, current_date, trading_value, amplitude, open],
)

# other
consolidation_end: datetime.time = datetime.time(10, 30, 0)
a = ImportableActorConfig(
    actor_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActor",
    config_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActorConfig",
    config={
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday],
        "consolidation_end": consolidation_end,
    },
)
s = ImportableStrategyConfig(
    strategy_path="strategy.intraday:ConsolidationAndBreakout",
    config_path="strategy.intraday:ConsolidationAndBreakoutConfig",
    config={
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday],
        "consolidation_end": consolidation_end,
    },
)


btrc = BacktestRunConfig(
    engine=BacktestEngineConfig(
        actors=[a], strategies=[s], logging=LoggingConfig(log_level="INFO")
    ),
    data=dcfs,
    venues=[backtest_venue_config],
)


node = BacktestNode(configs=[btrc])
results = node.run()
