import pandas as pd
from pydantic import BaseModel
from dataclasses import dataclass


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
