import datetime
import duckdb
from decimal import Decimal
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.model.objects import Currency, Money
from nautilus_trader.model import InstrumentId, BarType
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import (
    BacktestEngineConfig,
    DataEngineConfig,
    LoggingConfig,
    BacktestVenueConfig,
)
from schemas import (
    Operator,
    NautilusInstrumentId,
    NautilusBarType,
    NautilusInstrumentId,
    TieBreakingMethod,
    AggregationMethod,
    PercentileRankingConfig,
    ZScoreRankingConfig,
    RankingConfigs,
    PortfolioInfo,
    FeeModelInfo,
    OrderRules,
    PositionRules,
    RiskRules,
    SessionRule,
)
from nautilus_trader.model.enums import BarAggregation
from nautilus_trader.model.identifiers import Venue
from util import load_class_from_path
from indicator.field import IndicatorFieldConfig
from indicator.indicator import IndicatorMeta
from trading_signal.factor import FactorConfig
from trading_signal.signal import SignalMeta
from config import NAUTILUS_CONFIG, VENUE_CONFIG
from actor.intraday import (
    ConsolidationAndBreakoutIndicatorManageActor,
    ConsolidationAndBreakoutIndicatorManageActorConfig,
)
from strategy.intraday import ConsolidationAndBreakout, ConsolidationAndBreakoutConfig


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

# entry signal
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
orb_entry_signal = SignalMeta(
    name="orb_entry_signal",
    factor_configs=[clv_factor, two_bar_higher_close],
    internal_aggregation_method=AggregationMethod.MINIMUM,
    is_entry_signal=True,
    is_exit_signal=False,
)

# exit signal
one_hour_no_new_high = FactorConfig(
    name="one_hour_no_new_high",
    operator=Operator.GT,
    threshold=0.0,
    ascending=False,
    bar_buffer_size=1,
    bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
    ranking_config=RankingConfigs(
        percentile=PercentileRankingConfig(
            tie_breaking_method=TieBreakingMethod.MINIMUM, ascending=True
        ),
        zscore=ZScoreRankingConfig(ascending=True),
    ),
)
orb_exit_signal = SignalMeta(
    name="orb_exit_signal",
    factor_configs=[one_hour_no_new_high],
    internal_aggregation_method=AggregationMethod.MINIMUM,
    is_entry_signal=False,
    is_exit_signal=True,
)
ranking_method = "percentile"
signal_aggregation_method = AggregationMethod.MINIMUM
signal_manager = "orb_signal_manager"

# fee model info
fee_per_share = Decimal(str(0.005))
minimum_fee_per_order = Decimal(str(1.0))
maximum_fee_ratio_per_order = Decimal(str(0.01))

# trading rule
balance = Decimal(str(VENUE_CONFIG.starting_balances))
# position
open_position_maximum = Decimal(str(2.0))
# order
trading_bar_type = "1-MINUTE-LAST-EXTERNAL"
stop_price_buffer = Decimal(str(0.02))
order_size_multiplier_ratio = Decimal(str(0.5))
order_size_multiplier_trigger_loss_ratio = Decimal(str(0.5))
# risk
tradable_balance_ratio = Decimal(str(0.8))  # risk
tradable_balance = balance * tradable_balance_ratio  # risk
order_value_maximum = tradable_balance / open_position_maximum  # order
intraday_risk_ratio = Decimal(str(0.02))
intraday_loss_maximum = balance * intraday_risk_ratio
target_profit_minimum = Decimal(str(10.0))
cost_ratio_maximum = Decimal(str(0.1))
cost_estimated_per_trade = (
    minimum_fee_per_order
    if (order_value_maximum / target_profit_minimum) * fee_per_share
    < maximum_fee_ratio_per_order * order_value_maximum
    else maximum_fee_ratio_per_order * order_value_maximum
) * Decimal(str(2.0))
cost_efficiency_value_minimum = cost_estimated_per_trade / cost_ratio_maximum
risk_value_ratio_minimum = Decimal(str(0.005))
risk_value_minimum = balance * risk_value_ratio_minimum
# session
market_open_at = datetime.time(9, 30, 0)
market_close_at = datetime.time(16, 0, 0)
trading_start_at = datetime.time(10, 30, 0)
forced_close_at = datetime.time(15, 30, 0)
# rules
portfolio_info = PortfolioInfo(
    venue=Venue(VENUE_CONFIG.name),
    currency=Currency.from_str(VENUE_CONFIG.base_currency),
    balance=balance,
)
# fee model info
fee_model_info = FeeModelInfo(
    fee_per_share=fee_per_share,
    minimum_fee_per_order=minimum_fee_per_order,
    maximum_fee_ratio_per_order=maximum_fee_ratio_per_order,
)
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
    tradable_balance_ratio=tradable_balance_ratio,
    tradable_balance=tradable_balance,
    intraday_risk_ratio=intraday_risk_ratio,
    intraday_loss_maximum=intraday_loss_maximum,
    target_profit_minimum=target_profit_minimum,
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
trading_rule_manager = "orb_trading_rule_manager"
# cnadidate
candidate_manager = "orb_candidate_manager"
# order
order_validator = "orb_long_order_validator"
order_composer = "orb_order_composer"
# position
position_evaluator = "orb_position_evaluator"
# session

# engine
engine = BacktestEngine(
    config=BacktestEngineConfig(
        trader_id="test-trader",
        logging=LoggingConfig(log_level="INFO"),
        data_engine=DataEngineConfig(
            time_bars_timestamp_on_close=True,
            time_bars_build_with_no_updates=False,
            time_bars_skip_first_non_full_bar=True,
        ),
    )
)

# venue
venue_config = VENUE_CONFIG
venue_name = venue_config.name
venue_currency = venue_config.base_currency
venue_config.fee_model_path = "fee:IbkrTieredFeeModel"
venue_config.fee_model_config_path = "fee:IbkrTieredFeeConfig"
backtest_venue_config: BacktestVenueConfig = venue_config.to_backtest_venue_config()
# fee model
fill_model = FillModel(
    prob_fill_on_limit=venue_config.prob_fill_on_limit,
    prob_slippage=venue_config.prob_slippage,
    random_seed=venue_config.random_seed,
)

latency_model = (
    LatencyModel(base_latency_nanos=venue_config.base_latency_nanos)
    if venue_config.base_latency_nanos is not None
    else None
)
fee_model_cls = load_class_from_path(venue_config.fee_model_path)
fee_config_cls = load_class_from_path(venue_config.fee_model_config_path)
fee_model = fee_model_cls(config=fee_config_cls())

# add venue
engine.add_venue(
    venue=Venue(venue_config.name),
    oms_type=OmsType[venue_config.oms_type],
    account_type=AccountType[venue_config.account_type],
    base_currency=Currency.from_str(venue_config.base_currency),
    starting_balances=[
        Money(
            venue_config.starting_balances,
            Currency.from_str(venue_config.base_currency),
        )
    ],
    fill_model=fill_model,
    fee_model=fee_model,
    latency_model=latency_model,
)
# data config
engine_start_time = datetime.datetime(2019, 12, 1, 0, 0, 0)
warmup_data_start_time = engine_start_time + datetime.timedelta(days=-5)
data_end_time = datetime.datetime(2019, 12, 5, 17, 0, 0)
snapshot_time: datetime.time = datetime.time(10, 30, 0)
catalog_path = NAUTILUS_CONFIG.catalog_path
catalog = ParquetDataCatalog(catalog_path)
r = duckdb.sql(
    """
    SELECT DISTINCT(symbol) FROM read_parquet(?);
    """,
    params=[
        "/Volumes/backtesting_main/data/_missions/10_20_1min/2019-12-01 00:00:00|1|minute|23|day.parquet"
    ],
).df()
symbols = r["symbol"].to_list()
symbols = ["ANF", "CMC"]
# preparing bar type
# bar type information
data_cls = "bar"
l1_type = "trade"
instrument_ids = [
    NautilusInstrumentId(symbol=s, venue=venue_config.name).to_string() for s in symbols
]
bar_type_1_min = [
    NautilusBarType(
        instrument=NautilusInstrumentId(symbol=s, venue=venue_config.name),
        external_bar_size=1,
        external_bar_unit="minute",
        l1_type=l1_type,
        external=True,
    ).to_bar_type()
    for s in symbols
]
bars_1_min = catalog.bars(
    bar_types=bar_type_1_min,
    instrument_ids=instrument_ids,
    start=engine_start_time,
    end=data_end_time,
)
bar_type_1_day = [
    NautilusBarType(
        instrument=NautilusInstrumentId(symbol=s, venue=venue_config.name),
        external_bar_size=1,
        external_bar_unit="day",
        l1_type=l1_type,
        external=True,
    ).to_bar_type()
    for s in symbols
]
bars_1_day = catalog.bars(
    bar_types=bar_type_1_day,
    instrument_ids=instrument_ids,
    start=warmup_data_start_time,
    end=data_end_time,
)

bar_types = {
    InstrumentId.from_str(
        NautilusInstrumentId(symbol=s, venue=venue_config.name).to_string()
    ): [
        BarType.from_str(
            NautilusBarType(
                instrument=NautilusInstrumentId(symbol=s, venue=venue_config.name),
                external_bar_size=1,
                external_bar_unit="minute",
                l1_type=l1_type,
                external=True,
            ).to_bar_type()
        ),
        BarType.from_str(
            NautilusBarType(
                instrument=NautilusInstrumentId(symbol=s, venue=venue_config.name),
                external_bar_size=1,
                external_bar_unit="day",
                l1_type=l1_type,
                external=True,
            ).to_bar_type()
        ),
    ]
    for s in symbols
}


instruments = catalog.instruments(instrument_ids=instrument_ids)
for ins in instruments:
    engine.add_instrument(ins)

engine.add_data(bars_1_min)
engine.add_data(bars_1_day)
# actor config
actor_name = "actor_test_backtesting"
actor_config = ConsolidationAndBreakoutIndicatorManageActorConfig(
    name=actor_name,
    warmup_data_start_datetime=warmup_data_start_time,
    data_start_datetime=engine_start_time,
    bar_types=bar_types,
    indicator_meta_set=[intraday_1_min],
    snapshot_time=snapshot_time,
    watchlist_manager="orb_watchlist_manager",
)
actor = ConsolidationAndBreakoutIndicatorManageActor(config=actor_config)

# strategy_config
strategy_name = "strategy_test_backtesting"
strategy_config = ConsolidationAndBreakoutConfig(
    name=strategy_name,
    # portfolio info
    # data
    warmup_data_start_datetime=warmup_data_start_time,
    data_start_datetime=engine_start_time,
    bar_types=bar_types,
    # trading rule
    portfolio_info=portfolio_info,
    fee_model_info=fee_model_info,
    order_rule=order_rule,
    position_rule=position_rule,
    risk_rule=risk_rule,
    session_rule=session_rule,
    trading_rule_manager=trading_rule_manager,
    # candidate
    candidate_manager=candidate_manager,
    # signal
    signal_meta_set=[orb_entry_signal, orb_exit_signal],
    signal_aggregation_method=signal_aggregation_method,
    signal_manager=signal_manager,
    # ranking
    ranking_method=ranking_method,
    # order
    order_validator=order_validator,
    order_composer=order_composer,
    # position evaluator
    position_evaluator=position_evaluator,
)
strategy = ConsolidationAndBreakout(
    config=strategy_config, watchlist_manager_provider=actor
)

engine.add_actor(actor)
engine.add_strategy(strategy)
engine.run()
