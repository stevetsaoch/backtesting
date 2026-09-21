from graphlib import TopologicalSorter, CycleError

from indicator.field import IndicatorField
from indicator.schemas import IndicatorFieldConfig
from indicator.field_registry import FIELD_REGISTRY


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
            **dep_fields,
            **params,
            bar_spec_requirement=cfg.bar_spec_requirement,
            bar_buffer_size=cfg.bar_buffer_size,
        )
    return fields
