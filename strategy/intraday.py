import json
import datetime
import pandas as pd
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict
from functools import singledispatchmethod, lru_cache

from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.events.position import PositionClosed
from nautilus_trader.model import InstrumentId, BarType, Bar
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.enums import PositionSide, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.orders import Order

from config import NAUTILUS_CONFIG
from mixin import DailyResetMixin
from message import IntradayDataFrameRequest, IntradayDataFrameResponse
from indicator.indicator import IndicatorMeta
from indicator.field import IndicatorFieldConfig
from signal.signal import BaseSignal, SignalMeta, SIGNAL_REGISTRY
from signal.ranking import PercentilRanking
from order.order import ORDER_CONFIG_FACTOR_REGISTER
from order.order_validator import OrderValidator
from schemas import (
    SessionConfig,
    Operator,
    CandidateFlat,
    EventType,
    EventPayloadField,
    Event,
    WatchListAction,
    WatchListActionReason,
    CandidateAction,
    CandidateActionReason,
    AggregationMethod,
    OrderRules,
    PositionRules,
    RiskRules,
    TradingRulesMutable,
    OrderRulesMutable,
    PositionRulesMutable,
    RiskRulesMutable,
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
    session_config: SessionConfig
    order_rule: OrderRules
    position_rule: PositionRules
    risk_rule: RiskRules
    order_config_factory: str
    order_type: str
    venue_currency_pair: dict
    msg_enpoint: str
    msg_outbound_endpoint: str


class ConsolidationAndBreakout(Strategy, DailyResetMixin):
    def __init__(self, config: ConsolidationAndBreakoutConfig):
        super().__init__(config)
        self.instrument_bar_type_map: dict = defaultdict()
        self._current_session_date: datetime.date | None = None
        self._current_session_time: datetime.time | None = None
        self.candidate: set[str] = set()
        self.watch_list: dict[str, list[BaseSignal]] = defaultdict()
        self.screening_query = self._screening_query()
        self.screening_columns = self._screening_columns()
        self._latest_data = pd.DataFrame()
        self.latest_data_updated_at: datetime.time | None = None
        self.snapshot_data = pd.DataFrame()
        self.events: list[Event] = []
        self.event_dir = Path(f"{NAUTILUS_CONFIG.record_path}{self.config.name}/events")
        self._intraday_realized_pnl: float = 0.0
        self._ranking_metric = None
        self._trading_rule = TradingRulesMutable(
            order_rule=OrderRulesMutable(**asdict(self.config.order_rule)),
            position_rule=PositionRulesMutable(**asdict(self.config.position_rule)),
            risk_rule=RiskRulesMutable(**asdict(self.config.risk_rule)),
        )
        self._order_validator = OrderValidator(
            trading_rule=self._trading_rule,
            provider=self,
        )

    @property
    def latest_data(self):
        self._latest_data = self._request_intraday_dataframe(snapshot=False)
        return self._latest_data

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
            name="force_close_position",
            start_time=self.config.data_start_datetime.replace(
                hour=self.config.position_rule.forced_close_at.hour,
                minute=self.config.position_rule.forced_close_at.minute,
                second=self.config.position_rule.forced_close_at.second,
                microsecond=self.config.position_rule.forced_close_at.microsecond,
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
        if self.clock.utc_now().time() < self.config.session_config.market_open_at:
            return
        elif self.clock.utc_now().time() > self.config.session_config.market_close_at:
            return
        elif self.clock.utc_now().time() < self.config.consolidation_end:
            return
        # setup a time alert event to select best candidate from candidates
        bar_time = unix_nanos_to_dt(bar.ts_event)
        if self._current_session_time is None or self._current_session_time != bar_time:
            self._current_session_time = bar_time
            self.clock.set_time_alert(
                name="ranking_candidate",
                alert_time=bar_time + datetime.timedelta(seconds=2),
                callback=self._ranking_candidate,
            )
        # if bar.bar_type.spec != BarAggregation.MINUTE:
        #     pass
        # select candidate
        self._select_candidate(bar)

    def on_order_initialized(self, event: OrderInitialized) -> None:
        print(event)
        print("here====================")

    def on_position_closed(self, event: PositionClosed) -> None:
        self._intraday_realized_pnl += event.realized_pnl

    def on_stop(self):
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
        self.event_dir.mkdir(parents=True, exist_ok=True)

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

    def _screening(self):
        if self.snapshot_data.empty:
            self._request_intraday_dataframe(snapshot=True)
        mask = self.snapshot_data.eval(self.screening_query)
        self.snapshot_data["screening_result"] = mask
        self._create_and_append_event(
            event_type=EventType.SCREENING,
            payload={
                EventPayloadField.SOURCE: "snapshot_data",
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
                    provider=self,
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
    def _select_candidate(self, bar):
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
                    sm[f.name] = f.value
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

    def _ranking_candidate(self, event):
        records: list = []
        candidate_count = 0

        for can in self.candidate:
            candidate_count += 1
            sigs = self.watch_list.get(can)
            for s in sigs:
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
        self._ranking_metric = ranking_metric
        # insert a trade preparation event
        self.clock.set_time_alert(
            name="trade_preparation",
            alert_time=self.clock.utc_now() + datetime.timedelta(seconds=2),
            callback=self._trade_preparation,
        )

    def _trade_preparation(self, event):
        metric = self._ranking_metric

        if metric is None:
            return
        final_score = metric.final_scores
        if final_score is None:
            return
        # instrument_id, score = next(iter(final_score.items()))
        # order_config_factory = ORDER_CONFIG_FACTOR_REGISTER[
        #     f"{self.config.order_config_factory}"
        # ]
        # order_config_factory = order_config_factory(
        #     instrument_id, callback_provider=self
        # )
        #
        # order_config = order_config_factory.making_order()
        # if self.config.order_type == "bracket":
        #     order = self.order_factory.bracket(**order_config)
        # elif self.config.order_type == "market":
        #     order = self.order_factory.market(**order_config)
        #
        # # self._create_and_append_event(event_type=EventType.MAKING_ORDER)
        #
        # print(order)

    # order / position
    def _pre_order_check(self, order: Order, order_value: float) -> tuple[bool, str]:
        """
        Return the desicion and the reason for why the order placeing attemptation is accepted/refused
        """
        venue = order.instrument_id.venue
        # # check prosition open
        # open_positions = len(self.cache.positions_open())
        # if open_positions >= self.config.trading_rule.open_position_maximum:
        #     return (
        #         False,
        #         f"Size of open positions reach the open position maximum {self.config.trading_rule.open_position_maximum}",
        #     )
        #
        # open_order = self.cache.orders_open()
        # if open_order >= self.config.trading_rule.open_order_maximum:
        #     return (
        #         False,
        #         f"Size of open order reach the open order maximum {self.config.trading_rule.open_order_maximum}",
        #     )
        # # only one open order or position for a instrument id
        # if self.cache.orders_open_count(instrument_id=order.instrument_id) > 0:
        #     return (
        #         False,
        #         f"Open order for the instrument {order.instrument_id} exist.",
        #     )
        # if self.cache.positions_open(instrument_id=order.instrument_id) > 0:
        #     return (
        #         False,
        #         f"Open position for the instrument {order.instrument_id} exist.",
        #     )
        #
        # account = self.portfolio.account(venue)
        # balance = account.balance(self.config.venue_currency_pair[venue])
        # if balance.free.as_double() > order_value:
        #     return (True, "")
        # # might require to implement the logic of comparing which trade is better and change the order
        # elif balance.free.as_double() <= order_value:
        #     return (False, "Not enough balance.")

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
    def get_snapshot_intraday_high(self, instrument_id: str) -> float:
        v = self.snapshot_data.loc[
            self.snapshot_data["instrument_id"] == instrument_id, "intraday_high"
        ].item()
        return v

    def get_snapshot_intraday_low(self, instrument_id: str) -> float:
        v = self.snapshot_data.loc[
            self.snapshot_data["instrument_id"] == instrument_id, "intraday_low"
        ].item()
        return v

    def get_intraday_atr(self, instrument_id: str) -> float:
        v = self.latest_data.loc[
            self.latest_data["instrument_id"] == instrument_id, "intraday_atr"
        ].item()
        return v

    def get_latest_bar_with_trading_bar_type(self, instrument_id: str) -> Bar:
        target_bar_type = self.instrument_bar_type_map.get(instrument_id)[
            self._order_validator.order_rule.trading_bar_type
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

        self.events.append(event)

    def _save_events(self):
        records = []
        for e in self.events:
            te = e.model_dump(mode="python")
            te["payload"] = json.dumps(te["payload"])
            records.append(te)
        df = pd.DataFrame(records)
        date = self.clock.utc_now().date().isoformat()

        df.to_parquet(
            self.event_dir / f"{date}.parquet",
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
        self._current_session_date: datetime.date | None = None
        self._current_session_time: datetime.time | None = None
        self.candidate = set()
        self.screening_query = self._screening_query()
        self.screening_columes = []
        self._latest_data = pd.DataFrame()
        self.latest_data_updated_at = None
        self.snapshot_data = pd.DataFrame()
        self.watch_list: dict[str, list[BaseSignal]] = defaultdict()
        self.events = []
        self._intraday_realized_pnl: float = 0.0
        self._ranking_metric = None

    # request / response method
    def _request_intraday_dataframe(self, snapshot: bool):
        if not snapshot:
            time = self.clock.utc_now().time()
            if (
                self.latest_data_updated_at is None
                or self.latest_data_updated_at < time
            ):
                self.latest_data_updated_at = time
                self.msgbus.send(
                    endpoint=self.config.msg_outbound_endpoint,
                    msg=IntradayDataFrameRequest(snapshot=snapshot),
                )
            elif self.latest_data_updated_at == time:
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
            self.snapshot_data = msg.data
        else:
            self._latest_data = msg.data
