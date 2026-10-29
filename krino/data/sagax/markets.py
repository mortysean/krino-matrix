from functools import cached_property
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..data_source import Query, NoParams
from .client import SagaxData
from .common import shift, today, calendar_days, price_stats, sample, records

Asset = Literal["stock", "etf", "index", "futures", "option"]

# asset -> (quote table, code column)
QUOTES: dict[str, tuple[str, str]] = {
    "stock": ("quote_stock_daily_qfq", "code"),
    "etf": ("quote_etf_daily_qfq", "code"),
    "index": ("quote_index_daily", "code"),
    "futures": ("quote_futures_daily", "symbol"),
    "option": ("quote_option_daily", "code"),
}


class IndexParams(BaseModel):
    category: Literal["宽基", "行业"] | None = Field(None, description="宽基 for broad market indices, 行业 for sector indices")
    sw_level: Literal["L1", "L2"] | None = Field(None, description="Shenwan level of sector indices")
    keyword: str | None = Field(None, description="Part of the index name, e.g. 银行")


class FuturesParams(BaseModel):
    keyword: str | None = Field(None, description="Part of the product name or id, e.g. 螺纹, 黄金, IF")
    exchange: Literal["SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"] | None = None


class OptionParams(BaseModel):
    underlying: str | None = Field(
        None,
        description='Underlying code, e.g. "510300.SH" (300ETF), "000852.SH" (CSI 1000), "AG2612" (silver futures); '
                    "null for a summary of all underlyings",
    )
    call_put: Literal["C", "P"] | None = None
    expiry: str | None = Field(None, description='Expiry month "YYYYMM"; defaults to the nearest one')
    limit: int = Field(40, ge=1, le=80, description="Number of contracts to return")


class PriceParams(BaseModel):
    asset: Asset
    codes: list[str] = Field(
        min_length=1, max_length=10,
        description='Codes of one asset type: stocks "600519.SH", ETFs "510300.SH", indices "000300.SH" or '
                    'Shenwan sectors "801120.SI", futures contracts "SHFE.rb2701" (main_contract from list_futures), '
                    'options "10009633.SH"',
    )
    bars: int = Field(244, ge=2, le=2500, description="Number of most recent bars; 244 daily bars is about a year")
    points: int = Field(12, ge=2, le=60, description="Number of closing prices to sample evenly from the bars")
    freq: Literal["daily", "30min", "60min"] = Field("daily", description="Intraday bars exist for ETFs only")


class CalendarParams(BaseModel):
    start: str | None = Field(None, description='"YYYYMMDD"; defaults to today')
    end: str | None = Field(None, description='"YYYYMMDD"; defaults to 30 days after start')
    exchange: Literal["SSE", "SZSE", "SHFE", "DCE", "CZCE", "CFFEX", "INE", "GFEX"] = "SSE"


class MarketQueries:
    """Indices, ETFs, futures, options, price history of any asset, and the trading calendar."""

    def __init__(
        self,
        client: SagaxData
    ):
        self.client = client

    def queries(self) -> list[Query]:
        return [
            Query(
                name="list_indices",
                description="List stock indices (broad market and Shenwan sector) with their codes.",
                params=IndexParams,
                run=self.list_indices,
            ),
            Query(
                name="list_etfs",
                description="List the ETFs in the database with their latest close and 1-year return, "
                            "maximum drawdown and volatility.",
                params=NoParams,
                run=lambda _: self.list_etfs(),
            ),
            Query(
                name="list_futures",
                description="List futures products with their current main contract and its latest "
                            "close, volume and open interest.",
                params=FuturesParams,
                run=self.list_futures,
            ),
            Query(
                name="list_options",
                description="Option chain of an underlying for one expiry with latest prices, volume and "
                            "open interest; without an underlying, a summary of every underlying.",
                params=OptionParams,
                run=self.list_options,
            ),
            Query(
                name="price_history",
                description="Price history of stocks, ETFs, indices, futures or options: return, maximum "
                            "drawdown, volatility, high, low and evenly sampled closing prices.",
                params=PriceParams,
                run=self.price_history,
            ),
            Query(
                name="trading_days",
                description="Trading days of an exchange between two dates.",
                params=CalendarParams,
                run=self.trading_days,
            ),
        ]

    def list_indices(
        self,
        params: IndexParams
    ) -> dict[str, Any]:
        df = self._indices
        if params.category:
            df = df[df["category"] == params.category]
        if params.sw_level:
            df = df[df["sw_level"] == params.sw_level]
        if params.keyword:
            df = df[df["name"].str.contains(params.keyword, regex=False)]
        return {"indices": records(df[["code", "name", "category", "sw_level"]])}

    def list_etfs(self) -> dict[str, Any]:
        table, _ = QUOTES["etf"]
        date = self.client.latest(table)
        codes = self.client.table(table, start=date, end=date)["code"].tolist()
        result = self.price_history(PriceParams(asset="etf", codes=codes, points=2))
        return {"note": "The database stores no ETF names", **result}

    def list_futures(
        self,
        params: FuturesParams
    ) -> dict[str, Any]:
        df = self._futures
        if params.exchange:
            df = df[df["exchange"] == params.exchange]
        if params.keyword:
            keyword = params.keyword.lower()
            df = df[df["product_name"].str.contains(params.keyword, regex=False) | (df["product_id"].str.lower() == keyword)]

        table, _ = QUOTES["futures"]
        date = self.client.latest(table)
        quotes = self.client.table(table, codes=df["main_contract"].tolist(), start=date, end=date) if len(df) else pd.DataFrame()
        if not quotes.empty:
            quotes = quotes[["symbol", "close", "volume", "open_interest"]].rename(columns={"symbol": "main_contract"})
            df = df.merge(quotes, on="main_contract", how="left")
        # Quotes and price_history go by the main contract, so the continuous symbol is left out
        return {"as_of": date, "futures": records(df.drop(columns="symbol"))}

    def list_options(
        self,
        params: OptionParams
    ) -> dict[str, Any]:
        date, board = self._options
        if params.underlying is None:
            # Futures options have an underlying per futures contract, so they are summarized per product
            underlying = board["underlying"].str.removeprefix("OP")
            product = underlying.where(board["opt_type"] != "期货期权", underlying.str.replace(r"\d+(?=\.)", "", regex=True))
            summary = board.assign(product=product).groupby(["opt_type", "product"]).agg(
                underlyings=("underlying", lambda s: sorted(s.str.removeprefix("OP").unique())),
                contracts=("code", "size"),
                volume=("vol", "sum"),
                open_interest=("oi", "sum"),
            ).reset_index().sort_values("volume", ascending=False)
            return {"as_of": date, "products": records(summary)}

        wanted = params.underlying.upper().removeprefix("OP")
        key = board["underlying"].str.removeprefix("OP")
        df = board[(key == wanted) | (key.str.split(".").str[0] == wanted.split(".")[0])]
        if df.empty:
            raise LookupError(f"No options on {params.underlying!r}; call list_options without underlying to see them")
        expiries = sorted(df["expiry"].unique())
        expiry = params.expiry or expiries[0]
        df = df[df["expiry"] == expiry]
        if params.call_put:
            df = df[df["call_put"] == params.call_put]
        df = df.sort_values(["call_put", "exercise_price"])
        columns = ["code", "name", "call_put", "exercise_price", "delist_date", "close", "settle", "vol", "oi"]
        return {
            "as_of": date,
            "underlying": df["underlying"].iloc[0] if len(df) else params.underlying,
            "expiry": expiry,
            "expiries": expiries,
            "contracts": len(df),
            "options": records(df[columns].head(params.limit), decimals=4),
        }

    def price_history(
        self,
        params: PriceParams
    ) -> dict[str, Any]:
        table, column = QUOTES[params.asset]
        codes = params.codes
        if params.asset == "futures":
            # Continuous main contract quotes are not kept up to date; use the actual main contract
            mains = self._futures.set_index("symbol")["main_contract"]
            codes = [mains.get(code, code) for code in codes]

        if params.freq == "daily":
            start = shift(today(), -calendar_days(params.bars))
            df = self.client.table(table, codes=codes, start=start, limit=100_000)
            axis = "trade_date"
        else:
            if params.asset != "etf":
                raise ValueError("Intraday bars exist for ETFs only")
            df = self.client.table("quote_etf_mins", codes=codes, limit=100_000)
            df = df[df["freq"] == params.freq]
            axis = "trade_time"
        if df.empty:
            raise LookupError(f"No {params.asset} quotes for {codes}")

        closes = df.pivot_table(index=axis, columns=column, values="close").sort_index().tail(params.bars)
        stats = price_stats(closes)
        if params.freq != "daily":
            stats = stats.drop(columns="volatility")
        stats["high"] = closes.max()
        stats["low"] = closes.min()
        stats["close"] = closes.ffill().iloc[-1]

        series = []
        for code in codes:
            if code not in closes:
                series.append({"code": code, "error": "no quotes"})
                continue
            prices = closes[code].dropna()
            stat = records(stats.loc[[code]], decimals=4)[0]
            series.append({
                "code": code,
                "from": prices.index[0],
                "to": prices.index[-1],
                "bars": len(prices),
                **stat,
                "closes": sample(prices, params.points),
            })
        return {"asset": params.asset, "freq": params.freq, "units": "return, max_drawdown, volatility in %", "series": series}

    def trading_days(
        self,
        params: CalendarParams
    ) -> dict[str, Any]:
        start = params.start or today()
        end = params.end or shift(start, 30)
        cal = self._calendar
        cal = cal[(cal["exchange"] == params.exchange) & cal["cal_date"].between(start, end)]
        days = cal.loc[cal["is_open"].astype(str) == "1", "cal_date"].sort_values().tolist()
        result: dict[str, Any] = {"exchange": params.exchange, "start": start, "end": end, "trading_days": len(days)}
        result["dates" if len(days) <= 60 else "first_and_last"] = days if len(days) <= 60 else [days[0], days[-1]]
        return result

    @cached_property
    def _indices(self) -> pd.DataFrame:
        return self.client.table("base_index", limit=10_000)

    @cached_property
    def _futures(self) -> pd.DataFrame:
        df = self.client.table("base_futures_contract", limit=100_000)
        df = df[df["is_main"].astype(str) == "1"]
        df = df[["symbol", "product_id", "product_name", "exchange", "underlying_main", "multiplier"]]
        return df.rename(columns={"underlying_main": "main_contract"}).sort_values(["exchange", "product_id"])

    @cached_property
    def _options(self) -> tuple[str, pd.DataFrame]:
        """Latest trading day and every option quoted on it with its contract terms.

        The contract table is cut off at 100k rows, so contracts are fetched by the quoted codes instead.
        """
        table, _ = QUOTES["option"]
        date = self.client.latest(table)
        quotes = self.client.table(table, start=date, end=date, limit=100_000)
        contracts = self.client.table_batched("base_option_contract", quotes["code"].tolist())
        contracts = contracts[["code", "name", "opt_type", "underlying", "call_put", "exercise_price", "delist_date"]]
        board = quotes[["code", "close", "settle", "vol", "oi"]].merge(contracts, on="code")
        return date, board.assign(expiry=board["delist_date"].astype(str).str[:6])

    @cached_property
    def _calendar(self) -> pd.DataFrame:
        # Date filters are ignored on this table, so it is fetched whole (~80k rows)
        return self.client.table("base_trade_calendar", limit=100_000)
