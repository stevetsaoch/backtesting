import enum
from pydantic import BaseModel
from dataclasses import dataclass, asdict

from util import enum_value_factory


# ranking
class TieBreakingMethod(str, enum.Enum):
    MINIMUM = "min"
    MAXIMUM = "max"
    AVERAGE = "average"
    FIRST = "first"
    DENSE = "dense"


class AggregationMethod(str, enum.Enum):
    MINIMUM = "min"
    MAXIMUM = "max"
    AVGERAGE = "average"


@dataclass(frozen=True)
class PercentileRankingConfig:
    tie_breaking_method: TieBreakingMethod
    ascending: bool


@dataclass(frozen=True)
class ZScoreRankingConfig:
    ascending: bool


class PercentileRankingPresetInbound(BaseModel):
    tie_breaking_method: TieBreakingMethod
    ascending: bool


class PercentileRankingPresetOutbound(BaseModel):
    tie_breaking_method: TieBreakingMethod
    ascending: bool


class ZScoreRankingPresetInbound(BaseModel):
    ascending: bool


class ZScoreRankingPresetOutbound(BaseModel):
    ascending: bool


@dataclass(frozen=True)
class FactorRankingConfigs:
    percentile: PercentileRankingConfig
    zscore: ZScoreRankingConfig

    def to_dict(self):
        return asdict(self, dict_factory=enum_value_factory)


class FactorRankingPresetInbound(BaseModel):
    percentile: PercentileRankingPresetInbound
    zscore: ZScoreRankingPresetInbound


class FactorRankingPresetOutbound(BaseModel):
    percentile: PercentileRankingPresetOutbound
    zscore: ZScoreRankingPresetOutbound


@dataclass(frozen=True)
class RankingConfig:
    ranking_method: str
    signal_aggregation_method: AggregationMethod


class RankingPresetInbound(BaseModel):
    ranking_method: str
    signal_aggregation_method: str


class RankingPresetOutbound(BaseModel):
    ranking_method: str
    signal_aggregation_method: str
