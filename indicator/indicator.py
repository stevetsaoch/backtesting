from abc import abstractmethod
from dataclasses import dataclass
from graphlib import TopologicalSorter, CycleError
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import BarType, Bar
from indicator.field import IndicatorFieldConfig, IndicatorField, FIELD_REGISTRY


@dataclass(frozen=True)
class NativeIndicatorMeta:
    indicator_name: str


@dataclass(frozen=True)
class IndicatorMeta:
    """
    Meta data class share to Actor and Strategy to build and register indicator
    """

    name: str
    indicator_name: str
    field_configs: list[IndicatorFieldConfig]


def build_fields(configs: list[IndicatorFieldConfig]) -> dict[str, IndicatorField]:
    config_by_name = {cfg.name: cfg for cfg in configs}
    graph = {cfg.name: set(cfg.depends_on) for cfg in configs}
    try:
        ts = TopologicalSorter(graph)
        sorted_names = list(ts.static_order())
    except CycleError as e:
        raise ValueError(f"Field depends on other fields: {e}") from e

    fields: dict[str, IndicatorField] = {}
    for name in sorted_names:
        cfg = config_by_name[name]
        cls = FIELD_REGISTRY[cfg.field_name]
        dep_fields = {dep_name: fields[dep_name] for dep_name in cfg.depends_on}
        params = cfg.params if cfg.params else {}
        fields[name] = cls(
            **dep_fields, **params, bar_spec_requirement=cfg.bar_spec_requirement
        )
    return fields


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


INDICATOR_REGISTRY = {
    "intraday_short_period": IntradayShortPeriodIndicator,
}
