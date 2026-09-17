import duckdb
import pandas as pd
from nautilus_trader.model import BarType, Bar
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.wranglers import BarDataWrangler
from schemas import (
    NautilusEquityTask,
    ProjectConfig,
    NautilusConfig,
    NautilusBarType,
    NautilusInstrumentId,
)


class DataTransformer:
    """
    Raw data to Nastilus Trader catalog
    """

    def __init__(
        self,
        tasks: list[NautilusEquityTask],
        project_config: ProjectConfig,
        nautilus_config: NautilusConfig,
        bar_type: NautilusBarType,
        mission_name: str,
    ) -> None:
        self.tasks = tasks
        self.project_config = project_config
        self.nautilus_config = nautilus_config
        self.bar_type = bar_type
        self.mission_name = mission_name
        self.mission_path = f"{self.project_config.catalog_mission_dir}{self.mission_name}{self.project_config.catalog_mission_filetype}"
        self.last_task_interval: tuple

    def _init_mission(self):
        df = pd.DataFrame([f.model_dump() for f in self.tasks])
        df["done"] = False
        df.to_parquet(self.mission_path)
        return self.tasks

    def _update_mission(self, symbol: str):
        df = pd.read_parquet(self.mission_path)
        df.loc[df["symbol"] == symbol, "done"] = True
        df.to_parquet(self.mission_path)

    def _read_mission(self):
        try:
            df = duckdb.sql(
                """
                SELECT * FROM read_parquet(?);
            """,
                params=[self.mission_path],
            ).df()

            ld = df.to_dict("records")
            tasks = [NautilusEquityTask(**t) for t in ld]
            return tasks
        except Exception as e:
            return

    def _read_raw_data(self, raw_data_path) -> pd.DataFrame:
        df = duckdb.sql(
            """
            SELECT * FROM read_parquet(?);
            """,
            params=[raw_data_path],
        ).df()

        if df.empty:
            return pd.DataFrame()
        else:
            return df

    def _split_data_by_month(self, df: pd.DataFrame):
        # hard code
        df = df.rename(columns={"date": "timestamp"})  # hard code
        df = df.rename(columns=str.lower)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
        # 1 minute shift because the data from ib is bar start time
        df["timestamp"] = df["timestamp"] + pd.Timedelta(minutes=1)
        df = df.set_index("timestamp")
        ym_list = df.index.strftime("%Y-%m").unique().tolist()
        data_sets = []
        for ym in ym_list:
            ds = df.loc[ym]
            data_sets.append(ds)

        return data_sets

    def _normalize_timestamp(self, df: pd.DataFrame):
        df = df.rename(columns={"date": "timestamp"})  # hard code
        df = df.rename(columns=str.lower)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"])
        df = df.set_index("timestamp")
        return [df]

    def _check_exist_bars_quantity(
        self,
        catalog: ParquetDataCatalog,
        bar_types: list[BarType],
        instrument_ids: list[InstrumentId],
        start: pd.Timestamp,
    ):
        first_day = start.replace(day=1).normalize().replace(hour=0, minute=0, second=0)
        last_day = (
            start.replace(day=start.days_in_month)
            .normalize()
            .replace(hour=23, minute=59, second=59)
        )
        existing_bars = catalog.bars(
            bar_types=bar_types,
            instrument_ids=instrument_ids,
            start=first_day,
            end=last_day,
        )
        return len(existing_bars)

    def _delete_exist_data(
        self,
        catalog: ParquetDataCatalog,
        data_cls,
        identifier: str,
        start: pd.Timestamp,
    ):
        first_day = start.replace(day=1).normalize().replace(hour=0, minute=0, second=0)
        last_day = (
            start.replace(day=start.days_in_month)
            .normalize()
            .replace(hour=23, minute=59, second=59)
        )
        catalog.delete_data_range(
            data_cls=data_cls,
            identifier=identifier,
            start=first_day,
            end=last_day,
        )

    def _raw_to_bar_data(self, df: pd.DataFrame):
        pass

    def run(self):
        if (tasks := self._read_mission()) is None:
            tasks = self._init_mission()
        else:
            pass
        catalog = ParquetDataCatalog(self.nautilus_config.catalog_path)

        for t in tasks:
            if t.done == True:
                pass
            else:
                eq = t.to_equity()
                catalog.write_data([eq])
                data = self._read_raw_data(t.raw_data_path)

                if self.bar_type.external_bar_unit == "minute":
                    data_sets = self._split_data_by_month(data)
                if self.bar_type.external_bar_unit == "day":
                    data_sets = self._normalize_timestamp(data)

                for ds in data_sets:
                    # remove timezone
                    tz_cols = ds.select_dtypes(include=["datetimetz"]).columns
                    if not tz_cols.empty:
                        for col in tz_cols:
                            ds[col] = ds[col].dt.tz_localize(None)

                    bar_type = BarType.from_str(self.bar_type.to_bar_type())
                    wrangler = BarDataWrangler(bar_type=bar_type, instrument=eq)
                    if self.bar_type.external_bar_unit == "minute":
                        bars = wrangler.process(
                            data=ds,
                        )  # hard code, move ts_event to close
                    if self.bar_type.external_bar_unit == "day":
                        ds.index = ds.index + pd.Timedelta(hours=16, minutes=1)
                        bars = wrangler.process(
                            data=ds,
                        )  # hard code, move ts_event to close
                    # non-disjoin error could be currently bypassed by this way because of data is collected monthly
                    # improvement may required in the future
                    exist_bars_quantity = self._check_exist_bars_quantity(
                        catalog=catalog,
                        bar_types=[bar_type],
                        instrument_ids=[f"{t.symbol}.{t.venue}"],
                        start=ds.index.min(),
                    )
                    try:
                        if len(ds) > exist_bars_quantity:
                            self._delete_exist_data(
                                catalog=catalog,
                                data_cls=Bar,
                                identifier=self.bar_type.to_bar_type(),
                                start=ds.index.min(),
                            )

                            catalog.write_data(bars)
                        else:
                            pass
                    except Exception as e:
                        raise e
                self._update_mission(t.symbol)


if __name__ == "__main__":
    from config import PROJECT_CONFIG, NAUTILUS_CONFIG
    from util import find_files
    from pathlib import Path, PosixPath

    root = Path("/Volumes/backtesting_main/data/")
    folders = [p for p in root.iterdir() if p.is_dir()]
    for fo in folders:
        symbol = str(fo).split("/")[-1]
        venue = "SIM"
        currency = "USD"
        price_precision = 2
        price_increment = 0.01
        lot_size = 1
        ts_event = 0
        ts_init = 0
        el = []
        bt = NautilusBarType(
            instrument=NautilusInstrumentId(symbol=symbol, venue=venue),
            external_bar_unit="minute",
            external_bar_size=1,
            l1_type="trade",
            external=True,
        )
        files = find_files(
            str(fo),
            pattern=r"^.*\|(?:23|25) D\|1 min\.parquet$",
        )
        for f in files:
            e = NautilusEquityTask(
                raw_data_path=f,
                catalog_path=NAUTILUS_CONFIG.catalog_path,
                symbol=symbol,
                venue=venue,
                currency=currency,
                price_precision=price_precision,
                price_increment=price_increment,
                lot_size=lot_size,
                ts_event=ts_event,
                ts_init=ts_init,
            )
            el.append(e)
        dtrans = DataTransformer(
            tasks=el,
            project_config=PROJECT_CONFIG,
            nautilus_config=NAUTILUS_CONFIG,
            bar_type=bt,
            mission_name=symbol,
        )
        dtrans.run()
