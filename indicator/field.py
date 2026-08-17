from abc import abstractmethod
import datetime
from typing import Protocol
from dataclasses import dataclass, field

from nautilus_trader.model import Bar
from nautilus_trader.core.datetime import unix_nanos_to_dt

from schemas import Operator


TYPE_REGISTRY: dict[str, type] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "datetime.date": datetime.date,
    "datetime.time": datetime.time,
}


@dataclass(frozen=True)
class IndicatorDataFieldConfig:
    name: str
    field_type: str
    depends_on: tuple[str, ...]
    operator: Operator | None = field(default=None)
    threshold: float | None = field(default=None)


@dataclass(frozen=True)
class IndicatorMeta:
    """
    Meta data class share to Actor and Strategy to build and register indicator
    """

    name: str
    indicator_name: str
    bar_spec_requirements: list[str]
    field_configs: list[IndicatorDataFieldConfig]
    # normally all indicator will be same.....
    snapshot_time: datetime.time | None = field(default=None)


# fields
class FieldUpdate(Protocol):
    def update(
        self, bar: Bar
    ) -> float | datetime.time | datetime.date | datetime.datetime: ...

    @property
    def value(
        self,
    ) -> float | datetime.time | datetime.date | datetime.datetime: ...

    @abstractmethod
    def reset(self) -> None: ...


class IntradayOpenField(FieldUpdate):
    def __init__(self):
        self._value_default = float("-inf")
        self._value = float("-inf")

    def update(self, bar: Bar) -> float:
        if self._value == self._value_default:
            self._value = bar.open.as_double()
        else:
            pass
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayHighField(FieldUpdate):
    def __init__(self):
        self._value_default = float("-inf")
        self._value = float("-inf")

    def update(self, bar: Bar) -> float:
        self._value = max(self._value, bar.high.as_double())
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayLowField(FieldUpdate):
    def __init__(self):
        self._value_default = float("inf")
        self._value = float("inf")

    def update(self, bar: Bar) -> float:
        self._value = min(self._value, bar.low.as_double())
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayHighUpdatedAtField(FieldUpdate):
    def __init__(self, intraday_high: FieldUpdate):
        self._intraday_high = intraday_high
        self._last_value = None
        self._value_default = None
        self._value = None

    def update(self, bar: Bar) -> datetime.time:
        current = self._intraday_high.value
        if current != self._last_value:
            self._value = unix_nanos_to_dt(bar.ts_event).time()
            self._last_value = current
        return self._value

    @property
    def value(self) -> datetime.time:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayLowUpdatedAtField(FieldUpdate):
    def __init__(self, intraday_low: FieldUpdate):
        self._intraday_low = intraday_low
        self._last_value = None
        self._value_default = None
        self._value = None

    def update(self, bar: Bar) -> datetime.time:
        current = self._intraday_low.value
        if current != self._last_value:
            self._value = unix_nanos_to_dt(bar.ts_init).time()
            self._last_value = current
        return self._value

    @property
    def value(self) -> datetime.time:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayTradingValueField(FieldUpdate):
    def __init__(self):
        self._value_default = 0.0
        self._value = 0.0

    def update(self, bar: Bar) -> float:
        price = (
            bar.open.as_double()
            + bar.close.as_double()
            + bar.low.as_double()
            + bar.high.as_double()
        ) / 4
        self._value += price * bar.volume.as_double()
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default


class IntradayAmplitudeField(FieldUpdate):
    def __init__(
        self,
        intraday_high: FieldUpdate,
        intraday_open: FieldUpdate,
        intraday_low: FieldUpdate,
    ):
        self._high = intraday_high
        self._low = intraday_low
        self._open = intraday_open
        self._value_default = float("-inf")
        self._value = float("-inf")

    def update(self, bar: Bar) -> float:
        self._value = (self._high.value - self._low.value) / self._open.value
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default


FIELD_REGISTRY: dict[str, type] = {
    "intraday_open": IntradayOpenField,
    "intraday_high": IntradayHighField,
    "intraday_high_updated_at": IntradayHighUpdatedAtField,
    "intraday_low": IntradayLowField,
    "intraday_low_updated_at": IntradayLowUpdatedAtField,
    "intraday_trading_value": IntradayTradingValueField,
    "intraday_amplitude": IntradayAmplitudeField,
}

if __name__ == "__main__":
    pass
