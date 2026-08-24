import pandas as pd
from abc import ABC, abstractmethod
from pydantic import BaseModel
from schemas import AggregationMethod, CandidateFlat


class RankingMetric(BaseModel):
    ranked: dict | None = None
    signal_scores: dict | None = None
    final_scores: dict | None = None


class CandidateRanking(ABC):
    COL_INSTRUMENT = CandidateFlat.instrument_id
    COL_SIGNAL = CandidateFlat.signal
    COL_FACTOR = CandidateFlat.factor
    COL_FACTOR_VALUE = CandidateFlat.factor_value
    COL_FACTOR_RANKING = "factor_ranking"
    COL_SIGNAL_SCORE = "signal_scores"

    @abstractmethod
    def rank(self) -> RankingMetric: ...

    @abstractmethod
    def _percentile_ranking(self, group: pd.DataFrame) -> pd.Series: ...

    @abstractmethod
    def _signal_internal_aggregation(self, group: pd.DataFrame) -> float: ...

    @abstractmethod
    def _signal_between_aggregation(self, group: pd.DataFrame) -> float: ...


class PercentilRanking(CandidateRanking):
    def __init__(
        self,
        df: pd.DataFrame,
        factor_ranking_dict: dict,
        internal_aggregation_dict: dict,
        between_aggregation_method: AggregationMethod,
    ):
        super().__init__()
        self.df = df.copy(deep=True)
        self.factor_ranking_dict = factor_ranking_dict
        self.internal_aggregation_dict = internal_aggregation_dict
        self.between_aggregation_method = between_aggregation_method
        self.ranking_metric = RankingMetric()

    def rank(self) -> RankingMetric:
        self.df[self.COL_FACTOR_RANKING] = self.df.groupby(
            [self.COL_SIGNAL, self.COL_FACTOR], group_keys=False
        ).apply(self._percentile_ranking)
        self.ranking_metric.ranked = self.df.to_dict()

        signal_scores = (
            self.df.groupby([self.COL_INSTRUMENT, self.COL_SIGNAL], group_keys=False)
            .apply(self._signal_internal_aggregation)
            .reset_index(name=self.COL_SIGNAL_SCORE)
        )
        self.ranking_metric.signal_scores = signal_scores.to_dict()
        final_scores = (
            signal_scores.groupby(self.COL_INSTRUMENT, group_keys=False)
            .apply(self._signal_between_aggregation)
            .sort_values(ascending=False)
        )
        self.ranking_metric.final_scores = final_scores.to_dict()
        return self.ranking_metric

    def _percentile_ranking(self, group: pd.DataFrame) -> pd.Series:
        factor = group.name[1]
        direction = self.factor_ranking_dict[factor]["percentile"]["ascending"]
        method = self.factor_ranking_dict[factor]["percentile"]["tie_breaking_method"]
        return group[self.COL_FACTOR_VALUE].rank(
            pct=True, method=method, ascending=direction
        )

    def _signal_internal_aggregation(self, group: pd.DataFrame) -> float:
        signal_name = group.name[1]
        method = self.internal_aggregation_dict[signal_name]
        if method == AggregationMethod.MINIMUM:
            return group[self.COL_FACTOR_RANKING].min()
        elif method == AggregationMethod.AVGERAGE:
            return group[self.COL_FACTOR_RANKING].mean()
        else:
            raise ValueError(f"unknown aggregation method: {method}")

    def _signal_between_aggregation(self, group: pd.DataFrame) -> float:
        method = self.between_aggregation_method
        if method == AggregationMethod.MINIMUM:
            return group[self.COL_SIGNAL_SCORE].min()
        elif method == AggregationMethod.AVGERAGE:
            return group[self.COL_SIGNAL_SCORE].mean()
        else:
            raise ValueError(f"unknown aggregation method: {method}")
