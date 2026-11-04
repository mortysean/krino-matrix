import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..data_source import Query
from .client import SagaxData
from .common import shift, today, truncate, records

Codes = Field(min_length=1, max_length=10, description='Stock codes, e.g. ["600519.SH"]')

# News tagged with more codes than this is market-wide, not about the requested stocks
MAX_NEWS_CODES = 5

ANNOUNCEMENT_CATEGORIES = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
}
REPORT_TYPES = {"0": "company", "1": "industry", "2": "strategy"}


class NewsParams(BaseModel):
    codes: list[str] | None = Field(None, max_length=10, description="Only news about these stocks; null for all news")
    keywords: list[str] | None = Field(None, description="Keep news whose title contains any of these words")
    category: Literal[
        "market", "macro", "policy", "industry", "company", "earnings",
        "geopolitical", "investment_bank", "central_bank",
    ] | None = None
    days: int = Field(3, ge=1, le=7, description="Look back this many days")
    limit: int = Field(20, ge=1, le=50, description="Number of articles to return, newest first")
    with_content: bool = Field(False, description="Include the beginning of each article's text")


class AnnouncementParams(BaseModel):
    codes: list[str] = Codes
    category: Literal["年报", "半年报", "一季报", "三季报"] | None = Field(None, description="Periodic report type")
    keyword: str | None = Field(None, description="Part of the title")
    limit: int = Field(20, ge=1, le=50)


class ResearchParams(BaseModel):
    codes: list[str] = Codes
    days: int = Field(365, ge=1, le=3650, description="Look back this many days")
    limit: int = Field(20, ge=1, le=50, description="Number of reports to list, newest first")


class SurveyParams(BaseModel):
    codes: list[str] = Codes
    days: int = Field(365, ge=1, le=3650, description="Look back this many days")
    limit: int = Field(20, ge=1, le=50, description="Number of surveys to list, newest first")


class InfoQueries:
    """News, announcements, broker research reports and institutional surveys."""

    def __init__(
        self,
        client: SagaxData
    ):
        self.client = client

    def queries(self) -> list[Query]:
        return [
            Query(
                name="news",
                description="Recent financial news (titles in Chinese), optionally about specific stocks, "
                            "by keyword or category.",
                params=NewsParams,
                run=self.news,
            ),
            Query(
                name="announcements",
                description="Company announcements of stocks with links to the PDF, e.g. annual and "
                            "quarterly reports.",
                params=AnnouncementParams,
                run=self.announcements,
            ),
            Query(
                name="research_reports",
                description="Broker research reports on stocks: rating counts, median EPS and PE forecasts "
                            "for this and next year, and the latest reports with ratings and PDF links.",
                params=ResearchParams,
                run=self.research_reports,
            ),
            Query(
                name="institutional_surveys",
                description="Institutional investor visits and calls (机构调研) of stocks: when, how, "
                            "and how many and which institutions.",
                params=SurveyParams,
                run=self.institutional_surveys,
            ),
        ]

    def news(
        self,
        params: NewsParams
    ) -> dict[str, Any]:
        # At most the latest 1000 articles of a call come back, only part of a busy day, so each day is
        # fetched alone. Stock news is fetched both by code tag and from the general feed, since many
        # articles are tagged with hundreds of codes and the relevant ones are found by name instead
        days = [shift(today(), -i) for i in range(params.days)]
        calls = [(codes, day) for day in days for codes in ([params.codes, None] if params.codes else [None])]
        with ThreadPoolExecutor(len(calls)) as pool:
            parts = list(pool.map(
                lambda call: self.client.info(call[0], start=call[1], end=call[1], limit=1000, full=params.with_content),
                calls,
            ))
        df = pd.concat(parts, ignore_index=True).drop_duplicates("article_id")
        if df.empty:
            return {"articles": []}

        df = df.assign(title=df["title_zh"].replace("", np.nan).fillna(df["title"]))
        if params.codes:
            wanted = set(params.codes)
            tags = df["codes"].fillna("").str.split(",")
            tagged = tags.map(lambda t: len(t) <= MAX_NEWS_CODES and bool(wanted & set(t)))
            names = self.client.table("base_stock", codes=params.codes)["name"].tolist()
            named = df["title"].str.contains("|".join(map(re.escape, names))) if names else False
            df = df[tagged | named]
        if params.category:
            df = df[df["category"] == params.category]
        if params.keywords:
            df = df[df["title"].str.contains("|".join(map(re.escape, params.keywords)))]
        matched = len(df)
        df = df.sort_values("pub_time", ascending=False).head(params.limit)

        columns = ["pub_time", "category", "source", "title", "codes", "url"]
        if params.with_content:
            df = df.assign(content=df["content_zh"].replace("", np.nan).fillna(df["content"]))
            df = truncate(df, ["content"], max_chars=400)
            columns.append("content")
        # Drop market-wide code tags, which list hundreds of codes
        df = df.assign(codes=df["codes"].where(df["codes"].fillna("").str.count(",") < MAX_NEWS_CODES))
        return {"matched": matched, "articles": records(df[columns])}

    def announcements(
        self,
        params: AnnouncementParams
    ) -> dict[str, Any]:
        df = self.client.table("info_announcement", codes=params.codes, limit=10_000)
        if df.empty:
            return {"announcements": []}
        if params.category:
            df = df[df["category"] == ANNOUNCEMENT_CATEGORIES[params.category]]
        if params.keyword:
            df = df[df["title"].str.contains(params.keyword, regex=False)]
        df = df.sort_values("ann_date", ascending=False).head(params.limit)
        df = df.assign(url="https://static.cninfo.com.cn/" + df["adjunct_url"])
        return {"announcements": records(df[["ann_date", "code", "name", "title", "url"]])}

    def research_reports(
        self,
        params: ResearchParams
    ) -> dict[str, Any]:
        start = _dashed(shift(today(), -params.days))
        df = self.client.table("info_report", codes=params.codes, limit=10_000)
        if df.empty:
            return {"since": start, "consensus": [], "reports": []}
        df = df[df["pub_date"] >= start].sort_values("pub_date", ascending=False)
        forecasts = ["eps_this_year", "eps_next_year", "pe_this_year", "pe_next_year"]
        df[forecasts] = df[forecasts].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)   # 0 means missing

        consensus = []
        for code, reports in df.groupby("code", sort=False):
            consensus.append({
                "code": code,
                "name": reports["name"].iloc[0],
                "reports": len(reports),
                "brokers": reports["org_name"].nunique(),
                "ratings": reports["rating"].replace("", np.nan).dropna().value_counts().to_dict(),
                **{f"median_{f}": reports[f].median() for f in forecasts},
            })

        df = df.head(params.limit).assign(
            report_type=df["report_type"].astype(str).map(REPORT_TYPES),
            url="https://pdf.dfcfw.com/pdf/H3_" + df["report_id"] + "_1.pdf",
        )
        columns = ["pub_date", "code", "name", "org_name", "title", "rating", "eps_this_year", "eps_next_year", "url"]
        return {"since": start, "consensus": records(pd.DataFrame(consensus)), "reports": records(df[columns])}

    def institutional_surveys(
        self,
        params: SurveyParams
    ) -> dict[str, Any]:
        start = _dashed(shift(today(), -params.days))
        df = self.client.table("info_survey", codes=params.codes, limit=50_000)
        if df.empty:
            return {"since": start, "surveys": []}
        df = df[df["receive_date"] >= start]
        # One row per visiting institution; group them into one row per event
        surveys = df.groupby(["code", "name", "receive_date", "receive_way"], as_index=False).agg(
            institutions=("receive_object", "nunique"),
            examples=("receive_object", lambda s: "、".join(s.drop_duplicates().head(8))),
        ).sort_values("receive_date", ascending=False)
        counts = surveys.groupby("code")["institutions"].agg(["size", "sum"])
        return {
            "since": start,
            "totals": {code: {"events": int(row["size"]), "institutions": int(row["sum"])} for code, row in counts.iterrows()},
            "surveys": records(surveys.head(params.limit)),
        }


def _dashed(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"
