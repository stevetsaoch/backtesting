import enum
import datetime
import zoneinfo
import pandas as pd
from typing import Literal, ClassVar, Any, Union
from pydantic import (
    BaseModel,
    model_validator,
    ConfigDict,
    computed_field,
)
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
class Bar(BaseModel):
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


class Arithmetic(str, enum.Enum):
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"


class AggregatedArithmetic(str, enum.Enum):
    AVG = "avg"
    COUNT = "count"


class CalculatedField(BaseModel):
    fields: list[Field]
    ariths: list[Arithmetic]

    @computed_field
    def field_name(self) -> str:
        result = [
            x
            for pair in zip(
                map(self._field_to_string, self.fields),
                self.ariths,
            )
            for x in pair
        ] + [self._field_to_string(self.fields[-1])]

        return "_".join(result)

    def _field_to_string(self, field: Field):
        return field.value

    def _arithmetic_to_string(self, arith: Arithmetic):
        if arith == Arithmetic.ADD:
            return "+"
        if arith == Arithmetic.SUB:
            return "-"
        if arith == Arithmetic.MUL:
            return "/"
        if arith == Arithmetic.DIV:
            return "*"

    def _format_value(self, v):
        if type(v) in [datetime.date, datetime.datetime]:
            return f"'{v.isoformat()}'"
        return v

    def to_string(self):
        result = [
            x
            for pair in zip(
                map(self._field_to_string, self.fields),
                map(self._arithmetic_to_string, self.ariths),
            )
            for x in pair
        ] + [self._field_to_string(self.fields[-1])]
        sql = " ".join(result) + " " + f"AS {self.field_name}"
        return sql


class CalculatedFieldGroup(BaseModel):
    fields: list[CalculatedField]

    def to_string(self):
        sql = ", ".join([f.to_string() for f in self.fields])
        return sql


class AggregatedField(BaseModel):
    field: Field
    arith: AggregatedArithmetic

    @computed_field
    def field_name(self) -> str:
        if self.arith == AggregatedArithmetic.COUNT:
            return f"{AggregatedPrefix.COUNT.value}{self.field.value}"
        if self.arith == AggregatedArithmetic.AVG:
            return f"{AggregatedPrefix.AVG.value}{self.field.value}"

    def _format_value(self, v):
        if type(v) in [datetime.date, datetime.datetime]:
            return f"'{v.isoformat()}'"
        return v

    def to_string(self):
        if self.arith == AggregatedArithmetic.COUNT:
            return f"COUNT({self.field.value}) as {self.field_name}"
        if self.arith == AggregatedArithmetic.AVG:
            return f"AVG({self.field.value}) as {self.field_name}"


class AggregatedFieldGroup(BaseModel):
    fields: list[AggregatedField]

    def to_string(self):
        sql = ", ".join([f.to_string() for f in self.fields])
        return sql


class Condition(BaseModel):
    field: Field | CalculatedField | AggregatedField
    value: list[float | datetime.date | datetime.datetime]
    operator: Operator

    def _format_value(self, v):
        if type(v) in [datetime.date, datetime.datetime]:
            return f"'{v.isoformat()}'"
        return v

    def to_string(self):
        field_name = ""
        if isinstance(self.field, Field):
            field_name = self.field.value
        elif isinstance(self.field, CalculatedField) or isinstance(
            self.field, AggregatedField
        ):
            field_name = self.field.field_name

        if len(self.value) == 2:
            bv = self._format_value(max(self.value))
            sv = self._format_value(min(self.value))
        else:
            v = self._format_value(self.value[0])

        if self.operator == Operator.BETWEEN:
            return f"({field_name} > {sv} AND {self.field.value} < {bv})"
        if self.operator == Operator.EQ_BETWEEN:
            return f"({field_name} >= {sv} AND {self.field.value} <= {bv})"
        if self.operator == Operator.LTE_BETWEEN:
            return f"({field_name} > {sv} AND {self.field.value} <= {bv})"
        if self.operator == Operator.GTE_BETWEEN:
            return f"({field_name} >= {sv} AND {self.field.value} < {bv})"
        if self.operator == Operator.EQ:
            return f"{field_name} = {v}"
        if self.operator == Operator.GT:
            return f"{field_name} > {v}"
        if self.operator == Operator.GTE:
            return f"{field_name} >= {v}"
        if self.operator == Operator.LT:
            return f"{field_name} < {v}"
        if self.operator == Operator.LTE:
            return f"{field_name} <= {v}"

    @model_validator(mode="before")
    @classmethod
    def _validate_input(cls, data):
        field = data.get("field")
        v = data.get("value")
        if field == Field.DATE:
            for i in v:
                if type(i) not in [datetime.date, datetime.datetime]:
                    raise Exception(
                        "date or datetime object is alllowed when field is date or datetime."
                    )
        else:
            for i in v:
                if type(i) in [datetime.date, datetime.datetime]:
                    raise Exception(
                        "date or datetime object is alllowed when field is date or datetime."
                    )

        if len(v) not in [1, 2]:
            raise Exception("value should be 1 or 2.")
        elif len(v) == 2 and type(v[0]) != type(v[1]):
            raise Exception("value type should be same.")

        operator = data.get("operator")
        if operator in [
            Operator.BETWEEN,
            Operator.EQ_BETWEEN,
            Operator.GTE_BETWEEN,
            Operator.LTE_BETWEEN,
        ]:
            if type(v) != list:
                raise Exception("Value should be a list if operator is between.")

            bv = max(v)
            sv = min(v)

            if bv == sv:
                raise Exception("Value in the list should include two different value.")

        return data


class ConditionGroup(BaseModel):
    logic: list[Literal["AND", "OR"]]
    conditions: list[Union[Condition, "ConditionGroup"]]

    def to_sql(self):
        sql = ""
        cond_n = len(self.conditions)
        log_n = len(self.logic)
        if log_n != cond_n - 1:
            raise Exception("the mount of condition should be one more than logic")

        lc = 0
        for i in range(0, cond_n):
            if i + 1 == cond_n:
                sql = sql + self.conditions[i].to_string()
            else:
                sql = sql + self.conditions[i].to_string() + " " + self.logic[i] + " "
            lc += 1
            if lc > log_n:
                break
        return sql


class AggregatedPrefix(str, enum.Enum):
    # count
    COUNT = "count_"
    # AVG
    AVG = "avg_"


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


if __name__ == "__main__":
    pass
