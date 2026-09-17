from pydantic import BaseModel
from indicator.schemas import (
    IndicatorFieldPresetInbound,
    IndicatorFieldPresetOutbound,
    IndicatorMetaPresetInbound,
    IndicatorMetaPresetOutbound,
)
from trading_signal.schemas import FactorPresetInbound, FactorPresetOutbound
from trading_signal.schemas import SignalMetaPresetInbound, SignalMetaPresetOutbound
from candidate.schemas import RankingPresetInbound, RankingPresetOutbound
from trading_rule.schemas import TradingRulePresetInbound, TradingRulePresetOutbound
from schemas import (
    ManagerPresetInbound,
    VenuePresetInbound,
    CatalogPresetInbound,
    ManagerPresetOutbound,
    VenuePresetOutbound,
    CatalogPresetOutbound,
    BacktestingPresetOutbound,
    BacktestingPresetInbound,
)


class PresetInbound(BaseModel):
    indicator_field_presets: list[IndicatorFieldPresetInbound]
    indicator_meta_presets: list[IndicatorMetaPresetInbound]
    trading_signal_factor_presets: list[FactorPresetInbound]
    trading_signal_meta_presets: list[SignalMetaPresetInbound]
    candidate_ranking_preset: RankingPresetInbound
    trading_rule_preset: TradingRulePresetInbound
    manager_preset: ManagerPresetInbound
    venue_preset: VenuePresetInbound
    catalog_preset: CatalogPresetInbound
    backtesting_preset: BacktestingPresetInbound


class PresetOutbound(BaseModel):
    indicator_field_presets: list[IndicatorFieldPresetOutbound]
    indicator_meta_presets: list[IndicatorMetaPresetOutbound]
    trading_signal_factor_presets: list[FactorPresetOutbound]
    trading_signal_meta_presets: list[SignalMetaPresetOutbound]
    candidate_ranking_preset: RankingPresetOutbound
    venue_preset: VenuePresetOutbound
    trading_rule_preset: TradingRulePresetOutbound
    catalog_preset: CatalogPresetOutbound
    manager_preset: ManagerPresetOutbound
    backtesting_preset: BacktestingPresetOutbound
