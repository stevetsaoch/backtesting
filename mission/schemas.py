import math
import datetime
from pydantic import field_validator

from indicator.schemas import (
    IndicatorFieldConfig,
    IndicatorFieldPresetInbound,
    IndicatorMeta,
    IndicatorMetaPresetInbound,
)
from trading_signal.schemas import (
    FactorConfig,
    FactorPresetInbound,
    SignalMeta,
    SignalMetaPresetInbound,
)
from candidate.schemas import RankingPresetInbound, RankingConfig
from trading_rule.schemas import TradingRule, TradingRulePresetInbound
from schemas import (
    ManagerConfig,
    ManagerPresetInbound,
    VenueConfig,
    VenuePresetInbound,
    CatalogConfig,
    CatalogPresetInbound,
    BacktestingConfig,
    BacktestingPresetInbound,
)
from pydantic import BaseModel


class MissionInbound(BaseModel):
    # state
    name: str
    mission: str
    cycle: str
    oos: bool
    preset_index: str
    data_start_datetime: datetime.datetime
    data_end_datetime: datetime.datetime
    is_finished: bool

    # config
    indicator_field_presets: list[IndicatorFieldPresetInbound]
    indicator_meta_presets: list[IndicatorMetaPresetInbound]
    trading_signal_factor_presets: list[FactorPresetInbound]
    trading_signal_meta_presets: list[SignalMetaPresetInbound]
    trading_rule_preset: TradingRulePresetInbound
    candidate_ranking_preset: RankingPresetInbound
    manager_preset: ManagerPresetInbound
    venue_preset: VenuePresetInbound
    catalog_preset: CatalogPresetInbound
    backtesting_preset: BacktestingPresetInbound

    @field_validator("*", mode="before")
    @classmethod
    def nan_to_none(cls, v):
        if isinstance(v, float) and math.isnan(v):
            return None
        return v


class MissionOutbound(BaseModel):
    # state
    name: str
    mission: str
    cycle: str
    oos: bool
    preset_index: str | None
    is_finished: bool

    # config
    indicator_fields: list[IndicatorFieldConfig]
    indicator_metas: list[IndicatorMeta]
    trading_signal_factors: list[FactorConfig]
    trading_signal_metas: list[SignalMeta]
    candidate_ranking_config: RankingConfig
    trading_rule: TradingRule
    managers: ManagerConfig
    venue: VenueConfig
    catalog: CatalogConfig
    backtesting_config: BacktestingConfig
