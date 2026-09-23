from pathlib import Path
from typing import Literal

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import (
    BacktestEngineConfig,
    DataEngineConfig,
    LoggingConfig,
)
from nautilus_trader.model import Bar, Money, Currency
from nautilus_trader.analysis import create_tearsheet

from trading_rule.schemas import TradingRule
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
    MISSION_REPORT_PATH = "reports"

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
        self._mission_current_config: MissionOutbound | None = None

        # mission
        self._mission_file_path: Path = mission_file_path

        # actor
        self._actor_name = actor_name
        self._actor: BaseCustomActor

        # strategy
        self._strategy_name = strategy_name
        self._strategy: BaseCustomStrategy

        # share by cycle
        self._last_mission_category: Literal["oos", "is"] | None = None
        self._current_cycle: str | None = None
        self._shared_venue: VenueConfig | None = None
        self._shared_trading_rule: TradingRule | None = None

    def cycle_run(self):
        """
        run by cycle, same cycle of iis and os will share trading rule venue
        """
        # event_manager
        # venue
        for mission_config in self._mission_manager.mission_build_configs(
            self._mission_file_path
        ):
            current_mission_category = "is" if mission_config.is_ is not None else "oos"
            if (
                self._current_cycle is None
                or self._current_cycle != mission_config.cycle
            ):
                # change or init cycle
                self._current_cycle = mission_config.cycle
                self._shared_venue = mission_config.venue
                self._shared_trading_rule = mission_config.trading_rule
                self._last_category = current_mission_category
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule
            elif (self._current_cycle == mission_config.cycle) and (
                self._last_mission_category == current_mission_category
            ):
                self._shared_venue.starting_balances = [
                    Money(
                        self._shared_trading_rule.portfolio_info.balance,
                        self._shared_venue.base_currency,
                    )
                ]
                venue = self._shared_venue
                trading_rule = self._shared_trading_rule
            elif (self._current_cycle == mission_config.cycle) and (
                self._last_mission_category != current_mission_category
            ):
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule
                self._last_mission_category = current_mission_category
            else:
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule

            engine = self._build_engine()
            self._mission_current_config = mission_config
            event_manager = EventManager(
                root_path=self._mission_file_path,
                backtesting_name=mission_config.name,
            )
            self._actor = self._init_actor(
                event_manager=event_manager,
                mission_config=mission_config,
            )
            self._strategy = self._init_strategy(
                event_manager=event_manager,
                mission_config=mission_config,
                watchlist_manager_provider=self._actor,
                trading_rule=trading_rule,
            )
            # engine
            self._add_venue(engine=engine, venue_config=venue)
            self._add_instrument(
                engine=engine, instruments=mission_config.catalog.instruments
            )
            self._add_data(engine=engine, bars=mission_config.catalog.bars)
            engine.add_actor(self._actor)
            engine.add_strategy(self._strategy)
            engine.run()
            # update mission status
            self._mission_manager.update_mission_status(
                self._mission_file_path, mission_config.name
            )
            # save report
            self._save_report(
                engine=engine,
                mission_path=self._mission_file_path,
                mission_name=mission_config.name,
            )

    def debug_cycle_run(self, symbol_size: int, rounds: int):
        current_round = 1

        for mission_config in self._mission_manager.debug_build_configs(
            self._mission_file_path, symbol_size=symbol_size
        ):
            current_mission_category = "is" if mission_config.is_ is not None else "oos"

            if (
                self._current_cycle is None
                or self._current_cycle != mission_config.cycle
            ):
                # change or init cycle
                self._current_cycle = mission_config.cycle
                self._shared_venue = mission_config.venue
                self._shared_trading_rule = mission_config.trading_rule
                self._last_mission_category = current_mission_category
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule

            elif (self._current_cycle == mission_config.cycle) and (
                self._last_mission_category == current_mission_category
            ):
                self._shared_venue.starting_balances = [
                    Money(
                        self._shared_trading_rule.portfolio_info.balance,
                        self._shared_venue.base_currency,
                    )
                ]
                venue = self._shared_venue
                trading_rule = self._shared_trading_rule

            elif (self._current_cycle == mission_config.cycle) and (
                self._last_mission_category != current_mission_category
            ):
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule
                self._last_mission_category = current_mission_category

            else:
                venue = mission_config.venue
                trading_rule = mission_config.trading_rule

            engine = self._build_engine()
            self._mission_current_config = mission_config
            event_manager = EventManager(
                root_path=self._mission_file_path,
                backtesting_name=mission_config.name,
            )
            self._actor = self._init_actor(
                event_manager=event_manager, mission_config=mission_config
            )
            self._strategy = self._init_strategy(
                event_manager=event_manager,
                mission_config=mission_config,
                watchlist_manager_provider=self._actor,
                trading_rule=trading_rule,
            )
            # engine
            self._add_venue(engine=engine, venue_config=venue)
            self._add_instrument(
                engine=engine, instruments=mission_config.catalog.instruments
            )
            self._add_data(engine=engine, bars=mission_config.catalog.bars)
            engine.add_actor(self._actor)
            engine.add_strategy(self._strategy)
            engine.run()
            # update mission status
            self._mission_manager.update_mission_status(
                self._mission_file_path, mission_config.name
            )
            # save report
            self._save_report(
                engine=engine,
                mission_path=self._mission_file_path,
                mission_name=mission_config.name,
            )
            current_round += 1
            if current_round > rounds:
                break

    def mission_run(self):
        """
        run by mission

        """
        for mission_config in self._mission_manager.mission_build_configs(
            self._mission_file_path
        ):
            engine = self._build_engine()
            self._mission_current_config = mission_config
            event_manager = EventManager(
                root_path=self._mission_file_path,
                backtesting_name=mission_config.name,
            )
            self._actor = self._init_actor(
                event_manager=event_manager, mission_config=mission_config
            )
            self._strategy = self._init_strategy(
                event_manager=event_manager,
                mission_config=mission_config,
                watchlist_manager_provider=self._actor,
            )
            # engine
            self._add_venue(engine=engine, venue_config=mission_config.venue)
            self._add_instrument(
                engine=engine, instruments=mission_config.catalog.instruments
            )
            self._add_data(engine=engine, bars=mission_config.catalog.bars)
            engine.add_actor(self._actor)
            engine.add_strategy(self._strategy)
            engine.run()
            # update mission status
            self._mission_manager.update_mission_status(
                self._mission_file_path, mission_config.name
            )
            # save report
            self._save_report(
                engine=engine,
                mission_path=self._mission_file_path,
                mission_name=mission_config.name,
            )

    def debug_run(self, symbol_size: int, rounds: int):
        current_round = 1
        for mission_config in self._mission_manager.debug_build_configs(
            self._mission_file_path, symbol_size=symbol_size
        ):
            engine = self._build_engine()
            self._mission_current_config = mission_config
            event_manager = EventManager(
                root_path=self._mission_file_path,
                backtesting_name=mission_config.name,
            )
            self._actor = self._init_actor(
                event_manager=event_manager, mission_config=mission_config
            )
            self._strategy = self._init_strategy(
                event_manager=event_manager,
                mission_config=mission_config,
                watchlist_manager_provider=self._actor,
                trading_rule=mission_config.trading_rule,
            )
            # engine
            self._add_venue(engine=engine, venue_config=mission_config.venue)
            self._add_instrument(
                engine=engine, instruments=mission_config.catalog.instruments
            )
            self._add_data(engine=engine, bars=mission_config.catalog.bars)
            engine.add_actor(self._actor)
            engine.add_strategy(self._strategy)
            engine.run()
            # update mission status
            self._mission_manager.update_mission_status(
                self._mission_file_path, mission_config.name
            )
            # save report
            self._save_report(
                engine=engine,
                mission_path=self._mission_file_path,
                mission_name=mission_config.name,
            )
            current_round += 1
            if current_round > rounds:
                break

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

    def _add_venue(self, engine: BacktestEngine, venue_config: VenueConfig):
        engine.add_venue(**venue_config.model_dump())

    def _add_instrument(self, engine: BacktestEngine, instruments: list[str]):
        for ins in instruments:
            engine.add_instrument(ins)

    def _add_data(self, engine: BacktestEngine, bars: list[Bar]):
        engine.add_data(bars)

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
        trading_rule: TradingRule | None,
    ) -> BaseCustomStrategy:
        strategy_config: BaseCustomStrategyConfig = STRATEGY_CONFIG_REGISTRY[
            self._strategy_name
        ]()
        strategy: BaseCustomStrategy = STRATEGY_REGISTRY[self._strategy_name](
            name=mission_config.name,
            config=strategy_config,
            watchlist_manager_provider=watchlist_manager_provider,
            event_manager=event_manager,
            trading_rule=(
                mission_config.trading_rule if trading_rule == None else trading_rule
            ),
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

    def _save_report(
        self, engine: BacktestEngine, mission_path: Path, mission_name: str
    ):
        report_path = mission_path / self.MISSION_REPORT_PATH / f"{mission_name}.html"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        create_tearsheet(engine=engine, output_path=str(report_path))
