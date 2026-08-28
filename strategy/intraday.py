import json
import datetime
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict
from functools import singledispatchmethod, lru_cache

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
from message import IntradayDataFrameRequest, IntradayDataFrameResponse
from indicator.indicator import IndicatorMeta
from indicator.field import IndicatorFieldConfig
from trading_signal.signal import BaseSignal, SignalMeta, SIGNAL_REGISTRY
from trading_signal.ranking import PercentilRanking
from order.order_validator import ORDER_VALIDATOR_REGISTRY
from order.order import (
    OrderTicket,
    OrderTicketGroup,
    OrderTicketBook,
    OrderState,
    PositionState,
    OrderRole,
    ForcedCloseOrderComposer,
    ORDER_COMPOSER_REGISTRY,
)
from schemas import (
    Operator,
    CandidateFlat,
    EventType,
    EventPayloadField,
    Event,
    WatchListAction,
    WatchListActionReason,
    CandidateAction,
    CandidateActionReason,
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
    signal_meta_set: list[SignalMeta]
    signal_aggregation_method: AggregationMethod
    consolidation_end: (
        datetime.time
    )  # time point which decide when the consolidation period end
    order_rule: OrderRules
    position_rule: PositionRules
    risk_rule: RiskRules
    session_rule: SessionRule
    order_config_factory: str
    order_type: str
    order_validator: str
    order_composer: str
    venue_currency_pair: dict
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
        self._current_session_time: datetime.time | None = None
        self._current_session_bars: list[Bar] = []
        # indicator dataframe
        self.__latest_data = pd.DataFrame()
        self._latest_data_updated_at: datetime.time | None = None
        self._snapshot_data = pd.DataFrame()
        self._is_snapshot_data_screened: bool = False
        # screening, ranking and candidate
        self._watch_list: dict[str, list[BaseSignal]] = defaultdict()
        self._is_watch_list_built: bool = False
        self._candidate: set[str] = set()
        self._candidate_ranking_metric = None
        # event
        self._events: list[Event] = []
        self._event_dir = Path(
            f"{NAUTILUS_CONFIG.record_path}{self.config.name}/events"
        )
        # trade
        self._trading_rule = TradingRulesMutable(
            order_rule=OrderRulesMutable(**asdict(self.config.order_rule)),
            position_rule=PositionRulesMutable(**asdict(self.config.position_rule)),
            risk_rule=RiskRulesMutable(**asdict(self.config.risk_rule)),
            session_rule=SessionRuleMutable(**asdict(self.config.session_rule)),
        )
        self._order_ticket_book: OrderTicketBook = OrderTicketBook()

    @property
    def _latest_data(self) -> pd.DataFrame:
        self.__latest_data = self._request_intraday_dataframe(snapshot=False)
        return self.__latest_data

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
        current_time = self.clock.utc_now()
        if (
            self._current_session_time == None
            or self._current_session_time < current_time
        ):

            self._current_session_time = current_time
            self.clock.set_time_alert(
                name="process_current_session_bars",
                alert_time=current_time + datetime.timedelta(seconds=2),
                callback=self._process_current_session_bars,
            )

    def on_order_initialized(self, event: OrderInitialized) -> None:
        pass

    def on_order_submitted(self, event: OrderSubmitted):
        datetime = self.clock.utc_now()
        self._order_ticket_book.update_on_order_submitted(
            event.client_order_id, datetime
        )
        self._create_and_append_event(
            event_type=EventType.ORDER_SUBMITTED,
            payload={EventPayloadField.INVOLVED: str(event.client_order_id)},
        )

    def on_order_accepted(self, event: OrderAccepted) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_book.update_on_order_accepted(
            event.client_order_id, datetime
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_book.update_on_order_rejected(
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
        self._order_ticket_book.update_on_order_canceled(
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
        self._order_ticket_book.update_on_order_expired(event.client_order_id, datetime)
        self._create_and_append_event(
            event_type=EventType.ORDER_EXPIRED,
            payload={
                EventPayloadField.INVOLVED: str(event.client_order_id),
            },
        )

    def on_order_filled(self, event: OrderFilled) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_book.update_on_order_filled(event.client_order_id, datetime)
        self._order_ticket_book.update_position_id(
            event.client_order_id, event.position_id
        )
        self._order_ticket_book.update_order_filled_price_qty(
            event.client_order_id, event.last_qty, event.last_px
        )
        self._order_ticket_book.update_cost(event.client_order_id, event.commission)
        cot = self._order_ticket_book.get_child_order_ticket(event.client_order_id)
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
        self._order_ticket_book.update_position_state(
            event.opening_order_id, PositionState.OPEN
        )
        self._order_ticket_book.update_position_open_time(
            event.opening_order_id, datetime
        )

    def on_position_closed(self, event: PositionClosed) -> None:
        datetime = self.clock.utc_now()
        self._order_ticket_book.update_position_state(
            event.opening_order_id, PositionState.CLOSED
        )
        self._order_ticket_book.update_position_close_time(
            event.opening_order_id, datetime
        )
        self._order_ticket_book.update_position_realized_profit_and_loss(
            event.opening_order_id, event.realized_pnl
        )

    def on_stop(self):
        print(self._order_ticket_book._books)
        pass

    def _warm_up(self):
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "screening condition",
                EventPayloadField.CONDITION: self._screening_condition_dict(),
            },
        )
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "ranking condition",
                EventPayloadField.CONDITION: self._ranking_condition_dict(),
            },
        )
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "factor ranking condition",
                EventPayloadField.CONDITION: self._factor_ranking_dict(),
            },
        )
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "signal internal aggregation method",
                EventPayloadField.CONDITION: self._signal_internal_aggregation_dict(),
            },
        )
        self._create_and_append_event(
            event_type=EventType.WARM_UP,
            payload={
                EventPayloadField.DESCRIPTION: "signal between aggregation method",
                EventPayloadField.CONDITION: self.config.signal_aggregation_method,
            },
        )
        # make event dir
        self._event_dir.mkdir(parents=True, exist_ok=True)

    # screening, ranking and building watch list
    @lru_cache(maxsize=1)
    def _screening_query(self):
        fields: dict[str, IndicatorFieldConfig] = {}
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                fields[cfg.name] = cfg

        query = "&".join(
            [
                f" {n} {cfg.operator.to_symbol()} {str(cfg.threshold)} "
                for n, cfg in fields.items()
                if cfg.threshold is not None
            ]
        )
        return query

    @lru_cache(maxsize=1)
    def _screening_condition_dict(self) -> dict:
        condition_dict = defaultdict()
        fields: dict[str, IndicatorFieldConfig] = {}
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                fields[cfg.name] = cfg

        for n, cfg in fields.items():
            if cfg.threshold is not None:
                condition_dict[n] = f"{cfg.operator.value}|{str(cfg.threshold)}"

        return condition_dict

    def _screening_columns(self) -> list[str]:
        cols = []
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                if cfg.threshold is not None and cfg.operator is not None:
                    cols.append(cfg.name)

        return cols

    def _screening_snapshot_data(self):
        if self._snapshot_data.empty:
            self._request_intraday_dataframe(snapshot=True)
        mask = self._snapshot_data.eval(self._screening_query())
        self._snapshot_data[self.COL_SCREENING_RESULT] = mask
        self._create_and_append_event(
            event_type=EventType.SCREENING,
            payload={
                EventPayloadField.SOURCE: "snapshot_data",
            },
        )

    def _build_signal(self, instrument_id: str):
        sl = []
        for signal_config in self.config.signal_meta_set:
            s = SIGNAL_REGISTRY.get(signal_config.name)
            sl.append(
                s(
                    name=signal_config.name,
                    instrument_id=instrument_id,
                    factor_configs=signal_config.factor_configs,
                    provider=self,
                    is_entry_signal=signal_config.is_entry_signal,
                    is_exit_signal=signal_config.is_exit_signal,
                )
            )

        return sl

    def _build_watch_list(self):
        mask = self._snapshot_data.eval(self._screening_query())
        for k in self._snapshot_data.loc[mask][self.COL_INSTRUMENT_ID]:
            metrics = (
                self._snapshot_data.loc[
                    self._snapshot_data[self.COL_INSTRUMENT_ID] == k,
                    self._screening_columns(),
                ]
                .squeeze()
                .to_dict()
            )
            if k not in self._watch_list.keys():
                self._watch_list[k] = self._build_signal(k)

                self._create_and_append_event(
                    event_type=EventType.SELECT_WATCH_LIST,
                    payload={
                        EventPayloadField.ACTION: WatchListAction.ADD,
                        EventPayloadField.INVOLVED: k,
                        EventPayloadField.SOURCE: "snapshot_data",
                        EventPayloadField.METRICS: metrics,
                    },
                )
            elif k in self._watch_list.keys():
                self._create_and_append_event(
                    event_type=EventType.SELECT_WATCH_LIST,
                    payload={
                        EventPayloadField.ACTION: WatchListAction.SKIP,
                        EventPayloadField.INVOLVED: k,
                        EventPayloadField.REASON: WatchListActionReason.EXISTED,
                    },
                )

    @lru_cache(maxsize=1)
    def _ranking_condition_dict(self) -> dict:
        condition_dict = {}
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                if cfg.threshold is not None and cfg.operator is not None:
                    if cfg.operator in (Operator.GT or Operator.GTE):
                        ascending = True
                    elif cfg.operator in (Operator.LT, Operator.LTE):
                        ascending = False
                    else:
                        ascending = False
                    condition_dict[cfg.name] = {
                        "method": "dense",
                        "ascending": ascending,
                    }
        return condition_dict

    def _ranking(self, df: pd.DataFrame):
        r_cols = []
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                if cfg.threshold is not None and cfg.operator is not None:
                    if cfg.operator in (Operator.GT or Operator.GTE):
                        ascending = True
                    elif cfg.operator in (Operator.LT, Operator.LTE):
                        ascending = False
                    else:
                        ascending = False

                    n_col = f"{cfg.name}{self.COL_RANK_POSTFIX}"
                    r_cols.append(n_col)
                    df[n_col] = df[f"{cfg.name}"].rank(
                        method="dense", ascending=ascending
                    )
        df[f"{self.COL_RANK_SUM}"] = df[r_cols].sum(axis=1)

    def _ranking_snapshot_data(self):
        self._ranking(df=self._snapshot_data)
        self._create_and_append_event(
            event_type=EventType.RANKING,
            payload={
                EventPayloadField.SOURCE: "snapshot_data",
            },
        )

    def _ranking_latest_data(self):
        self._ranking(df=self._latest_data)
        self._create_and_append_event(
            event_type=EventType.RANKING,
            payload={
                EventPayloadField.SOURCE: "latest_data",
            },
        )

    # candidate
    def _select_candidate(self, bar):
        instrument_id_string = str(bar.bar_type.instrument_id)
        for k, v in self._watch_list.items():
            # v is a list of Signal
            if instrument_id_string != k:
                continue

            metrics = {}
            for s in v:
                s.update(bar)  # signal update
                metrics[s.name] = {}
                sm = {}
                for f in s.factors:
                    sm[f.name] = f.value
                metrics[s.name] = metrics[s.name] | sm
            signal = all([s.signal for s in v])
            if instrument_id_string in self._candidate:
                if signal:
                    continue
                elif not signal:
                    self._candidate.remove(k)
                    self._create_and_append_event(
                        event_type=EventType.SELECT_CANDIDATE,
                        payload={
                            EventPayloadField.ACTION: CandidateAction.REMOVE,
                            EventPayloadField.INVOLVED: k,
                            EventPayloadField.REASON: CandidateActionReason.SIGNAL_INVALIDATED,
                            EventPayloadField.METRICS: metrics,
                        },
                    )

            elif not instrument_id_string in self._candidate:
                if signal:
                    self._candidate.add(k)
                    self._create_and_append_event(
                        event_type=EventType.SELECT_CANDIDATE,
                        payload={
                            EventPayloadField.ACTION: CandidateAction.ADD,
                            EventPayloadField.INVOLVED: k,
                            EventPayloadField.METRICS: metrics,
                        },
                    )
                elif not signal:
                    self._create_and_append_event(
                        event_type=EventType.SELECT_CANDIDATE,
                        payload={
                            EventPayloadField.ACTION: CandidateAction.SKIP,
                            EventPayloadField.INVOLVED: k,
                            EventPayloadField.REASON: CandidateActionReason.SIGNAL_INVALIDATED,
                            EventPayloadField.METRICS: metrics,
                        },
                    )

    @lru_cache(maxsize=1)
    def _factor_ranking_dict(self):
        frd = defaultdict()
        for sm in self.config.signal_meta_set:
            for fcfg in sm.factor_configs:
                frd[fcfg.name] = fcfg.ranking_config.to_dict()
        return frd

    def _percentil_ranking(self, df: pd.DataFrame):
        factor = df.name[1]
        direction = self._factor_ranking_dict()[factor]["percentile"]["ascending"]
        method = self._factor_ranking_dict()[factor]["percentile"][
            "tie_breaking_method"
        ]
        return df["factor_value"].rank(pct=True, method=method, ascending=direction)

    @lru_cache(maxsize=1)
    def _signal_internal_aggregation_dict(self):
        sd = defaultdict()
        for s in self.config.signal_meta_set:
            sd[s.name] = s.internal_aggregation_method
        return sd

    def _ranking_candidate(self):
        records: list = []
        candidate_count = 0

        for can in self._candidate:
            candidate_count += 1
            sigs = self._watch_list.get(can)
            for s in sigs:
                if not s.is_entry_signal:
                    continue
                for f in s.factors:
                    record = CandidateFlat(
                        instrument_id=can,
                        signal=s.name,
                        factor=f.name,
                        factor_value=f.value,
                    )
                    records.append(record)

        df = pd.DataFrame([r.model_dump() for r in records])
        if df.empty:
            return
        ranking_metric = PercentilRanking(
            df=df,
            factor_ranking_dict=self._factor_ranking_dict(),
            internal_aggregation_dict=self._signal_internal_aggregation_dict(),
            between_aggregation_method=self.config.signal_aggregation_method,
        ).rank()
        self._create_and_append_event(
            event_type=EventType.RANKING_CANDIDATE,
            payload={
                EventPayloadField.METRICS: ranking_metric.model_dump(),
            },
        )
        self._candidate_ranking_metric = ranking_metric

    def _process_current_session_bars(self, event):
        # may use a class to put the logic
        if self.clock.utc_now().time() < self.config.consolidation_end:
            self._current_session_bars = []
            return
        # built watch list
        if self._is_snapshot_data_screened:
            pass
        elif not self._is_snapshot_data_screened:
            self._screening_snapshot_data()
            self._is_snapshot_data_screened = True

        if self._is_watch_list_built:
            pass
        elif not self._is_watch_list_built:
            self._build_watch_list()
            self._is_watch_list_built = True

        for bar in self._current_session_bars:
            # select candidate
            self._select_candidate(bar)
            # update mfe and mae
            self._order_ticket_book.upate_mae_mfe(bar)

        self._current_session_bars = []

        # ranking candidate
        self._ranking_candidate()

        self.clock.set_time_alert(
            name="create_and_submit_order",
            alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
            callback=self._create_and_submit_order,
        )

    def _create_and_submit_order(self, event):
        instrument_id = self._pre_order_validation()
        if instrument_id is None:
            return

        order_ticket_group = self._create_order_ticket_groups(instrument_id)
        if order_ticket_group is None:
            return

        order_tickets = self._create_and_register_order_ticket(order_ticket_group)
        for ot in order_tickets:
            if ot.order_role == OrderRole.PARENT:
                self.submit_order(ot.order)

    def _pre_order_validation(self):
        if not self._candidate:
            self._create_and_append_event(
                event_type=EventType.PRE_ORDER_VALIDATION,
                payload={
                    EventPayloadField.ACTION: PreOrderValidationAction.SKIP,
                    EventPayloadField.REASON: PreOrderValidationReason.NO_CANDIDATE,
                },
            )
            return

        metric = self._candidate_ranking_metric
        final_score = metric.final_scores
        instrument_id, score = next(iter(final_score.items()))
        validator = ORDER_VALIDATOR_REGISTRY[self.config.order_validator](
            trading_rule=self._trading_rule, provider=self
        )
        metric = validator.pre_order_validate(instrument_id)

        if not all(metric.values()):
            self._create_and_append_event(
                event_type=EventType.PRE_ORDER_VALIDATION,
                payload={
                    EventPayloadField.ACTION: PreOrderValidationAction.SKIP,
                    EventPayloadField.REASON: PreOrderValidationReason.FAIL,
                    EventPayloadField.METRICS: metric,
                },
            )
            return
        else:
            return instrument_id

    def _create_order_ticket_groups(self, instrument_id: str):
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
            self._order_ticket_book.register_ticket(
                client_order_id=p_order.client_order_id, order_ticket=p_order_ticket
            )
            self._order_ticket_book.register_ticket(
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
        tickets = self._order_ticket_book.get_tickets()
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
            self._order_ticket_book.register_ticket(t.order_client_order_id, t)

    def _submit_forced_close_order(self, order_tickets: list[OrderTicket]):
        for t in order_tickets:
            self.submit_order(t.order)

    # provider mehtod
    def get_snapshot_intraday_high(self, instrument_id: str) -> float:
        v = self._snapshot_data.loc[
            self._snapshot_data["instrument_id"] == instrument_id, "intraday_high"
        ].item()
        return v

    def get_snapshot_intraday_low(self, instrument_id: str) -> float:
        v = self._snapshot_data.loc[
            self._snapshot_data["instrument_id"] == instrument_id, "intraday_low"
        ].item()
        return v

    def get_intraday_atr(self, instrument_id: str) -> float:
        v = self._latest_data.loc[
            self._latest_data["instrument_id"] == instrument_id, "intraday_atr"
        ].item()
        return v

    def get_latest_bar_with_trading_bar_type(self, instrument_id: str) -> Bar:
        target_bar_type = self.instrument_bar_type_map.get(instrument_id)[
            self._trading_rule.order_rule.trading_bar_type
        ]
        bar = self.cache.bars(target_bar_type)[0]
        return bar

    def get_trading_rule(self) -> TradingRulesMutable:
        return self._trading_rule

    def get_intraday_realized_pnl(self) -> float:
        return self._intraday_realized_pnl

    def get_instrument(self, instrument_id: str) -> Instrument:
        instrument_id = InstrumentId.from_str(instrument_id)
        instrument = self.cache.instrument(instrument_id)
        return instrument

    def get_current_datetime(self) -> datetime.datetime:
        return self.clock.utc_now()

    # position
    def get_open_positions(
        self, side: PositionSide, instrument_id: str
    ) -> list[Position]:
        return self.cache.positions_open(
            instrument_id=InstrumentId.from_str(instrument_id), side=side
        )

    # order
    def get_open_orders(self, side: OrderSide, instrument_id: str) -> list[Order]:
        return self.cache.orders_open(
            side=side, instrument_id=InstrumentId.from_str(instrument_id)
        )

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

    def get_depolyed_balance(self, instrument_id: str) -> float:
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
        # reset variables
        # session
        self._current_session_date: datetime.date | None = None
        self._current_session_time: datetime.time | None = None
        self._current_session_bars: list[Bar] = []
        # indicator dataframe
        self.__latest_data = pd.DataFrame()
        self._latest_data_updated_at: datetime.time | None = None
        self._snapshot_data = pd.DataFrame()
        self._is_snapshot_data_screened: bool = False
        # screening, ranking and candidate
        self._watch_list: dict[str, list[BaseSignal]] = defaultdict()
        self._is_watch_list_built: bool = False
        self._candidate: set[str] = set()
        self._candidate_ranking_metric = None

    # request / response method
    def _request_intraday_dataframe(self, snapshot: bool):
        if not snapshot:
            time = self.clock.utc_now().time()
            if (
                self._latest_data_updated_at is None
                or self._latest_data_updated_at < time
            ):
                self._latest_data_updated_at = time
                self.msgbus.send(
                    endpoint=self.config.msg_outbound_endpoint,
                    msg=IntradayDataFrameRequest(snapshot=snapshot),
                )
            elif self._latest_data_updated_at == time:
                pass
        elif snapshot:
            self.msgbus.send(
                endpoint=self.config.msg_outbound_endpoint,
                msg=IntradayDataFrameRequest(snapshot=snapshot),
            )

    @singledispatchmethod
    def _dispatch_msg(self, msg) -> None:
        self.log.warning(f"Unhandled custom data type: {type(msg).__name__}")

    @_dispatch_msg.register
    def _intraday_data_frame(self, msg: IntradayDataFrameResponse) -> None:
        if msg.snapshot:
            self._snapshot_data = msg.data
        else:
            self.__latest_data = msg.data
