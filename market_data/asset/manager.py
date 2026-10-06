import datetime
import pandas as pd
from typing import Union
from pathlib import Path
from pydantic import BaseModel

from alpaca.common import RawData
from alpaca.trading.models import Asset
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from market_data.schemas import AssetFields


class AssetManager(BaseModel):
    def __init__(self, file_path: Path, client: TradingClient):
        self._client: TradingClient = client
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._key = "id"
        self._tracked = [
            "symbol",
            "name",
            "exchange",
            "asset_class",
            "status",
        ]
        self._ts_cols = ["created_at", "edited_at"]

    def get_symbols(self, exchanges: list[str], status: AssetStatus):
        file = pd.read_parquet(self._file_path)
        mask = (file["exchange"].isin(exchanges)) & (file["status"] == status)
        results = file[mask]
        return list(results["symbol"])

    def initialize(self, asset_class: AssetClass):
        if self._file_path.exists():
            print("file exists, start updating")
            for status in AssetStatus:
                self.update(asset_class=asset_class, status=status)

        assets = []
        for status in AssetStatus:
            _assets = self._download_asset(asset_class=asset_class, status=status)
            assets += _assets

        record = [
            AssetFields.model_validate(r.model_dump()).model_dump() for r in assets
        ]
        pd.DataFrame(record).to_parquet(
            path=self._file_path,
            engine="pyarrow",
            compression="snappy",
            index=False,
        )

    def _utc_now(self) -> datetime.datetime:
        return datetime.datetime.now()

    def _normalize_ts(self, df: pd.DataFrame) -> pd.DataFrame:
        """All-NaT columns come back tz-naive; force UTC so tz-aware assignment works."""
        df = df.copy()
        for c in self._ts_cols:
            df[c] = pd.to_datetime(df[c]).dt.as_unit("us")
        return df

    def update(self, asset_class: AssetClass, status: AssetStatus):
        cur_records = pd.read_parquet(self._file_path)
        d_records = self._download_asset(asset_class=asset_class, status=status)
        now = pd.Timestamp(self._utc_now())
        cur = self._normalize_ts(cur_records).set_index(self._key)
        new = (
            pd.DataFrame(
                [
                    dr.model_dump(include={self._key, *self._tracked}, mode="json")
                    for dr in d_records
                ]
            )
            .drop_duplicates(self._key, keep="last")
            .set_index(self._key)
        )

        common = new.index.intersection(cur.index)
        a, b = cur.loc[common, self._tracked], new.loc[common, self._tracked]
        diff = (a != b) & ~(a.isna() & b.isna())
        changed = diff.index[diff.any(axis=1)]
        cur.loc[changed, self._tracked] = b.loc[changed]
        cur.loc[changed, "edited_at"] = now

        added = new.loc[new.index.difference(cur.index)].assign(
            created_at=now, edited_at=pd.NaT
        )
        out = pd.concat([cur, added]).reset_index()
        for c in self._ts_cols:
            out[c] = pd.to_datetime(out[c]).dt.as_unit("us")
        out.to_parquet(self._file_path)

    def _download_asset(
        self, asset_class: AssetClass, status: AssetStatus
    ) -> Union[list[Asset], RawData]:
        assets = self._client.get_all_assets(
            GetAssetsRequest(
                asset_class=asset_class,
                status=status,
            )
        )
        return assets
