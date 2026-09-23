import enum
import datetime
import operator
import zoneinfo
import pandas as pd
from dataclasses import dataclass
from ib_async import Contract, Stock
from typing import Literal, ClassVar, Any, Union
from pydantic import BaseModel, ConfigDict, model_validator

from nautilus_trader.model.instruments import Equity, Instrument
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model import Venue, Currency, Money, BarType, Bar
from nautilus_trader.backtest.models import FillModel, LatencyModel, FeeModel
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.model.currencies import USD
from nautilus_trader.config import (
    BacktestDataConfig,
)


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
    exchange: Literal["AMEX", "SMART"] = "SMART"
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
    done: bool = False
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


# condition
class IbkrBar(BaseModel):
    date: datetime.datetime | datetime.date
    open: float
    high: float
    low: float
    close: float
    volume: float
    average: float
    barCount: float


class Field(str, enum.Enum):
    DATE = "date"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


FIELD_TYPES: dict[Field, Any] = {
    Field.DATE: Union[datetime.date | datetime.datetime],
    Field.OPEN: float,
    Field.HIGH: float,
    Field.LOW: float,
    Field.CLOSE: float,
    Field.VOLUME: float,
}


class Operator(str, enum.Enum):
    EQ = "eq"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"
    BETWEEN = "between"
    EQ_BETWEEN = "eq_between"
    GTE_BETWEEN = "gte_between"
    LTE_BETWEEN = "lte_between"

    def to_symbol(self):
        mapping = {
            "eq": "==",
            "gt": ">",
            "lt": "<",
            "gte": ">=",
            "lte": "<=",
        }
        return mapping.get(self.value)

    def to_operator(self):
        mapping = {
            "gt": operator.gt,
            "gte": operator.ge,
            "lt": operator.lt,
            "lte": operator.le,
        }
        return mapping.get(self.value)


# filter
class UniversalStockPoolCondition(BaseModel):
    start_date: datetime.date | datetime.datetime
    end_date: datetime.date | datetime.datetime
    total_amount_average_upper_limit: float
    total_amount_average_lower_limit: float
    total_amount_ratio_threshold: float
    average_upper_limit: float
    average_lower_limit: float
    average_ratio_threshold: float

    def _format_number(self, value: float) -> str:
        abs_value = abs(value)
        sign = "-" if value < 0 else ""

        units = [
            (1_000_000_000_000, "T"),
            (1_000_000_000, "B"),
            (1_000_000, "M"),
            (1_000, "K"),
        ]

        for threshold, suffix in units:
            if abs_value >= threshold:
                formatted = abs_value / threshold
                if formatted == int(formatted):
                    return f"{sign}{int(formatted)}{suffix}"
                return f"{sign}{formatted}{suffix}"

        if abs_value == int(abs_value):
            return f"{sign}{int(abs_value)}"

        return f"{sign}{abs_value}"

    def to_name(self):
        file_name = "|".join(
            [
                str(self.end_date),
                "taal",
                self._format_number(self.total_amount_average_lower_limit),
                "tart",
                str(self.total_amount_ratio_threshold),
                "aul",
                self._format_number(self.average_upper_limit),
                "all",
                self._format_number(self.average_lower_limit),
                "art",
                str(self.average_ratio_threshold),
            ]
        )

        return file_name


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
    mission_filetype: str
    mission_dir: str
    task_filetype: str
    task_dir: str
    data_filetype: str
    index_path: str
    universal_equity_dir: str
    catalog_mission_dir: str
    catalog_mission_filetype: str
    cooldown: int
    flag: Literal["paper", "live"]
    proxy: Literal["gateway", "tws"]


class IBInfo(BaseModel):
    host: str
    port: int
    timeout: int = 120
    readonly: bool = True


class IBConnectionPoolInfo(IBInfo):
    size: int


class IBConnectionInfo(IBInfo):
    client_id: int


class SymbolInfo(BaseModel):
    ib_us_stock_etf_path: str


class NautilusConfig(BaseModel):
    catalog_path: str
    record_path: str


class NautilusEquityTask(BaseModel):
    raw_data_path: str
    catalog_path: str
    symbol: str
    venue: str
    currency: Literal["USD"]
    price_precision: int
    price_increment: float
    lot_size: int
    ts_event: int
    ts_init: int
    done: bool = False

    def to_equity(self) -> Equity:
        e = Equity(
            instrument_id=InstrumentId.from_str(f"{self.symbol}.{self.venue}"),
            raw_symbol=Symbol(f"{self.symbol}"),
            currency=self._str_to_currency(),
            price_precision=self.price_precision,
            price_increment=Price.from_str(str(self.price_increment)),
            lot_size=Quantity.from_int(self.lot_size),
            ts_event=self.ts_event,
            ts_init=self.ts_init,
        )
        return e

    def _str_to_currency(self):
        if self.currency == "USD":
            return USD


class NautilusInstrumentId(BaseModel):
    symbol: str
    venue: str

    def to_string(self):
        return f"{self.symbol}.{self.venue}"


class NautilusBarType(BaseModel):
    instrument: NautilusInstrumentId
    external_bar_unit: Literal["year", "month", "day", "minute"]
    external_bar_size: int
    l1_type: Literal["bid", "ask", "trade"]
    external: bool
    internal_bar_size: int | None = None
    internal_bar_unit: Literal["year", "month", "day", "minute"] | None = None

    def to_bar_type(self):
        symbol = self.instrument.symbol.upper()
        venue = self.instrument.venue.upper()
        if self.l1_type == "trade":
            lt = "LAST"

        if self.external:
            bt = f"{symbol}.{venue}-{str(self.external_bar_size)}-{self.external_bar_unit.upper()}-{lt}-EXTERNAL"
        if not self.external:
            bt = f"{symbol}.{venue}-{str(self.internal_bar_size)}-{self.internal_bar_unit.upper()}-{lt}-INTERNAL@{str(self.external_bar_size)}-{self.external_bar_unit.upper()}-EXTERNAL"

        return bt


class DataConfig(BaseModel):
    instrument: NautilusInstrumentId
    catalog_path: str
    data_cls: str
    bar_types: list[str]
    start_time: str | datetime.datetime
    end_time: str | datetime.datetime

    def to_backtest_data_config(self) -> BacktestDataConfig:

        btdf = BacktestDataConfig(
            catalog_path=self.catalog_path,
            data_cls=Bar if self.data_cls == "bar" else None,
            bar_types=self.bar_types,
            instrument_id=self.instrument.to_string(),
            start_time=self.start_time,
            end_time=self.end_time,
            optimize_file_loading=True,
        )
        return btdf


class VenueEnvConfig(BaseModel):
    name: str
    oms_type: str
    account_type: str
    base_currency: str
    starting_balances: float
    # fill model
    prob_fill_on_limit: float
    prob_slippage: float
    random_seed: int
    # fee model
    fee_model_path: str
    fee_model_config_path: str
    base_latency_nanos: int


class VenuePresetInbound(BaseModel):
    name: str
    oms_type: str
    account_type: str
    base_currency: str
    starting_balances: float
    # fill model
    prob_fill_on_limit: float
    prob_slippage: float
    random_seed: int
    # fee model
    fee_model_path: str
    fee_model_config_path: str
    base_latency_nanos: int


class VenuePresetOutbound(VenuePresetInbound):
    pass


class VenueConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    venue: Venue
    oms_type: OmsType
    account_type: AccountType
    base_currency: Currency
    starting_balances: list[Money]
    fill_model: FillModel
    fee_model: FeeModel
    latency_model: LatencyModel


@dataclass(frozen=True)
class SessionConfig:
    market_open_at: datetime.time
    market_close_at: datetime.time


class ManagerPresetInbound(BaseModel):
    trading_rule_manager: str
    candidate_manager: str
    order_validator: str
    order_composer: str
    position_evaluator: str
    watchlist_manager: str
    signal_manager: str


class ManagerPresetOutbound(ManagerPresetInbound):
    pass


class ManagerConfig(BaseModel):
    trading_rule_manager: str
    candidate_manager: str
    order_validator: str
    order_composer: str
    position_evaluator: str
    watchlist_manager: str
    signal_manager: str


class BarPresetInbound(BaseModel):
    external_bar_unit: Literal["year", "month", "day", "minute"]
    external_bar_size: int
    l1_type: Literal["bid", "ask", "trade"]
    external: bool
    internal_bar_size: int | None = None
    internal_bar_unit: Literal["year", "month", "day", "minute"] | None = None
    is_warmup_data: bool


class BarPresetOutbound(BarPresetInbound):
    pass


class CatalogConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    data_start_datetime: datetime.datetime
    data_end_datetime: datetime.datetime
    warmup_data_start_datetime: datetime.datetime
    catalog: ParquetDataCatalog
    instrument_ids: list[str] | None
    instruments: list[Instrument] | None
    bar_types: dict[InstrumentId, list[BarType]] | None
    bars: list[Bar] | None


class WarmupDataDatetimeDeltaPresetInbound(BaseModel):
    unit: Literal["day", "second", "minute"]
    value: int


class WarmupDataDatetimeDeltaPresetOutbound(BaseModel):
    unit: Literal["day", "second", "minute"]
    value: int


class CatalogPresetInbound(BaseModel):

    data_start_datetime: datetime.datetime
    data_end_datetime: datetime.datetime
    warmup_data_delta_preset: WarmupDataDatetimeDeltaPresetInbound
    catalog_path: str
    bar_presets: list[BarPresetInbound]
    symbols: list[str]


class CatalogPresetOutbound(BaseModel):
    data_start_datetime: datetime.datetime
    data_end_datetime: datetime.datetime
    warmup_data_delta_preset: WarmupDataDatetimeDeltaPresetOutbound
    catalog_path: str
    bar_presets: list[BarPresetOutbound]


class BacktestingPresetInbound(BaseModel):
    snapshot_time: datetime.time | None


class BacktestingPresetOutbound(BaseModel):
    snapshot_time: datetime.time | None


class BacktestingConfig(BaseModel):
    snapshot_time: datetime.time | None


class SweepConfig(BaseModel):
    field_name: str
    values: list[Any]


if __name__ == "__main__":
    pass
