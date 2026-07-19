import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta
from container import IB_CONNECTION_POOL, PACING_CONTROLLER
from config import PROJECT_CONFIG
from request_manager import RequestManager
from schemas import HistoricalBarRequest
from util import find_files

files = find_files(
    PROJECT_CONFIG.universal_equity_dir,
    pattern=r".*(\|taal\|8M\|tart\|0\.5\|aul\|50\|all\|40\|art\|0\.8\.parquet)",
)

for f in files:
    file_date = datetime.datetime.strptime(f.split("/")[-1].split("|")[0], "%Y-%m-%d")
    end_datetime = file_date + relativedelta(months=1)
    market = "stock"
    bar_unit = "minute"
    bar_size = 1
    duration_unit = "day"
    duration_size = 25
    time_zone = "America/New_York"
    mission_name = "|".join(
        [
            str(file_date),
            str(bar_size),
            str(bar_unit),
            str(duration_size),
            str(duration_unit),
        ]
    )
    requests = []
    symbols = pd.read_parquet(f)
    for s in symbols.itertuples():
        r = HistoricalBarRequest(
            symbol=s.symbol,
            market=market,
            end_datetime=end_datetime,
            bar_unit=bar_unit,
            bar_size=bar_size,
            duration_unit=duration_unit,
            duration_size=duration_size,
            time_zone=time_zone,
        )
        requests.append(r)
    rm = RequestManager(
        project_config=PROJECT_CONFIG,
        ib_connection_pool=IB_CONNECTION_POOL,
        pacing_controller=PACING_CONTROLLER,
        mission_name=mission_name,
    )
    print(f"{mission_name} start running.")
    rm.run(requests)
