import datetime
from abc import ABC, abstractmethod
from typing import Generic, Callable

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import InstrumentId, Bar, BarType, ClientOrderId
from nautilus_trader.model.events.position import PositionClosed, PositionOpened
from nautilus_trader.model.events import (
    OrderInitialized,
    OrderSubmitted,
    OrderAccepted,
    OrderRejected,
    OrderCanceled,
    OrderExpired,
    OrderFilled,
)

from watchlist.interfaces import WatchlistManagerProvider, T_WL_CO
from trading_signal.schemas import SignalMeta, AggregationMethod
from trading_signal.manager import SignalManager
from trading_signal.manager_registry import SIGNAL_MANAGER_REGISTRY
from trading_rule.schemas import TradingRule
from trading_rule.registry import TRADING_RULE_MANAGER_REGISTRY
from candidate.ranking import CandidateRankingMethod
from candidate.registry import RANKING_METHOD_REGISTRY, CANDIDATE_MANAGER_REGISTRY
from order.registry import ORDER_VALIDATOR_REGISTRY, ORDER_COMPOSER_REGISTRY
from order.order import OrderTicketManager, OrderTicket
from order.composer import OrderTicketComposer
from position.registry import POSITION_EVALUATOR_REGISTRY
from event.manager import EventManager
from event.schemas import Event


class BaseCustomStrategyConfig(StrategyConfig, frozen=True):
    pass


class BaseCustomStrategy(Strategy, ABC, Generic[T_WL_CO]):
    def __init__(
        self,
        name: str,
        config: BaseCustomStrategyConfig,
        watchlist_manager_provider: WatchlistManagerProvider[T_WL_CO],
        event_manager: EventManager,
        trading_rule: TradingRule,
        # data
        warmup_data_start_datetime: datetime.datetime,
        data_start_datetime: datetime.datetime,
        bar_types: dict[InstrumentId, list[BarType]],
        # signal
        signal_manager_name: str,
        signal_meta_set: list[SignalMeta],
        # candidate
        candidate_manager_name: str,
        ranking_method: str,
        signal_aggregation_method: AggregationMethod,
        # trading rule
        trading_rule_manager_name: str,
        # order
        order_ticket_book: dict[ClientOrderId, OrderTicket],
        order_validator_name: str,
        order_composer_name: str,
        # position
        position_evaluator_name: str,
        # event
    ):
        super().__init__(config)
        self._reset_callbacks: list[Callable[[], None]] = []
        self._name = name
        self._bar_types = bar_types
        self._data_start_datetime = data_start_datetime

        # order
        self._order_ticket_book = order_ticket_book

        # session
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []

        # watchlist
        self._watchlist_manager_provider = watchlist_manager_provider
        # event manager
        self._event_manager = event_manager

        # trading_rule
        self._trading_rule = trading_rule

        # signal
        self._signal_meta_set: list[SignalMeta] = signal_meta_set
        self._signal_manager: SignalManager = SIGNAL_MANAGER_REGISTRY[
            signal_manager_name
        ](signal_meta_set)

        # candidate
        self._candidate_ranking_method: (
            CandidateRankingMethod
        ) = RANKING_METHOD_REGISTRY[ranking_method](
            signal_aggregation_method=signal_aggregation_method,
            signal_meta_set=self._signal_meta_set,
        )

        # manager
        self._candidate_manager_name = candidate_manager_name
        self._trading_rule_manager_name = trading_rule_manager_name
        self._order_validator_name = order_validator_name
        self._order_composer_name = order_composer_name
        self._position_evaluator_name = position_evaluator_name

        # event
        self._events: list[Event] = []

    def on_start(self):
        # watchlist
        self._watchlist_manager: T_WL_CO = (
            self._watchlist_manager_provider.get_watchlist_manager()
        )
        self._watchlist: list[InstrumentId] | None = None

        # candidate
        self._candidate_manager = CANDIDATE_MANAGER_REGISTRY[
            self._candidate_manager_name
        ](
            signal_manager=self._signal_manager,
            candidate_ranking_method=self._candidate_ranking_method,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )

        # order
        self._order_validator = ORDER_VALIDATOR_REGISTRY[self._order_validator_name](
            trading_rule=self._trading_rule,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager(
            event_manager=self._event_manager,
            clock_provider=self.clock,
            order_ticket_book=self._order_ticket_book,
        )
        self._order_composer: OrderTicketComposer = ORDER_COMPOSER_REGISTRY[
            self._order_composer_name
        ](
            trading_rule=self._trading_rule,
            info_provider=self._watchlist_manager,
            clock_provider=self.clock,
            order_factory_method_provider=self.order_factory,
            cache_info_provider=self.cache,
            event_manager=self._event_manager,
        )

        # position
        self._position_evaluator = POSITION_EVALUATOR_REGISTRY[
            self._position_evaluator_name
        ](
            trading_rule=self._trading_rule,
            signal_manager=self._signal_manager,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )

        # trading rule manager
        self._trading_rule_manager = TRADING_RULE_MANAGER_REGISTRY[
            self._trading_rule_manager_name
        ](
            trading_rule=self._trading_rule,
            account_info_provider=self.portfolio.account(
                self._trading_rule.portfolio_info.venue
            ),
        )

        # reset
        self._register_daily_reset(self._signal_manager.reset)
        self._register_daily_reset(self._candidate_manager.reset)
        self._register_daily_reset(self._order_validator.reset)
        self._register_daily_reset(self._order_composer.reset)
        self._register_daily_reset(self._order_ticket_manager.reset)
        self._register_daily_reset(self._position_evaluator.reset)
        self._register_daily_reset(self._event_manager.save_and_reset)

        for bts in self._bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self._data_start_datetime.replace(
                hour=23, minute=59, second=59, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._daily_reset,
        )

    def on_bar(self, bar: Bar):
        self._current_session_bars.append(bar)
        current_datetime = self.clock.utc_now().replace(tzinfo=None)
        if (
            self._current_session_datetime == None
            or self._current_session_datetime < current_datetime
        ):

            self._current_session_datetime = current_datetime
            self.clock.set_time_alert(
                name="post_on_bar",
                alert_time=current_datetime + datetime.timedelta(seconds=2),
                callback=self._post_on_bar,
            )

    def on_order_initialized(self, event: OrderInitialized) -> None:
        pass

    def on_order_submitted(self, event: OrderSubmitted):
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_submitted(
            event.client_order_id, datetime
        )

    def on_order_accepted(self, event: OrderAccepted) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_accepted(
            event.client_order_id, datetime
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_rejected(
            event.client_order_id, datetime
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_canceled(
            event.client_order_id, datetime
        )

    def on_order_expired(self, event: OrderExpired) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_expired(
            event.client_order_id, datetime
        )

    def on_order_filled(self, event: OrderFilled) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_order_filled(
            event.client_order_id, datetime
        )
        self._order_ticket_manager.update_order_filled_price_qty(
            event.client_order_id, event.last_qty, event.last_px
        )
        self._order_ticket_manager.update_cost(event.client_order_id, event.commission)

        # submit child order
        cot = self._order_ticket_manager.get_child_order_ticket(event.client_order_id)
        if cot is not None:
            self.submit_order(cot.order)

    def on_position_opened(self, event: PositionOpened):
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_position_opened(
            client_order_id=event.opening_order_id,
            datetime=datetime,
            position_id=event.position_id,
        )

        # register exit signal when order filled
        self._signal_manager.register_exit_signal(
            event.opening_order_id,
            event.instrument_id,
            established_at=self.clock.utc_now().replace(tzinfo=None),
        )
        self._trading_rule_manager.update_remaining_trade(size=1)

    def on_position_closed(self, event: PositionClosed) -> None:
        datetime = self.clock.utc_now().replace(tzinfo=None)
        self._order_ticket_manager.update_on_position_closed(
            client_order_id=event.opening_order_id,
            datetime=datetime,
        )
        self._order_ticket_manager.update_position_realized_profit_and_loss(
            event.opening_order_id, event.realized_pnl
        )

    def on_stop(self):
        pass

    def _daily_reset(self, event):
        for cb in self._reset_callbacks:
            cb()
        self._trading_rule_manager.update()

        # session
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []

    def _register_daily_reset(self, callback: Callable[[], None]) -> None:
        self._reset_callbacks.append(callback)

    @abstractmethod
    def _post_on_bar(self, event): ...

    @abstractmethod
    def _forced_close(self, event): ...
