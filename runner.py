from pathlib import Path
from typing import Literal

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import (
    BacktestEngineConfig,
    DataEngineConfig,
    LoggingConfig,
)
from nautilus_trader.model import Bar

from watchlist.interfaces import WatchlistManagerProvider
from preset.registry import PresetRegistry
from preset.repository import PresetRepository
from mission.manager import MissionManager
from mission.schemas import MissionOutbound
from actor.base import BaseCustomActor, BaseCustomActorConfig
from actor.registry import ACTOR_REGISTRY, ACTOR_CONFIG_REGISTRY
from strategy.base import BaseCustomStrategy, BaseCustomStrategyConfig
from strategy.registry import STRATEGY_REGISTRY, STRATEGY_CONFIG_REGISTRY
from schemas import VenueConfig
from event.manager import EventManager


class BacktestingRunner:
    def __init__(
        self,
        preset_registry: PresetRegistry,
        preset_repository: PresetRepository,
        mission_manager: MissionManager,
        # engine
        trader_id: str,
        log_level: Literal["INFO", "DEBUG"],
        time_bars_timestamp_on_close: bool,
        time_bars_build_with_no_updates: bool,
        time_bars_skip_first_non_full_bar: bool,
        # mission
        mission_file_path: Path,
        # actor
        actor_name: str,
        # strategy
        strategy_name: str,
    ):
        self._preset_registry = preset_registry
        self._preset_repository = preset_repository
        self._mission_manager = mission_manager

        # engine
        self._trader_id = trader_id
        self._log_level = log_level
        self._time_bars_timestamp_on_close = time_bars_timestamp_on_close
        self._time_bars_build_with_no_updates = time_bars_build_with_no_updates
        self._time_bars_skip_first_non_full_bar = time_bars_skip_first_non_full_bar
        self._engine: BacktestEngine = self._build_engine()
        self._mission_current_config: MissionOutbound | None = None

        # mission
        self._mission_file_path: Path = mission_file_path

        # actor
        self._actor_name = actor_name
        self._actor: BaseCustomActor

        # strategy
        self._strategy_name = strategy_name
        self._strategy: BaseCustomStrategy

    def run(self):
        mission_config = self._mission_manager.build_configs(self._mission_file_path)
        if mission_config is None:
            pass
        else:
            self._mission_current_config = mission_config
            event_manager = EventManager(
                root_path=self._mission_file_path.parent,
                backtesting_name=mission_config.name,
            )
            self._actor = self._init_actor(
                event_manager=event_manager, mission_config=mission_config
            )
            self._strategy = self._init_strategy()
            self._engine.add_actor(self._actor)
            self._engine.add_strategy(self._strategy)
            self._engine.run()

    def _build_engine(self):
        engine = BacktestEngine(
            config=BacktestEngineConfig(
                trader_id=self._trader_id,
                logging=LoggingConfig(log_level=self._log_level),
                data_engine=DataEngineConfig(
                    time_bars_timestamp_on_close=self._time_bars_timestamp_on_close,
                    time_bars_build_with_no_updates=self._time_bars_build_with_no_updates,
                    time_bars_skip_first_non_full_bar=self._time_bars_skip_first_non_full_bar,
                ),
            )
        )
        return engine

    def _add_venue(self, venue_config: VenueConfig):
        self._engine.add_venue(**venue_config.model_dump())

    def _add_instrument(self, instruments: list[str]):
        for ins in instruments:
            self._engine.add_instrument(ins)

    def _add_data(self, bars: list[Bar]):
        self._engine.add_data(bars)

    def _init_actor(
        self, event_manager: EventManager, mission_config: MissionOutbound
    ) -> BaseCustomActor:
        actor_config: BaseCustomActorConfig = ACTOR_CONFIG_REGISTRY[self._actor_name]()
        actor: BaseCustomActor = ACTOR_REGISTRY[self._actor_name](
            config=actor_config,
            event_manager=event_manager,
            warmup_data_start_datetime=mission_config.catalog.warmup_data_start_datetime,
            data_start_datetime=mission_config.catalog.data_start_datetime,
            bar_types=mission_config.catalog.bar_types,
            indicator_meta_set=mission_config.indicator_metas,
            snapshot_time=mission_config.backtesting_config.snapshot_time,
            watchlist_manager_name=mission_config.managers.watchlist_manager,
        )
        return actor

    def _init_strategy(
        self,
        event_manager: EventManager,
        mission_config: MissionOutbound,
        watchlist_manager_provider: WatchlistManagerProvider,
    ) -> BaseCustomStrategy:
        strategy_config: BaseCustomStrategyConfig = STRATEGY_CONFIG_REGISTRY[
            self._strategy_name
        ]()
        strategy: BaseCustomStrategy = STRATEGY_REGISTRY[self._strategy_name](
            name=mission_config.name,
            config=strategy_config,
            watchlist_manager_provider=watchlist_manager_provider,
            event_manager=event_manager,
            trading_rule=mission_config.trading_rule,
            warmup_data_start_datetime=mission_config.catalog.warmup_data_start_datetime,
            data_start_datetime=mission_config.catalog.data_start_datetime,
            bar_types=mission_config.catalog.bar_types,
            signal_manager_name=mission_config.managers.signal_manager,
            signal_meta_set=mission_config.trading_signal_metas,
            candidate_manager_name=mission_config.managers.candidate_manager,
            ranking_method=mission_config.candidate_ranking_config.ranking_method,
            signal_aggregation_method=mission_config.candidate_ranking_config.signal_aggregation_method,
            trading_rule_manager_name=mission_config.managers.trading_rule_manager,
            order_validator_name=mission_config.managers.order_validator,
            order_composer_name=mission_config.managers.order_composer,
            position_evaluator_name=mission_config.managers.position_evaluator,
        )

        return strategy


if __name__ == "__main__":
    from preset.repository import PresetRepository
    from preset.registry import PresetRegistry

    preset_registry = PresetRegistry(presets_dir=Path("./preset/presets"))
    preset_registry.load_all()

    file_dir = Path("/Volumes/backtesting_main/record")
    preset_repository = PresetRepository(
        root_dir=file_dir, preset_pairs=preset_registry.all()
    )
    preset_repository.save_presets()
    #
    from mission.manager import MissionManager
    from mission.builder import MissionBuilder

    mm = MissionManager(
        builder=MissionBuilder(),
        record_root_path=file_dir,
        preset_name="consolidation_and_breakout_v1",
        mission_period=1,
        mission_period_unit="month",
        iis_period=3,
        os_period=1,
        symbol_file_path=Path("/Volumes/backtesting_main/data/_missions/10_20_1min"),
        symbol_file_name_pattern=" 00:00:00|1|minute|23|day.parquet",
    )
    mm.build_missions()
    mm.build_configs(
        mission_file_path=Path(
            "/Volumes/backtesting_main/record/consolidation_and_breakout_v1/consolidation_and_breakout_v1_1/missions.parquet"
        )
    )
