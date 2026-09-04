import pandas as pd
from typing import Generic
from abc import ABC, abstractmethod
from collections import defaultdict

from nautilus_trader.model import InstrumentId

from trading_signal.signal import InstrumentSignal, SIGNAL_MANAGER
from trading_signal.ranking import CANDIDATE_RANKING_METHOD, SignalResultFlat


class CandidateManager(ABC, Generic[SIGNAL_MANAGER, CANDIDATE_RANKING_METHOD]):
    def __init__(
        self,
        signal_manager: SIGNAL_MANAGER,
        candidate_ranking_method: CANDIDATE_RANKING_METHOD,
    ):
        self._candidate: set[InstrumentId] = set()
        self._signal_manager: SIGNAL_MANAGER = signal_manager
        self._candidate_ranking_method: CANDIDATE_RANKING_METHOD = (
            candidate_ranking_method
        )
        self._signal_result_flat: pd.DataFrame = pd.DataFrame()
        self._ranking_result: dict = defaultdict()

    @property
    @abstractmethod
    def candidate(self) -> set[InstrumentSignal]: ...

    @property
    @abstractmethod
    def ranking_result(self) -> dict: ...

    @abstractmethod
    def _select_candidate(self, signal_map: dict[InstrumentId, InstrumentSignal]): ...

    @abstractmethod
    def _flating_signals_result(self): ...

    @abstractmethod
    def _ranking_candidate(self): ...


class ORBCandidateManager(CandidateManager):

    @property
    @abstractmethod
    def ranking_result(self) -> dict:
        return self._ranking_result

    @property
    def candidate(self) -> set[InstrumentSignal]:
        self._select_candidate(self._signal_manager.signal_map)
        return self._candidate

    def _select_candidate(self, signal_map: dict[InstrumentId, InstrumentSignal]):
        for iid, iss in signal_map.items():
            if all([s.signal for s in iss.signals]):
                if iid in self._candidate:
                    continue
                elif iid not in self._candidate:
                    self._candidate.add(iid)
            elif not all([s.signal for s in iss.signals]):
                if iid in self._candidate:
                    self._candidate.remove(iid)

    def _flating_signals_result(self):
        records: list = []
        candidate_count = 0

        for can in self._candidate:
            candidate_count += 1
            sigs = self._signal_manager.signal_map[can]
            for s in sigs:
                if not s.is_entry_signal:
                    continue
                for f in s.factors:
                    record = SignalResultFlat(
                        instrument_id=can,
                        signal=s.name,
                        factor=f.name,
                        factor_value=f.value,
                    )
                    records.append(record)

        df = pd.DataFrame([r.model_dump() for r in records])
        self._signal_result_flat = df.copy(deep=True)

    def _ranking_candidate(self):
        if self._signal_result_flat.empty:
            return
        self._ranking_result = self._candidate_ranking_method.rank(
            self._signal_result_flat
        )


CANDIDATE_MANAGER_REGISTRY = {"orb_candidate_manager": ORBCandidateManager}
