from strategy.intraday import ConsolidationAndBreakout, ConsolidationAndBreakoutConfig

STRATEGY_REGISTRY = {
    "consolidation_and_breakout": ConsolidationAndBreakout,
}
STRATEGY_CONFIG_REGISTRY = {
    "consolidation_and_breakout": ConsolidationAndBreakoutConfig
}
