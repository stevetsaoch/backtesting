from dataclasses import dataclass, field
from pydantic import BaseModel
from schemas import Operator, SweepConfig


@dataclass(frozen=True)
class IndicatorFieldConfig:
    name: str
    field_name: str
    field_type: str
    depends_on: tuple[str, ...]
    bar_spec_requirement: str
    params: dict | None = field(default=None)
    operator: Operator | None = field(default=None)
    threshold: float | None = field(default=None)
    bar_buffer_size: int | None = field(default=None)


class IndicatorFieldPresetInbound(BaseModel):
    name: str
    field_name: str
    field_type: str
    threshold: float | None = None
    bar_buffer_size: int | None = None
    bar_spec_requirement: str
    depends_on: list[str] | None = None
    params: dict | None = None
    operator: str | None = None


class IndicatorFieldPresetOutbound(BaseModel):
    name: str
    field_name: str
    field_type: str
    threshold: float | None = None
    bar_buffer_size: int | None = None
    bar_spec_requirement: str
    depends_on: list[str] | None = None
    params: dict | None = None
    operator: str | None = None
    sweep: SweepConfig | None


# indicator
@dataclass(frozen=True)
class IndicatorMeta:
    """
    Meta data class share to Actor and Strategy to build and register indicator
    """

    name: str
    indicator_name: str
    field_configs: list[IndicatorFieldConfig]


class IndicatorMetaPresetInbound(BaseModel):
    name: str
    indicator_name: str
    field_configs: list[str]


class IndicatorMetaPresetOutbound(BaseModel):
    name: str
    indicator_name: str
    field_configs: list[str]
