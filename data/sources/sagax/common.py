from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 244


def shift(
    date: str,
    days: int
) -> str:
    """A "YYYYMMDD" date moved by a number of calendar days."""
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def today() -> str:
    return datetime.now().strftime("%Y%m%d")


def calendar_days(trading_days: int) -> int:
    """Calendar days that safely cover a number of trading days, holidays included."""
    return round(trading_days * 1.5) + 15


def price_stats(prices: pd.DataFrame) -> pd.DataFrame:
    """Return, maximum drawdown and annualized volatility in % per column of a date-indexed price table."""
    returns = prices.pct_change(fill_method=None)
    stats = pd.DataFrame({
        "return": (prices.ffill().iloc[-1] / prices.bfill().iloc[0] - 1) * 100,
        "max_drawdown": (1 - prices / prices.cummax()).max() * 100,
        "volatility": returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
    })
    stats.index.name = "code"
    return stats


def sample(
    series: pd.Series,
    points: int
) -> dict[str, float]:
    """About `points` evenly spaced values of a series, always including the last one."""
    series = series.dropna()
    step = max(1, -(-len(series) // points))
    picked = series.iloc[::-1].iloc[::step].iloc[::-1]
    return {str(k): round(float(v), 4) for k, v in picked.items()}


def truncate(
    df: pd.DataFrame,
    columns: list[str],
    max_chars: int = 200
) -> pd.DataFrame:
    """Shorten long text columns so results stay compact."""
    df = df.copy()
    for column in columns:
        if column in df:
            text = df[column].fillna("").astype(str)
            df[column] = text.where(text.str.len() <= max_chars, text.str[:max_chars] + "…")
    return df


def records(
    df: pd.DataFrame,
    decimals: int = 2
) -> list[dict[str, Any]]:
    """Rows as JSON-ready dicts: floats rounded, missing values and empty strings as None."""
    df = df.drop(columns=["updated_at", "update_flag"], errors="ignore").replace("", np.nan)
    df = df.round(decimals).astype(object).where(df.notna(), None)
    return df.to_dict(orient="records")
