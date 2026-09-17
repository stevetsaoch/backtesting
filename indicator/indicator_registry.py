from indicator.indicator import IntradayShortPeriodIndicator

INDICATOR_REGISTRY: dict[str, type] = {
    "intraday_short_period": IntradayShortPeriodIndicator,
}
