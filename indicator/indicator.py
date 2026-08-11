import copy
import datetime
from abc import abstractmethod
from graphlib import TopologicalSorter, CycleError
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import BarType, Bar
from nautilus_trader.core.datetime import unix_nanos_to_dt
from indicator.field import IndicatorDataFieldConfig, FieldUpdate, FIELD_REGISTRY


def build_fields(configs: list[IndicatorDataFieldConfig]) -> dict[str, FieldUpdate]:
    config_by_name = {cfg.name: cfg for cfg in configs}
    graph = {cfg.name: set(cfg.depends_on) for cfg in configs}
    try:
        ts = TopologicalSorter(graph)
        sorted_names = list(ts.static_order())
    except CycleError as e:
        raise ValueError(f"Field depends on other fields: {e}") from e

    fields: dict[str, FieldUpdate] = {}
    for name in sorted_names:
        cfg = config_by_name[name]
        cls = FIELD_REGISTRY[cfg.name]
        dep_fields = {dep_name: fields[dep_name] for dep_name in cfg.depends_on}
        fields[name] = cls(**dep_fields)
    return fields


class BaseIndicator(Indicator):
    def __init__(
        self,
        bar_types: list[BarType],
        field_configs: list[IndicatorDataFieldConfig],
        snapshot_time: datetime.time | None = None,
    ):
        super().__init__(
            params=[
                "_".join(
                    [str(b) for b in bar_types],
                ),
                snapshot_time.isoformat() if snapshot_time is not None else None,
            ]
        )
        self.snapshot_time = snapshot_time
        self.fields = build_fields(configs=field_configs)

    @abstractmethod
    def get(self, snapshot: bool) -> dict: ...


class IntradayShortPeriodIndicator(BaseIndicator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_data = {n: f.value for n, f in self.fields.items()}
        self.snapshot_data = self.default_data
        self.latest_data = self.default_data

    def handle_bar(self, bar: Bar):
        for field in self.fields.values():
            field.update(bar)
        self._update_latest_date()
        self._update_snapshot(bar)

    def get(self, snapshot: bool = False) -> dict:
        if snapshot:
            return self.snapshot_data
        else:
            return self.latest_data

    def _update_latest_date(self):
        data = {}
        for n, f in self.fields.items():
            data[n] = f.value
        self.latest_data = {n: f.value for n, f in self.fields.items()}

    def _update_snapshot(self, bar):
        bar_time = unix_nanos_to_dt(bar.ts_event).time()
        if bar_time == self.snapshot_time:
            self.snapshot_data = copy.deepcopy(self.latest_data)

    def _reset(self):
        for field in self.fields.values():
            field.reset()
        self.snapshot_data = self.default_data
        self.latest_data = self.default_data


class IndicatorHub:
    indicators = {
        "intraday_short_period": IntradayShortPeriodIndicator,
    }

    @classmethod
    def get(cls, indicator_name: str):
        return cls.indicators.get(indicator_name, None)
