import pandas as pd
from abc import abstractmethod
from nautilus_trader.core.data import Data
from nautilus_trader.model import DataType


class PublishableData(Data):
    _registry: list[type["PublishableData"]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        PublishableData._registry.append(cls)

    @property
    @abstractmethod
    def data_type(self) -> DataType: ...

    @classmethod
    @abstractmethod
    def subscription_type(cls) -> DataType: ...


class IntradayDataFrame(PublishableData):
    def __init__(
        self,
        data: pd.DataFrame,
        snapshot: bool,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.data: pd.DataFrame = data
        self.snapshot: bool = snapshot
        self._ts_event = ts_event
        self._ts_init = ts_init

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    @property
    def data_type(self) -> DataType:
        return DataType(
            IntradayDataFrame,
            metadata={"name": "intraday_dataframe", "snapshot": self.snapshot},
        )

    @classmethod
    def subscription_type(cls) -> DataType:
        return DataType(IntradayDataFrame)
