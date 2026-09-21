from pathlib import Path
from preset.repository import PresetRepository
from preset.registry import PresetRegistry
from mission.manager import MissionManager
from mission.builder import MissionBuilder
from runner import BacktestingRunner

preset_registry = PresetRegistry(presets_path=Path("./preset/presets"))
preset_registry.load_all()

file_dir = Path("/Volumes/backtesting_main/record")
preset_repository = PresetRepository(
    root_dir=file_dir, preset_pairs=preset_registry.all()
)
preset_repository.save_presets()

mm = MissionManager(
    builder=MissionBuilder(),
    record_root_dir=file_dir,
    preset_name="consolidation_and_breakout_example",
    mission_period=1,
    mission_period_unit="month",
    iis_period=3,
    os_period=1,
    symbol_file_path=Path("/Volumes/backtesting_main/data/_missions/10_20_1min"),
    symbol_file_name_pattern=" 00:00:00|1|minute|23|day.parquet",
)
mm.build_missions()

runner = BacktestingRunner(
    preset_registry=preset_registry,
    preset_repository=preset_repository,
    mission_manager=mm,
    trader_id="trader-nobody",
    log_level="INFO",
    time_bars_timestamp_on_close=True,
    time_bars_build_with_no_updates=True,
    time_bars_skip_first_non_full_bar=True,
    mission_file_path=Path(
        "/Volumes/backtesting_main/record/consolidation_and_breakout_example/consolidation_and_breakout_example_1/"
    ),
    actor_name="consolidation_and_breakout",
    strategy_name="consolidation_and_breakout",
)

runner.debug_run(symbol_size=4, rounds=1)
