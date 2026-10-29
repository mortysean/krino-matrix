from functools import cached_property
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..data_source import Query, NoParams
from .client import SagaxData
from .common import shift, today, calendar_days, price_stats, records

Market = Literal["主板", "创业板", "科创板", "北交所"]
SortKey = Literal["total_mv", "dv_ttm", "roe", "pe_ttm", "pb", "netprofit_yoy"]
Codes = Field(min_length=1, max_length=10, description='Stock codes, e.g. ["600900.SH", "000333.SZ"]')


class ScreenParams(BaseModel):
    markets: list[Market] = Field(
        default=["主板", "创业板"],
        description="Boards to include; leave out boards the investor has no permission to trade",
    )
    exclude_st: bool = Field(True, description="Exclude ST and *ST stocks")
    min_listed_years: float = Field(0, description="Exclude stocks listed for less than this many years")
    industries: list[str] | None = Field(
        None, description="Industry names exactly as returned by list_industries; null for all industries"
    )
    min_total_mv: float | None = Field(None, description="Minimum total market value, in 100 million CNY (亿元)")
    max_pe_ttm: float | None = Field(None, description="Maximum PE (TTM); loss-making stocks are excluded when set")
    max_pb: float | None = Field(None, description="Maximum PB")
    min_dv_ttm: float | None = Field(None, description="Minimum dividend yield (TTM), %")
    min_roe: float | None = Field(None, description="Minimum annualized ROE of the latest report, %")
    max_debt_to_assets: float | None = Field(None, description="Maximum debt-to-assets ratio, %")
    min_netprofit_yoy: float | None = Field(None, description="Minimum net profit growth year over year, %")
    sort_by: SortKey = "total_mv"
    descending: bool = True
    limit: int = Field(20, ge=1, le=50, description="Number of stocks to return")


class DetailParams(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=20, description='Stock codes, e.g. ["600900.SH", "000333.SZ"]')


class ValuationParams(BaseModel):
    codes: list[str] = Codes
    years: int = Field(5, ge=1, le=15, description="Years of history to compare the current valuation with")


class FlowParams(BaseModel):
    codes: list[str] = Codes
    days: int = Field(20, ge=1, le=250, description="Number of recent trading days to sum over")


class StatementParams(BaseModel):
    code: str = Field(description='One stock code, e.g. "600519.SH"')
    statement: Literal["income", "balance", "cashflow", "indicator"] = Field(
        description="income statement, balance sheet, cash flow statement, or financial indicators (ratios)"
    )
    periods: int = Field(4, ge=1, le=20, description="Number of most recent report periods")
    fields: list[str] | None = Field(
        None, description="Tushare field names to return instead of the default key items, e.g. [\"rd_exp\"]"
    )


class SectorListParams(BaseModel):
    level: Literal["sw_l1", "sw_l2", "sw_l3"] = Field(
        "sw_l1", description="Shenwan (申万) industry level: sw_l1 has 31 broad sectors, sw_l2 and sw_l3 are finer"
    )


class SectorParams(BaseModel):
    sector_id: str = Field(description='Sector id from list_sectors, e.g. "801120.SI"')
    exclude_st: bool = Field(True, description="Exclude ST and *ST stocks")
    sort_by: SortKey = "total_mv"
    descending: bool = True
    limit: int = Field(20, ge=1, le=50, description="Number of stocks to return")


# ScreenParams bound -> (snapshot column, comparison)
BOUNDS = {
    "min_total_mv": ("total_mv", "ge"),
    "max_pe_ttm": ("pe_ttm", "le"),
    "max_pb": ("pb", "le"),
    "min_dv_ttm": ("dv_ttm", "ge"),
    "min_roe": ("roe", "ge"),
    "max_debt_to_assets": ("debt_to_assets", "le"),
    "min_netprofit_yoy": ("netprofit_yoy", "ge"),
}

# Key items returned by financial_statements unless fields are given
STATEMENT_FIELDS = {
    "income": [
        "total_revenue", "revenue", "oper_cost", "sell_exp", "admin_exp", "rd_exp", "fin_exp",
        "operate_profit", "total_profit", "income_tax", "n_income", "n_income_attr_p", "basic_eps",
    ],
    "balance": [
        "total_assets", "total_cur_assets", "money_cap", "accounts_receiv", "inventories", "goodwill",
        "total_liab", "total_cur_liab", "st_borr", "lt_borr", "bond_payable", "total_hldr_eqy_exc_min_int",
    ],
    "cashflow": [
        "n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "c_pay_acq_const_fiolta",
        "free_cashflow", "c_pay_dist_dpcp_int_exp", "n_incr_cash_cash_equ", "end_bal_cash",
    ],
    "indicator": [
        "eps", "bps", "ocfps", "roe", "roe_yearly", "roa", "roic", "grossprofit_margin", "netprofit_margin",
        "debt_to_assets", "current_ratio", "quick_ratio", "netprofit_yoy", "dt_netprofit_yoy", "or_yoy", "ocf_yoy",
    ],
}


class StockQueries:
    """A-share stocks: screening, details, valuation history, capital flows, statements and Shenwan sectors."""

    def __init__(
        self,
        client: SagaxData
    ):
        self.client = client

    def queries(self) -> list[Query]:
        return [
            Query(
                name="list_industries",
                description="List the industries of listed A-share stocks with the number of stocks in each, "
                            "for choosing industries in screen_stocks.",
                params=NoParams,
                run=lambda _: self.list_industries(),
            ),
            Query(
                name="screen_stocks",
                description="Screen all listed A-share stocks by board, ST status, listing age, industry, "
                            "valuation and financials. Returns the matching count and the top stocks with "
                            "price, PE, PB, dividend yield, market value, ROE, debt ratio and growth.",
                params=ScreenParams,
                run=self.screen_stocks,
            ),
            Query(
                name="stock_details",
                description="Details of specific stocks: everything screen_stocks returns, plus the 1-year "
                            "return, maximum drawdown and annualized volatility of the forward-adjusted price.",
                params=DetailParams,
                run=self.stock_details,
            ),
            Query(
                name="valuation_history",
                description="How cheap stocks are against their own history: current PE (TTM), PB, PS (TTM) "
                            "and dividend yield with their percentile, minimum, median and maximum over the years.",
                params=ValuationParams,
                run=self.valuation_history,
            ),
            Query(
                name="capital_flows",
                description="Recent capital flows of stocks: net inflow of all and of large orders, days "
                            "with net inflow, and margin financing / short-selling balances with their change.",
                params=FlowParams,
                run=self.capital_flows,
            ),
            Query(
                name="financial_statements",
                description="Financial statements of one stock for its latest report periods, the latest "
                            "revision of each. Income and cash flow figures are year-to-date cumulative.",
                params=StatementParams,
                run=self.financial_statements,
            ),
            Query(
                name="list_sectors",
                description="List Shenwan (申万) industry sectors with their ids and member counts, "
                            "for sector_members and for sector indices in price_history.",
                params=SectorListParams,
                run=self.list_sectors,
            ),
            Query(
                name="sector_members",
                description="Current member stocks of a Shenwan sector, with the same fields as screen_stocks.",
                params=SectorParams,
                run=self.sector_members,
            ),
        ]

    def list_industries(self) -> dict[str, Any]:
        counts = self._snapshot["industry"].replace("", np.nan).dropna().value_counts()
        return {"industries": counts.to_dict()}

    def screen_stocks(
        self,
        params: ScreenParams
    ) -> dict[str, Any]:
        df = self._snapshot
        df = df[df["market"].isin(params.markets)]
        if params.exclude_st:
            df = df[~df["name"].str.contains("ST")]
        if params.min_listed_years:
            df = df[df["list_date"] <= shift(self._date, -round(params.min_listed_years * 365))]
        if params.industries:
            df = df[df["industry"].isin(params.industries)]
        if params.max_pe_ttm is not None:
            df = df[df["pe_ttm"] > 0]
        for field, (column, op) in BOUNDS.items():
            bound = getattr(params, field)
            if bound is not None:
                df = df[getattr(df[column], op)(bound)]

        df = df.sort_values(params.sort_by, ascending=not params.descending, na_position="last")
        return {"as_of": self._date, "matched": len(df), "stocks": records(df.head(params.limit))}

    def stock_details(
        self,
        params: DetailParams
    ) -> dict[str, Any]:
        df = self._snapshot.set_index("code")
        found = [code for code in params.codes if code in df.index]
        missing = [code for code in params.codes if code not in df.index]
        if not found:
            return {"as_of": self._date, "stocks": [], "not_found": missing}

        df = df.loc[found].join(self._price_stats(found)).reset_index()
        result: dict[str, Any] = {"as_of": self._date, "stocks": records(df)}
        if missing:
            result["not_found"] = missing
        return result

    def valuation_history(
        self,
        params: ValuationParams
    ) -> dict[str, Any]:
        start = shift(self._date, -params.years * 365)
        df = self.client.table("quote_stock_indicator", codes=params.codes, start=start, end=self._date, limit=100_000)
        stocks = []
        for code in params.codes:
            rows = df[df["code"] == code].sort_values("trade_date")
            if rows.empty:
                stocks.append({"code": code, "error": "no valuation data"})
                continue
            stock: dict[str, Any] = {"code": code, "name": self._names.get(code), "since": rows["trade_date"].iloc[0]}
            for column in ("pe_ttm", "pb", "ps_ttm", "dv_ttm"):
                stock[column] = _percentile(rows[column], positive_only=column != "dv_ttm")
            stocks.append(stock)
        return {"as_of": self._date, "stocks": stocks}

    def capital_flows(
        self,
        params: FlowParams
    ) -> dict[str, Any]:
        start = shift(self._date, -calendar_days(params.days))
        flows = self.client.table("quote_stock_moneyflow", codes=params.codes, start=start, limit=100_000)
        margin = self.client.table("quote_stock_margin", codes=params.codes, start=start, limit=100_000)
        stocks = []
        for code in params.codes:
            stock: dict[str, Any] = {"code": code, "name": self._names.get(code)}
            f = flows[flows["code"] == code].sort_values("trade_date").tail(params.days) if not flows.empty else flows
            if not f.empty:
                large = f["buy_lg_amount"] + f["buy_elg_amount"] - f["sell_lg_amount"] - f["sell_elg_amount"]
                stock |= {
                    "from": f["trade_date"].iloc[0],
                    "to": f["trade_date"].iloc[-1],
                    "net_inflow": f["net_mf_amount"].sum() / 1e4,          # 万元 -> 亿元
                    "large_order_net_inflow": large.sum() / 1e4,
                    "net_inflow_days": int((f["net_mf_amount"] > 0).sum()),
                    "trading_days": len(f),
                }
            m = margin[margin["code"] == code].sort_values("trade_date").tail(params.days + 1) if not margin.empty else margin
            if not m.empty:
                stock |= {
                    "margin_balance": m["rzye"].iloc[-1] / 1e8,             # 元 -> 亿元
                    "margin_balance_change_pct": (m["rzye"].iloc[-1] / m["rzye"].iloc[0] - 1) * 100,
                    "short_balance": m["rqye"].iloc[-1] / 1e8,
                }
            stocks.append(stock)
        return {
            "as_of": self._date,
            "units": "amounts in 100 million CNY (亿元); large orders are 大单 + 特大单",
            "stocks": records(pd.DataFrame(stocks)),
        }

    def financial_statements(
        self,
        params: StatementParams
    ) -> dict[str, Any]:
        df = self.client.table(f"fin_{params.statement}", codes=params.code, limit=1_000)
        if df.empty:
            raise LookupError(f"No {params.statement} data for {params.code}")
        if "report_type" in df:
            df = df[df["report_type"].astype(str) == "1"]          # consolidated statements only
        df = df.sort_values(["end_date", "ann_date"]).groupby("end_date").tail(1)
        df = df.sort_values("end_date", ascending=False).head(params.periods)

        fields = params.fields or STATEMENT_FIELDS[params.statement]
        unknown = [f for f in fields if f not in df]
        if unknown:
            raise ValueError(f"Unknown fields {unknown}; available: {[c for c in df if c not in ('code', 'updated_at')]}")
        df = df[["end_date", "ann_date", *fields]]

        units = "ratios and growth in %, per-share items in CNY"
        if params.statement != "indicator":
            amounts = [f for f in fields if "eps" not in f]
            df = df.assign(**{f: pd.to_numeric(df[f]) / 1e8 for f in amounts})
            units = "amounts in 100 million CNY (亿元), EPS in CNY"
        return {
            "code": params.code,
            "name": self._names.get(params.code),
            "statement": params.statement,
            "units": units,
            "periods": records(df),
        }

    def list_sectors(
        self,
        params: SectorListParams
    ) -> dict[str, Any]:
        df = self._sectors[self._sectors["level"] == params.level]
        return {"sectors": records(df[["sector_id", "sector_name", "members"]])}

    def sector_members(
        self,
        params: SectorParams
    ) -> dict[str, Any]:
        members = self.client.sector(params.sector_id, today())
        if members.empty:
            raise LookupError(f"Unknown sector {params.sector_id!r}; ids come from list_sectors")
        df = self._snapshot[self._snapshot["code"].isin(members["code"])]
        if params.exclude_st:
            df = df[~df["name"].str.contains("ST")]
        df = df.sort_values(params.sort_by, ascending=not params.descending, na_position="last")
        name = self._sectors.set_index("sector_id")["sector_name"].get(params.sector_id)
        return {
            "as_of": self._date,
            "sector": name,
            "members": len(df),
            "stocks": records(df.head(params.limit)),
        }

    @cached_property
    def _date(self) -> str:
        """Latest trading day with valuation data, which lags the daily quotes by about a day."""
        return self.client.latest("quote_stock_indicator", codes="000001.SZ")

    @cached_property
    def _snapshot(self) -> pd.DataFrame:
        """Every listed stock with its latest valuation and latest published financials, one row per code."""
        stocks = self.client.table("base_stock", limit=20_000)
        stocks = stocks.loc[stocks["list_status"] == "L", ["code", "name", "industry", "market", "list_date"]]

        valuation = self.client.table("quote_stock_indicator", start=self._date, end=self._date, limit=20_000)
        valuation = valuation[["code", "close", "pe_ttm", "pb", "dv_ttm", "total_mv"]].assign(
            total_mv=valuation["total_mv"] / 1e4,       # 万元 -> 亿元
        )

        # fin_indicator is filtered by report period; ~300 days covers every stock's latest report
        fin = self.client.table("fin_indicator", start=shift(self._date, -300), end=self._date, limit=100_000)
        fin = fin[fin["ann_date"] <= self._date]       # only reports already published on the date
        fin = fin.sort_values(["end_date", "ann_date"]).groupby("code").tail(1)
        fin = fin[["code", "end_date", "roe_yearly", "debt_to_assets", "netprofit_yoy", "or_yoy", "grossprofit_margin"]]
        fin = fin.rename(columns={"end_date": "report_period", "roe_yearly": "roe", "or_yoy": "revenue_yoy"})

        return stocks.merge(valuation, on="code", how="left").merge(fin, on="code", how="left")

    @cached_property
    def _names(self) -> dict[str, str]:
        return self._snapshot.set_index("code")["name"].to_dict()

    @cached_property
    def _sectors(self) -> pd.DataFrame:
        sectors = self.client.sector()
        return sectors.assign(members=pd.to_numeric(sectors["members"]))

    def _price_stats(
        self,
        codes: list[str]
    ) -> pd.DataFrame:
        prices = self.client.csd(codes, "CLOSE_QFQ", start=shift(self._date, -365), end=self._date)
        if prices.empty:
            return pd.DataFrame(index=pd.Index(codes, name="code"))
        # csd drops the code level when only one series comes back
        if prices.columns.nlevels == 2:
            prices = prices.xs("CLOSE_QFQ", axis=1, level=1)
        else:
            prices.columns = codes[:1]
        return price_stats(prices).add_suffix("_1y")


def _percentile(
    series: pd.Series,
    positive_only: bool
) -> dict[str, Any] | None:
    """The latest value and where it stands in the series: percentile (0 = cheapest seen), min, median, max."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    current = values.iloc[-1]
    if positive_only:
        # Multiples of loss-making periods are not comparable
        values = values[values > 0]
        if current <= 0 or values.empty:
            return {"current": round(float(current), 2), "percentile": None}
    return {
        "current": round(float(current), 2),
        "percentile": round(float((values <= current).mean() * 100), 1),
        "min": round(float(values.min()), 2),
        "median": round(float(values.median()), 2),
        "max": round(float(values.max()), 2),
    }
