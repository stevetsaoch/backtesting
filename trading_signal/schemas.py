from pydantic import BaseModel
from dataclasses import dataclass
from candidate.schemas import (
    FactorRankingConfigs,
    AggregationMethod,
    FactorRankingPresetOutbound,
)


from schemas import Operator, SweepConfig


# factor
@dataclass(frozen=True)
class FactorConfig:
    name: str
    operator: Operator
    threshold: float
    bar_spec_requirement: str
    # for ranking,
    ascending: bool
    ranking_config: FactorRankingConfigs
    bar_buffer_size: int


class FactorPresetInbound(BaseModel):
    name: str
    operator: str
    threshold: float
    bar_spec_requirement: str
    # for ranking,
    ascending: bool
    ranking_config: dict
    bar_buffer_size: int


class FactorPresetOutbound(BaseModel):
    name: str
    operator: str
    threshold: float
    bar_spec_requirement: str
    # for ranking,
    ascending: bool
    ranking_config: FactorRankingPresetOutbound
    bar_buffer_size: int
    sweep: SweepConfig | None


# signal
@dataclass(frozen=True)
class SignalMeta:
    name: str
    factor_configs: list[FactorConfig]
    internal_aggregation_method: AggregationMethod
    is_entry_signal: bool
    is_exit_signal: bool


class SignalMetaPresetInbound(BaseModel):
    name: str
    factor_configs: list[str]
    internal_aggregation_method: str
    is_entry_signal: bool
    is_exit_signal: bool


class SignalMetaPresetOutbound(BaseModel):
    name: str
    factor_configs: list[str]
    internal_aggregation_method: str
    is_entry_signal: bool
    is_exit_signal: bool
