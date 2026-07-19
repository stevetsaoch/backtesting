import duckdb
import datetime
from nautilus_trader.model.data import Bar
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId, BarType
from nautilus_trader.backtest.config import BacktestDataConfig


class BatchDataConfig:
    """
    Return backtest data configs.
    """

    def __init__(
        self,
        stock_pool_path: str,
        venue: str,
        catalog_path: str,
        data_cls: str,
        start_time: datetime.datetime,
        end_time: datetime.datetime,
    ):
        self.stock_pool_path = stock_pool_path
        self.venue = venue
        self.catalog_path = catalog_path
        self.symbol_list = self._get_symbols()
        self.data_cls = Bar if data_cls == "bar" else None
        self.start_time = start_time
        self.end_time = end_time

    def _get_symbols(self):
        # hard code
        return (
            duckdb.sql(
                """
        SELECT symbol FROM read_parquet(?);
        """,
                params=[self.stock_pool_path],
            )
            .to_arrow_table()
            .column(0)
            .to_pylist()
        )

    def _init_configs(self):
        if self.data_cls is None:
            raise Exception
        bds = []
        for s in self.symbol_list:
            instrument_id = f"{s}.{self.venue}"
            bd = BacktestDataConfig(
                catalog_path=self.catalog_path,
                data_cls=self.data_cls,
                instrument_id=instrument_id,
                start_time=self.start_time,
                end_time=self.end_time,
            )
            bds.append(bd)
        return bds

    def run(self):
        return self._init_configs()


class BatchStrategyConfig:

    instrument_id: InstrumentId
    bar_type: BarType

    def __init__(self):
        pass

    def run(self):
        pass


if __name__ == "__main__":
    catalog_path = "/Volumes/backtesting_main/catalog/"
    path = "/Volumes/backtesting_main/data/_universal_equity/10_20_1min/2019-12-01|taal|4M|tart|0.8|aul|20|all|10|art|0.8.parquet"

    bdf = BatchDataConfig(
        stock_pool_path=path,
        catalog_path=catalog_path,
        venue="SIM",
        data_cls="bar",
        start_time=datetime.datetime(2019, 12, 1, 0, 0, 0),
        end_time=datetime.datetime(2020, 1, 1, 0, 0, 0),
    )

    print(bdf._init_configs())
