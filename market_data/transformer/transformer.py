from pathlib import Path
import pandas as pd
from nautilus_trader.model import BarType
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler


class CatalogDataTransformer:
    def __init__(
        self,
        catalog_path: Path,
    ):
        self._catalog = ParquetDataCatalog(catalog_path)

    def transfer(
        self,
        df: pd.DataFrame,
        bar_type: BarType,
        instrument: Instrument,
    ):
        bars_df = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        bars_df.index = bars_df.index + pd.Timedelta(minutes=1)
        bars_df[["open", "high", "low", "close"]] = bars_df[
            ["open", "high", "low", "close"]
        ].round(2)

        wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)
        bars = wrangler.process(bars_df)

        try:
            self._catalog.write_data([instrument])
            self._catalog.write_data(bars)
        except AssertionError as e:
            print("assert error", e)
