from collections import deque
from abc import ABC, abstractmethod

import pandas as pd

from nautilus_trader.model import Bar


class Signal(ABC):
    pass

    @abstractmethod
    def update(self, *args, **kwargs) -> dict: ...

    @property
    @abstractmethod
    def signal(self) -> bool: ...


class ORBEntrySignal(Signal):
    def __init__(
        self, instrument_id: str, reference: pd.DataFrame, depend_on: list[str]
    ):
        self.score = 0.0
        self.stage = 0
        self.bars = deque(maxlen=2)
        self.instrument_id = instrument_id
        self.reference = reference
        self.depend_on = depend_on
        self.depend_on_value = self._create_depend_on_dict()

    def update(self, bar: Bar):
        self.bars.append(bar)
        if len(self.bars) == 2:
            high = self.bars[0].high.as_double()
            low = self.bars[0].low.as_double()
            close = self.bars[0].close.as_double()
            try:
                clv = ((close - low) - (high - close)) / (high - low)
            except:
                clv = 0.0
            self.score = (
                clv
                + (
                    self.bars[1].close.as_double()
                    - self.depend_on_value["intraday_high"]
                )
                / self.bars[1].close.as_double()
            )

            if (
                clv >= 0.7
                and self.bars[1].close.as_double() > self.bars[0].close.as_double()
            ):
                self.stage = 1

            elif self.bars[1].close.as_double() < self.bars[0].close.as_double():
                self.stage = 0

            return {
                "score": {
                    "clv": clv,
                    "bars[1].close - bars[0].close > 0": self.bars[1].close.as_double()
                    - self.bars[0].close.as_double(),
                },
                "score_logic": "bars[0] clv gte 0.7 and bars[1].close > bars[0].close",
            }
        else:
            return {}

    @property
    def signal(self):
        trade: bool = False
        if self.stage == 0:
            pass
        if self.stage == 1:
            trade = True
        return trade

    def _create_depend_on_dict(self):
        dod = {}
        for c in self.depend_on:
            dod[c] = self.reference.loc[
                self.reference["instrument_id"] == self.instrument_id, c
            ].item()

        return dod
