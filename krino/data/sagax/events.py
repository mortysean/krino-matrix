from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..data_source import Query
from .client import SagaxData
from .common import shift, today, truncate, records

Report = Literal[
    "block_trade", "dividend", "express", "forecast", "holder_number",
    "holder_trade", "hsgt", "limit_list", "share_float", "suspend",
]


@dataclass(frozen=True)
class Spec:
    date: str                       # column the lookback applies to and results are sorted by
    pad: int | None = 0             # days the server-side start is moved back; None when its date filter is broken
    needs_codes: bool = False
    future: bool = False            # also keep upcoming dates


# Server-side date filters of dividend / express / forecast / holder_number apply to the report period
# (end_date), not to the announcement date, so they are queried with a wide margin and filtered here
SPECS: dict[str, Spec] = {
    "block_trade": Spec("trade_date"),
    "dividend": Spec("ann_date", pad=500),
    "express": Spec("ann_date", pad=500),
    "forecast": Spec("ann_date", pad=500),
    "holder_number": Spec("ann_date", pad=500),
    "holder_trade": Spec("ann_date"),
    "hsgt": Spec("trade_date"),
    "limit_list": Spec("trade_date"),
    "share_float": Spec("float_date", pad=None, needs_codes=True, future=True),
    "suspend": Spec("trade_date"),
}


class ReportParams(BaseModel):
    report: Report = Field(
        description="block_trade: block trades (大宗交易); dividend: dividend plans and dates; "
                    "express: preliminary earnings (业绩快报); forecast: earnings forecasts (业绩预告); "
                    "holder_number: number of shareholders; holder_trade: major shareholders buying (IN) or "
                    "selling (DE); hsgt: daily Stock Connect flows, in million CNY, codes ignored; "
                    "limit_list: stocks hitting limit up (U), limit down (D) or opening a limit (Z); "
                    "share_float: lock-up expiries, codes required, upcoming ones included; suspend: trading suspensions"
    )
    codes: list[str] | None = Field(None, max_length=20, description="Stock codes; null for the whole market")
    days: int = Field(30, ge=1, le=1000, description="Look back this many calendar days")
    limit: int = Field(30, ge=1, le=100, description="Number of rows to return, newest first")


class EventQueries:
    """Special reports: corporate events, shareholder changes, limit moves and Stock Connect flows."""

    def __init__(
        self,
        client: SagaxData
    ):
        self.client = client

    def queries(self) -> list[Query]:
        return [
            Query(
                name="special_report",
                description="Corporate events and market reports: block trades, dividends, earnings forecasts "
                            "and preliminary results, shareholder counts and trades, lock-up expiries, "
                            "limit-up/down lists, suspensions and Stock Connect flows.",
                params=ReportParams,
                run=self.special_report,
            ),
        ]

    def special_report(
        self,
        params: ReportParams
    ) -> dict[str, Any]:
        spec = SPECS[params.report]
        codes = params.codes if params.report != "hsgt" else None
        if spec.needs_codes and not codes:
            raise ValueError(f"{params.report} needs codes")

        start = shift(today(), -params.days)
        server_start = shift(start, -spec.pad) if spec.pad is not None else None
        df = self.client.table(f"ctr_{params.report}", codes=codes, start=server_start, limit=100_000)
        if df.empty:
            return {"report": params.report, "since": start, "matched": 0, "rows": []}

        df = df[df[spec.date].astype(str) >= start]
        if not spec.future:
            df = df[df[spec.date].astype(str) <= today()]
        df = df.sort_values(spec.date, ascending=False)
        df = truncate(df, ["summary", "change_reason", "perf_summary"])
        return {
            "report": params.report,
            "since": start,
            "matched": len(df),
            "rows": records(df.head(params.limit)),
        }
