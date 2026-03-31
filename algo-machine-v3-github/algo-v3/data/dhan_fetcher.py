"""
Dhan Data Fetcher
=================
- Chunked requests for intraday (5M/15M): Dhan limits per-request range
  5M  → 75 days per chunk  → loop to get up to 1 year
  15M → 90 days per chunk  → loop to get up to 1 year
  4H  → single request, 1 year
  1D/1W → single request, 5 years
- All timestamps converted to IST (UTC+5:30)
- Falls back to synthetic data if no credentials
"""

import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
BASE_URL          = "https://api.dhan.co"
IST               = ZoneInfo("Asia/Kolkata")

STOCK_UNIVERSE = {
    "RELIANCE": "2885",  "TCS": "11536",     "INFY": "1594",
    "HDFCBANK": "1333",  "ICICIBANK": "4963", "SBIN": "3045",
    "BAJFINANCE": "317", "WIPRO": "3787",     "AXISBANK": "5900",
    "KOTAKBANK": "1922", "LT": "11483",       "MARUTI": "10999",
    "SUNPHARMA": "3351", "TATAMOTORS": "3456","TATASTEEL": "3499",
    "NTPC": "11630",     "POWERGRID": "14977","ONGC": "11723",
    "COALINDIA": "20374","HEROMOTOCO": "1348","ASIANPAINT": "236",
    "TITAN": "3506",     "NESTLEIND": "17963","ULTRACEMCO": "11532",
    "GRASIM": "1232",    "HINDUNILVR": "1394","BAJAJFINSV": "16675",
    "ADANIENT": "25",    "ADANIPORTS": "15083","DRREDDY": "881",
}

# Per-timeframe config:
#   interval  = Dhan interval string
#   chunk_days = max days per single API call
#   total_days = how far back we want
TIMEFRAME_CONFIG = {
    "1D":  {"interval": "D",   "chunk_days": 1825, "total_days": 1825},
    "1W":  {"interval": "W",   "chunk_days": 1825, "total_days": 1825},
    "4H":  {"interval": "240", "chunk_days": 365,  "total_days": 365},
    "1H":  {"interval": "60",  "chunk_days": 90,   "total_days": 365},
    "15M": {"interval": "15",  "chunk_days": 75,   "total_days": 365},
    "5M":  {"interval": "5",   "chunk_days": 30,   "total_days": 365},
}

# backward compat alias
TIMEFRAME_MAP = {k: {"interval": v["interval"], "days": v["total_days"]}
                 for k, v in TIMEFRAME_CONFIG.items()}


def _to_ist(ts_series: pd.Series) -> pd.Series:
    """Convert unix timestamps to IST datetime (tz-naive for storage)."""
    return pd.to_datetime(ts_series, unit="s", utc=True).dt.tz_convert(IST).dt.tz_localize(None)


def _single_fetch(security_id, interval, from_date, to_date, headers) -> pd.DataFrame | None:
    """One API call for a date range. Returns raw df or None."""
    payload = {
        "securityId": security_id,
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": interval,
        "fromDate": from_date.strftime("%Y-%m-%d"),
        "toDate":   to_date.strftime("%Y-%m-%d"),
    }
    try:
        resp = requests.post(f"{BASE_URL}/v2/charts/historical",
                             json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "open" not in data or not data["open"]:
            return None
        df = pd.DataFrame({
            "date":   _to_ist(data["timestamp"]),
            "open":   data["open"],
            "high":   data["high"],
            "low":    data["low"],
            "close":  data["close"],
            "volume": data["volume"],
        })
        return df
    except Exception as e:
        print(f"[DATA] chunk fetch error: {e}")
        return None


def fetch_dhan_ohlc(symbol: str, timeframe: str = "1D") -> pd.DataFrame:
    """
    Fetch OHLC from Dhan with chunked loops for intraday timeframes.
    Falls back to synthetic data if no credentials.
    """
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN or DHAN_CLIENT_ID == "your_client_id_here":
        print(f"[DATA] No Dhan credentials — generating synthetic data for {symbol}")
        return _generate_synthetic_data(symbol, timeframe)

    security_id = STOCK_UNIVERSE.get(symbol.upper())
    if not security_id:
        print(f"[DATA] {symbol} not in universe — using synthetic")
        return _generate_synthetic_data(symbol, timeframe)

    cfg        = TIMEFRAME_CONFIG.get(timeframe, TIMEFRAME_CONFIG["1D"])
    interval   = cfg["interval"]
    chunk_days = cfg["chunk_days"]
    total_days = cfg["total_days"]

    headers = {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id":    DHAN_CLIENT_ID,
        "Content-Type": "application/json",
    }

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=total_days)

    # Build list of (chunk_start, chunk_end) windows
    chunks = []
    cur = start_date
    while cur < end_date:
        chunk_end = min(cur + timedelta(days=chunk_days), end_date)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)

    all_dfs = []
    for i, (c_from, c_to) in enumerate(chunks):
        print(f"[DATA] {symbol} [{timeframe}] chunk {i+1}/{len(chunks)}: {c_from.date()} → {c_to.date()}")
        chunk_df = _single_fetch(security_id, interval, c_from, c_to, headers)
        if chunk_df is not None and len(chunk_df) > 0:
            all_dfs.append(chunk_df)

    if not all_dfs:
        print(f"[DATA] No data returned for {symbol} [{timeframe}] — using synthetic")
        return _generate_synthetic_data(symbol, timeframe)

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    print(f"[DATA] Fetched {len(df)} bars for {symbol} ({timeframe}) from Dhan [IST]")
    return df


def _generate_synthetic_data(symbol: str, timeframe: str = "1D") -> pd.DataFrame:
    """Synthetic OHLC with regime shifts. IST-aligned timestamps."""
    np.random.seed(hash(symbol) % 10000)
    cfg  = TIMEFRAME_CONFIG.get(timeframe, TIMEFRAME_CONFIG["1D"])
    days = cfg["total_days"]

    bar_map = {
        "1D": (days,        "B"),
        "1W": (days // 5,   "W-FRI"),
        "4H": (days * 2,    "4h"),
        "1H": (days * 7,    "h"),
        "15M":(days * 26,   "15min"),
        "5M": (days * 75,   "5min"),
    }
    n_bars, freq = bar_map.get(timeframe, (days, "B"))

    base_prices = {
        "RELIANCE": 2500, "TCS": 3800, "INFY": 1700, "HDFCBANK": 1600,
        "ICICIBANK": 1100, "SBIN": 800, "BAJFINANCE": 7000, "WIPRO": 500,
        "AXISBANK": 1200,  "KOTAKBANK": 1800,
    }
    S0 = base_prices.get(symbol, np.random.uniform(200, 3000))
    prices = [S0]
    mu, sigma, rc = 0.0003, 0.015, 0

    for _ in range(n_bars - 1):
        rc += 1
        if rc > np.random.randint(50, 200):
            mu    = np.random.choice([0.0005, -0.0003, 0.0001], p=[0.4, 0.3, 0.3])
            sigma = np.random.uniform(0.01, 0.025)
            rc    = 0
        prices.append(prices[-1] * (1 + np.random.normal(mu, sigma)))

    prices = np.array(prices)
    hf = np.random.uniform(1.001, 1.015, n_bars)
    lf = np.random.uniform(0.985, 0.999, n_bars)
    of = np.random.uniform(0.995, 1.005, n_bars)

    # IST end date
    end_ist = datetime.now(IST).replace(tzinfo=None)
    dates   = pd.date_range(end=end_ist, periods=n_bars, freq=freq)

    df = pd.DataFrame({
        "date":   dates,
        "open":   np.round(prices * of, 2),
        "high":   np.round(np.maximum(prices * of, prices) * hf, 2),
        "low":    np.round(np.minimum(prices * of, prices) * lf, 2),
        "close":  np.round(prices, 2),
        "volume": np.random.lognormal(15, 0.5, n_bars).astype(int),
    })
    df = df.dropna().reset_index(drop=True)
    print(f"[DATA] Generated {len(df)} synthetic bars for {symbol} ({timeframe}) [IST]")
    return df


def fetch_all_stocks(timeframe: str = "1D") -> dict:
    return {sym: fetch_dhan_ohlc(sym, timeframe) for sym in STOCK_UNIVERSE}
