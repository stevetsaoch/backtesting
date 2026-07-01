import time
import datetime
import duckdb
import pandas as pd
from ib_async import IB
from pathlib import Path
from dateutil.relativedelta import relativedelta
from client import IBConnectionPool
from collector import Collector
from util import PacingController
from schemas import (
    ProjectConfig,
    HistoricalBarRequest,
    HistoricalBarTask,
    IBHistoricalBarRequest,
    HistoricalBar,
)


class HistoricalBarTaskManager:
    def __init__(
        self,
        request: HistoricalBarRequest,
        config: ProjectConfig,
        ib_connection_pool: IBConnectionPool,
        pacing_controller: PacingController,
    ):
        self.request = request
        self.config = config
        self.task_file_path = Path(
            f"{self.config.data_dir}{self.request.request_name()}{self.config.task_filetype}"
        )
        self.ib_connection_pool = ib_connection_pool
        self.pacing_controller = pacing_controller
        self.conn: IB | None = None
        self.latest_task: HistoricalBarTask | None = None

    def _normalize_duration_unit(self):
        du: str = ""
        if self.request.duration_unit == "year":
            du = "Y"
        if self.request.duration_unit == "month":
            du = "M"
        if self.request.duration_unit == "week":
            du = "W"
        if self.request.duration_unit == "day":
            du = "D"
        if self.request.duration_unit == "second":
            du = "S"
        return du

    def _normalize_bar_unit(self):
        bs: str = ""
        if self.request.bar_unit == "month":
            bs = "months"
        if self.request.bar_unit == "week":
            bs = "weeks"
        if self.request.bar_unit == "day":
            bs = "day"
        if self.request.bar_unit == "hour":
            bs = "hours"
        if self.request.bar_unit == "minute":
            bs = "mins"
        if self.request.bar_unit == "second":
            bs = "secs"
        return bs

    def _update_latest_task(self, task: HistoricalBarTask):
        self.latest_task = task

    def _retrieve_latest_bar(self, task: HistoricalBarTask) -> HistoricalBar | None:
        file_name = "|".join(
            [
                str(task.symbol),
                str(task.endDateTime),
                str(task.durationStr),
                str(task.barSizeSetting),
            ]
        )
        try:
            df = pd.read_parquet(
                f"{self.config.data_dir}{self.request.symbol}/{file_name}{self.config.data_filetype}"
            )
            idx = df["date"].idxmin()
            return HistoricalBar.model_validate(df.iloc[idx].to_dict())
        except Exception as e:
            return

    def _form_end_datetime_and_duration(self, latest_datetime: datetime.datetime):
        end_datetime = datetime.datetime.combine(
            latest_datetime, datetime.datetime.min.time()
        )
        if (
            self.request.duration_unit == "year"
            and self.request.bar_unit == "minute"
            and self.request.bar_size in [1, 5]
        ):
            duration = "31 D"
        if self.request.duration_unit == "year" and self.request.bar_unit == "day":
            duration = f"{self.request.duration_size} {self._normalize_duration_unit()}"

        return end_datetime, duration

    def _init_task(self, latest_datetime: datetime.datetime):
        end_datetime, duration = self._form_end_datetime_and_duration(latest_datetime)
        t = HistoricalBarTask(
            symbol=self.request.symbol,
            market=self.request.market,
            exchange=self.request.exchange,
            currency=self.request.currency,
            endDateTime=end_datetime,
            durationStr=duration,
            barSizeSetting=f"{self.request.bar_size} {self._normalize_bar_unit()}",
            time_zone=self.request.time_zone,
        )
        return t

    def _decide_next_step(self, latest_task: HistoricalBarTask):
        lt = latest_task
        if lt.done == True:
            # retrieve latest bar
            latest_bar = self._retrieve_latest_bar(lt)
            if latest_bar is None:
                return

            # terminate next request for long period duration
            if (
                self.request.duration_unit == "year"
                and self.request.duration_size >= 10
            ):
                return

            # check wheather data is enough
            if self.request.duration_unit == "year":
                if (
                    self.request.end_datetime
                    - relativedelta(years=self.request.duration_size)
                    <= latest_bar.date
                ):
                    task = self._init_task(latest_bar.date)
                    self._insert_new_task(task)
                    return task
                else:
                    return
        if lt.done == False:
            return lt

    def _insert_new_task(self, task: HistoricalBarTask):
        task_df = pd.DataFrame([task.model_dump()])
        df = self._read_task_file()
        df = pd.concat([df, task_df], ignore_index=True)
        df.to_parquet(self.task_file_path)

    def _update_task_status(self, end_datetime):
        con = duckdb.connect()
        con.execute(
            f"CREATE TABLE t AS SELECT * FROM read_parquet(?)",
            [str(Path(self.task_file_path))],
        )
        con.execute(f"UPDATE t SET done = True WHERE endDatetime='{end_datetime}'")
        con.execute(f"COPY t TO (?) (FORMAT PARQUET)", [str(Path(self.task_file_path))])

    def _save_task_file(self):
        # init first task
        task = self._init_task(self.request.end_datetime)
        df = pd.DataFrame([task.model_dump()])
        df.to_parquet(self.task_file_path)
        return df

    def _read_task_file(self) -> pd.DataFrame:
        df = pd.read_parquet(self.task_file_path)
        return df

    def _save_and_return_task(self):
        # check file exist
        if self.task_file_path.exists():
            tasks = self._read_task_file()
        else:
            # save tasks
            tasks = self._save_task_file()
        return tasks

    def run(self):
        tasks = self._save_and_return_task()
        latest_task = HistoricalBarTask.model_validate(tasks.iloc[-1].to_dict())
        self._update_latest_task(latest_task)

        while (task := self._decide_next_step(self.latest_task)) is not None:
            ib_task = task.to_ib_request()

            # start and run a collector
            while (conn := self.ib_connection_pool.get()) is None:
                time.sleep(1)

            self.conn = conn
            collector = Collector(
                conn=self.conn, task=ib_task, data_dir=self.config.data_dir
            )

            # get pacing permission
            while not self.pacing_controller.acquire():
                time.sleep(0.5)
            result = collector.run()

            # release connection
            self.ib_connection_pool.release(collector.conn)
            self.conn = None

            # update task
            task.done = True
            self._update_task_status(task.endDateTime)
            self._update_latest_task(task)

            if result is None:
                break

        self.stop()

    def stop(self):
        if self.conn is not None:
            self.ib_connection_pool.release(self.conn)
        return


if __name__ == "__main__":
    t = HistoricalBarRequest(
        symbol="AAPL",
        market="stock",
        end_datetime="2026-01-01 00:00:00",
        bar_unit="day",
        bar_size=1,
        duration_unit="year",
        duration_size=10,
        time_zone="America/New_York",
    )
    from config import PROJECT_CONFIG
    from container import IB_CONNECTION_POOL, PACING_CONTROLLER

    htm = HistoricalBarTaskManager(
        request=t,
        config=PROJECT_CONFIG,
        ib_connection_pool=IB_CONNECTION_POOL,
        pacing_controller=PACING_CONTROLLER,
    )
    htm.run()
