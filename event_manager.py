import json
import datetime
import pandas as pd
from enum import Enum
from typing import Any, Literal
from pathlib import Path
from collections import deque, defaultdict

from nautilus_trader.model import InstrumentId, ClientOrderId

from schemas import Event, EventType, EventPayload


class RecordSignalRawDataEvent(Event):
    event_type: Literal[EventType.RECORD_SIGNAL_RAW_DATA] = (
        EventType.RECORD_SIGNAL_RAW_DATA
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, InstrumentId):
        return str(obj)
    if isinstance(obj, ClientOrderId):
        return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class EventManager:
    def __init__(self, root_path: str, backtesting_name: str):
        self._root_path: Path = Path(root_path)
        self._backtesting_name: str = backtesting_name
        self._events: deque = deque()
        self._event_dir: str = "events"
        self._event_path: Path = self._init_path(self._event_dir)
        self._reference_dir: str = "references"
        self._reference_path: Path = self._init_path(self._reference_dir)
        self._signal_raw_data_event: list[Event] = []

    def add(self, event: Event) -> None:
        if event.event_type == EventType.CREATE_SIGNAL_RAW_DATA:
            self._signal_raw_data_event.append(event)
        else:
            self._events.append(event)

    def save_and_reset(self):
        self._save_signal_raw_data()
        self._save()
        self._signal_raw_data_event: list[Event] = []

    def _save(self):
        records: dict[datetime.date, list[dict]] = defaultdict(list)
        for e in self._events:
            if (
                e.payload.reference_file_name is not None
                and e.payload.reference_data is not None
            ):
                file_name = f"{e.created_at.date()}_{e.payload.reference_file_name}"
                self._save_pandas_dataframe_to_parquet(
                    file_name=file_name,
                    data=e.payload.reference_data,
                    is_reference_file=True,
                )
                e.payload.reference_file_name = file_name
                e.payload.reference_data = None

            te = e.model_dump(mode="python")
            te["payload"] = json.dumps(te["payload"], default=_json_default)
            records[e.created_at.date()].append(te)

        for date, rs in records.items():
            file_name = f"{date}"
            df = pd.DataFrame(rs)
            self._save_pandas_dataframe_to_parquet(
                file_name=file_name, data=df, is_reference_file=False
            )

    def _save_pandas_dataframe_to_parquet(
        self, file_name: str, data: pd.DataFrame, is_reference_file: bool
    ) -> None:

        data_sanitized = self._sanitize_dataframe_for_parquet(data)

        path: Path
        if is_reference_file:
            path = self._reference_path / f"{file_name}.parquet"
        else:
            path = self._event_path / f"{file_name}.parquet"

        data_sanitized.to_parquet(
            path,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )

    def _sanitize_dataframe_for_parquet(self, data: pd.DataFrame) -> pd.DataFrame:
        data = data.copy()
        for col in data.columns:
            if data[col].dtype == "object":
                sample = (
                    data[col].dropna().iloc[0] if not data[col].dropna().empty else None
                )
                if isinstance(sample, (InstrumentId)):
                    data[col] = data[col].astype(str)
        return data

    def _init_path(self, dir: str) -> Path:
        path: Path = self._root_path / self._backtesting_name / dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_signal_raw_data(self):
        tmp = defaultdict(list)
        for e in self._signal_raw_data_event:
            tmp[e.created_at.date()].append(e)

        for le in tmp.values():
            created_at = max([e.created_at for e in le])
            data = pd.concat([e.payload.reference_data for e in le], ignore_index=True)
            file_name = f"signal_raw_data"
            event = RecordSignalRawDataEvent(
                created_at=created_at,
                payload=EventPayload(
                    result={},
                    reference_data=data,
                    reference_file_name=file_name,
                ),
            )
            self.add(event)
