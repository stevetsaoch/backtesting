import json
import datetime
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.events.position import PositionClosed, PositionOpened
from nautilus_trader.model import InstrumentId, Bar, BarType
from nautilus_trader.model.identifiers import Venue
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
from protocols.provider import (
    WatchlistManagerProvider,
)
from indicator.indicator import IndicatorMeta
from trading_signal.signal import (
    SignalMeta,
    SignalManager,
    SIGNAL_MANAGER_REGISTRY,
)
from trading_signal.ranking import CandidateRankingMethod
from candidate import CANDIDATE_MANAGER_REGISTRY

from trading_signal.ranking import RANKING_METHOD_REGISTRY
from order.order_validator import ORDER_VALIDATOR_REGISTRY
from order.order import (
    OrderRole,
    OrderTicketManager,
    OrderState,
    PositionState,
)
from order.order_composer import (
    ORBOrderTicketComposer,
    ORDER_COMPOSER_REGISTRY,
)
from position_manager import POSITION_MANAGER_REGISTRY
from schemas import (
    EventType,
    EventPayloadField,
    Event,
    AggregationMethod,
    OrderRules,
    SessionRule,
    PositionRules,
    RiskRules,
    TradingRulesMutable,
    OrderRulesMutable,
    PositionRulesMutable,
    RiskRulesMutable,
    SessionRuleMutable,
)


class ConsolidationAndBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for trading equities which consolidating in the morning and breakout the highest point in the period of consolidation
    """

    name: str
    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    indicator_meta_set: list[IndicatorMeta]
    bar_types: dict[InstrumentId, list[BarType]]
    # signal
    signal_meta_set: list[SignalMeta]
    signal_aggregation_method: AggregationMethod
    signal_manager: str
    # candidate
    candidate_manager: str
    ranking_method: str
    # trading rule
    order_rule: OrderRules
    position_rule: PositionRules
    risk_rule: RiskRules
    session_rule: SessionRule
    # order
    order_config_factory: str
    order_type: str
    order_validator: str
    order_composer: str
    #
    # position
    position_manager: str
    venue_currency_pair: dict


class ConsolidationAndBreakout(Strategy, DailyResetMixin):
    def __init__(
        self,
        config: ConsolidationAndBreakoutConfig,
        watchlist_manager_provider: WatchlistManagerProvider,
    ):
        super().__init__(config)
        self._watchlist_manager_provider = watchlist_manager_provider
        self._venue = Venue(self.config.venue_currency_pair["venue"])
        # session
        self._current_session_date: datetime.date | None = None
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []
        # trade rule
        self._trading_rule = TradingRulesMutable(
            order_rule=OrderRulesMutable(**asdict(self.config.order_rule)),
            position_rule=PositionRulesMutable(**asdict(self.config.position_rule)),
            risk_rule=RiskRulesMutable(**asdict(self.config.risk_rule)),
            session_rule=SessionRuleMutable(**asdict(self.config.session_rule)),
        )
        # watchlist
        self._watchlist: list[InstrumentId] | None = None
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
        self._candidate_manager = CANDIDATE_MANAGER_REGISTRY[
            self.config.candidate_manager
        ](
            signal_manager=self._signal_manager,
            candidate_ranking_method=self._candidate_ranking_method,
        )

        # event
        self._events: list[Event] = []
        self._event_dir = Path(
            f"{NAUTILUS_CONFIG.record_path}{self.config.name}/events"
        )

    def on_start(self):
        # order
        self._order_validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
            trading_rule=self._trading_rule,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager()
        self._order_composer: ORBOrderTicketComposer = ORDER_COMPOSER_REGISTRY[
            self.config.order_composer
        ](
            trading_rule=self._trading_rule,
            orb_snapshot_intraday_info_provider=self._watchlist_manager_provider.get_watchlist_manager(),
            clock_provider=self.clock,
            order_factory_method_provider=self.order_factory,
            cache_info_provider=self.cache,
        )
        # position
        self._position_manager = POSITION_MANAGER_REGISTRY[
            self.config.position_manager
        ](
            trading_rule=self._trading_rule,
            signal_manager=self._signal_manager,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
        )

        self._init_daily_reset()
        self._register_daily_reset(self._on_daily_reset)
        self._register_daily_reset(self._signal_manager.reset)
        self._register_daily_reset(self._candidate_manager.reset)
        self._register_daily_reset(self._order_validator.reset)
        self._register_daily_reset(self._order_ticket_manager.reset)
        self._register_daily_reset(self._order_composer.reset)
        self._warm_up()

        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self.config.data_start_datetime.replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._check_and_reset,
        )

    def _warm_up(self):
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "signal between aggregation method",
                EventPayloadField.CONDITION: self.config.signal_aggregation_method,
            },
        )
        # make event dir
        self._event_dir.mkdir(parents=True, exist_ok=True)

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
        self._create_and_append_event(
            event_type=EventType.ORDER_SUBMITTED,
            payload={EventPayloadField.INVOLVED: str(event.client_order_id)},
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

        self._create_and_append_event(
            event_type=EventType.ORDER_REJECTED,
            payload={
                EventPayloadField.INVOLVED: str(event.client_order_id),
                EventPayloadField.REASON: event.reason,
            },
        )

    def on_order_canceled(self, event: OrderCanceled) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_canceled(
            event.client_order_id, datetime
        )
        self._create_and_append_event(
            event_type=EventType.ORDER_CANCELED,
            payload={
                EventPayloadField.INVOLVED: str(event.client_order_id),
            },
        )

    def on_order_expired(self, event: OrderExpired) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_expired(
            event.client_order_id, datetime
        )
        self._create_and_append_event(
            event_type=EventType.ORDER_EXPIRED,
            payload={
                EventPayloadField.INVOLVED: str(event.client_order_id),
            },
        )

    def on_order_filled(self, event: OrderFilled) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_on_order_filled(
            event.client_order_id, datetime
        )
        self._order_ticket_manager.update_position_id(
            event.client_order_id, event.position_id
        )
        self._order_ticket_manager.update_order_filled_price_qty(
            event.client_order_id, event.last_qty, event.last_px
        )
        self._order_ticket_manager.update_cost(event.client_order_id, event.commission)
        cot = self._order_ticket_manager.get_child_order_ticket(event.client_order_id)
        if cot is None:
            return
        self.submit_order(cot.order)

        self._create_and_append_event(
            event_type=EventType.ORDER_FILLED,
            payload={
                EventPayloadField.INVOLVED: str(event.client_order_id),
            },
        )

    def on_position_opened(self, event: PositionOpened):
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_position_state(
            event.opening_order_id, PositionState.OPEN
        )
        self._order_ticket_manager.update_position_open_time(
            event.opening_order_id, datetime
        )

    def on_position_closed(self, event: PositionClosed) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_manager.update_position_state(
            event.opening_order_id, PositionState.CLOSED
        )
        self._order_ticket_manager.update_position_close_time(
            event.opening_order_id, datetime
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

        # upate mae and mfe
        for bar in self._current_session_bars:
            # update mfe and mae
            self._order_ticket_manager.upate_mae_mfe(bar)

        # position managing
        if self._position_manager.evaluate_forced_close_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )
            return
        elif self._position_manager.evaluate_exit_signal_triggered():
            self.clock.set_time_alert(
                name="forced_close",
                alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
                callback=self._forced_close,
            )

        # watchlist
        is_watchlist_ready = (
            self._watchlist_manager_provider.get_watchlist_manager().is_watchlist_ready
        )
        if not is_watchlist_ready:
            return
        self._signal_manager.register(
            self._watchlist_manager_provider.get_watchlist_manager().watchlist
        )

        # select and ranking candidate
        ranked_candidate = self._candidate_manager.ranked_candidate
        if len(ranked_candidate) == 0:
            return

        # pre order validation
        self._order_validator.pre_order_validate(ranked_candidate)
        pre_order_validation_result = self._order_validator.pre_order_validation_result
        final_candidates = []
        for iid, r in pre_order_validation_result.items():
            if all(r.values()):
                final_candidates.append(iid)
        if len(final_candidates) == 0:
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
                self._order_ticket_manager.update_on_validation_succeed(
                    otci, self.clock.utc_now()
                )
            else:
                self._order_ticket_manager.update_on_validation_failed(
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
        self._position_manager.reset()
        self._current_session_bars = []

    def _forced_close(self, event):
        if self._position_manager.is_forced_close_triggered:
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
            for id in self._position_manager.client_order_ids:
                ots.append(self._order_ticket_manager.get_ticket(id))
            fots = self._order_composer.compose_forced_close_order_ticket(ots)
            for fot in fots:
                self._order_ticket_manager.register_ticket(
                    client_order_id=fot.order_client_order_id, order_ticket=fot
                )
                self.submit_order(fot.order)
        self._position_manager.reset()

    # event log
    def _create_and_append_event(
        self, event_type: EventType, payload: dict = defaultdict()
    ):
        event = Event(
            event_type=event_type,
            created_at=self.clock.utc_now()
            .replace(tzinfo=None)
            .isoformat(timespec="seconds"),
            payload=payload,
        )

        self._events.append(event)

    def _save_events(self):
        records = []
        for e in self._events:
            te = e.model_dump(mode="python")
            te["payload"] = json.dumps(te["payload"])
            records.append(te)
        df = pd.DataFrame(records)
        date = self.clock.utc_now().date().isoformat()

        df.to_parquet(
            self._event_dir / f"{date}.parquet",
            engine="pyarrow",
            compression="snappy",
            index=False,
        )

    # reset
    def _check_and_reset(self, event) -> bool:
        date = self.clock.utc_now().date()
        if self._current_session_date is None:
            self._current_session_date = date
            return False

        if date != self._current_session_date:
            self._current_session_date = date
            for cb in self._reset_callbacks:
                cb()
            return True
        return False

    def _on_daily_reset(self):
        # save event
        self._save_events()
        # session
        self._current_session_date: datetime.date | None = None
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []
        # signal
        self._signal_manager: SignalManager = SIGNAL_MANAGER_REGISTRY[
            self.config.signal_manager
        ](self.config.signal_meta_set)
        # candidate_manager
        self._candidate_manager = CANDIDATE_MANAGER_REGISTRY[
            self.config.candidate_manager
        ](
            signal_manager=self._signal_manager,
            candidate_ranking_method=self._candidate_ranking_method,
        )
        # order
        self._order_validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
            trading_rule=self._trading_rule,
            cache_info_provider=self.cache,
            clock_provider=self.clock,
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager()
