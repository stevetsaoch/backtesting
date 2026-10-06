from __future__ import annotations
import os
import re
import enum
import time
import threading
import importlib
import types
import datetime
from enum import Enum
from decimal import Decimal
from typing import Any, Union, get_args, get_origin

import pandas as pd
from pydantic import (
    AwareDatetime,
    BaseModel,
    FutureDatetime,
    NaiveDatetime,
    PastDatetime,
)


class PacingController:
    def __init__(self, cooldown: int = 10):
        self._cooldown = cooldown
        self._deadline = 0.0
        self._lock = threading.Lock()

    @property
    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self._deadline - time.monotonic())

    @property
    def ready(self) -> bool:
        return self.remaining == 0

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now >= self._deadline:
                self._deadline = now + self._cooldown
                return True
            return False

    def reset(self):
        with self._lock:
            self._deadline = time.monotonic() + self._cooldown


class RequestIdManager:
    def __init__(self):
        self.request_id = 1
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            request_id = self.request_id
            self.request_id += 1
            return request_id


def find_files(root_dir, pattern):
    regex = re.compile(pattern)
    result = []
    stack = [root_dir]

    while stack:
        current_dir = stack.pop()
        try:
            entries = os.listdir(current_dir)
        except PermissionError:
            continue
        except FileNotFoundError as e:
            continue

        for entry in entries:
            full_path = os.path.join(current_dir, entry)

            if os.path.isdir(full_path):
                stack.append(full_path)
            elif os.path.isfile(full_path):
                if regex.search(entry):
                    result.append(full_path)

    return result


def load_class_from_path(path: str):
    module_path, class_name = path.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def enum_value_factory(items):
    out = {}
    for k, v in items:
        out[k] = v.value if isinstance(v, enum.Enum) else v
    return out


class PydanticModelPandasDataframeTransformer:
    # pydantic's datetime helper types are not datetime subclasses; treat them as datetime
    _DATETIME_ALIASES = (AwareDatetime, NaiveDatetime, PastDatetime, FutureDatetime)

    # Python type -> pandas dtype. Nullable dtypes are used where a column may hold None.
    _DTYPES: dict[type, tuple[str, str]] = {  # (not-null dtype, nullable dtype)
        bool: ("bool", "boolean"),
        int: ("int64", "Int64"),
        float: ("float64", "float64"),
        str: ("str", "str"),
        datetime.datetime: ("datetime64[s]", "datetime64[s]"),
        datetime.date: ("object", "object"),
        Decimal: ("object", "object"),
    }

    def _unwrap_optional(self, tp: Any) -> tuple[Any, bool]:
        if get_origin(tp) in (Union, types.UnionType):
            args = [a for a in get_args(tp) if a is not type(None)]
            if len(args) == 1:
                return args[0], True
        return tp, False

    def _dtype_for(self, tp: Any) -> str:
        base, nullable = self._unwrap_optional(tp)
        if base in self._DATETIME_ALIASES:
            base = datetime.datetime
        if isinstance(base, type) and issubclass(base, Enum):
            base = str if issubclass(base, str) else object
        for py_type, (dtype, null_dtype) in self._DTYPES.items():
            if (
                isinstance(base, type)
                and issubclass(base, py_type)
                and not (py_type is int and base is bool)
            ):
                return null_dtype if nullable else dtype
        return "object"  # unknown / arbitrary types

    def _frame_schema(self, model: type[BaseModel]) -> dict[str, str]:
        """Column -> pandas dtype, in field order, including computed fields."""
        schema = {
            name: self._dtype_for(f.annotation)
            for name, f in model.model_fields.items()
        }
        schema |= {
            name: self._dtype_for(f.return_type)
            for name, f in model.model_computed_fields.items()
        }
        return schema

    def _empty_frame(self, model: type[BaseModel]) -> pd.DataFrame:
        return pd.DataFrame(
            {c: pd.Series(dtype=d) for c, d in self._frame_schema(model).items()}
        )

    def to_frame(self, models: list[Any], model: type[BaseModel]) -> pd.DataFrame:
        """Models -> DataFrame with a fixed schema (works for an empty list too)."""
        schema = self._frame_schema(model)
        if not models:
            return self._empty_frame(model)
        df = pd.DataFrame([m.model_dump() for m in models], columns=list(schema))
        for col, dtype in schema.items():
            if dtype.startswith("datetime64"):
                df[col] = pd.to_datetime(df[col]).dt.as_unit("us")
            elif dtype != "object":
                df[col] = df[col].astype(dtype)
        return df

    def from_frame(self, df: pd.DataFrame, model: type[Any]) -> list[Any]:
        """DataFrame -> models (NaN/NaT -> None)."""
        records = df.astype(object).where(df.notna(), None).to_dict(orient="records")
        return [model.model_validate(r, strict=False) for r in records]
