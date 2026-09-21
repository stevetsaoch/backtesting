import os
import duckdb
import calendar
import datetime
import pandas as pd
from typing import Literal
from pathlib import Path
from operator import attrgetter
from collections import defaultdict
from dateutil.relativedelta import relativedelta

from mixin.mixin import FileNameMixin
from mission.builder import MissionBuilder
from mission.schemas import MissionInbound

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


class MissionManager(FileNameMixin):
    EVENTS_DIR = "events"
    REFERENCES_DIR = "references"
    DEFAULT_SUBDIRS = [EVENTS_DIR, REFERENCES_DIR]

    def __init__(
        self,
        builder: MissionBuilder,
        record_root_dir: Path,
        preset_name: str,
        mission_period: int,
        mission_period_unit: Literal["month"],
        iis_period: int,
        os_period: int,
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
        self._outbound_presets: list[PresetOutbound] = self._read_outbound_presets()
        self._mission_path_outbound_preset_pair: dict[Path, PresetOutbound] = (
            defaultdict()
        )
        # inbound
        self._inbound_presets: list[PresetInbound] = []
        self._mission_path_inbound_preset_pair: dict[Path, list[PresetInbound]] = (
            defaultdict()
        )
        # mission
        self._mission_period = mission_period
        self._mission_period_unit = mission_period_unit
        self._iis_period = iis_period
        self._os_period = os_period
        # symbol
        self._symbol_file_path = symbol_file_path
        self._symbol_file_name_pattern = symbol_file_name_pattern

    def build_missions(self):
        self._init_mission_dir()
        self._outbound_presets_to_inbound_presets()
        self._inbound_presets_to_missions()

    def _read_outbound_presets(self) -> list[PresetOutbound]:
        data = pd.read_parquet(self._outbound_presets_path)
        presets = []
        for index, r in data.iterrows():
            presets.append(PresetOutbound.model_validate(r.to_dict()))
        return presets

    def _init_mission_dir(self):
        i = 1
        for preset in self._outbound_presets:
            mission_path = self._preset_root / f"{self._preset_name}_{str(i)}"
            mission_path.mkdir(parents=True, exist_ok=True)
            self._mission_path_outbound_preset_pair[mission_path] = preset
            i += 1

    def _outbound_presets_to_inbound_presets(self):
        for path, preset in self._mission_path_outbound_preset_pair.items():

            catalog_preset = preset.catalog_preset
            month_pairs = self._split_by_month(
                start=catalog_preset.data_start_datetime,
                end=catalog_preset.data_end_datetime,
                months=self._mission_period,
            )
            # warmup data delta
            warmup_data_delta_preset = (
                WarmupDataDatetimeDeltaPresetInbound.model_validate(
                    catalog_preset.warmup_data_delta_preset.model_dump()
                )
            )

            inbound_catalog_presets = []
            for month_pair in month_pairs:
                start = month_pair[0]
                symbols = self._get_symbols(start)
                inbound_catalog_preset = CatalogPresetInbound(
                    data_start_datetime=month_pair[0],
                    data_end_datetime=month_pair[1],
                    warmup_data_delta_preset=warmup_data_delta_preset,
                    symbols=symbols,
                    catalog_path=catalog_preset.catalog_path,
                    bar_presets=[
                        BarPresetInbound(**bpo.model_dump())
                        for bpo in catalog_preset.bar_presets
                    ],
                )
                inbound_catalog_presets.append(inbound_catalog_preset)

            # inbound presets
            inbound_presets: list[PresetInbound] = []
            for in_catalog_preset in inbound_catalog_presets:
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
                in_manager_preset = ManagerPresetInbound(
                    **preset.manager_preset.model_dump()
                )
                in_backtesting_preset = BacktestingPresetInbound(
                    **preset.backtesting_preset.model_dump()
                )
                in_catalog_preset = in_catalog_preset
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
                inbound_presets.append(inbound_preset)
            self._mission_path_inbound_preset_pair[path] = inbound_presets

    def _inbound_presets_to_missions(self):
        session_period = self._iis_period + self._os_period

        for path, inbound_presets in self._mission_path_inbound_preset_pair.items():
            if len(inbound_presets) < session_period:
                raise Exception(
                    f"Mission number {len(inbound_presets)} not enough for one backtesting session. iis {self._iis_period} + os {self._os_period}"
                )
            sorted_inbound_presets = sorted(
                inbound_presets, key=attrgetter("catalog_preset.data_start_datetime")
            )
            #
            i = 1
            iis_count = 1
            os_count = 1
            cycle = 1
            missions = []
            for preset in sorted_inbound_presets:
                if i % session_period != 0:
                    r = {
                        "name": f"cycle|{cycle}|iis|{str(iis_count)}|os|N",
                        "iis": str(iis_count),
                        "os": None,
                        "cycle": str(cycle),
                        "is_finished": False,
                    } | preset.model_dump()
                    iis_count += 1
                else:
                    r = {
                        "name": f"cycle|{cycle}|iis|N|os|{os_count}",
                        "iis": None,
                        "os": str(os_count),
                        "cycle": str(cycle),
                        "is_finished": False,
                    } | preset.model_dump()
                    os_count += 1
                    cycle += 1
                missions.append(r)
                i += 1

            mission_data = pd.DataFrame(missions)
            mission_path = path / self.MISSIONS_PARQUET
            if mission_path.exists():
                pass
            else:
                mission_data.to_parquet(
                    path=path / self.MISSIONS_PARQUET,
                    engine="pyarrow",
                    compression="snappy",
                    index=False,
                )

    def build_configs(self, mission_file_path: Path):
        missions = self._read_missions(mission_file_path)
        for index, mission in missions.iterrows():
            mission_inbound = MissionInbound.model_validate(mission.to_dict())
            mission_outbound = self._builder.build(mission_inbound)
            yield mission_outbound

    def debug_build_configs(self, mission_file_path: Path, symbol_size: int):
        missions = self._read_missions(mission_file_path)
        for index, mission in missions.iterrows():
            mission_inbound = MissionInbound.model_validate(mission.to_dict())
            mission_outbound = self._builder.debug_build(
                mission_inbound, symbol_size=symbol_size
            )
            yield mission_outbound

    def update_mission_status(self, mission_file_path: Path, mission_name: str):
        tmp_file_name = f"tmp.{self.MISSIONS_PARQUET}"
        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT * REPLACE (
                    CASE WHEN name = ? THEN true ELSE is_finished END AS is_finished
                )
                FROM read_parquet('{mission_file_path / self.MISSIONS_PARQUET}')
            ) TO '{mission_file_path/tmp_file_name}' (FORMAT PARQUET);
            """,
            [mission_name],
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
                    / f"{datetime.date().isoformat()}{self._symbol_file_name_pattern}"
                )
            ],
        ).df()
        symbols = r["symbol"].to_list()
        return symbols

    def _split_by_month(
        self, start: datetime.datetime, end: datetime.datetime, months: int = 1
    ) -> list[tuple[datetime.datetime, datetime.datetime]]:
        if start > end:
            raise ValueError(f"start ({start}) must <= end ({end})")
        if months < 1:
            raise ValueError(f"months must >= 1，received {months}")

        chunks: list[tuple[datetime.datetime, datetime.datetime]] = []
        chunk_start = start

        while chunk_start < end:  # ← 改成嚴格小於
            target_month = chunk_start.replace(day=1) + relativedelta(months=months - 1)
            last_day = calendar.monthrange(target_month.year, target_month.month)[1]
            chunk_end_of_month = target_month.replace(
                day=last_day, hour=23, minute=59, second=59, microsecond=0
            )
            chunk_end = min(chunk_end_of_month, end)
            chunks.append((chunk_start, chunk_end))

            next_month = target_month + relativedelta(months=1)
            next_start = next_month.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if chunk_start.tzinfo is not None:
                next_start = next_start.replace(tzinfo=chunk_start.tzinfo)
            chunk_start = next_start

        return chunks
