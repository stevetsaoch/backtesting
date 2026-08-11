import os
import pandas as pd
from ib_async import IB, util, BarDataList
from schemas import IBHistoricalBarRequest, IBConnectionInfo


class Collector:
    def __init__(
        self, conn_info: IBConnectionInfo, task: IBHistoricalBarRequest, data_dir: str
    ):
        self.task = task
        self.data_filetype = ".parquet"
        self.file_name = "|".join(
            [
                str(self.task.contract.symbol),
                str(self.task.endDateTime.replace(tzinfo=None)),
                str(self.task.durationStr),
                str(self.task.barSizeSetting),
            ]
        )
        self.data_dir = f"{data_dir}/{self.task.contract.symbol}/"
        self.done = False
        self.conn_info = conn_info
        self.data = []

    def _setup_connection(self) -> IB:
        ib = IB()
        conn = ib.connect(
            host=self.conn_info.host,
            port=self.conn_info.port,
            clientId=self.conn_info.client_id,
            timeout=self.conn_info.timeout,
            readonly=self.conn_info.readonly,
        )
        return conn

    def _mkdir(self):
        if os.path.exists(self.data_dir):
            pass
        else:
            os.mkdir(self.data_dir)

    def _save_data(self, bar_data: BarDataList):
        df = util.df(bar_data)
        if pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = df["date"].dt.tz_localize(None)
        self._mkdir()
        df.to_parquet(f"{self.data_dir}{self.file_name}{self.data_filetype}")

    def run(self):
        conn = self._setup_connection()
        try:
            data = conn.reqHistoricalData(
                contract=self.task.contract,
                endDateTime=self.task.endDateTime,
                durationStr=self.task.durationStr,
                barSizeSetting=self.task.barSizeSetting,
                whatToShow=self.task.whatToShow,
                useRTH=self.task.useRTH,
            )
            self._save_data(data)
            self.done = True
            # return latest row
            return data[0]
        except Exception as e:
            return
        finally:
            conn.disconnect()
