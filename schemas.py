import pandas as pd
import datetime
import zoneinfo
from typing import Literal, ClassVar, Any
from pydantic import BaseModel, model_validator, field_validator, ConfigDict
from ib_async import Contract, Stock


class USStockDefault(BaseModel):
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"

    def to_contract(self) -> Stock:
        return Stock(symbol=self.symbol, exchange=self.exchange, currency=self.currency)


class IBHistoricalBarRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract: Contract | Stock | None = None
    endDateTime: datetime.datetime | None = None
    durationStr: str | None = None
    barSizeSetting: str | None = None
    whatToShow: str = "TRADES"
    useRTH: bool = True

    @model_validator(mode="before")
    @classmethod
    def _symbol_to_contract(cls, data):
        s = data.get("symbol")
        e = data.get("exchange")
        c = data.get("currency")

        if data.get("market") == "stock":
            con = Stock(symbol=s, exchange=e, currency=c)
        data["contract"] = con
        return data

    @model_validator(mode="before")
    @classmethod
    def _coerce_timestamp(cls, data):
        tz = data.get("time_zone")
        edt = data.get("endDateTime")

        if isinstance(edt, pd.Timestamp):
            data["endDateTime"] = edt.tz_localize(tz)
        elif isinstance(edt, datetime.datetime):
            data["endDateTime"] = edt.replace(tzinfo=zoneinfo.ZoneInfo(tz))
        return data


class HistoricalBarBase(BaseModel):
    symbol: str
    market: Literal["stock", "crypto"]
    exchange: Literal["SMART"] = "SMART"
    currency: Literal["USD"] = "USD"
    whatToShow: str = "TRADES"
    useRTH: bool = True
    time_zone: str


class HistoricalBarTask(HistoricalBarBase):
    endDateTime: datetime.datetime | None = None
    durationStr: str | None = None
    barSizeSetting: str | None = None
    done: bool = False

    def to_ib_request(self):
        return IBHistoricalBarRequest(**self.model_dump())


class HistoricalBarRequest(HistoricalBarBase):
    end_datetime: datetime.date | datetime.datetime | str
    duration_unit: Literal["second", "day", "week", "month", "year"]
    duration_size: int
    bar_unit: Literal["second", "minute", "hour", "day", "week", "month"]
    bar_size: int
    _valid_bar: ClassVar[dict[str, list[int]]] = {
        "second": [1, 5, 10, 15, 30],
        "minute": [1, 2, 3, 5, 10, 15, 20, 30],
        "hour": [1, 2, 3, 4, 8],
        "day": [1],
        "week": [1],
        "month": [1],
    }
    _valid_duration: ClassVar[dict[str, list[int]]] = {
        "second": [i for i in range(1, 86401)],
        "day": [i for i in range(1, 365)],
        "week": [i for i in range(1, 53)],
        "month": [i for i in range(1, 13)],
        "year": [i for i in range(1, 69)],
    }

    def request_name(self):
        return "|".join(
            [
                str(self.symbol),
                str(self.market),
                str(self.exchange),
                str(self.currency),
                str(self.whatToShow),
                str(self.useRTH),
                str(self.end_datetime),
                str(self.duration_size),
                str(self.duration_unit),
                str(self.bar_size),
                str(self.bar_unit),
            ]
        )

    @model_validator(mode="after")
    @classmethod
    def _init_bar_str(cls, data: Any) -> Any:
        valid_size = cls._valid_bar.get(data.bar_unit, None)
        if valid_size is None:
            raise ValueError("invalid bar size")
        return data

    @model_validator(mode="after")
    @classmethod
    def _init_duration_str(cls, data: Any) -> Any:
        valid_size = cls._valid_duration.get(data.duration_unit, None)
        if valid_size is not None:
            # exception for 1 secs bar request
            if data.bar_size == 1 and data.bar_unit == "secs":
                if data.duration_unit != "second":
                    raise ValueError("invalid duration unit for 1 secs bar")
                elif data.duration_size > 2000:
                    raise ValueError("invalid duration size for 1 secs bar")
        else:
            raise ValueError("valid duration size not found")
        return data

    @model_validator(mode="after")
    @classmethod
    def _init_end_datetime(cls, data: Any) -> Any:
        if isinstance(data.end_datetime, str):
            tmp_datetime = datetime.datetime.strptime(
                data.end_datetime, "%Y-%m-%d %H:%M:%S"
            )
        else:
            tmp_datetime = data.end_datetime

        data.end_datetime = datetime.datetime.combine(
            tmp_datetime, datetime.datetime.min.time()
        )

        return data


class HistoricalBar(BaseModel):
    date: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    average: float
    barCount: int


# config
class PostgresConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str
    database: str
    pool_min: int
    pool_max: int


class ProjectConfig(BaseModel):
    data_dir: str
    task_filetype: str
    data_filetype: str
    cooldown: int
    flag: Literal["paper", "live"]
    proxy: Literal["gateway", "tws"]
    # @model_validator(mode="after")
    # @classmethod
    # def _transform_data_dir(cls, data: Any) -> Any:
    #     p = Path(data.data_base_dir)
    #     data.data_base_dir = p
    #     return data


class IBConnectionInfo(BaseModel):
    host: str
    port: int
    size: int
    timeout: int = 5
    readonly: bool = True


class SymbolInfo(BaseModel):
    ib_us_stock_etf: str
