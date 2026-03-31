"""
Strategy File Generator — produces clean, deployable Python strategy files
that can be used directly in live trading with Dhan API.
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output_strategies")


def generate_strategy_file(strategy_name: str, params: dict, symbol: str,
                            timeframe: str, metrics: dict,
                            rr: float = 2.0, risk_pct: float = 1.0) -> str:
    """
    Generate a deployable Python strategy file.
    Returns the file path.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    param_str = "_".join(f"{k}{v}" for k, v in params.items())
    rr_str = f"RR{rr}".replace(".", "")
    filename = f"{symbol}_{strategy_name}_{rr_str}_{param_str[:30]}_{timeframe}.py"
    filepath = os.path.join(OUTPUT_DIR, filename)

    code = _build_strategy_code(strategy_name, params, symbol, timeframe, metrics, rr, risk_pct)

    with open(filepath, 'w') as f:
        f.write(code)

    return filepath


def _build_strategy_code(strategy_name: str, params: dict, symbol: str,
                          timeframe: str, metrics: dict,
                          rr: float = 2.0, risk_pct: float = 1.0) -> str:
    """Build the actual deployable strategy Python file."""

    param_lines = "\n".join(f"    {k} = {repr(v)}" for k, v in params.items())
    metrics_comment = json.dumps({k: v for k, v in metrics.items()
                                  if k not in ['equity_curve']}, indent=4)

    # Map strategy to its signal logic
    signal_logic = SIGNAL_LOGIC_MAP.get(strategy_name, _default_signal_logic(strategy_name, params))

    code = f'''#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
  AUTO-GENERATED TRADING STRATEGY
  Strategy   : {strategy_name}
  Symbol     : {symbol}
  Timeframe  : {timeframe}
  Generated  : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
═══════════════════════════════════════════════════════════════

BACKTEST METRICS:
{metrics_comment}

USAGE:
  1. Install: pip install pandas numpy requests python-dotenv
  2. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env
  3. Run: python {symbol}_{strategy_name}.py
═══════════════════════════════════════════════════════════════
"""

import os
import time
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────
SYMBOL = "{symbol}"
TIMEFRAME = "{timeframe}"
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")
CAPITAL = 100000        # Starting capital in INR — CHANGE THIS\n"
f"RISK_PCT = {risk_pct}            # % of equity risked per trade\n"
f"RR_RATIO = {rr}             # Risk:Reward used in backtest

# ── Strategy Parameters ────────────────────────────────────────
class StrategyParams:
{param_lines}

params = StrategyParams()

# ── Dhan API Client ────────────────────────────────────────────
class DhanClient:
    BASE_URL = "https://api.dhan.co"

    def __init__(self):
        self.headers = {{
            "access-token": DHAN_ACCESS_TOKEN,
            "client-id": DHAN_CLIENT_ID,
            "Content-Type": "application/json"
        }}

    def get_ohlc(self, security_id: str, interval: str = "D", days: int = 365) -> pd.DataFrame:
        end = datetime.now()
        start = end - timedelta(days=days)
        payload = {{
            "securityId": security_id,
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "interval": interval,
            "fromDate": start.strftime("%Y-%m-%d"),
            "toDate": end.strftime("%Y-%m-%d")
        }}
        resp = requests.post(f"{{self.BASE_URL}}/v2/charts/historical",
                             json=payload, headers=self.headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame({{
            "date": pd.to_datetime(data["timestamp"], unit="s"),
            "open": data["open"], "high": data["high"],
            "low": data["low"], "close": data["close"],
            "volume": data["volume"]
        }})
        return df.sort_values("date").reset_index(drop=True)

    def place_order(self, security_id: str, txn_type: str,
                    quantity: int, order_type: str = "MARKET") -> dict:
        payload = {{
            "dhanClientId": DHAN_CLIENT_ID,
            "transactionType": txn_type,  # BUY or SELL
            "exchangeSegment": "NSE_EQ",
            "productType": "CNC",
            "orderType": order_type,
            "validity": "DAY",
            "securityId": security_id,
            "quantity": quantity,
            "price": 0,
        }}
        resp = requests.post(f"{{self.BASE_URL}}/v2/orders",
                             json=payload, headers=self.headers, timeout=30)
        return resp.json()

    def get_positions(self) -> list:
        resp = requests.get(f"{{self.BASE_URL}}/v2/positions",
                             headers=self.headers, timeout=30)
        return resp.json()


# ── Signal Generation ──────────────────────────────────────────
{signal_logic}

# ── Position Sizing ────────────────────────────────────────────
def calculate_quantity(price: float, stop_loss_pct: float) -> int:
    risk_amount = CAPITAL * RISK_PER_TRADE
    risk_per_share = price * (stop_loss_pct / 100)
    qty = int(risk_amount / risk_per_share)
    return max(qty, 1)


# ── Main Trading Loop ──────────────────────────────────────────
def run():
    print(f"[{{datetime.now()}}] Starting {{SYMBOL}} - {strategy_name}")
    client = DhanClient()

    # IMPORTANT: Update security_id for your symbol from Dhan API instrument list
    SECURITY_ID = "REPLACE_WITH_ACTUAL_SECURITY_ID"

    while True:
        try:
            # Fetch latest data
            df = client.get_ohlc(SECURITY_ID, interval="D", days=365)
            print(f"[{{datetime.now()}}] Fetched {{len(df)}} bars")

            # Generate signal
            signal = generate_signal(df)
            print(f"[{{datetime.now()}}] Signal: {{signal}}")

            latest_price = df["close"].iloc[-1]

            if signal == "BUY":
                qty = calculate_quantity(latest_price, params.stop_loss_pct)
                print(f"[{{datetime.now()}}] PLACING BUY: {{qty}} shares @ ₹{{latest_price:.2f}}")
                # result = client.place_order(SECURITY_ID, "BUY", qty)  # Uncomment to go live
                # print(f"Order result: {{result}}")

            elif signal == "SELL":
                print(f"[{{datetime.now()}}] PLACING SELL @ ₹{{latest_price:.2f}}")
                # result = client.place_order(SECURITY_ID, "SELL", qty)  # Uncomment to go live

            # Sleep until next candle close
            # For daily: sleep 3600 seconds, adjust for other timeframes
            time.sleep(3600)

        except KeyboardInterrupt:
            print("[!] Strategy stopped by user.")
            break
        except Exception as e:
            print(f"[ERROR] {{e}}")
            time.sleep(60)


if __name__ == "__main__":
    run()
'''
    return code


SIGNAL_LOGIC_MAP = {
    "EMA_Crossover": """
def generate_signal(df: pd.DataFrame) -> str:
    close = df['close']
    ema_fast = close.ewm(span=params.fast, adjust=False).mean()
    ema_slow = close.ewm(span=params.slow, adjust=False).mean()
    if ema_fast.iloc[-1] > ema_slow.iloc[-1] and ema_fast.iloc[-2] <= ema_slow.iloc[-2]:
        return "BUY"
    elif ema_fast.iloc[-1] < ema_slow.iloc[-1] and ema_fast.iloc[-2] >= ema_slow.iloc[-2]:
        return "SELL"
    return "HOLD"
""",
    "RSI_MeanReversion": """
def generate_signal(df: pd.DataFrame) -> str:
    close = df['close']
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/params.rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/params.rsi_period, adjust=False).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0, float('nan'))))
    if rsi.iloc[-2] < params.oversold and rsi.iloc[-1] >= params.oversold:
        return "BUY"
    elif rsi.iloc[-2] > params.overbought and rsi.iloc[-1] <= params.overbought:
        return "SELL"
    return "HOLD"
""",
    "MACD": """
def generate_signal(df: pd.DataFrame) -> str:
    close = df['close']
    ema_fast = close.ewm(span=params.fast, adjust=False).mean()
    ema_slow = close.ewm(span=params.slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=params.signal, adjust=False).mean()
    hist = macd - signal_line
    if hist.iloc[-2] < 0 and hist.iloc[-1] >= 0:
        return "BUY"
    elif hist.iloc[-2] > 0 and hist.iloc[-1] <= 0:
        return "SELL"
    return "HOLD"
""",
}


def _default_signal_logic(strategy_name: str, params: dict) -> str:
    """Fallback signal logic template."""
    return f'''
def generate_signal(df: pd.DataFrame) -> str:
    """
    {strategy_name} signal logic.
    Customize this function with your exact entry/exit conditions.
    Strategy params: {params}
    """
    # TODO: Implement signal logic based on strategy parameters
    close = df['close']
    # Add indicator calculations here
    return "HOLD"  # Returns: "BUY", "SELL", or "HOLD"
'''
