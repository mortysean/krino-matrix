from functools import cached_property
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..data_source import Query, NoParams
from .client import SagaxData
from .common import shift, today, records


class SeriesParams(BaseModel):
    ids: list[str] = Field(
        min_length=1, max_length=10, description='Indicator ids from list_macro_indicators, e.g. ["CPI_YOY", "PMI_MFG"]'
    )
    years: int = Field(3, ge=1, le=20, description="Years of history")


class MacroQueries:
    """China macro indicators: GDP, prices, PMI, money supply, rates, bond yields and trade."""

    def __init__(
        self,
        client: SagaxData
    ):
        self.client = client

    def queries(self) -> list[Query]:
        return [
            Query(
                name="list_macro_indicators",
                description="List the macro indicators (GDP, CPI, PPI, PMI, money supply, social financing, "
                            "LPR, SHIBOR, bond yields, FX, output, investment, retail, trade) with their ids.",
                params=NoParams,
                run=lambda _: self.list_macro_indicators(),
            ),
            Query(
                name="macro_series",
                description="History of macro indicators with their latest value. Daily series are "
                            "reduced to month-end values.",
                params=SeriesParams,
                run=self.macro_series,
            ),
        ]

    def list_macro_indicators(self) -> dict[str, Any]:
        df = self._indicators[["indicator_id", "name_zh", "freq", "unit"]]
        return {"freq": "D daily, M monthly, Q quarterly", "indicators": records(df)}

    def macro_series(
        self,
        params: SeriesParams
    ) -> dict[str, Any]:
        known = self._indicators.set_index("indicator_id")
        unknown = [i for i in params.ids if i not in known.index]
        if unknown:
            raise ValueError(f"Unknown indicators {unknown}; ids come from list_macro_indicators")

        start = shift(today(), -params.years * 365)
        df = self.client.edb(params.ids, start=start)
        series = []
        for id in params.ids:
            info = known.loc[id]
            values = df[id].dropna() if id in df else pd.Series(dtype=float)
            # Dates are "YYYYMMDD", "YYYYMM" or "YYYYQn" by frequency; keep those since start
            values = values[[_since(date, start) for date in values.index]]
            if info["freq"] == "D":
                values = values.groupby(values.index.str[:6]).last()
            series.append({
                "id": id,
                "name": info["name_zh"],
                "unit": info["unit"] or None,
                "freq": info["freq"],
                "latest": {"date": values.index[-1], "value": round(float(values.iloc[-1]), 4)} if len(values) else None,
                "values": {date: round(float(v), 4) for date, v in values.items()},
            })
        return {"series": series}

    @cached_property
    def _indicators(self) -> pd.DataFrame:
        return self.client.table("edb_indicator", limit=1_000)


def _since(
    date: str,
    start: str
) -> bool:
    if "Q" in date:
        year, quarter = date.split("Q")
        return f"{year}{int(quarter) * 3:02d}" >= start[:6]
    return date >= start[:len(date)]
