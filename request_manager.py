import time
import threading
import pandas as pd
from pathlib import Path
from client import IBConnectionPool
from task_manager import HistoricalBarTaskManager
from schemas import ProjectConfig, HistoricalBarRequest, IBConnectionInfo


class RequestManager:
    def __init__(
        self,
        project_config: ProjectConfig,
        ib_connection_pool: IBConnectionPool,
        pacing_controller,
        mission_name,
    ):
        self.config = project_config
        self.ib_connection_pool = ib_connection_pool
        self.pacing_controller = pacing_controller
        self.mission_name: str = mission_name
        self.mission_file_path = Path(
            f"{self.config.mission_dir}{self.mission_name}{self.config.mission_filetype}"
        )
        self.symbol_conn_thread_pair: dict[
            str, tuple[threading.Thread, IBConnectionInfo, HistoricalBarTaskManager]
        ] = {}

    def _init_requests(self, requests: list[HistoricalBarRequest]):

        df = pd.DataFrame.from_records((r.model_dump() for r in requests))
        df.to_parquet(self.mission_file_path)
        return df

    def _read_requests(self):
        df = pd.read_parquet(self.mission_file_path)
        return [
            HistoricalBarRequest.model_validate(row) for row in df.to_dict("records")
        ]

    def _check_task_status(self, symbol: str):
        task = self.symbol_conn_thread_pair[symbol][2]
        task_path = task.task_file_path
        df = pd.read_parquet(task_path)
        row = df.loc[df["endDateTime"].idxmax()]  # hard code
        status = row["done"]  # hard code
        return status

    def _update_requests(self, symbol: str):
        df = pd.read_parquet(self.mission_file_path)
        task_status = self._check_task_status(symbol)
        if task_status:
            df.loc[df["symbol"] == symbol, "done"] = True
        else:
            df.loc[df["symbol"] == symbol, "done"] = False

        df.to_parquet(self.mission_file_path)

    def _init_request(self, request: HistoricalBarRequest, conn_info: IBConnectionInfo):
        hbtm = HistoricalBarTaskManager(
            request=request,
            config=self.config,
            ib_connection_info=conn_info,
            pacing_controller=self.pacing_controller,
        )
        return hbtm

    def _release_conn(self):
        dts = []  # dead threads
        for s in self.symbol_conn_thread_pair.keys():
            if not self.symbol_conn_thread_pair[s][0].is_alive():
                dts.append(s)

        for s in dts:
            self.ib_connection_pool.release(self.symbol_conn_thread_pair[s][1])
            self._update_requests(s)
            self.symbol_conn_thread_pair.pop(s)

    def run(self, requests: list[HistoricalBarRequest]):
        if not self.mission_file_path.exists():
            self._init_requests(requests)
        else:
            requests = self._read_requests()

        while requests:
            try:
                r = requests.pop()
            except:
                self.stop()

            if r.done == True:
                continue
            while (conn := self.ib_connection_pool.get()) is None:
                self._release_conn()
                time.sleep(1)

            tm = self._init_request(r, conn)
            t = threading.Thread(target=tm.run, daemon=True)
            t.start()
            self.symbol_conn_thread_pair[r.symbol] = (t, conn, tm)

        self.stop()

    def stop(self):
        for tc in self.symbol_conn_thread_pair.values():
            tc[0].join()
            self.ib_connection_pool.release(tc[1])
        return


if __name__ == "__main__":

    r1 = HistoricalBarRequest(
        symbol="AAPL",
        market="stock",
        end_datetime="2026-01-01 00:00:00",
        bar_unit="day",
        bar_size=1,
        duration_unit="year",
        duration_size=10,
        time_zone="America/New_York",
    )
    r2 = HistoricalBarRequest(
        symbol="MSFT",
        market="stock",
        end_datetime="2026-01-01 00:00:00",
        bar_unit="day",
        bar_size=1,
        duration_unit="year",
        duration_size=10,
        time_zone="America/New_York",
    )

    rl = [r1, r2]
    from config import PROJECT_CONFIG
    from container import IB_CONNECTION_POOL, PACING_CONTROLLER

    rm = RequestManager(
        project_config=PROJECT_CONFIG,
        ib_connection_pool=IB_CONNECTION_POOL,
        pacing_controller=PACING_CONTROLLER,
        mission_name="test_request",
    )
    rm.run(rl)
