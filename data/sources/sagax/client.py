import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import pandas as pd
import sagax_data
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class SagaxData(sagax_data.Client):
    """sagax data platform, docs at https://www.sagax.cn/data/v1/ (tables, indicators, examples).

    Same interface as sagax_data.Client; dates are "YYYYMMDD" strings, codes like "510300.SH",
    codes and indicators accept a list or a comma-separated string:
      csd(codes, indicators, start, end)          time series, index=date, columns=(code, indicator)
      css(codes, indicators, date)                cross section, index=code, columns=indicator (financials PIT)
      table(name, codes, start, end, limit)       any table by name, newest rows first
      edb(ids, start, end)                        macro, index=date, columns=indicator_id
      ctr(report, start, end, codes)              special reports
      info(codes, start, end, limit)              news
      indicators()                                indicator dictionary: indicator / table / column / asset / zh
    Added here:
      sector(id, date)                            SW sector list, or one sector's members on a date
      table_batched(name, codes, ...)             table() for many codes, split to keep URLs short
      latest(name, codes, axis)                   latest value of a table's date axis
    """

    @classmethod
    def from_env(cls) -> "SagaxData":
        """Read SAGAX_API_KEY / SAGAX_SECRET_KEY / SAGAX_BASE_URL."""
        api_key, secret_key = os.getenv("SAGAX_API_KEY"), os.getenv("SAGAX_SECRET_KEY")
        if not api_key or not secret_key:
            raise KeyError("SAGAX_API_KEY / SAGAX_SECRET_KEY are not set in .env")
        return cls(api_key, secret_key, os.getenv("SAGAX_BASE_URL") or sagax_data.DEFAULT_BASE_URL)

    def table(
        self,
        name: str,
        codes: str | list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10_000,
        full: bool = False
    ) -> pd.DataFrame:
        df = super().table(name, codes, start, end, limit, full)
        # Rows come newest first, so a full page means the oldest rows were cut off
        if len(df) >= limit:
            warnings.warn(
                f"table({name!r}) returned {len(df)} rows, hitting limit={limit}; "
                "older rows may be missing, narrow start/end or raise limit",
                stacklevel=2,
            )
        return df

    def sector(
        self,
        id: str | None = None,
        date: str | None = None
    ) -> pd.DataFrame:
        """Without id, every sector with its level and member count; with id, its members on date (PIT)."""
        body = self._get("sector", {"id": id, "date": date})
        return pd.DataFrame(body["rows"] if id else body["sectors"])

    def table_batched(
        self,
        name: str,
        codes: list[str],
        start: str | None = None,
        end: str | None = None,
        max_chars: int = 3000,
        max_workers: int = 8
    ) -> pd.DataFrame:
        """table() over many codes, split into batches since too long a code list fails (HTTP 400/414)."""
        batches, batch, size = [], [], 0
        for code in codes:
            if batch and size + len(code) + 1 > max_chars:
                batches.append(batch)
                batch, size = [], 0
            batch.append(code)
            size += len(code) + 1
        if batch:
            batches.append(batch)
        with ThreadPoolExecutor(max_workers) as pool:
            parts = list(pool.map(lambda b: self.table(name, b, start, end, limit=100_000), batches))
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    def latest(
        self,
        name: str,
        codes: str | list[str] | None = None,
        axis: str = "trade_date",
        lookback_days: int = 30
    ) -> str:
        """Latest value of the table's date axis within the lookback, e.g. its latest trading day."""
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        # Rows come newest first, so one row is enough; skips the limit warning of table()
        df = super().table(name, codes, start, None, 1)
        if df.empty:
            raise LookupError(f"{name} has no rows in the last {lookback_days} days")
        return df[axis].iloc[0]


@cache
def sagax() -> SagaxData:
    """Shared client built from .env."""
    return SagaxData.from_env()
