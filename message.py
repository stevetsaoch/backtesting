import pandas as pd
from dataclasses import dataclass

from nautilus_trader.model import InstrumentId


@dataclass
class Message:
    pass


@dataclass
class Request(Message):
    pass


@dataclass
class Response(Message):
    pass


@dataclass
class IntradayDataFrameRequest(Request):
    snapshot: bool


@dataclass
class IntradayDataFrameResponse(Response):
    data: pd.DataFrame
    snapshot: bool


@dataclass
class WatchListRequest(Request):
    pass


@dataclass
class WatchListResponse(Response):
    is_ready: bool
    payload: list[InstrumentId]
