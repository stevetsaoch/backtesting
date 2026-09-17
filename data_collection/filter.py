import os
import re
import datetime
import pandas as pd
import duckdb
from pathlib import Path
from schemas import ProjectConfig, UniversalStockPoolCondition


class UniverseStockPoolFilter:
    """
    Return the stock pool according to conditions.
    """

    def __init__(
        self,
        project_config: ProjectConfig,
        condition: UniversalStockPoolCondition,
        file_name_pattern: str,
    ):
        self.project_config = project_config
        self.condition = condition
        self.file_name_pattern = file_name_pattern

    def _read_index_file(self) -> pd.DataFrame:
        pool = duckdb.sql(
            f"""
            SELECT * FROM read_parquet("{self.project_config.index_path}");
            """
        ).df()
        return pool

    def _filter(
        self,
        file_path: Path,
    ):
        # hard code
        query = f"""
        WITH filtered AS (
            SELECT *,
            average * volume as total_amount
            FROM read_parquet('{file_path}')
            WHERE date >= '{self.condition.start_date}' AND date < '{self.condition.end_date}'
        ),
        metrics AS (
            SELECT
            COUNT(*) FILTER (WHERE average >= {self.condition.average_lower_limit} AND average <= {self.condition.average_upper_limit}) * 1.0 / NULLIF(COUNT(*), 0) AS pct_average_in_range,
            COUNT(*) FILTER (WHERE total_amount >= {self.condition.total_amount_average_lower_limit} AND total_amount <= {self.condition.total_amount_average_upper_limit}) * 1.0 / NULLIF(COUNT(*), 0) AS pct_total_amount_in_range
        FROM filtered
        )
        SELECT * FROM metrics
        WHERE pct_average_in_range >= {self.condition.average_ratio_threshold}
        AND pct_total_amount_in_range >= {self.condition.total_amount_ratio_threshold}
        """
        tmp = duckdb.sql(query)
        return tmp

    def _dfs_find_files(self, root_dir):
        regex = re.compile(self.file_name_pattern)
        result = []
        stack = [root_dir]

        while stack:
            current_dir = stack.pop()
            try:
                entries = os.listdir(current_dir)
            except PermissionError:
                continue
            except FileNotFoundError as e:
                continue

            for entry in entries:
                full_path = os.path.join(current_dir, entry)

                if os.path.isdir(full_path):
                    stack.append(full_path)
                elif os.path.isfile(full_path):
                    if regex.search(entry):
                        result.append(full_path)

        return result

    def run(self):
        symbols = self._read_index_file()
        target = []
        for s in symbols.itertuples():
            dir = s.dir
            files = self._dfs_find_files(dir)
            if files:
                for f in files:
                    r = self._filter(f).fetchone()
                    pct_avg = None
                    pct_amount = None
                    if r:
                        pct_avg = r[0]
                        pct_amount = r[1]
                        pass
                    else:
                        pass
                    tmp = {
                        "symbol": s.symbol,
                        "pct_avg": pct_avg,
                        "pct_amount": pct_amount,
                    }
                    target.append(tmp)
        target = pd.DataFrame(target)
        return target


if __name__ == "__main__":
    from config import PROJECT_CONFIG
    from schemas import UniversalStockPoolCondition
    from dateutil.relativedelta import relativedelta

    ref_period = 6
    final_date = datetime.date(2026, 1, 1)
    start_date = datetime.date(2019, 6, 1)
    end_date = start_date + relativedelta(months=ref_period)
    total_amount_average_upper_limit = 10000000000.0
    total_amount_average_lower_limit = 8000000.0
    total_amount_ratio_threshold = 0.5
    average_upper_limit = 50.0
    average_lower_limit = 40.0
    average_ratio_threshold = 0.8

    while end_date <= final_date:
        ufs = UniversalStockPoolCondition(
            start_date=start_date,
            end_date=end_date,
            total_amount_average_upper_limit=total_amount_average_upper_limit,
            total_amount_average_lower_limit=total_amount_average_lower_limit,
            total_amount_ratio_threshold=total_amount_ratio_threshold,
            average_upper_limit=average_upper_limit,
            average_lower_limit=average_lower_limit,
            average_ratio_threshold=average_ratio_threshold,
        )
        uf = UniverseStockPoolFilter(
            project_config=PROJECT_CONFIG,
            condition=ufs,
            file_name_pattern=r".*(\|20 Y\|1 day\.parquet)",
        )
        df = uf.run()
        df = df.dropna(subset=["pct_avg", "pct_amount"])
        file_name = PROJECT_CONFIG.universal_equity_dir + ufs.to_name() + ".parquet"
        df.to_parquet(file_name, index=False)
        print(file_name)
        start_date = start_date + relativedelta(months=1)
        end_date = end_date + relativedelta(months=1)
