"""Try the sagax data channel (needs SAGAX_API_KEY / SAGAX_SECRET_KEY in .env):

    python data/sagax_demo.py
"""
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from krino.data.sagax import sagax

# Edit these to try your own query
CODES = ["510300.SH", "510500.SH", "588000.SH"]
START, END = "20260901", "20261010"

data = sagax()

print("== Indicators for ETFs ==")
indicators = data.indicators()
print(indicators.loc[indicators["asset"] == "ETF", ["indicator", "zh"]].to_string(index=False))

print("\n== Forward-adjusted close, wide table ==")
print(data.csd(CODES, "QUOTE_ETF_DAILY_QFQ.CLOSE", start=START, end=END).tail())

print("\n== Raw table rows ==")
print(data.table("quote_etf_daily_qfq", codes=CODES[0], start=START, end=END).head())
