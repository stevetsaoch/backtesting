import os
import duckdb
import datetime
import pandas as pd
from pathlib import Path
from collections import defaultdict
from typing import Literal, Iterator

from mixin.mixin import FileNameMixin
from mission.builder import MissionConfigBuilder
from mission.schemas import MissionInbound, MissionOutbound

from preset.schemas import PresetInbound, PresetOutbound
from indicator.schemas import IndicatorFieldPresetInbound
from indicator.schemas import IndicatorMetaPresetInbound
from trading_signal.schemas import (
    FactorPresetInbound,
    SignalMetaPresetInbound,
)
from candidate.schemas import RankingPresetInbound
from trading_rule.schemas import TradingRulePresetInbound
from schemas import (
    CatalogPresetInbound,
    BarPresetInbound,
    VenuePresetInbound,
    ManagerPresetInbound,
    BacktestingPresetInbound,
    WarmupDataDatetimeDeltaPresetInbound,
)

Window = tuple[datetime.datetime, datetime.datetime]


class MissionManager(FileNameMixin):
    EVENTS_DIR = "events"
    REFERENCES_DIR = "references"
    DEFAULT_SUBDIRS = [EVENTS_DIR, REFERENCES_DIR]

    def __init__(
        self,
        builder: MissionConfigBuilder,
        record_root_dir: Path,
        preset_name: str,
        window_size: int,
        window_unit: Literal["day", "month"],
        is_window_size: int,
        oos_window_size: int,
        cycle: int,
        start_date: datetime.date,
        symbol_file_path: Path,
        symbol_file_name_pattern: str,
    ):
        self._builder = builder
        self._record_root_dir = record_root_dir
        self._preset_name = preset_name
        self._preset_root = self._record_root_dir / self._preset_name
        # outbound
        self._outbound_presets_path = (
            self._record_root_dir / self._preset_name / self.PRESETS_PARQUET
        )
        self._outbound_presets: dict[str, PresetOutbound] = (
            self._read_outbound_presets()
        )
        # inbound
        self._inbound_presets: list[PresetInbound] = []
        self._mission_path_inbound_preset_pair: dict[Path, list[PresetInbound]] = (
            defaultdict()
        )
        # window
        self._start_date = start_date
        self._cycle = cycle
        self._window_size = window_size
        self._window_unit: Literal["day", "month"] = window_unit
        self._is_window_size = is_window_size
        self._oos_window_size = oos_window_size
        # symbol
        self._symbol_file_path = symbol_file_path
        self._symbol_file_name_pattern = symbol_file_name_pattern

    def build_missions(self):
        walk_forward_windows = self._generate_walk_forward_windows(
            window_size=self._window_size,
            window_unit=self._window_unit,
            cycle=self._cycle,
            start_date=self._start_date,
            is_window_size=self._is_window_size,
            oos_window_size=self._oos_window_size,
        )
        mission_index = 1
        missions = []
        oos_missions = []
        for k, v in walk_forward_windows.items():
            for p_index, p in self._outbound_presets.items():
                for cat, pairs in v.items():
                    if cat == "is":
                        for pair in pairs:
                            inp = self._outbound_preset_to_inbound_preset(pair, p)
                            mission = {
                                "name": f"c|{k}|is|prest|{p_index}",
                                "mission": str(mission_index),
                                "cycle": k,
                                "oos": False,
                                "preset_index": p_index,
                                "data_start_datetime": pair[0],
                                "data_end_datetime": pair[1],
                                "is_finished": False,
                                **inp.model_dump(),
                            }
                            missions.append(mission)
                            mission_index += 1
            for cat, pairs in v.items():
                if cat == "oos":
                    for pair in pairs:
                        oos_mission = {
                            "name": f"c|{k}|oos",
                            "mission": str(mission_index),
                            "cycle": k,
                            "oos": True,
                            "preset_index": None,
                            "data_start_datetime": pair[0],
                            "data_end_datetime": pair[1],
                            "is_finished": False,
                        }
                        oos_missions.append(oos_mission)
                        mission_index += 1

        # save mission
        mission_path = self._preset_root
        mission_path.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(missions + oos_missions).to_parquet(
            path=mission_path / self.MISSIONS_PARQUET,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )
        missions = []
        oos_missions = []

    def _read_outbound_presets(self) -> dict[str, PresetOutbound]:
        data = pd.read_parquet(self._outbound_presets_path)
        presets = {}
        i = 1
        for index, r in data.iterrows():
            presets[str(i)] = PresetOutbound.model_validate(r.to_dict())
            i += 1
        return presets

    def _outbound_preset_to_inbound_preset(
        self, window_pair: Window, preset: PresetOutbound
    ) -> PresetInbound:

        catalog_preset = preset.catalog_preset
        # warmup data delta
        warmup_data_delta_preset = WarmupDataDatetimeDeltaPresetInbound.model_validate(
            catalog_preset.warmup_data_delta_preset.model_dump()
        )

        start = window_pair[0]
        symbols = self._get_symbols(start)
        in_catalog_preset = CatalogPresetInbound(
            warmup_data_delta_preset=warmup_data_delta_preset,
            symbols=symbols,
            catalog_path=catalog_preset.catalog_path,
            bar_presets=[
                BarPresetInbound(**bpo.model_dump())
                for bpo in catalog_preset.bar_presets
            ],
        )

        # inbound presets
        in_indicator_field_presets = [
            IndicatorFieldPresetInbound(**ifpo.model_dump())
            for ifpo in preset.indicator_field_presets
        ]
        in_indicator_meta_presets = [
            IndicatorMetaPresetInbound(**impo.model_dump())
            for impo in preset.indicator_meta_presets
        ]
        in_trading_signal_factor_presets = [
            FactorPresetInbound(**sfpo.model_dump())
            for sfpo in preset.trading_signal_factor_presets
        ]
        in_trading_signal_meta_presets = [
            SignalMetaPresetInbound(**smpo.model_dump())
            for smpo in preset.trading_signal_meta_presets
        ]
        in_trading_signal_ranking = RankingPresetInbound(
            **preset.candidate_ranking_preset.model_dump()
        )
        in_venue_preset = VenuePresetInbound(**preset.venue_preset.model_dump())
        in_trading_rule_preset = TradingRulePresetInbound(
            **preset.trading_rule_preset.model_dump()
        )
        in_manager_preset = ManagerPresetInbound(**preset.manager_preset.model_dump())
        in_backtesting_preset = BacktestingPresetInbound(
            **preset.backtesting_preset.model_dump()
        )
        inbound_preset = PresetInbound(
            indicator_field_presets=in_indicator_field_presets,
            indicator_meta_presets=in_indicator_meta_presets,
            trading_signal_factor_presets=in_trading_signal_factor_presets,
            trading_signal_meta_presets=in_trading_signal_meta_presets,
            candidate_ranking_preset=in_trading_signal_ranking,
            trading_rule_preset=in_trading_rule_preset,
            manager_preset=in_manager_preset,
            venue_preset=in_venue_preset,
            catalog_preset=in_catalog_preset,
            backtesting_preset=in_backtesting_preset,
        )
        return inbound_preset

    def get_mission_configs(self, mission_file_path: Path) -> Iterator[MissionOutbound]:
        missions = self._read_missions(mission_file_path)
        for index, mission in missions.iterrows():
            mission_inbound = MissionInbound.model_validate(mission.to_dict())
            mission_outbound = self._builder.mission_build(mission_inbound)
            yield mission_outbound

    def get_debug_mission_configs(
        self, mission_file_path: Path, symbol_size: int
    ) -> Iterator[MissionOutbound]:
        missions = self._read_missions(mission_file_path)
        for index, mission in missions.iterrows():
            mission_inbound = MissionInbound.model_validate(mission.to_dict())
            mission_outbound = self._builder.debug_build(
                mission_inbound, symbol_size=symbol_size
            )
            yield mission_outbound

    def update_mission_status(self, mission_file_path: Path, mission: str):
        tmp_file_name = f"tmp.{self.MISSIONS_PARQUET}"
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT * REPLACE (
                    CASE WHEN mission = ? THEN true ELSE is_finished END AS is_finished
                )
                FROM read_parquet('{mission_file_path / self.MISSIONS_PARQUET}')
            ) TO '{mission_file_path/tmp_file_name}' (FORMAT PARQUET);
            """,
            [mission],
        )

        os.replace(
            mission_file_path / tmp_file_name, mission_file_path / self.MISSIONS_PARQUET
        )

    def _read_missions(self, mission_file_path: Path):
        unfinished_missions = pd.read_parquet(
            mission_file_path / self.MISSIONS_PARQUET,
            filters=[("is_finished", "=", False)],
        )
        return unfinished_missions

    def _get_symbols(self, datetime: datetime.datetime):
        r = duckdb.sql(
            """
            SELECT DISTINCT(symbol) FROM read_parquet(?);
            """,
            params=[
                str(
                    self._symbol_file_path
                    / f"{datetime.date().replace(day=1).isoformat()}{self._symbol_file_name_pattern}"
                )
            ],
        ).df()
        symbols = r["symbol"].to_list()
        return symbols

    # walk forward
    def _add_months(self, first_of_month: datetime.date, n: int) -> datetime.date:
        """Return the first day of the month n months after first_of_month."""
        total = first_of_month.year * 12 + (first_of_month.month - 1) + n
        return datetime.date(total // 12, total % 12 + 1, 1)

    def _window_bounds(
        self,
        start_date: datetime.date,
        window_size: int,
        window_unit: Literal["day", "month"],
        index: int,
    ) -> tuple[datetime.date, datetime.date]:
        if window_unit == "day":
            start = start_date + datetime.timedelta(days=index * window_size)
            end = start + datetime.timedelta(days=window_size - 1)
            return start, end

        # month: windows align to calendar months; the first one is clipped at start_date
        month_start = self._add_months(start_date.replace(day=1), index * window_size)
        start = max(month_start, start_date)
        end = self._add_months(month_start, window_size) - datetime.timedelta(days=1)
        return start, end

    def _to_datetime_range(self, start: datetime.date, end: datetime.date) -> Window:
        return datetime.datetime.combine(
            start, datetime.time.min
        ), datetime.datetime.combine(end, datetime.time(23, 59, 59))

    def _generate_walk_forward_windows(
        self,
        window_size: int,
        window_unit: Literal["day", "month"],
        cycle: int,
        start_date: datetime.date,
        is_window_size: int,
        oos_window_size: int,
    ) -> dict[str, dict[str, list[Window]]]:
        if window_unit not in ("day", "month"):
            raise ValueError(
                f"window_unit must be 'day' or 'month', got {window_unit!r}"
            )
        for name, value in (
            ("window_size", window_size),
            ("cycle", cycle),
            ("is_window_size", is_window_size),
            ("oos_window_size", oos_window_size),
        ):
            if value < 1:
                raise ValueError(f"{name} must be >= 1, got {value}")

        def _window(index: int) -> Window:
            return self._to_datetime_range(
                *self._window_bounds(start_date, window_size, window_unit, index)
            )

        result: dict[str, dict[str, list[Window]]] = {}
        for c in range(1, cycle + 1):
            offset = (c - 1) * oos_window_size
            result[str(c)] = {
                "is": [_window(offset + i) for i in range(is_window_size)],
                "oos": [
                    _window(offset + is_window_size + j) for j in range(oos_window_size)
                ],
            }
        return result
