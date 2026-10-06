import datetime
from pathlib import Path
from preset.repository import PresetRepository
from preset.registry import PresetRegistry
from mission.manager import MissionManager
from mission.builder import MissionConfigBuilder
from runner import BacktestingRunner

preset_registry = PresetRegistry(presets_path=Path("./preset/presets"))
preset_registry.load_all()

file_dir = Path("/Volumes/backtesting_main/record")
preset_repository = PresetRepository(
    root_dir=file_dir, preset_pairs=preset_registry.all()
)
preset_repository.save_presets()

mm = MissionManager(
    builder=MissionConfigBuilder(),
    record_root_dir=file_dir,
    preset_name="consolidation_and_breakout_v1",
    window_size=1,
    window_unit="month",
    is_window_size=3,
    oos_window_size=1,
    cycle=2,
    start_date=datetime.date(2019, 12, 4),
    symbol_file_path=Path("/Volumes/backtesting_main/data/_missions/10_20_1min"),
    symbol_file_name_pattern=" 00:00:00|1|minute|23|day.parquet",
)
mm.build_missions()

runner = BacktestingRunner(
    preset_registry=preset_registry,
    preset_repository=preset_repository,
    mission_manager=mm,
    trader_id="trader-nobody",
    log_level="INFO",
    time_bars_timestamp_on_close=True,
    time_bars_build_with_no_updates=True,
    time_bars_skip_first_non_full_bar=True,
    mission_file_path=Path(
        "/Volumes/backtesting_main/record/consolidation_and_breakout_v1/"
    ),
    actor_name="consolidation_and_breakout",
    strategy_name="consolidation_and_breakout",
)
runner.debug_cycle_run(symbol_size=3, rounds=15)
# runner.debug_run(symbol_size=4, rounds=1)

if __name__ == "__main__":
    # data download

    import duckdb
    import datetime
    from pathlib import Path

    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.enums import DataFeed
    from alpaca.data.timeframe import TimeFrame

    from market_data.data.manager import DataManager
    from market_data.asset.manager import AssetManager
    from util import PydanticModelPandasDataframeTransformer
    from config import MARKET_DATA_CONFIG, ALPACA_CONFIG

    trading_client = TradingClient(
        api_key=ALPACA_CONFIG.api_key, secret_key=ALPACA_CONFIG.secret_key
    )

    asset_file_path = (
        Path(MARKET_DATA_CONFIG.root_directory) / MARKET_DATA_CONFIG.assets_file
    )

    asset_manager = AssetManager(file_path=asset_file_path, client=trading_client)

    symbols = asset_manager.get_symbols(
        exchanges=["NASDAQ", "AMEX", "NYSE"], status=AssetStatus.ACTIVE
    )

    historical_data_client = StockHistoricalDataClient(
        api_key=ALPACA_CONFIG.api_key, secret_key=ALPACA_CONFIG.secret_key
    )

    data_manager = DataManager(
        client=historical_data_client,
        root_directory=MARKET_DATA_CONFIG.root_directory,
        aggregated_data_daily_file_name=MARKET_DATA_CONFIG.aggregated_data_daily_file,
        aggregated_data_monthly_file_name=MARKET_DATA_CONFIG.aggregated_data_monthly_file,
        index_file_name=MARKET_DATA_CONFIG.index_file,
        model_frame_transformer=PydanticModelPandasDataframeTransformer(),
    )
    symbol_downloaded = (
        duckdb.sql(
            """
    select distinct(symbol) from '/Volumes/backtesting_main/data/_index.parquet'
    """
        )
        .df()["symbol"]
        .to_list()
    )
    dbs = set(symbol_downloaded)
    result = [x for x in symbols if x not in dbs]
    for symbol in result:
        data_manager.download_and_save_raw_bars(
            symbol=symbol,
            started_at=datetime.datetime(2016, 1, 1, 0, 0, 0),
            ended_at=datetime.datetime(2026, 9, 2, 0, 0, 0),
            timeframe=TimeFrame.Minute,
            feed=DataFeed.SIP,
        )
