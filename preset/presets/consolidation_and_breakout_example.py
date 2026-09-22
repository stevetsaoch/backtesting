import datetime

from nautilus_trader.model.enums import BarAggregation
from indicator.schemas import IndicatorFieldPresetOutbound, IndicatorMetaPresetOutbound
from trading_signal.schemas import (
    FactorPresetOutbound,
    FactorRankingPresetOutbound,
    SignalMetaPresetOutbound,
)
from candidate.schemas import (
    TieBreakingMethod,
    AggregationMethod,
    FactorRankingPresetOutbound,
    PercentileRankingPresetOutbound,
    ZScoreRankingPresetOutbound,
    RankingPresetOutbound,
)
from trading_rule.schemas import TradingRulePresetOutbound
from schemas import (
    SweepConfig,
    VenuePresetOutbound,
    WarmupDataDatetimeDeltaPresetOutbound,
    CatalogPresetOutbound,
    BarPresetOutbound,
    ManagerPresetOutbound,
    BacktestingPresetOutbound,
)
from config import VENUE_ENV_CONFIG
from preset.schemas import PresetOutbound

indicator_field_presets = [
    IndicatorFieldPresetOutbound(
        name="intraday_high",
        field_name="intraday_high",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        sweep=None,
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_low",
        field_name="intraday_low",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        sweep=None,
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_low_updated_at",
        field_name="intraday_low_updated_at",
        field_type="datetime.time",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        sweep=None,
        depends_on=["intraday_low"],
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_high_updated_at",
        field_name="intraday_high_updated_at",
        field_type="datetime.time",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        sweep=None,
        depends_on=["intraday_high"],
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_open",
        field_name="intraday_open",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        sweep=None,
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_amplitude",
        field_name="intraday_amplitude",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        depends_on=["intraday_high", "intraday_low", "intraday_open"],
        operator="lte",
        threshold=10.0,
        sweep=SweepConfig(field_name="threshold", values=[10.0, 11.0]),
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_trading_value",
        field_name="intraday_trading_value",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        operator="gt",
        threshold=20_000_000,
        sweep=SweepConfig(field_name="threshold", values=[10_000.0, 10_000.0]),
    ),
    IndicatorFieldPresetOutbound(
        name="intraday_atr",
        field_name="intraday_atr",
        field_type="float",
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        operator="gte",
        bar_buffer_size=14,
        threshold=0.001,
        sweep=None,
    ),
]

indicator_meta_presets = [
    IndicatorMetaPresetOutbound(
        name="intraday_short_period",
        indicator_name="intraday_short_period",
        field_configs=[idf.name for idf in indicator_field_presets],
    )
]

trading_signal_factor_presets = [
    FactorPresetOutbound(
        name="clv",
        operator="gt",
        threshold=0.7,
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        ascending=True,
        bar_buffer_size=2,
        ranking_config=FactorRankingPresetOutbound(
            percentile=PercentileRankingPresetOutbound(
                tie_breaking_method=TieBreakingMethod.MINIMUM, ascending=True
            ),
            zscore=ZScoreRankingPresetOutbound(ascending=True),
        ),
        sweep=None,
    ),
    FactorPresetOutbound(
        name="one_hour_no_new_high",
        operator="gt",
        threshold=0.7,
        bar_spec_requirement=f"1-{BarAggregation.MINUTE}",
        ascending=True,
        bar_buffer_size=1,
        ranking_config=FactorRankingPresetOutbound(
            percentile=PercentileRankingPresetOutbound(
                tie_breaking_method=TieBreakingMethod.MINIMUM, ascending=True
            ),
            zscore=ZScoreRankingPresetOutbound(ascending=True),
        ),
        sweep=None,
    ),
]
trading_signal_meta_presets = [
    SignalMetaPresetOutbound(
        name="orb_entry_signal",
        factor_configs=["clv"],
        internal_aggregation_method=AggregationMethod.MINIMUM,
        is_entry_signal=True,
        is_exit_signal=False,
    ),
    SignalMetaPresetOutbound(
        name="orb_exit_signal",
        factor_configs=["one_hour_no_new_high"],
        internal_aggregation_method=AggregationMethod.MINIMUM,
        is_entry_signal=False,
        is_exit_signal=True,
    ),
]

candidate_ranking_preset = RankingPresetOutbound(
    ranking_method="percentile", signal_aggregation_method=AggregationMethod.MINIMUM
)

venue_preset = VenuePresetOutbound(
    name=VENUE_ENV_CONFIG.name,
    oms_type=VENUE_ENV_CONFIG.oms_type,
    account_type=VENUE_ENV_CONFIG.account_type,
    base_currency=VENUE_ENV_CONFIG.base_currency,
    starting_balances=VENUE_ENV_CONFIG.starting_balances,
    prob_fill_on_limit=VENUE_ENV_CONFIG.prob_fill_on_limit,
    prob_slippage=VENUE_ENV_CONFIG.prob_slippage,
    random_seed=VENUE_ENV_CONFIG.random_seed,
    fee_model_path=VENUE_ENV_CONFIG.fee_model_path,
    fee_model_config_path=VENUE_ENV_CONFIG.fee_model_config_path,
    base_latency_nanos=VENUE_ENV_CONFIG.base_latency_nanos,
)

trading_rule_preset = TradingRulePresetOutbound(
    venue=VENUE_ENV_CONFIG.name,
    currency=VENUE_ENV_CONFIG.base_currency,
    balance=str(VENUE_ENV_CONFIG.starting_balances),
    fee_per_share="0.005",
    minimum_fee_per_order="1.0",
    maximum_fee_ratio_per_order="0.01",
    open_position_maximum="2.0",
    trading_bar_type="1-MINUTE-LAST-EXTERNAL",
    stop_price_buffer="0.02",
    order_size_multiplier_ratio="0.5",
    order_size_multiplier_trigger_loss_ratio="0.5",
    tradable_balance_ratio="0.8",
    intraday_risk_ratio="0.02",
    target_profit_minimum="10.0",
    risk_value_ratio_minimum="0.0005",
    cost_ratio_maximum="0.5",
    market_open_at=datetime.time(9, 30, 0),
    market_close_at=datetime.time(16, 0, 0),
    trading_start_at=datetime.time(10, 30, 0),
    forced_close_at=datetime.time(15, 30, 0),
    remaining_trade="2.0",
    sweep=None,
)
catalog_preset = CatalogPresetOutbound(
    data_start_datetime=datetime.datetime(2019, 12, 1, 0, 0, 0),
    data_end_datetime=datetime.datetime(2020, 5, 1, 0, 0, 0),
    warmup_data_delta_preset=WarmupDataDatetimeDeltaPresetOutbound(
        unit="day", value=-5
    ),
    catalog_path="/Volumes/backtesting_main/catalog",
    bar_presets=[
        BarPresetOutbound(
            external_bar_unit="minute",
            external_bar_size=1,
            l1_type="trade",
            external=True,
            is_warmup_data=False,
        ),
        BarPresetOutbound(
            external_bar_unit="day",
            external_bar_size=1,
            l1_type="trade",
            external=True,
            is_warmup_data=True,
        ),
    ],
)
manager_preset = ManagerPresetOutbound(
    trading_rule_manager="orb_trading_rule_manager",
    candidate_manager="orb_candidate_manager",
    order_validator="orb_long_order_validator",
    order_composer="orb_order_composer",
    position_evaluator="orb_position_evaluator",
    watchlist_manager="orb_watchlist_manager",
    signal_manager="orb_signal_manager",
)

backtesting_prest = BacktestingPresetOutbound(snapshot_time=datetime.time(10, 30, 0))

preset = PresetOutbound(
    indicator_field_presets=indicator_field_presets,
    indicator_meta_presets=indicator_meta_presets,
    trading_signal_factor_presets=trading_signal_factor_presets,
    trading_signal_meta_presets=trading_signal_meta_presets,
    candidate_ranking_preset=candidate_ranking_preset,
    venue_preset=venue_preset,
    trading_rule_preset=trading_rule_preset,
    catalog_preset=catalog_preset,
    manager_preset=manager_preset,
    backtesting_preset=backtesting_prest,
)
