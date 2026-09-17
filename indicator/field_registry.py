from indicator.field import (
    IntradayOpenField,
    IntradayHighField,
    IntradayHighUpdatedAtField,
    IntradayLowField,
    IntradayLowUpdatedAtField,
    IntradayTradingValueField,
    IntradayAmplitudeField,
    IntradayATRField,
)

FIELD_REGISTRY: dict[str, type] = {
    "intraday_open": IntradayOpenField,
    "intraday_high": IntradayHighField,
    "intraday_high_updated_at": IntradayHighUpdatedAtField,
    "intraday_low": IntradayLowField,
    "intraday_low_updated_at": IntradayLowUpdatedAtField,
    "intraday_trading_value": IntradayTradingValueField,
    "intraday_amplitude": IntradayAmplitudeField,
    "intraday_atr": IntradayATRField,
}
