import datetime
import pandas as pd
from collections import defaultdict
from functools import singledispatchmethod

from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.enums import (
    PositionSide,
    OrderSide,
    OrderType,
)
from nautilus_trader.model.orders import Order

from mixin import DailyResetMixin
from indicator.field import IndicatorMeta
from message import IntradayDataFrameRequest, IntradayDataFrameResponse
from strategy.signal import SignalMeta, SIGNAL_REGISTRY
from schemas import (
    TradingRule,
    SessionConfig,
    Operator,
    EventType,
    EventPayloadField,
    Event,
    WatchListAction,
    WatchListActionReason,
    CandidateAction,
    CandidateActionReason,
)


class ConsolidationAndBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for trading equities which consolidating in the morning and breakout the highest point in the period of consolidation
    """

    warmup_data_start_datetime: datetime.datetime
    data_start_datetime: datetime.datetime
    bar_types: dict[InstrumentId, list[BarType]]
    indicator_meta_set: list[IndicatorMeta]
    consolidation_end: (
        datetime.time
    )  # time point which decide when the consolidation period end
    session_config: SessionConfig
    trading_rule: TradingRule
    venue_currency_pair: dict
    msg_enpoint: str
    msg_outbound_endpoint: str
    signal_meta_set: list[SignalMeta]


class ConsolidationAndBreakout(Strategy, DailyResetMixin):
    def __init__(self, config: ConsolidationAndBreakoutConfig):
        super().__init__(config)
        self._current_session_date: datetime.date | None = None
        self._current_session_time: datetime.time | None = None
        self.candidate: set[str] = set()
        self.watch_list: dict[str, Signal] = defaultdict()
        self.screening_query = self._screening_query()
        self.screening_columns = self._screening_columns()
        self.latest_data = pd.DataFrame()
        self.snapshot_data = pd.DataFrame()
        self.events: list[Event] = []

    def on_start(self):
        self._init_daily_reset()
        self._register_daily_reset(self._on_daily_reset)
        for bts in self.config.bar_types.values():
            for bt in bts:
                self.subscribe_bars(bt)

        # set timer to froce close the position before the time
        self.clock.set_timer(
            name="force_close_position",
            start_time=self.config.data_start_datetime.replace(
                hour=self.config.trading_rule.forced_close_at.hour,
                minute=self.config.trading_rule.forced_close_at.minute,
                second=self.config.trading_rule.forced_close_at.second,
                microsecond=self.config.trading_rule.forced_close_at.microsecond,
            ),
            interval=datetime.timedelta(days=1),
            callback=self._forced_close_positions,
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
        # build_watch_list
        self.clock.set_timer(
            name="build_watch_list",
            start_time=self.config.data_start_datetime.replace(
                hour=self.config.consolidation_end.hour,
                minute=self.config.consolidation_end.minute,
                second=self.config.consolidation_end.second,
            ),
            interval=datetime.timedelta(days=1),
            callback=self._build_watch_list,
        )

        # request register
        self.msgbus.register(
            endpoint=self.config.msg_enpoint,
            handler=self._dispatch_msg,
        )

    def on_bar(self, bar: Bar):
        if self.clock.utc_now().time() < self.config.consolidation_end:
            return
        # setup a time alert event to select best candidate from candidates
        bar_time = unix_nanos_to_dt(bar.ts_event)
        if self._current_session_time is None or self._current_session_time != bar_time:
            self._current_session_time = bar_time
            self.clock.set_time_alert(
                name="select_best_candidate",
                alert_time=bar_time + datetime.timedelta(seconds=2),
                callback=self._select_best_candidate,
            )
        # select candidate
        self._selectt_candidate(bar)

    def on_stop(self):
        pass

    # screening, ranking and building watch list
    def _screening_query(self):
        fields = set()
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                fields.add(cfg)
        query = "&".join(
            [
                f" {cfg.name} {cfg.operator.to_symbol()} {str(cfg.threshold)} "
                for cfg in fields
                if cfg.threshold is not None
            ]
        )
        return query

    def _screening_condition_dict(self) -> dict:
        condition_dict = defaultdict()
        fields = set()
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                fields.add(cfg)
        for cfg in fields:
            if cfg.threshold is not None:
                condition_dict[cfg.name] = f"{cfg.operator.value}|{str(cfg.threshold)}"

        return condition_dict

    def _screening_columns(self) -> list[str]:
        cols = []
        for indm in self.config.indicator_meta_set:
            for cfg in indm.field_configs:
                if cfg.threshold is not None and cfg.operator is not None:
                    cols.append(cfg.name)

        return cols

    def _screening(self):
        if self.snapshot_data.empty:
            self._request_intraday_dataframe(snapshot=True)
        mask = self.snapshot_data.eval(self.screening_query)
        self.snapshot_data["screening_result"] = mask
        self._create_and_append_event(
            event_type=EventType.SCREENING,
            payload={
                EventPayloadField.CONDITION: self._screening_condition_dict(),
                EventPayloadField.SOURCE: "snapshot_data",
            },
        )

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

                    n_col = f"{cfg.name}_rank"
                    r_cols.append(n_col)
                    df[n_col] = df[f"{cfg.name}"].rank(
                        method="dense", ascending=ascending
                    )
        # higher ranking sum is better
        df["rank_sum"] = df[r_cols].sum(axis=1)
        # for event
        if df.equals(self.snapshot_data):
            source = "snapshot_data"
        elif df.equals(self.latest_data):
            source = "latest_data"
        self._create_and_append_event(
            event_type=EventType.RANKING,
            payload={
                EventPayloadField.CONDITION: self._ranking_condition_dict(),
                EventPayloadField.SOURCE: source,
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
                    callback_provider=self,
                )
            )

        return sl

    def _build_watch_list(self, event):
        self._screening()  # may have better place to run this method
        mask = self.snapshot_data.eval(self.screening_query)
        for k in self.snapshot_data.loc[mask]["instrument_id"]:
            metrics = (
                self.snapshot_data.loc[
                    self.snapshot_data["instrument_id"] == k, self.screening_columns
                ]
                .squeeze()
                .to_dict()
            )
            if k not in self.watch_list.keys():
                self.watch_list[k] = self._build_signal(k)

                self._create_and_append_event(
                    event_type=EventType.SELECT_WATCH_LIST,
                    payload={
                        EventPayloadField.ACTION: WatchListAction.ADD,
                        EventPayloadField.INVOLVED: k,
                        EventPayloadField.SOURCE: "snapshot_data",
                        EventPayloadField.CONDITION: self._screening_condition_dict(),
                        EventPayloadField.METRICS: metrics,
                    },
                )
            elif k in self.watch_list.keys():
                self._create_and_append_event(
                    event_type=EventType.SELECT_WATCH_LIST,
                    payload={
                        EventPayloadField.ACTION: WatchListAction.SKIP,
                        EventPayloadField.INVOLVED: k,
                        EventPayloadField.REASON: WatchListActionReason.EXISTED,
                    },
                )

    # candidate
    def _selectt_candidate(self, bar):
        instrument_id_string = str(bar.bar_type.instrument_id)
        for k, v in self.watch_list.items():
            # v is a list of Signal
            if instrument_id_string != k:
                continue

            metrics = {}
            for s in v:
                s.update(bar)
                metrics[s.name] = {}
                sm = {}
                for f in s.factors:
                    sm[f.name] = f.metric
                metrics[s.name] = metrics[s.name] | sm
            signal = all([s.signal for s in v])
            if instrument_id_string in self.candidate:
                if signal:
                    continue
                elif not signal:
                    self.candidate.remove(k)
                    self._create_and_append_event(
                        event_type=EventType.SELECT_CANDIDATE,
                        payload={
                            EventPayloadField.ACTION: CandidateAction.REMOVE,
                            EventPayloadField.INVOLVED: k,
                            EventPayloadField.REASON: CandidateActionReason.SIGNAL_INVALIDATED,
                            EventPayloadField.METRICS: metrics,
                        },
                    )

            elif not instrument_id_string in self.candidate:
                if signal:
                    self.candidate.add(k)
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

    def _select_best_candidate(self, event):
        pass

    # order / position
    def _pre_close_position_check(self):
        pass

    def _pre_order_check(self, order: Order, order_value: float) -> tuple[bool, str]:
        """
        Return the desicion and the reason for why the order placeing attemptation is accepted/refused
        """
        venue = order.instrument_id.venue
        # check prosition open
        open_positions = len(self.cache.positions_open())
        if open_positions >= self.config.trading_rule.open_position_maximum:
            return (
                False,
                f"Size of open positions reach the open position maximum {self.config.trading_rule.open_position_maximum}",
            )

        open_order = self.cache.orders_open()
        if open_order >= self.config.trading_rule.open_order_maximum:
            return (
                False,
                f"Size of open order reach the open order maximum {self.config.trading_rule.open_order_maximum}",
            )
        # only one open order or position for a instrument id
        if self.cache.orders_open_count(instrument_id=order.instrument_id) > 0:
            return (
                False,
                f"Open order for the instrument {order.instrument_id} exist.",
            )
        if self.cache.positions_open(instrument_id=order.instrument_id) > 0:
            return (
                False,
                f"Open position for the instrument {order.instrument_id} exist.",
            )

        account = self.portfolio.account(venue)
        balance = account.balance(self.config.venue_currency_pair[venue])
        if balance.free.as_double() > order_value:
            return (True, "")
        # might require to implement the logic of comparing which trade is better and change the order
        elif balance.free.as_double() <= order_value:
            return (False, "Not enough balance.")

    def _closing_position(self):
        # closing position logic
        # close the position that no new high during past five minute
        if len(self.cache.position_open()) == 0:
            return
        for position in self.cache.positions_open():
            instrument_id = position.instrument_id
            # get the current high from subscribed dataframe and
            pass

    def _forced_close_positions(self, event):
        for position in self.cache.positions_open():
            self.close_position(position)
            # put the record some where

    # callbacks
    def get_snapshot_intraday_high(self, instrument_id: str):
        v = self.snapshot_data.loc[
            self.snapshot_data["instrument_id"] == instrument_id, "intraday_high"
        ].item()
        return v

    # event log
    def _create_and_append_event(
        self, event_type: EventType, payload: dict = defaultdict()
    ):
        event = Event(
            event_type=event_type,
            created_at=self.clock.utc_now(),
            payload=payload,
        )
        print(event.model_dump_json())
        self.events.append(event)

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
        self._current_session_date: datetime.date | None = None
        self._current_session_time: datetime.time | None = None
        self.candidate = set()
        self.screening_query = self._screening_query()
        self.screening_columes = []
        self.latest_data = pd.DataFrame()
        self.snapshot_data = pd.DataFrame()
        self.watch_list: dict[str, Signal] = defaultdict()
        self.events = []

    # request / response method
    def _request_intraday_dataframe(self, snapshot: bool) -> None:
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
            self.snapshot_data = msg.data
        else:
            self.latest_data = msg.data
