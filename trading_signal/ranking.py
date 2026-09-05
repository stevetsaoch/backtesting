import enum
import pandas as pd
from typing import TypeVar
from collections import defaultdict
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict

from nautilus_trader.model import InstrumentId

from trading_signal.signal import SignalMeta


# field can use as string to assign to variable
class FieldNameMeta(type(BaseModel)):
    def __getattr__(cls, item: str):
        if item.startswith("__") and item.endswith("__"):
            raise AttributeError(item)

        for klass in cls.__mro__:
            fields = klass.__dict__.get("__pydantic_fields__")
            if fields and item in fields:
                return item

        raise AttributeError(f"{cls.__name__!r} has no attribute {item!r}")


class SignalResultFlat(BaseModel, metaclass=FieldNameMeta):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    instrument_id: InstrumentId
    signal: str
    factor: str
    factor_value: float | int


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
class PercentileRankingMethod:
    tie_breaking_method: TieBreakingMethod
    ascending: bool


@dataclass(frozen=True)
class ZScoreRankingMethodConfig:
    ascending: bool


class RankingMetric(BaseModel):
    ranked: dict = defaultdict()
    signal_scores: dict = defaultdict()
    final_scores: dict = defaultdict()


class CandidateRankingMethod(ABC):
    COL_INSTRUMENT = SignalResultFlat.instrument_id
    COL_SIGNAL = SignalResultFlat.signal
    COL_FACTOR = SignalResultFlat.factor
    COL_FACTOR_VALUE = SignalResultFlat.factor_value
    COL_FACTOR_RANKING = "factor_ranking"
    COL_SIGNAL_SCORE = "signal_scores"
    COL_SCREENING_RESULT = "screening_result"
    COL_INSTRUMENT_ID = "instrument_id"
    COL_RANK_POSTFIX = "_rank"
    COL_RANK_SUM = "rank_sum"

    def __init__(
        self,
        signal_aggregation_method: AggregationMethod,
        signal_meta_set: list[SignalMeta],
    ):
        self._factor_ranking_dict = self._build_factor_ranking_dict(signal_meta_set)
        self._signal_internal_aggregation_dict = (
            self._build_signal_internal_aggregation_dict(signal_meta_set)
        )
        self._signal_aggregation_method = signal_aggregation_method

    @abstractmethod
    def rank(self, df: pd.DataFrame) -> RankingMetric: ...

    @abstractmethod
    def _percentile_ranking(self, group: pd.DataFrame) -> pd.Series: ...

    @abstractmethod
    def _signal_internal_aggregation(self, group: pd.DataFrame) -> float: ...

    @abstractmethod
    def _signal_between_aggregation(self, group: pd.DataFrame) -> float: ...

    @abstractmethod
    def _build_factor_ranking_dict(self, signal_meta_set) -> dict: ...

    @abstractmethod
    def _build_signal_internal_aggregation_dict(self, signal_meta_set) -> dict: ...


CANDIDATE_RANKING_METHOD = TypeVar(
    "CANDIDATE_RANKING_METHOD", bound=CandidateRankingMethod
)


class PercentilRanking(CandidateRankingMethod):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ranking_metric = RankingMetric()

    def rank(self, df: pd.DataFrame) -> RankingMetric:
        df[self.COL_FACTOR_RANKING] = df.groupby(
            [self.COL_SIGNAL, self.COL_FACTOR], group_keys=False
        ).apply(self._percentile_ranking)
        self._ranking_metric.ranked = df.to_dict()

        signal_scores = (
            df.groupby([self.COL_INSTRUMENT, self.COL_SIGNAL], group_keys=False)
            .apply(self._signal_internal_aggregation)
            .reset_index(name=self.COL_SIGNAL_SCORE)
        )
        self._ranking_metric.signal_scores = signal_scores.to_dict()
        final_scores = (
            signal_scores.groupby(self.COL_INSTRUMENT, group_keys=False)
            .apply(self._signal_between_aggregation)
            .sort_values(ascending=False)
        )
        self._ranking_metric.final_scores = final_scores.to_dict()
        return self._ranking_metric

    def _percentile_ranking(self, group: pd.DataFrame) -> pd.Series:
        factor = group.name[1]
        direction = self._factor_ranking_dict[factor]["percentile"]["ascending"]
        method = self._factor_ranking_dict[factor]["percentile"]["tie_breaking_method"]
        return group[self.COL_FACTOR_VALUE].rank(
            pct=True, method=method, ascending=direction
        )

    def _signal_internal_aggregation(self, group: pd.DataFrame) -> float:
        signal_name = group.name[1]
        method = self._signal_internal_aggregation_dict[signal_name]
        if method == AggregationMethod.MINIMUM:
            return group[self.COL_FACTOR_RANKING].min()
        elif method == AggregationMethod.AVGERAGE:
            return group[self.COL_FACTOR_RANKING].mean()
        else:
            raise ValueError(f"unknown aggregation method: {method}")

    def _signal_between_aggregation(self, group: pd.DataFrame) -> float:
        method = self._signal_aggregation_method
        if method == AggregationMethod.MINIMUM:
            return group[self.COL_SIGNAL_SCORE].min()
        elif method == AggregationMethod.AVGERAGE:
            return group[self.COL_SIGNAL_SCORE].mean()
        else:
            raise ValueError(f"unknown aggregation method: {method}")

    def _build_factor_ranking_dict(self, signal_meta_set: list[SignalMeta]) -> dict:
        frd = defaultdict()
        for sm in signal_meta_set:
            for fcfg in sm.factor_configs:
                frd[fcfg.name] = fcfg.ranking_config.to_dict()
        return frd

    def _build_signal_internal_aggregation_dict(
        self, signal_meta_set: list[SignalMeta]
    ) -> dict:
        sd = defaultdict()
        for s in signal_meta_set:
            sd[s.name] = s.internal_aggregation_method
        return sd


RANKING_METHOD_REGISTRY = {
    "percentile": PercentilRanking,
}
