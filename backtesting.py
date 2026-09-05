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
    TieBreakingMethod,
    AggregationMethod,
    PercentileRankingConfig,
    ZScoreRankingConfig,
    RankingConfigs,
    OrderRules,
    PositionRules,
    RiskRules,
    SessionRule,
)
from indicator.field import IndicatorFieldConfig
from indicator.indicator import IndicatorMeta
from trading_signal.factor import FactorConfig
from trading_signal.signal import SignalMeta
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
# symbols = ["AGNC", "B", "CNO"]
symbols = ["ANF", "CMC"]
# IIS/OS window
engine_start_time = datetime.datetime(2019, 12, 1, 0, 0, 0)
warmup_data_start_time = engine_start_time + datetime.timedelta(days=-5)
data_end_time = datetime.datetime(2019, 12, 5, 17, 0, 0)
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

intraday_open = IndicatorFieldConfig(
    name="intraday_open",
    field_name="intraday_open",
    field_type="float",
    depends_on=(),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_high = IndicatorFieldConfig(
    name="intraday_high",
    field_name="intraday_high",
    field_type="float",
    depends_on=(),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_low = IndicatorFieldConfig(
    name="intraday_low",
    field_name="intraday_low",
    field_type="float",
    depends_on=(),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_trading_value = IndicatorFieldConfig(
    name="intraday_trading_value",
    field_name="intraday_trading_value",
    field_type="float",
    operator=Operator.GTE,
    threshold=10_000.0,
    depends_on=(),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_high_updated_at = IndicatorFieldConfig(
    name="intraday_high_updated_at",
    field_name="intraday_high_updated_at",
    field_type="datetime.time",
    depends_on=("intraday_high",),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_low_updated_at = IndicatorFieldConfig(
    name="intraday_low_updated_at",
    field_name="intraday_low_updated_at",
    field_type="datetime.time",
    depends_on=("intraday_low",),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_amplitude = IndicatorFieldConfig(
    name="intraday_amplitude",
    field_name="intraday_amplitude",
    field_type="float",
    operator=Operator.LTE,
    threshold=10.0,
    depends_on=(
        "intraday_high",
        "intraday_low",
        "intraday_open",
    ),
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_atr = IndicatorFieldConfig(
    name="intraday_atr",
    field_name="intraday_atr",
    field_type="float",
    operator=Operator.LTE,
    threshold=10.0,
    depends_on=(),
    params={"bar_buffer_size": 14},
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
)
intraday_1_min = IndicatorMeta(
    name="intraday_1_min",
    indicator_name="intraday_short_period",
    field_configs=[
        intraday_open,
        intraday_low,
        intraday_high,
        intraday_amplitude,
        intraday_trading_value,
        intraday_low_updated_at,
        intraday_high_updated_at,
        intraday_atr,
    ],
)

# signal
clv_factor = FactorConfig(
    name="clv",
    operator=Operator.GTE,
    threshold=0.7,
    ascending=True,
    bar_buffer_size=2,
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
    ranking_config=RankingConfigs(
        percentile=PercentileRankingConfig(
            tie_breaking_method=TieBreakingMethod.MINIMUM, ascending=True
        ),
        zscore=ZScoreRankingConfig(ascending=True),
    ),
)
two_bar_higher_close = FactorConfig(
    name="two_bar_higher_close",
    operator=Operator.GT,
    threshold=0.0,
    ascending=False,
    bar_buffer_size=2,
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
    ranking_config=RankingConfigs(
        percentile=PercentileRankingConfig(
            tie_breaking_method=TieBreakingMethod.MINIMUM, ascending=True
        ),
        zscore=ZScoreRankingConfig(ascending=True),
    ),
)
ranking_method = "percentile"

signal_aggregation_method = AggregationMethod.MINIMUM

orb_entry_signal = SignalMeta(
    name="orb_entry_signal",
    factor_configs=[clv_factor, two_bar_higher_close],
    internal_aggregation_method=AggregationMethod.MINIMUM,
    is_entry_signal=True,
    is_exit_signal=False,
)
# other
snapshot_time: datetime.time = datetime.time(10, 30, 0)
signal_manager = "orb_signal_manager"

# fee model info, not include in config
fee_per_share = 0.005
minimum_fee_per_order = 1.0
maximum_fee_ratio_per_order = 0.01
target_price_minimum = 10.0


# trading rule
# position
open_position_maximum = 2.0
# order
trading_bar_type = f"1-MINUTE-LAST"
stop_price_buffer = 0.02
order_value_maximum = 800.0
order_size_multiplier_ratio = 0.5
order_size_multiplier_trigger_loss_ratio = 0.5
# risk
balance = VENUE_CONFIG.starting_balances
tradable_balance_ratio = 0.8
tradable_balance = balance * tradable_balance_ratio
intraday_risk_ratio = 0.02
intraday_loss_maximum = balance * intraday_risk_ratio
cost_ratio_maximum = 0.05
cost_estimated_per_trade = (
    minimum_fee_per_order
    if (order_value_maximum / target_price_minimum) * fee_per_share
    < maximum_fee_ratio_per_order * order_value_maximum
    else maximum_fee_ratio_per_order * order_value_maximum
) * 2.0
cost_efficiency_value_minimum = cost_estimated_per_trade / cost_ratio_maximum
risk_value_ratio_minimum = 0.005
risk_value_minimum = balance * risk_value_ratio_minimum
# session
market_open_at = datetime.time(9, 30, 0)
market_close_at = datetime.time(16, 0, 0)
trading_start_at = datetime.time(10, 30, 0)
forced_close_at = datetime.time(15, 30, 0)
# rules
order_rule: OrderRules = OrderRules(
    trading_bar_type=trading_bar_type,
    stop_price_buffer=stop_price_buffer,
    order_value_maximum=order_value_maximum,
    order_size_multiplier_trigger_loss_ratio=order_size_multiplier_trigger_loss_ratio,
    order_size_multiplier_trigger_minimum=intraday_loss_maximum
    * order_size_multiplier_trigger_loss_ratio,  # order_size_multiplier_trigger_loss_ratio * intraday_loss_limit, update frequence: daily
    order_size_multiplier_ratio=order_size_multiplier_ratio,
)
position_rule: PositionRules = PositionRules(
    open_position_maximum=open_position_maximum,
)
risk_rule: RiskRules = RiskRules(
    balance=balance,
    tradable_balance_ratio=tradable_balance_ratio,
    tradable_balance=tradable_balance,
    intraday_risk_ratio=intraday_risk_ratio,
    intraday_loss_maximum=intraday_loss_maximum,
    cost_ratio_maximum=cost_ratio_maximum,
    cost_estimated_per_trade=cost_estimated_per_trade,
    cost_efficiency_value_minimum=cost_efficiency_value_minimum,
    risk_value_ratio_minimum=risk_value_ratio_minimum,
    risk_value_minimum=risk_value_minimum,
)
session_rule: SessionRule = SessionRule(
    market_open_at=market_open_at,
    market_close_at=market_close_at,
    trading_start_at=trading_start_at,
    forced_close_at=forced_close_at,
)
# order
order_validator = "orb_long_order_validator"
order_composer = "orb_order_composer"
order_type = "bracket"
candidate_manager = "orb_candidate_manager"
# session
name = "test_backtesting"
order_config_factory = "orb_long_bracket_order_config_factory"
order_type = "bracket"
a = ImportableActorConfig(
    actor_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActor",
    config_path="actor.intraday:ConsolidationAndBreakoutIndicatorManageActorConfig",
    config={
        "name": name,
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday_1_min],
        "snapshot_time": snapshot_time,
        "msg_enpoint": "consolidation.actor",
        "msg_outbound_endpoint": "consolidation.strategy",
        "watchlist_manager": "orb_watchlist_manager",
    },
)

s = ImportableStrategyConfig(
    strategy_path="strategy.intraday:ConsolidationAndBreakout",
    config_path="strategy.intraday:ConsolidationAndBreakoutConfig",
    config={
        "name": name,
        "warmup_data_start_datetime": warmup_data_start_time,
        "data_start_datetime": engine_start_time,
        "bar_types": bar_types,
        "indicator_meta_set": [intraday_1_min],
        "order_rule": order_rule,
        "position_rule": position_rule,
        "risk_rule": risk_rule,
        "session_rule": session_rule,
        "order_config_factory": order_config_factory,
        "order_type": order_type,
        "order_validator": order_validator,
        "order_composer": order_composer,
        "signal_meta_set": [orb_entry_signal],
        "signal_aggregation_method": signal_aggregation_method,
        "signal_manager": signal_manager,
        # hard code
        "venue_currency_pair": {"venue": "SIM", "currency": "USD"},
        "msg_enpoint": "consolidation.strategy",
        "msg_outbound_endpoint": "consolidation.actor",
        "candidate_manager": "orb_candidate_manager",
        "ranking_method": "percentile",
    },
)


btrc = BacktestRunConfig(
    engine=BacktestEngineConfig(
        trader_id="test-trader",  # hard code
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
    dispose_on_completion=False,
)


node = BacktestNode(configs=[btrc])
results = node.run()
