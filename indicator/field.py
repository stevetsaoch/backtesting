import datetime
from collections import deque
from abc import ABC, abstractmethod

from nautilus_trader.model import Bar
from nautilus_trader.core.datetime import unix_nanos_to_dt


TYPE_REGISTRY: dict[str, type] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "datetime.date": datetime.date,
    "datetime.time": datetime.time,
}


# fields
class IndicatorField(ABC):
    def __init__(self, bar_spec_requirement: str, bar_buffer_size: int | None):
        self.bar_spec_requirement = bar_spec_requirement
        self.bar_buffer_size = bar_buffer_size

    def update(
        self, bar: Bar
    ) -> float | datetime.time | datetime.date | datetime.datetime: ...

    @property
    def value(
        self,
    ) -> float | datetime.time | datetime.date | datetime.datetime: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def _check_bar_spec(self, bar: Bar) -> bool: ...


class IntradayOpenField(IndicatorField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayHighField(IndicatorField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayLowField(IndicatorField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayHighUpdatedAtField(IndicatorField):
    def __init__(self, intraday_high: IndicatorField, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayLowUpdatedAtField(IndicatorField):
    def __init__(self, intraday_low: IndicatorField, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayTradingValueField(IndicatorField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayAmplitudeField(IndicatorField):
    def __init__(
        self,
        intraday_high: IndicatorField,
        intraday_open: IndicatorField,
        intraday_low: IndicatorField,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
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

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True


class IntradayATRField(IndicatorField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value_default = float("-inf")
        self._value = float("-inf")
        self.bars = deque(maxlen=self.bar_buffer_size)
        self.atr_n = deque(maxlen=self.bar_buffer_size)

    def update(self, bar: Bar) -> float:
        self.bars.append(bar)
        self._atr(bar)
        if len(self.atr_n) < self.bar_buffer_size:
            pass
        elif self._value == self._value_default:
            self._value = sum(self.atr_n) / len(self.atr_n)
        else:
            self._value = sum(self.atr_n) / len(self.atr_n)
        return self._value

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = self._value_default
        self.bars = deque(maxlen=self.bar_buffer_size)
        self.atr_n = deque(maxlen=self.bar_buffer_size)

    def _atr(self, bar: Bar):
        if len(self.bars) < 2:
            return
        tr = max(
            self.bars[-1].high.as_double() - self.bars[-1].low.as_double(),
            abs(self.bars[-1].high.as_double() - self.bars[-2].close.as_double()),
            abs(self.bars[-1].low.as_double() - self.bars[-2].close.as_double()),
        )
        self.atr_n.append(tr)

    def _check_bar_spec(self, bar: Bar) -> bool:
        if (
            f"{bar.bar_type.spec.step}-{bar.bar_type.spec.aggregation}"
            != self.bar_spec_requirement
        ):
            return False
        else:
            return True
