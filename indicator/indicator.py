from abc import abstractmethod

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import BarType, Bar

from indicator.schemas import IndicatorFieldConfig
from indicator.util import build_fields


class CustomIndicator(Indicator):
    def __init__(
        self,
        bar_types: list[BarType],
        field_configs: list[IndicatorFieldConfig],
    ):
        super().__init__(
            params=[
                "_".join(
                    [str(b) for b in bar_types],
                ),
            ]
        )
        self.fields = build_fields(configs=field_configs)

    @abstractmethod
    def get(self) -> dict: ...


class IntradayShortPeriodIndicator(CustomIndicator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._default_data = {n: f.value for n, f in self.fields.items()}
        self._data = self._default_data

    def handle_bar(self, bar: Bar):
        for field in self.fields.values():
            field.update(bar)
        self._update_data()

    def get(self) -> dict:
        return self._data

    def _update_data(self):
        data = {}
        for n, f in self.fields.items():
            data[n] = f.value
        self._data = {n: f.value for n, f in self.fields.items()}

    def _reset(self):
        for field in self.fields.values():
            field.reset()
        self._data = self._default_data
