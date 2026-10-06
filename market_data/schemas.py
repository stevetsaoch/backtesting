import enum
import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from alpaca.trading.enums import AssetClass, AssetStatus


class MarketSession(str, enum.Enum):
    RTH = "rth"
    PRE = "pre"
    POST = "post"


class AssetFields(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    id: UUID
    symbol: str
    name: str
    exchange: str
    asset_class: AssetClass
    status: AssetStatus
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    edited_at: datetime.datetime | None = None


class IndexFields(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    year: str
    month: str
    symbol: str
    timeframe: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    file_path: str


class AggregatedDataRawMonthlyFields(BaseModel):
    symbol: str
    year: str
    month: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    session: MarketSession
    highest_price: float
    lowest_price: float
    trading_volume: float
    trading_value: float
    avg_trading_value: float
    avg_trading_volume: float
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    edited_at: datetime.datetime | None = None


class AggregatedDataRawDailyFields(BaseModel):
    symbol: str
    year: str
    month: str
    day: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    session: MarketSession
    highest_price: float
    lowest_price: float
    trading_volume: float
    trading_value: float
    avg_trading_value: float
    avg_trading_volume: float
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    edited_at: datetime.datetime | None = None
