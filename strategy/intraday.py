import datetime
from pathlib import Path
from dataclasses import asdict

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import InstrumentId, Bar, BarType
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

from config import NAUTILUS_CONFIG
from mixin import DailyResetMixin
from trading_signal.signal import (
    SignalMeta,
)
from trading_signal.signal_manager import SignalManager, SIGNAL_MANAGER_REGISTRY
from trading_signal.ranking import CandidateRankingMethod, RANKING_METHOD_REGISTRY
from candidate import CANDIDATE_MANAGER_REGISTRY
from order.order_validator import ORDER_VALIDATOR_REGISTRY
from order.order import (
    OrderRole,
    OrderTicketManager,
    OrderState,
    PositionState,
)
from order.order_composer import (
    OrderTicketComposer,
    ORDER_COMPOSER_REGISTRY,
)
from position_evaluator import POSITION_EVALUATOR_REGISTRY
from trading_rule_manager import (
    TRADING_RULE_MANAGER_REGISTRY,
    PortfolioInfoMutable,
    TradingRulesMutable,
    OrderRulesMutable,
    PositionRulesMutable,
    RiskRulesMutable,
    SessionRuleMutable,
    FeeModelInfoMutable,
)
from event_manager import EventManager
from watchlist.interfaces import WatchlistManagerProvider, ORBWatchlistManagerInterface
from schemas import (
    Event,
    AggregationMethod,
    PortfolioInfo,
    FeeModelInfo,
    OrderRules,
    SessionRule,
    PositionRules,
    RiskRules,
)


class ConsolidationAndBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for trading equities which consolidating in the morning and breakout the highest point in the period of consolidation
    """

    name: str
    # data
    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    # signal
    signal_meta_set: list[SignalMeta]
    signal_aggregation_method: AggregationMethod
    signal_manager: str
    # candidate
    candidate_manager: str
    ranking_method: str
    # trading rule
    portfolio_info: PortfolioInfo
    fee_model_info: FeeModelInfo
    order_rule: OrderRules
    position_rule: PositionRules
    risk_rule: RiskRules
    session_rule: SessionRule
    trading_rule_manager: str
    # order
    order_validator: str
    order_composer: str
    # position
    position_evaluator: str


class ConsolidationAndBreakout(Strategy, DailyResetMixin):
    def __init__(
        self,
        config: ConsolidationAndBreakoutConfig,
        watchlist_manager_provider: WatchlistManagerProvider[
            ORBWatchlistManagerInterface
        ],
        event_manager: EventManager,
    ):
        super().__init__(config)
        self._watchlist_manager_provider = watchlist_manager_provider
        # event manager
        self._event_manager = event_manager

        # session
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []

        # trade rule
        self._trading_rule = TradingRulesMutable(
            portfolio_info=PortfolioInfoMutable(**asdict(self.config.portfolio_info)),
            fee_model_info=FeeModelInfoMutable(**asdict(self.config.fee_model_info)),
            order_rule=OrderRulesMutable(**asdict(self.config.order_rule)),
            position_rule=PositionRulesMutable(**asdict(self.config.position_rule)),
            risk_rule=RiskRulesMutable(**asdict(self.config.risk_rule)),
            session_rule=SessionRuleMutable(**asdict(self.config.session_rule)),
        )
        # signal
        self._signal_manager: SignalManager = SIGNAL_MANAGER_REGISTRY[
            self.config.signal_manager
        ](self.config.signal_meta_set)

        # candidate
        self._candidate_ranking_method: (
            CandidateRankingMethod
        ) = RANKING_METHOD_REGISTRY[self.config.ranking_method](
            signal_aggregation_method=self.config.signal_aggregation_method,
            signal_meta_set=self.config.signal_meta_set,
        )

        # event
        self._events: list[Event] = []
        self._event_dir = Path(
            f"{NAUTILUS_CONFIG.record_path}{self.config.name}/events"
        )

    def on_start(self):
        # watchlist
        self._watchlist_manager: ORBWatchlistManagerInterface = (
            self._watchlist_manager_provider.get_watchlist_manager()
        )
        self._watchlist: list[InstrumentId] | None = None
        # candidate
        self._candidate_manager = CANDIDATE_MANAGER_REGISTRY[
            self.config.candidate_manager
        ](
            signal_manager=self._signal_manager,
            candidate_ranking_method=self._candidate_ranking_method,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )
        # order
        self._order_validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
            trading_rule=self._trading_rule,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager(
            event_manager=self._event_manager, clock_provider=self.clock
        )
        self._order_composer: OrderTicketComposer = ORDER_COMPOSER_REGISTRY[
            self.config.order_composer
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
            self.config.position_evaluator
        ](
            trading_rule=self._trading_rule,
            signal_manager=self._signal_manager,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
            event_manager=self._event_manager,
        )

        self._trading_rule_manager = TRADING_RULE_MANAGER_REGISTRY[
            self.config.trading_rule_manager
        ](
            trading_rule=self._trading_rule,
            account_info_provider=self.portfolio.account(
                self._trading_rule.portfolio_info.venue
            ),
        )

        self._init_daily_reset()
        self._register_daily_reset(self._signal_manager.reset)
        self._register_daily_reset(self._candidate_manager.reset)
        self._register_daily_reset(self._order_validator.reset)
        self._register_daily_reset(self._order_composer.reset)
        self._register_daily_reset(self._order_ticket_manager.reset)
        self._register_daily_reset(self._position_evaluator.reset)
        self._register_daily_reset(self._event_manager.save_and_reset)

        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self.config.data_start_datetime.replace(
                hour=23, minute=59, second=59, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._daily_reset,
        )

    def on_bar(self, bar: Bar):
        self._current_session_bars.append(bar)
        current_datetime = self.clock.utc_now()
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
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_submitted(
            event.client_order_id, datetime
        )

    def on_order_accepted(self, event: OrderAccepted) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_accepted(
            event.client_order_id, datetime
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_rejected(
            event.client_order_id, datetime
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_canceled(
            event.client_order_id, datetime
        )

    def on_order_expired(self, event: OrderExpired) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_expired(
            event.client_order_id, datetime
        )

    def on_order_filled(self, event: OrderFilled) -> None:
        datetime = self.clock.utc_now()
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
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_position_opened(
            client_order_id=event.opening_order_id,
            datetime=datetime,
            position_id=event.position_id,
        )

        # register exit signal when order filled
        self._signal_manager.register_exit_signal(
            event.opening_order_id,
            event.instrument_id,
            established_at=self.clock.utc_now(),
        )

    def on_position_closed(self, event: PositionClosed) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_position_closed(
            client_order_id=event.opening_order_id,
            datetime=datetime,
        )
        self._order_ticket_manager.update_position_realized_profit_and_loss(
            event.opening_order_id, event.realized_pnl
        )

    def on_stop(self):
        print(self._order_ticket_manager._books.keys())
        print(len(self._order_ticket_manager._books.keys()))
        pass

    def _post_on_bar(self, event):
        # update
        # update signal
        self._signal_manager.update_signals(self._current_session_bars)

        # update mae and mfe
        self._order_ticket_manager.update_mae_mfe(self._current_session_bars)

        # position managing
        if self._position_evaluator.evaluate_forced_close_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )
            return
        elif self._position_evaluator.evaluate_exit_signal_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )

        # watchlist
        is_watchlist_ready = self._watchlist_manager.is_watchlist_ready
        if not is_watchlist_ready:
            return
        self._signal_manager.register_entry_signal(
            self._watchlist_manager.watchlist,
            established_at=self.clock.utc_now(),
        )
        # select and ranking candidate
        ranked_candidate = self._candidate_manager.rank_candidate()
        if len(ranked_candidate) == 0:
            self._candidate_manager.reset()
            return

        # pre order validation
        self._order_validator.pre_order_validate(ranked_candidate)
        pre_order_validation_result = self._order_validator.pre_order_validation_result
        final_candidates = []
        for iid, r in pre_order_validation_result.items():
            if all(r.values()):
                final_candidates.append(iid)
        if len(final_candidates) == 0:
            self._order_validator.reset()
            return

        # order compose
        self._order_composer.compose(final_candidates)

        # register
        for otg in self._order_composer.order_ticket_groups:
            self._order_ticket_manager.register_ticket(
                client_order_id=otg.parent.order_client_order_id,
                order_ticket=otg.parent,
            )
            self._order_ticket_manager.register_ticket(
                client_order_id=otg.child.order_client_order_id,
                order_ticket=otg.child,
            )

        # post order validation
        for ot in self._order_ticket_manager.get_tickets_with_specific_state(
            order_state=OrderState.CREATED
        ).values():
            if ot.order_role == OrderRole.PARENT:
                self._order_validator.post_order_validate(ot)

        post_order_validation_result = (
            self._order_validator.post_order_validation_result
        )
        for otci, r in post_order_validation_result.items():
            if all(r.values()):
                self._order_ticket_manager.update_on_post_validation_succeed(
                    otci, self.clock.utc_now()
                )
            else:
                self._order_ticket_manager.update_on_post_validation_failed(
                    otci, self.clock.utc_now()
                )

        # submit orders
        for ot in self._order_ticket_manager.get_tickets().values():
            if (
                ot.order_state == OrderState.VALIDATION_SUCCESSED
                and ot.order_role == OrderRole.PARENT
            ):
                self.submit_order(ot.order)

        # reset sessionly
        self._candidate_manager.reset()
        self._order_validator.reset()
        self._order_composer.reset()
        self._position_evaluator.reset()
        self._current_session_bars = []

    def _forced_close(self, event):
        if self._position_evaluator.is_forced_close_triggered:
            # order
            ooots = [
                ot
                for ot in self._order_ticket_manager.get_tickets().values()
                if ot.order_state == OrderState.SUBMITTED
                and ot.position_id is None
                and not ot.is_forced_close_order
            ]
            if len(ooots) > 0:
                for ooot in ooots:
                    self.cancel_all_orders(ooot.instrument_id)
            # position
            ots = []
            for id in self._position_evaluator.client_order_ids:
                ots.append(self._order_ticket_manager.get_ticket(id))
            fots = self._order_composer.compose_forced_close_order_ticket(ots)
            for fot in fots:
                self._order_ticket_manager.register_ticket(
                    client_order_id=fot.order_client_order_id, order_ticket=fot
                )
                self.submit_order(fot.order)
        elif self._position_evaluator.is_exit_signal_triggered:
            # close stop lost order
            # position
            cos = []
            ots = []
            for id in self._position_evaluator.client_order_ids:
                pot = self._order_ticket_manager.get_ticket(id)
                co = self._order_ticket_manager.get_ticket(
                    pot.order_child_order_id
                ).order
                cos.append(co)
                ots.append(pot)

            # cancel original stop loss order
            for co in cos:
                self.cancel_order(co)

            # submit force close order
            fots = self._order_composer.compose_forced_close_order_ticket(ots)
            for fot in fots:
                self._order_ticket_manager.register_ticket(
                    client_order_id=fot.order_client_order_id, order_ticket=fot
                )
                self.submit_order(fot.order)

        self._position_evaluator.reset()

    def _daily_reset(self, event):
        for cb in self._reset_callbacks:
            cb()
        self._trading_rule_manager.update()

        # session
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []
