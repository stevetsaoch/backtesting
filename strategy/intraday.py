import json
import datetime
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict
from functools import singledispatchmethod

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.events.position import PositionClosed, PositionOpened
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.orders import Order
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.position import Position
from nautilus_trader.model.enums import OrderType, OrderSide, PositionSide
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.events import (
    OrderInitialized,
    OrderSubmitted,
    OrderAccepted,
    OrderRejected,
    OrderCanceled,
    OrderExpired,
    OrderFilled,
)
from nautilus_trader.model.orders import Order

from config import NAUTILUS_CONFIG
from mixin import DailyResetMixin
from message import WatchListRequest, WatchListResponse
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
    OrderTicket,
    OrderTicketGroup,
    OrderTicketManager,
    OrderState,
    PositionState,
    OrderRole,
    ForcedCloseOrderComposer,
    ORDER_COMPOSER_REGISTRY,
)
from schemas import (
    EventType,
    EventPayloadField,
    Event,
    PreOrderValidationAction,
    PreOrderValidationReason,
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
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
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
    venue_currency_pair: dict
    # msg
    msg_enpoint: str
    msg_outbound_endpoint: str


class ConsolidationAndBreakout(Strategy, DailyResetMixin):
    COL_SCREENING_RESULT = "screening_result"
    COL_INSTRUMENT_ID = "instrument_id"
    COL_RANK_POSTFIX = "_rank"
    COL_RANK_SUM = "rank_sum"

    def __init__(self, config: ConsolidationAndBreakoutConfig):
        super().__init__(config)
        self.instrument_bar_type_map: dict = defaultdict()
        self.venue = Venue(self.config.venue_currency_pair["venue"])
        # session
        self._current_session_date: datetime.date | None = None
        self._current_session_datetime: datetime.datetime | None = None
        self._current_session_bars: list[Bar] = []
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
        # trade
        self._trading_rule = TradingRulesMutable(
            order_rule=OrderRulesMutable(**asdict(self.config.order_rule)),
            position_rule=PositionRulesMutable(**asdict(self.config.position_rule)),
            risk_rule=RiskRulesMutable(**asdict(self.config.risk_rule)),
            session_rule=SessionRuleMutable(**asdict(self.config.session_rule)),
        )
        # order
        self._order_validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
            trading_rule=self._trading_rule, provider=self
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager()
        # event
        self._events: list[Event] = []
        self._event_dir = Path(
            f"{NAUTILUS_CONFIG.record_path}{self.config.name}/events"
        )

    def on_start(self):
        self._init_daily_reset()
        self._register_daily_reset(self._on_daily_reset)
        self._warm_up()
        for iid, bts in self.config.bar_types.items():
            iid_bar_t = {}
            for bt in bts:
                iid_bar_t[f"{bt.spec}"] = bt
                self.subscribe_bars(bt)
            self.instrument_bar_type_map[str(iid)] = iid_bar_t

        # set timer to froce close the position before the time
        self.clock.set_timer(
            name="forced_close_position_and_orders",
            start_time=self.config.data_start_datetime.replace(
                hour=self.config.session_rule.forced_close_at.hour,
                minute=self.config.session_rule.forced_close_at.minute,
                second=self.config.session_rule.forced_close_at.second,
                microsecond=self.config.session_rule.forced_close_at.microsecond,
            ),
            interval=datetime.timedelta(days=1),
            callback=self._forced_close_positions_and_orders,
        )
        # reset
        self.clock.set_timer(
            name="daily_reset",
            start_time=self.config.data_start_datetime.replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            interval=datetime.timedelta(days=1),
            callback=self._check_and_reset,
        )

        # request register
        self.msgbus.register(
            endpoint=self.config.msg_enpoint,
            handler=self._dispatch_msg,
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
        if cot is not None:
            pass

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
        print(self._order_ticket_manager._books)
        pass

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

    def _post_on_bar(self, event):
        self._request_watchlist()
        if self._watchlist is None:
            return
        self._signal_manager.register(self._watchlist)
        self._signal_manager.update_signals(self._current_session_bars)
        # select and ranking candidate
        ranked_candidate = self._candidate_manager.ranked_candidate
        if len(ranked_candidate) == 0:
            return
        # preorder validation
        self._order_validator.pre_order_validate(ranked_candidate)
        validation_result = self._order_validator.result

        for bar in self._current_session_bars:
            # update mfe and mae
            self._order_ticket_manager.upate_mae_mfe(bar)

        self._current_session_bars = []

        self.clock.set_time_alert(
            name="create_and_submit_order",
            alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
            callback=self._create_and_submit_order,
        )

    def _create_and_submit_order(self, event):
        return
        if instrument_id is None:
            return

        order_ticket_group = self._create_order_ticket_groups(instrument_id)
        if order_ticket_group is None:
            return

        order_tickets = self._create_and_register_order_ticket(order_ticket_group)
        for ot in order_tickets:
            if ot.order_role == OrderRole.PARENT:
                self.submit_order(ot.order)

    def _create_order_ticket_groups(self, instrument_id: InstrumentId):
        order_composer = ORDER_COMPOSER_REGISTRY[self.config.order_composer](
            instrument_id=instrument_id, provider=self
        )
        order_composer.compose()
        order_tickets = order_composer.order_ticket_groups
        return order_tickets

    def _create_and_register_order_ticket(
        self, order_ticket_groups: list[OrderTicketGroup]
    ):
        tickets = []
        for otg in order_ticket_groups:
            p_order_ticket = otg.parent
            c_order_ticket = otg.child
            # create child order
            c_order = self._create_order(c_order_ticket)
            c_order_ticket.order_client_order_id = c_order.client_order_id
            c_order_ticket.order = c_order
            # creat parent order
            p_order = self._create_order(p_order_ticket)
            p_order_ticket.order = p_order
            p_order_ticket.order_client_order_id = p_order.client_order_id
            # post order validate
            validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
                trading_rule=self._trading_rule, provider=self
            )
            metric = validator.post_order_validate(p_order_ticket)
            if not all(metric.values()):
                self._create_and_append_event(
                    event_type=EventType.POST_ORDER_VALIDATION,
                    payload={
                        EventPayloadField.ACTION: PreOrderValidationAction.SKIP,
                        EventPayloadField.REASON: PreOrderValidationReason.FAIL,
                        EventPayloadField.METRICS: metric,
                    },
                )
                continue

            tickets.append(p_order_ticket)
            tickets.append(c_order_ticket)

            c_order_ticket.order_parent_order_id = p_order.client_order_id
            c_order_ticket.order_state = OrderState.CREATED
            c_order_ticket.order_created_at = self.clock.utc_now()
            p_order_ticket.order_child_order_id = c_order.client_order_id
            p_order_ticket.order_state = OrderState.CREATED
            p_order_ticket.order_created_at = self.clock.utc_now()
            self._order_ticket_manager.register_ticket(
                client_order_id=p_order.client_order_id, order_ticket=p_order_ticket
            )
            self._order_ticket_manager.register_ticket(
                client_order_id=c_order.client_order_id, order_ticket=c_order_ticket
            )
            self._create_and_append_event(
                event_type=EventType.ORDER_CREATED,
                payload={
                    EventPayloadField.DETAIL: p_order_ticket.model_dump(
                        context={"readable": True}
                    )
                },
            )
            self._create_and_append_event(
                event_type=EventType.ORDER_CREATED,
                payload={
                    EventPayloadField.DETAIL: c_order_ticket.model_dump(
                        context={"readable": True}
                    )
                },
            )

        return tickets

    # order helper method
    def _create_order(self, order_ticket: OrderTicket):
        """
        router method
        """
        if order_ticket.entry_order_type == OrderType.MARKET:
            order = self._create_market_order(order_ticket)
        elif order_ticket.entry_order_type == OrderType.STOP_MARKET:
            order = self._create_stop_market_order(order_ticket)
        elif order_ticket.entry_order_type == OrderType.LIMIT:
            order = self._create_limit_order(order_ticket)
        self._create_and_append_event(
            event_type=EventType.ORDER_TICKET_CREATED,
            payload={
                EventPayloadField.DETAIL: order_ticket.model_dump(
                    context={"readable": True}
                )
            },
        )
        return order

    # orders helper function
    def _create_market_order(self, order_ticket: OrderTicket) -> Order:
        order = self.order_factory.market(
            instrument_id=order_ticket.instrument_id,
            order_side=order_ticket.order_side,
            quantity=order_ticket.quantity,
            time_in_force=order_ticket.time_in_force,
        )
        return order

    def _create_limit_order(self, order_ticket: OrderTicket) -> Order:
        pass

    def _create_stop_limit_order(self, order_ticket: OrderTicket) -> Order:
        pass

    def _create_stop_market_order(self, order_ticket: OrderTicket) -> Order:
        order = self.order_factory.stop_market(
            instrument_id=order_ticket.instrument_id,
            order_side=order_ticket.order_side,
            quantity=order_ticket.quantity,
            trigger_price=order_ticket.trigger_price,
            time_in_force=order_ticket.time_in_force,
            expire_time=order_ticket.expire_time,
            reduce_only=True,
        )
        return order

    # position
    def _closing_position(self):
        # closing position logic
        # close the position that no new high during past five minute
        if len(self.cache.position_open()) == 0:
            return
        for position in self.cache.positions_open():
            instrument_id = position.instrument_id
            # get the current high from subscribed dataframe and
            pass

    def _forced_close_positions_and_orders(self, event):
        tickets = self._order_ticket_manager.get_tickets()
        forced_close_order_tickets = []
        for ot in tickets.values():
            if ot.order_state == OrderState.SUBMITTED and ot.position_id is None:
                self.cancel_order(self.cache.order(ot.client_order_id))

            elif ot.position_id is not None and ot.position_state == PositionState.OPEN:
                self.cache.is_position_open(ot.position_id)
                forced_close_order_ticket = self._created_forced_close_order_ticket(ot)
                forced_close_order_tickets.append(forced_close_order_ticket)
        self._register_forced_close_order_ticket(forced_close_order_tickets)
        self._submit_forced_close_order(forced_close_order_tickets)

    def _created_forced_close_order_ticket(self, parent_order_ticket: OrderTicket):
        order_ticket = ForcedCloseOrderComposer().compose(parent_order_ticket)
        order = self._create_order(order_ticket)
        order_ticket.order = order
        order_ticket.order_client_order_id = order.client_order_id
        order_ticket.order_state = OrderState.CREATED
        order_ticket.order_created_at = self.clock.utc_now()
        order_ticket.is_forced_close_order = True
        return order_ticket

    def _register_forced_close_order_ticket(self, order_tickets: list[OrderTicket]):
        for t in order_tickets:
            self._order_ticket_manager.register_ticket(t.order_client_order_id, t)

    def _submit_forced_close_order(self, order_tickets: list[OrderTicket]):
        for t in order_tickets:
            self.submit_order(t.order)

    # provider mehtod
    def get_snapshot_intraday_high(self, instrument_id: InstrumentId) -> float:
        v = self._snapshot_data.loc[
            self._snapshot_data["instrument_id"] == instrument_id, "intraday_high"
        ].item()
        return v

    def get_snapshot_intraday_low(self, instrument_id: InstrumentId) -> float:
        v = self._snapshot_data.loc[
            self._snapshot_data["instrument_id"] == instrument_id, "intraday_low"
        ].item()
        return v

    def get_latest_bar_with_trading_bar_type(self, instrument_id: InstrumentId) -> Bar:
        target_bar_type = self.instrument_bar_type_map.get(instrument_id)[
            self._trading_rule.order_rule.trading_bar_type
        ]
        bar = self.cache.bars(target_bar_type)[0]
        return bar

    def get_trading_rule(self) -> TradingRulesMutable:
        return self._trading_rule

    def get_intraday_realized_pnl(self) -> float:
        return self._intraday_realized_pnl

    def get_instrument(self, instrument_id: InstrumentId) -> Instrument:
        instrument_id = instrument_id
        instrument = self.cache.instrument(instrument_id)
        return instrument

    def get_current_datetime(self) -> datetime.datetime:
        return self.clock.utc_now()

    # position
    def get_open_positions(
        self, side: PositionSide, instrument_id: InstrumentId
    ) -> list[Position]:
        return self.cache.positions_open(instrument_id=instrument_id, side=side)

    # order
    def get_open_orders(
        self, side: OrderSide, instrument_id: InstrumentId
    ) -> list[Order]:
        return self.cache.orders_open(side=side, instrument_id=instrument_id)

    # pnl
    def get_unrealized_profit_and_loss(self) -> float:
        open_positions = self.cache.positions_open(instrument_id=None)
        unrealized_pnl = 0.0
        for p in open_positions:
            latest_bar = self.get_latest_bar_with_trading_bar_type(str(p.instrument_id))
            pnl = p.unrealized_pnl(latest_bar.low)
            unrealized_pnl += pnl.as_double()
        return unrealized_pnl

    def get_realized_profit_and_loss(self) -> float:
        current_balance = self.portfolio.account(self.venue).balance_total()

        realized = current_balance.as_double() - self._trading_rule.risk_rule.balance
        return realized

    def get_depolyed_balance(self, instrument_id: InstrumentId) -> float:
        balance_from_positions = sum(
            (p.avg_px_open.as_double() * p.quantity.as_double())
            for p in self.cache.positions_open()
        )

        reference_bar = self.get_latest_bar_with_trading_bar_type(instrument_id)
        balance_from_pending_orders = sum(
            (
                ((reference_bar.high.as_double() + reference_bar.low.as_double()) / 2)
                * o.quantity.as_double()
            )
            for o in list(self.cache.orders_inflight()) + list(self.cache.orders_open())
        )

        balance_deployed = balance_from_positions + balance_from_pending_orders
        return balance_deployed

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
            trading_rule=self._trading_rule, provider=self
        )
        self._order_ticket_manager: OrderTicketManager = OrderTicketManager()

    # request / response method
    def _request_watchlist(self):
        self.msgbus.send(
            endpoint=self.config.msg_outbound_endpoint, msg=WatchListRequest()
        )

    @singledispatchmethod
    def _dispatch_msg(self, msg) -> None:
        self.log.warning(f"Unhandled custom data type: {type(msg).__name__}")

    @_dispatch_msg.register
    def _receive_watchlist(self, msg: WatchListResponse) -> None:
        if msg.is_ready:
            self._watchlist = msg.payload
