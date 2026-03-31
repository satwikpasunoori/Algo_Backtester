"""
Regime Filter Engine — labels market conditions on each bar.
Regimes: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
Uses ADX, EMA slope, ATR-based volatility, and Bollinger Band width.
"""

import pandas as pd
import numpy as np


def label_regimes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'regime' column to OHLC dataframe.
    Returns df with regime labels.
    """
    df = df.copy()
    close = df['close']
    high = df['high']
    low = df['low']

    # --- ADX (Average Directional Index) ---
    df['adx'] = _compute_adx(high, low, close, period=14)

    # --- EMA Slope ---
    ema50 = close.ewm(span=50, adjust=False).mean()
    df['ema_slope'] = ema50.diff(5) / ema50.shift(5) * 100

    # --- ATR-based Volatility ---
    atr = _compute_atr(high, low, close, period=14)
    atr_pct = atr / close * 100
    df['atr_pct'] = atr_pct
    df['atr_pct_ma'] = atr_pct.rolling(50).mean()

    # --- Bollinger Band Width ---
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_width = (std20 * 2) / sma20 * 100
    df['bb_width'] = bb_width
    df['bb_width_ma'] = bb_width.rolling(50).mean()

    # --- Regime labeling ---
    regimes = []
    for i in range(len(df)):
        adx = df['adx'].iloc[i]
        slope = df['ema_slope'].iloc[i]
        atr_now = df['atr_pct'].iloc[i]
        atr_avg = df['atr_pct_ma'].iloc[i]
        bb = df['bb_width'].iloc[i]
        bb_avg = df['bb_width_ma'].iloc[i]

        if pd.isna(adx) or pd.isna(slope):
            regimes.append('UNKNOWN')
            continue

        # High volatility: ATR spike OR BB expansion
        if (not pd.isna(atr_avg) and atr_now > atr_avg * 1.5) or \
           (not pd.isna(bb_avg) and bb > bb_avg * 1.4):
            regimes.append('VOLATILE')
        elif adx > 25:
            # Strong trend
            if slope > 0:
                regimes.append('TRENDING_UP')
            else:
                regimes.append('TRENDING_DOWN')
        else:
            # Weak trend = ranging
            regimes.append('RANGING')

    df['regime'] = regimes

    # Cleanup helper columns
    drop_cols = ['adx', 'ema_slope', 'atr_pct', 'atr_pct_ma', 'bb_width', 'bb_width_ma']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    return df


def _compute_adx(high, low, close, period=14):
    """Compute ADX."""
    high = pd.Series(high).reset_index(drop=True)
    low = pd.Series(low).reset_index(drop=True)
    close = pd.Series(close).reset_index(drop=True)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx


def _compute_atr(high, low, close, period=14):
    """Compute ATR."""
    high = pd.Series(high).reset_index(drop=True)
    low = pd.Series(low).reset_index(drop=True)
    close = pd.Series(close).reset_index(drop=True)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def get_regime_breakdown(trades: list, df: pd.DataFrame) -> dict:
    """
    For each trade, look up regime at entry, then compute winrate per regime.
    """
    if df is None or 'regime' not in df.columns or not trades:
        return {}

    df_indexed = df.set_index('date')
    regime_results = {'TRENDING_UP': [], 'TRENDING_DOWN': [], 'RANGING': [], 'VOLATILE': []}

    for trade in trades:
        try:
            entry_dt = pd.to_datetime(trade['entry_date'])
            # Find nearest date
            idx = df_indexed.index.get_indexer([entry_dt], method='nearest')[0]
            regime = df_indexed.iloc[idx]['regime']
            if regime in regime_results:
                regime_results[regime].append(trade['pnl'])
        except Exception:
            continue

    summary = {}
    for regime, pnls in regime_results.items():
        if pnls:
            wins = sum(1 for p in pnls if p > 0)
            summary[regime] = {
                'trades': len(pnls),
                'win_rate': round(wins / len(pnls) * 100, 1),
                'net_pnl': round(sum(pnls), 2)
            }

    best = max(summary.items(), key=lambda x: x[1].get('win_rate', 0), default=(None, {}))[0]
    return {'breakdown': summary, 'best_regime': best}
