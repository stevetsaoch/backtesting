import pandas as pd
from typing import Generic, Literal
from abc import ABC, abstractmethod

from nautilus_trader.model import InstrumentId

from protocols.provider import ClockProvider
from trading_signal.signal_manager import InstrumentSignal, SIGNAL_MANAGER
from trading_signal.ranking import (
    CANDIDATE_RANKING_METHOD,
    SignalResultFlat,
    RankingMetric,
)
from event_manager import EventManager
from schemas import Event, EventType, EventPayload


class RankCandidateEvent(Event):
    event_type: Literal[EventType.RANK_CANDIDATE] = EventType.RANK_CANDIDATE


class SignalRawDataEvent(Event):
    event_type: Literal[EventType.CREATE_SIGNAL_RAW_DATA] = (
        EventType.CREATE_SIGNAL_RAW_DATA
    )


class CandidateManager(ABC, Generic[SIGNAL_MANAGER, CANDIDATE_RANKING_METHOD]):
    def __init__(
        self,
        signal_manager: SIGNAL_MANAGER,
        candidate_ranking_method: CANDIDATE_RANKING_METHOD,
        event_manager: EventManager,
        clock_provider: ClockProvider,
    ):
        self._signal_manager: SIGNAL_MANAGER = signal_manager
        self._candidate_ranking_method: CANDIDATE_RANKING_METHOD = (
            candidate_ranking_method
        )
        self._candidate: set[InstrumentId] = set()
        self._signal_result_flat: pd.DataFrame = pd.DataFrame()
        self._ranking_result: RankingMetric = RankingMetric()
        self._ranked_candidate: list[InstrumentId] = []
        self._event_manager = event_manager
        self._clock_provider = clock_provider

    @property
    @abstractmethod
    def candidate(self) -> set[InstrumentId]: ...

    @property
    @abstractmethod
    def ranking_result(self) -> RankingMetric: ...

    @abstractmethod
    def rank_candidate(self) -> list[InstrumentId]: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def _select_candidate(
        self, entry_signal_map: dict[InstrumentId, InstrumentSignal]
    ): ...

    @abstractmethod
    def _flating_signals_result(self): ...

    @abstractmethod
    def _ranking_candidate(self): ...


class ORBCandidateManager(CandidateManager):

    @property
    def ranking_result(self) -> RankingMetric:
        return self._ranking_result

    @property
    def candidate(self) -> set[InstrumentId]:
        return self._candidate

    def rank_candidate(self) -> list[InstrumentId]:
        self._select_candidate(self._signal_manager.entry_signal_map)
        self._flating_signals_result()
        self._ranking_candidate()
        self._ranked_candidate = [
            instrument_id for instrument_id in self._ranking_result.final_scores.keys()
        ]
        if len(self._ranked_candidate) > 0:
            event = RankCandidateEvent(
                created_at=self._clock_provider.utc_now().replace(tzinfo=None),
                payload=EventPayload(
                    result=self._ranked_candidate,
                ),
            )
            self._event_manager.add(event)
            # signal raw data event
            self._signal_result_flat["datetime"] = (
                self._clock_provider.utc_now().replace(tzinfo=None)
            )
            event = SignalRawDataEvent(
                created_at=self._clock_provider.utc_now().replace(tzinfo=None),
                payload=EventPayload(
                    result={}, reference_data=self._signal_result_flat
                ),
            )
            self._event_manager.add(event)
        return self._ranked_candidate

    def reset(self):
        self._candidate: set[InstrumentId] = set()
        self._signal_result_flat: pd.DataFrame = pd.DataFrame()
        self._ranking_result: RankingMetric = RankingMetric()
        self._ranked_candidate: list[InstrumentId] = []

    def _select_candidate(self, entry_signal_map: dict[InstrumentId, InstrumentSignal]):
        for iid, iss in entry_signal_map.items():
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
            sigs = self._signal_manager.entry_signal_map[can].signals
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
