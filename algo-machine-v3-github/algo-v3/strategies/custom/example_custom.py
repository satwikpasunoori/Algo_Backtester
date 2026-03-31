"""
Example Custom Strategy — Morning Momentum
==========================================
Upload your own .py file with this format.

REQUIRED:
  - get_signals(df, **params) function
  - PARAMS dict with param grid

OPTIONAL:
  - NAME string (display name)
"""
import pandas as pd
from typing import List, Dict

NAME = "MorningMomentum"  # shows in UI

PARAMS = {
    "ema_period": [21, 50],
    "momentum_bars": [3, 5],
}


def get_signals(df: pd.DataFrame, ema_period=21, momentum_bars=3) -> List[Dict]:
    """
    Simple momentum strategy:
    - Price above EMA
    - Last N bars all closed higher
    - Enter long; stop = lowest low of last 3 bars
    
    df columns: date, open, high, low, close, volume
    Returns: list of {'bar_index': int, 'signal': 1/-1, 'stop_price': float}
    """
    signals = []
    ema = df['close'].shift(1).ewm(span=ema_period, adjust=False).mean()

    for i in range(momentum_bars + 2, len(df) - 1):
        close = df['close'].iloc[i]
        prev_closes = [df['close'].iloc[i - j] for j in range(1, momentum_bars + 1)]

        # All previous bars closing higher (momentum up)
        momentum_up = all(prev_closes[k] > prev_closes[k+1] for k in range(len(prev_closes)-1))
        above_ema   = close > ema.iloc[i]

        if momentum_up and above_ema:
            stop = df['low'].iloc[i-3:i].min()
            if stop > 0 and stop < close:
                signals.append({
                    'bar_index':   i,
                    'signal':      1,       # long
                    'stop_price':  round(stop, 2),
                })

    return signals
