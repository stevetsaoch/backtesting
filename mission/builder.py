from decimal import Decimal

from nautilus_trader.model import Venue, Currency, Money, InstrumentId, BarType
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.model.enums import OmsType, AccountType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from indicator.schemas import (
    IndicatorFieldConfig,
    IndicatorFieldPresetInbound,
    IndicatorMeta,
    IndicatorMetaPresetInbound,
)
from trading_signal.schemas import FactorPresetInbound, FactorConfig
from trading_signal.schemas import (
    FactorRankingConfigs,
    AggregationMethod,
)
from candidate.schemas import (
    FactorRankingPresetInbound,
    PercentileRankingConfig,
    ZScoreRankingConfig,
    RankingPresetInbound,
    RankingConfig,
)
from trading_signal.schemas import SignalMetaPresetInbound, SignalMeta
from trading_rule.schemas import (
    TradingRulePresetInbound,
    TradingRule,
    PortfolioInfo,
    FeeModelInfo,
    OrderRule,
    PositionRule,
    RiskRule,
    SessionRule,
)

from schemas import (
    Operator,
    ManagerConfig,
    ManagerPresetInbound,
    VenuePresetInbound,
    VenueConfig,
    BarPresetInbound,
    CatalogPresetInbound,
    CatalogConfig,
    BacktestingPresetInbound,
    BacktestingConfig,
)
from mission.schemas import MissionInbound, MissionOutbound
from util import load_class_from_path


class MissionBuilder:
    def __init__(self):
        self._indicator_fields: list[IndicatorFieldConfig] = []
        self._indicator_metas: list[IndicatorMeta] = []
        self._trading_signal_factors: list[FactorConfig] = []
        self._trading_signal_metas: list[SignalMeta] = []
        self._trading_rule: TradingRule
        self._managers: ManagerConfig
        self._venue: VenueConfig
        self._catalog: CatalogConfig
        self._backtesting_config: BacktestingConfig

    def build(self, mission_inbound: MissionInbound) -> MissionOutbound:
        for indicator_field_preset in mission_inbound.indicator_field_presets:
            self._indicator_fields.append(
                self._build_indicator_fields(indicator_field_preset)
            )
        for indicator_meta_preset in mission_inbound.indicator_meta_presets:
            self._indicator_metas.append(
                self._build_indicator_meta(indicator_meta_preset)
            )

        for trading_signal_factor in mission_inbound.trading_signal_factor_presets:
            self._trading_signal_factors.append(
                self._build_trading_signal_factor(trading_signal_factor)
            )
        for trading_signal_meta in mission_inbound.trading_signal_meta_presets:
            self._trading_signal_metas.append(
                self._build_trading_signal_meta(trading_signal_meta)
            )
        self._trading_rule = self._build_trading_rule(
            mission_inbound.trading_rule_preset
        )
        self._candidate_ranking_config = self._build_candidate_ranking_config(
            mission_inbound.candidate_ranking_preset
        )
        self._managers = self._build_manager_config(mission_inbound.manager_preset)
        self._venue = self._build_venue_config(mission_inbound.venue_preset)
        self._catalog = self._build_catalog_config(mission_inbound.catalog_preset)
        self._backtesting_config = self._build_backtesting_config(
            mission_inbound.backtesting_preset
        )
        mission_outbound = MissionOutbound(
            name=mission_inbound.name,
            iis=mission_inbound.iis,
            os=mission_inbound.os,
            cycle=mission_inbound.cycle,
            is_finished=mission_inbound.is_finished,
            indicator_fields=self._indicator_fields,
            indicator_metas=self._indicator_metas,
            trading_signal_factors=self._trading_signal_factors,
            trading_signal_metas=self._trading_signal_metas,
            trading_rule=self._trading_rule,
            candidate_ranking_config=self._candidate_ranking_config,
            managers=self._managers,
            venue=self._venue,
            catalog=self._catalog,
            backtesting_config=self._backtesting_config,
        ).model_copy(deep=True)

        self._reset()
        return mission_outbound

    def _build_indicator_fields(
        self, preset: IndicatorFieldPresetInbound
    ) -> IndicatorFieldConfig:
        """
        name: str
        field_name: str
        field_type: str
        depends_on: tuple[str,...]
        bar_spec_requirement: str
        params: dict | None = field(default=None)
        operator: Operator | None = field(default=None)
        threshold: float | None = field(default=None)
        bar_buffer_size: int | None = field(default=None)

        """
        indf = IndicatorFieldConfig(
            name=preset.name,
            field_name=preset.field_name,
            field_type=preset.field_type,
            depends_on=(
                tuple(preset.depends_on) if preset.depends_on is not None else tuple()
            ),
            bar_spec_requirement=preset.bar_spec_requirement,
            params=preset.params,
            operator=(
                Operator(preset.operator) if preset.operator is not None else None
            ),
            threshold=preset.threshold,
            bar_buffer_size=preset.bar_buffer_size,
        )

        return indf

    def _build_indicator_meta(
        self, preset: IndicatorMetaPresetInbound
    ) -> IndicatorMeta:
        """
        name: str
        indicator_name: str
        field_configs: list[IndicatorFieldConfig]

        """
        indm = IndicatorMeta(
            name=preset.name,
            indicator_name=preset.indicator_name,
            field_configs=[
                f for f in self._indicator_fields if f.name in preset.field_configs
            ],
        )
        return indm

    def _build_trading_signal_factor(self, preset: FactorPresetInbound) -> FactorConfig:
        """
        name: str
        operator: Operator
        threshold: float
        bar_spec_requirement: str
        # for ranking,
        ascending: bool
        ranking_config: RankingConfigs
        bar_buffer_size: int

        """
        ranking_preset = FactorRankingPresetInbound(**preset.ranking_config)
        ranking_config = FactorRankingConfigs(
            percentile=PercentileRankingConfig(
                **ranking_preset.percentile.model_dump()
            ),
            zscore=ZScoreRankingConfig(**ranking_preset.zscore.model_dump()),
        )
        factor = FactorConfig(
            name=preset.name,
            operator=Operator(preset.operator),
            threshold=preset.threshold,
            bar_spec_requirement=preset.bar_spec_requirement,
            ascending=preset.ascending,
            ranking_config=ranking_config,
            bar_buffer_size=preset.bar_buffer_size,
        )
        return factor

    def _build_trading_signal_meta(self, preset: SignalMetaPresetInbound) -> SignalMeta:
        """
        name: str
        factor_configs: list[FactorConfig]
        internal_aggregation_method: AggregationMethod
        is_entry_signal: bool
        is_exit_signal: bool
        """
        sigm = SignalMeta(
            name=preset.name,
            factor_configs=[
                fc
                for fc in self._trading_signal_factors
                if fc.name in preset.factor_configs
            ],
            internal_aggregation_method=AggregationMethod(
                preset.internal_aggregation_method
            ),
            is_entry_signal=preset.is_entry_signal,
            is_exit_signal=preset.is_exit_signal,
        )
        return sigm

    def _build_candidate_ranking_config(
        self, preset: RankingPresetInbound
    ) -> RankingConfig:
        rc = RankingConfig(
            ranking_method=preset.ranking_method,
            signal_aggregation_method=AggregationMethod(
                preset.signal_aggregation_method
            ),
        )
        return rc

    def _build_trading_rule(self, preset: TradingRulePresetInbound) -> TradingRule:
        sei = SessionRule(
            market_open_at=preset.market_open_at,
            market_close_at=preset.market_close_at,
            trading_start_at=preset.trading_start_at,
            forced_close_at=preset.forced_close_at,
        )
        fee = FeeModelInfo(
            fee_per_share=Decimal(preset.fee_per_share),
            minimum_fee_per_order=Decimal(preset.minimum_fee_per_order),
            maximum_fee_ratio_per_order=Decimal(preset.maximum_fee_ratio_per_order),
        )
        posir = PositionRule(
            open_position_maximum=Decimal(preset.open_position_maximum)
        )
        pfi = PortfolioInfo(
            venue=Venue(preset.venue),
            currency=Currency.from_str(preset.currency),
            balance=Decimal(preset.balance),
        )
        # risk and order
        tradable_balance_ratio = Decimal(preset.tradable_balance_ratio)
        tradable_balance = pfi.balance * tradable_balance_ratio
        intraday_risk_ratio = Decimal(preset.intraday_risk_ratio)
        intraday_loss_maximum = pfi.balance * intraday_risk_ratio
        # order
        order_value_maximum = tradable_balance / posir.open_position_maximum
        order_size_multiplier_trigger_minimum = intraday_loss_maximum * Decimal(
            preset.order_size_multiplier_trigger_loss_ratio
        )
        odr = OrderRule(
            trading_bar_type=preset.trading_bar_type,
            stop_price_buffer=Decimal(preset.stop_price_buffer),
            order_size_multiplier_ratio=Decimal(preset.order_size_multiplier_ratio),
            order_size_multiplier_trigger_loss_ratio=Decimal(
                preset.order_size_multiplier_trigger_loss_ratio
            ),
            order_value_maximum=order_value_maximum,
            order_size_multiplier_trigger_minimum=order_size_multiplier_trigger_minimum,
        )
        target_profit_minimum = Decimal(preset.target_profit_minimum)
        cost_estimated_per_trade = (
            fee.minimum_fee_per_order
            if (order_value_maximum / target_profit_minimum) * fee.fee_per_share
            < fee.maximum_fee_ratio_per_order * order_value_maximum
            else fee.maximum_fee_ratio_per_order * order_value_maximum
        ) * Decimal(str(2.0))
        cost_ratio_maximum = Decimal(preset.cost_ratio_maximum)
        cost_efficiency_value_minimun = cost_estimated_per_trade / cost_ratio_maximum
        risk_value_ratio_minimum = Decimal(preset.risk_value_ratio_minimum)
        risk_value_minimum = pfi.balance * risk_value_ratio_minimum

        riskr = RiskRule(
            tradable_balance_ratio=tradable_balance_ratio,
            tradable_balance=tradable_balance,
            intraday_risk_ratio=intraday_risk_ratio,
            intraday_loss_maximum=intraday_loss_maximum,
            target_profit_minimum=target_profit_minimum,
            cost_estimated_per_trade=cost_estimated_per_trade,
            cost_ratio_maximum=cost_ratio_maximum,
            cost_efficiency_value_minimum=cost_efficiency_value_minimun,
            risk_value_ratio_minimum=risk_value_ratio_minimum,
            risk_value_minimum=risk_value_minimum,
        )
        return TradingRule(
            portfolio_info=pfi,
            fee_model_info=fee,
            order_rule=odr,
            position_rule=posir,
            risk_rule=riskr,
            session_rule=sei,
        )

    def _build_manager_config(self, preset: ManagerPresetInbound) -> ManagerConfig:
        return ManagerConfig(**preset.model_dump())

    def _build_venue_config(self, preset: VenuePresetInbound) -> VenueConfig:
        fee_model_cls = load_class_from_path(preset.fee_model_path)
        fee_config_cls = load_class_from_path(preset.fee_model_config_path)
        fee_model = fee_model_cls(config=fee_config_cls)

        fill_model = FillModel(
            prob_fill_on_limit=preset.prob_fill_on_limit,
            prob_slippage=preset.prob_fill_on_limit,
            random_seed=preset.random_seed,
        )
        latency_model = (
            LatencyModel(base_latency_nanos=preset.base_latency_nanos)
            if preset.base_latency_nanos is not None
            else None
        )

        return VenueConfig(
            venue=Venue(preset.name),
            oms_type=OmsType[preset.oms_type],
            account_type=AccountType[preset.account_type],
            base_currency=Currency.from_str(preset.base_currency),
            starting_balances=[
                Money(preset.starting_balances, Currency.from_str(preset.base_currency))
            ],
            fill_model=fill_model,
            fee_model=fee_model,
            lantency_model=latency_model,
        )

    def _build_catalog_config(self, preset: CatalogPresetInbound) -> CatalogConfig:
        catalog = ParquetDataCatalog(path=preset.catalog_path)

        catac = CatalogConfig(
            data_start_datetime=preset.data_start_datetime,
            data_end_datetime=preset.data_end_datetime,
            warmup_data_start_datetime=preset.data_start_datetime
            + preset.warmup_data_delta,
            catalog=ParquetDataCatalog(path=preset.catalog_path),
            instrument_ids=[
                f"{symbol}.{str(self._venue.venue)}" for symbol in preset.symbols
            ],
            instruments=catalog.instruments(
                instrument_ids=[
                    f"{symbol}.{str(self._venue.venue)}" for symbol in preset.symbols
                ]
            ),
            bar_types={
                InstrumentId.from_str(f"{symbol}.{str(self._venue.venue)}"): [
                    BarType.from_str(
                        self._to_bar_type_string(
                            bar_preset=bp, symbol=symbol, venue=str(self._venue.venue)
                        )
                    )
                    for bp in preset.bar_presets
                ]
                for symbol in preset.symbols
            },
            bars=catalog.bars(
                bar_types=[
                    self._to_bar_type_string(
                        bar_preset=bp, symbol=symbol, venue=str(self._venue.venue)
                    )
                    for bp in preset.bar_presets
                    for symbol in preset.symbols
                ],
                instrument_ids=[
                    f"{symbol}.{str(self._venue.venue)}" for symbol in preset.symbols
                ],
                start=preset.data_start_datetime,
                end=preset.data_end_datetime,
            ),
        )
        return catac

    def _build_backtesting_config(self, preset: BacktestingPresetInbound):
        return BacktestingConfig(**preset.model_dump())

    def _reset(self):
        self._indicator_fields: list[IndicatorFieldConfig] = []
        self._indicator_metas: list[IndicatorMeta] = []
        self._trading_signal_factors: list[FactorConfig] = []
        self._trading_signal_metas: list[SignalMeta] = []
        self._trading_rule: TradingRule
        self._managers: ManagerConfig
        self._venue: VenueConfig
        self._catalog: CatalogConfig
        self._backtesting_config: BacktestingConfig

    def _to_bar_type_string(
        self, bar_preset: BarPresetInbound, symbol: str, venue: str
    ):
        if bar_preset.l1_type == "trade":
            lt = "LAST"

        if bar_preset.external:
            bt = f"{symbol}.{venue}-{str(bar_preset.external_bar_size)}-{bar_preset.external_bar_unit.upper()}-{lt}-EXTERNAL"
        elif not bar_preset.external:
            bt = f"{symbol}.{venue}-{str(bar_preset.internal_bar_size)}-{bar_preset.internal_bar_unit.upper()}-{lt}-INTERNAL@{str(bar_preset.external_bar_size)}-{bar_preset.external_bar_unit.upper()}-EXTERNAL"

        return bt
