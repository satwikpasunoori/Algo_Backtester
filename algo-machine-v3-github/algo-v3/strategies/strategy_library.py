"""
Candle-Based Strategy Library
==============================
BAR CONVENTION (critical — no lookahead):
  - Signal is generated AT bar i using data UP TO AND INCLUDING bar i
  - Bar i is assumed to be a CLOSED candle at the time of signal
  - The backtest engine enters at OPEN of bar i+1 (next bar)
  - So: close[i] is fine to read — it's the close of the completed candle
  - WRONG: reading close[i] while "current candle forming" — 
           not applicable here since we only run on closed bars
  - WRONG: using bar[i+1] data in signal logic — never done here
  
All strategies use df.iloc[i-1] for "previous bar" checks.
The engine shift ensures entry = next bar open.

Transaction costs are applied in the engine:
  - Swing (1D/1W): 0.03% per side = 0.06% round trip
  - Intraday (5M/15M/1H): 0.05% per side = 0.10% round trip
"""

import pandas as pd
import numpy as np
from typing import List, Dict
import itertools


# ─── HELPERS ─────────────────────────────────────────────────────
# All helpers return series aligned to bar i using data up to bar i-1

def _ema(series: pd.Series, period: int) -> pd.Series:
    """EMA on shifted series — value at i uses data up to i-1."""
    return series.shift(1).ewm(span=period, adjust=False).mean()

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI on shifted close — no lookahead."""
    c = close.shift(1)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR using shifted OHLC — no lookahead."""
    h = df['high'].shift(1)
    l = df['low'].shift(1)
    c = df['close'].shift(1)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def _signals_to_list(signals: pd.Series, stops: pd.Series) -> List[Dict]:
    """
    Convert signal/stop series to list of dicts.
    bar_index = i means: signal confirmed at close of bar i,
    entry will be at OPEN of bar i+1.
    """
    result = []
    for i in range(len(signals)):
        sig = signals.iloc[i]
        stop = stops.iloc[i]
        if sig != 0 and stop is not None and not pd.isna(stop) and stop > 0:
            result.append({
                'bar_index': i,       # signal bar (closed)
                'signal': int(sig),
                'stop_price': float(stop),
            })
    return result


# ─── STRATEGY 1: VCB — Volatility Compression Breakout ──────────
def strategy_vcb(df, atr_short=5, atr_long=20, compression=0.7, range_len=4):
    """
    Volatility Compression Breakout.
    Signal: ATR squeeze + price breaks N-bar range.
    All data shifted — signal on closed candle i-1, confirmed at bar i close.
    Entry: next bar open.
    Stop: opposite side of the range (from closed bars only).
    """
    df = df.copy()
    # Use shifted data — all computed from CLOSED candles
    c = df['close'].shift(1)
    h = df['high'].shift(1)
    l = df['low'].shift(1)

    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    atr_s = tr.rolling(atr_short).mean()
    atr_l = tr.rolling(atr_long).mean()

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(atr_long + range_len + 1, len(df)):
        # All references are shifted — using closed candle data
        prev_close = df['close'].iloc[i-1]   # last confirmed close
        prev_high  = df['high'].iloc[i-1]
        prev_low   = df['low'].iloc[i-1]

        # Range from closed candles only (excluding current bar i)
        range_slice_h = df['high'].iloc[i-1-range_len:i-1]
        range_slice_l = df['low'].iloc[i-1-range_len:i-1]
        rng_high = range_slice_h.max()
        rng_low  = range_slice_l.min()

        as_ = atr_s.iloc[i-1]
        al_ = atr_l.iloc[i-1]
        if pd.isna(as_) or pd.isna(al_) or al_ == 0:
            continue

        if as_ < al_ * compression:
            if prev_close > rng_high and prev_close > df['high'].iloc[i-2]:
                sigs.iloc[i-1] = 1
                stops.iloc[i-1] = rng_low
            elif prev_close < rng_low and prev_close < df['low'].iloc[i-2]:
                sigs.iloc[i-1] = -1
                stops.iloc[i-1] = rng_high

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 2: Inside Bar Breakout ────────────────────────────
def strategy_inside_bar(df, min_body_pct=0.5, ema_confirm=0):
    """
    Pattern: bar[i-1] is inside bar[i-2] (mother bar).
    Signal: bar[i-1] closes beyond mother bar high/low.
    Lookahead-free: we only look at i-2 (mother) and i-1 (inside+breakout).
    Entry: bar[i] open.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_confirm) if ema_confirm > 0 else None

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(3, len(df)):
        # Mother bar = i-2 (closed 2 bars ago)
        mh = df['high'].iloc[i-2];   ml = df['low'].iloc[i-2]
        mo = df['open'].iloc[i-2];   mc = df['close'].iloc[i-2]
        mbody = abs(mc - mo)
        mrng  = mh - ml
        if mrng == 0: continue

        # Inside bar = i-1 (last closed bar)
        ih = df['high'].iloc[i-1];   il = df['low'].iloc[i-1]
        ic = df['close'].iloc[i-1]

        is_inside = ih < mh and il > ml
        if not is_inside: continue
        if mbody / mrng < min_body_pct: continue

        ev = ema.iloc[i-1] if ema is not None else None

        # Signal: inside bar closes above/below mother bar
        if ic > mh:
            if ev is None or ic > ev:
                sigs.iloc[i-1] = 1
                stops.iloc[i-1] = ml
        elif ic < ml:
            if ev is None or ic < ev:
                sigs.iloc[i-1] = -1
                stops.iloc[i-1] = mh

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 3: Engulfing ───────────────────────────────────────
def strategy_engulfing(df, ema_trend=50, require_trend=True):
    """
    Pattern: bar[i-1] fully engulfs bar[i-2].
    Signal at close of bar[i-1]. Entry at bar[i] open.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(3, len(df)):
        po = df['open'].iloc[i-2];  pc = df['close'].iloc[i-2]
        co = df['open'].iloc[i-1];  cc = df['close'].iloc[i-1]
        cl = df['low'].iloc[i-1];   ch = df['high'].iloc[i-1]
        ev = ema.iloc[i-1]

        bull = pc < po and cc > co and cc > po and co < pc
        bear = pc > po and cc < co and cc < po and co > pc

        if bull and (not require_trend or cc > ev):
            sigs.iloc[i-1] = 1;  stops.iloc[i-1] = cl
        elif bear and (not require_trend or cc < ev):
            sigs.iloc[i-1] = -1; stops.iloc[i-1] = ch

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 4: Pin Bar ─────────────────────────────────────────
def strategy_pin_bar(df, wick_ratio=2.0, ema_trend=50, require_trend=True):
    """
    Pattern: bar[i-1] has long wick (wick_ratio × body).
    Signal at close of bar[i-1]. Entry at bar[i] open.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(2, len(df)):
        o = df['open'].iloc[i-1];   c = df['close'].iloc[i-1]
        h = df['high'].iloc[i-1];   l = df['low'].iloc[i-1]
        body  = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        ev = ema.iloc[i-1]
        if body == 0: continue

        if lower >= body * wick_ratio and upper <= body * 0.5:
            if not require_trend or c > ev:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = l
        elif upper >= body * wick_ratio and lower <= body * 0.5:
            if not require_trend or c < ev:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = h

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 5: Outside Bar ─────────────────────────────────────
def strategy_outside_bar(df, ema_trend=50):
    """
    Pattern: bar[i-1] range fully contains bar[i-2].
    Direction from close vs midpoint. Entry at bar[i] open.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(3, len(df)):
        ph = df['high'].iloc[i-2]; pl = df['low'].iloc[i-2]
        ch = df['high'].iloc[i-1]; cl = df['low'].iloc[i-1]
        cc = df['close'].iloc[i-1]
        mid = (ch + cl) / 2
        ev = ema.iloc[i-1]

        if ch > ph and cl < pl:
            if cc > mid and cc > ev:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = cl
            elif cc < mid and cc < ev:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = ch

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 6: Fakey (False Breakout Reversal) ────────────────
def strategy_fakey(df, range_len=5):
    """
    bar[i-2]: wick breaks N-bar range but closes back inside.
    bar[i-1]: confirms reversal direction.
    Signal at bar[i-1] close. Entry at bar[i] open.
    """
    df = df.copy()
    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(range_len + 3, len(df)):
        # Range = closed bars from i-range_len-2 to i-2 (not including fake bar)
        rh = df['high'].iloc[i-range_len-2:i-2].max()
        rl = df['low'].iloc[i-range_len-2:i-2].min()

        # Fake breakout bar = i-2
        fh = df['high'].iloc[i-2]; fl = df['low'].iloc[i-2]
        fc = df['close'].iloc[i-2]

        # Confirmation bar = i-1
        cc = df['close'].iloc[i-1]
        cl = df['low'].iloc[i-1]; ch = df['high'].iloc[i-1]

        # False upside break: wick above range, close back inside, confirm down
        if fh > rh and fc < rh and cc < fc:
            sigs.iloc[i-1] = -1; stops.iloc[i-1] = fh
        # False downside break: wick below range, close back inside, confirm up
        elif fl < rl and fc > rl and cc > fc:
            sigs.iloc[i-1] = 1;  stops.iloc[i-1] = fl

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 7: VCB + RSI ───────────────────────────────────────
def strategy_vcb_rsi(df, atr_short=5, atr_long=20, compression=0.7,
                      range_len=4, rsi_period=14, rsi_bull=50, rsi_bear=50):
    """VCB with RSI confirmation. All lookahead-free (shifted)."""
    df = df.copy()
    h = df['high'].shift(1); l = df['low'].shift(1); c = df['close'].shift(1)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr_s = tr.rolling(atr_short).mean()
    atr_l = tr.rolling(atr_long).mean()
    rsi   = _rsi(df['close'], rsi_period)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(atr_long + range_len + 1, len(df)):
        pc  = df['close'].iloc[i-1]
        ph  = df['high'].iloc[i-1]
        pl  = df['low'].iloc[i-1]
        rh  = df['high'].iloc[i-1-range_len:i-1].max()
        rl  = df['low'].iloc[i-1-range_len:i-1].min()
        rv  = rsi.iloc[i-1]
        as_ = atr_s.iloc[i-1]; al_ = atr_l.iloc[i-1]
        if pd.isna(as_) or pd.isna(al_) or al_ == 0: continue

        if as_ < al_ * compression:
            if pc > rh and pc > df['high'].iloc[i-2] and rv > rsi_bull:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = rl
            elif pc < rl and pc < df['low'].iloc[i-2] and rv < rsi_bear:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = rh

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 8: VCB + EMA ───────────────────────────────────────
def strategy_vcb_ema(df, atr_short=5, atr_long=20, compression=0.7,
                      range_len=4, ema_period=50):
    """VCB with EMA trend filter. All lookahead-free."""
    df = df.copy()
    h = df['high'].shift(1); l = df['low'].shift(1); c = df['close'].shift(1)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr_s = tr.rolling(atr_short).mean()
    atr_l = tr.rolling(atr_long).mean()
    ema   = _ema(df['close'], ema_period)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(atr_long + range_len + 1, len(df)):
        pc  = df['close'].iloc[i-1]
        rh  = df['high'].iloc[i-1-range_len:i-1].max()
        rl  = df['low'].iloc[i-1-range_len:i-1].min()
        ev  = ema.iloc[i-1]
        as_ = atr_s.iloc[i-1]; al_ = atr_l.iloc[i-1]
        if pd.isna(as_) or pd.isna(al_) or al_ == 0: continue

        if as_ < al_ * compression:
            if pc > rh and pc > df['high'].iloc[i-2] and pc > ev:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = rl
            elif pc < rl and pc < df['low'].iloc[i-2] and pc < ev:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = rh

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 9: Engulfing + Volume ─────────────────────────────
def strategy_engulfing_volume(df, vol_period=20, vol_mult=1.5, ema_trend=50):
    """Engulfing + volume surge from closed bars. Entry next open."""
    df = df.copy()
    avg_vol = df['volume'].shift(1).rolling(vol_period).mean()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(3, len(df)):
        po = df['open'].iloc[i-2];  pc = df['close'].iloc[i-2]
        co = df['open'].iloc[i-1];  cc = df['close'].iloc[i-1]
        cl = df['low'].iloc[i-1];   ch = df['high'].iloc[i-1]
        vol = df['volume'].iloc[i-1]
        av  = avg_vol.iloc[i-1]
        ev  = ema.iloc[i-1]
        if pd.isna(av) or av == 0: continue

        surge = vol > av * vol_mult
        bull  = pc < po and cc > co and cc > po and co < pc
        bear  = pc > po and cc < co and cc < po and co > pc

        if bull and surge and cc > ev:
            sigs.iloc[i-1] = 1;  stops.iloc[i-1] = cl
        elif bear and surge and cc < ev:
            sigs.iloc[i-1] = -1; stops.iloc[i-1] = ch

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 10: Three Bar Play ─────────────────────────────────
def strategy_three_bar_play(df, body_pct=0.6, ema_trend=50):
    """
    Bar[i-3]: strong trend candle.
    Bar[i-2]: inside bar.
    Bar[i-1]: breaks inside bar in direction of bar[i-3].
    Signal at bar[i-1] close. Entry at bar[i] open.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(4, len(df)):
        # Strong candle = i-3
        b1o = df['open'].iloc[i-3];   b1c = df['close'].iloc[i-3]
        b1h = df['high'].iloc[i-3];   b1l = df['low'].iloc[i-3]
        b1body = abs(b1c - b1o);       b1rng = b1h - b1l
        if b1rng == 0: continue
        b1_bull = b1c > b1o

        # Inside bar = i-2
        b2h = df['high'].iloc[i-2];   b2l = df['low'].iloc[i-2]
        if not (b2h < b1h and b2l > b1l): continue

        # Breakout bar = i-1
        b3c = df['close'].iloc[i-1]
        ev  = ema.iloc[i-1]

        if b1body / b1rng >= body_pct:
            if b1_bull and b3c > b2h and b3c > ev:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = b2l
            elif not b1_bull and b3c < b2l and b3c < ev:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = b2h

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 11: Pin Bar at S/R ─────────────────────────────────
def strategy_pin_bar_sr(df, wick_ratio=2.0, sr_lookback=20, sr_tol=0.005):
    """Pin bar[i-1] rejecting swing high/low from last sr_lookback bars."""
    df = df.copy()
    ema50 = _ema(df['close'], 50)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(sr_lookback + 2, len(df)):
        o = df['open'].iloc[i-1];   c = df['close'].iloc[i-1]
        h = df['high'].iloc[i-1];   l = df['low'].iloc[i-1]
        body  = abs(c - o)
        upper = h - max(o, c)
        lower = min(o, c) - l
        if body == 0: continue

        # S/R from bars before i-1 only (no lookahead)
        sh = df['high'].iloc[i-1-sr_lookback:i-1].max()
        sl = df['low'].iloc[i-1-sr_lookback:i-1].min()

        if lower >= body*wick_ratio and upper <= body*0.5:
            if abs(l - sl) <= sl * sr_tol:
                sigs.iloc[i-1] = 1;  stops.iloc[i-1] = l
        elif upper >= body*wick_ratio and lower <= body*0.5:
            if abs(h - sh) <= sh * sr_tol:
                sigs.iloc[i-1] = -1; stops.iloc[i-1] = h

    return _signals_to_list(sigs, stops)


# ─── STRATEGY 12: Morning/Evening Star ───────────────────────────
def strategy_star_patterns(df, doji_ratio=0.3, ema_trend=50):
    """
    Bars i-3, i-2, i-1 form the 3-candle pattern.
    Signal at close of i-1. Entry at open of i.
    """
    df = df.copy()
    ema = _ema(df['close'], ema_trend)

    sigs = pd.Series(0, index=df.index, dtype=int)
    stops = pd.Series(np.nan, index=df.index)

    for i in range(4, len(df)):
        b1o = df['open'].iloc[i-3];  b1c = df['close'].iloc[i-3]
        b1h = df['high'].iloc[i-3];  b1l = df['low'].iloc[i-3]
        b2o = df['open'].iloc[i-2];  b2c = df['close'].iloc[i-2]
        b2h = df['high'].iloc[i-2];  b2l = df['low'].iloc[i-2]
        b3o = df['open'].iloc[i-1];  b3c = df['close'].iloc[i-1]
        b3h = df['high'].iloc[i-1];  b3l = df['low'].iloc[i-1]

        b2rng  = b2h - b2l
        if b2rng == 0: continue
        b2body = abs(b2c - b2o)

        b1_bear = b1c < b1o;  b1_bull = b1c > b1o
        b2_doji = b2body / b2rng <= doji_ratio
        b3_bull = b3c > b3o;  b3_bear = b3c < b3o
        ev = ema.iloc[i-1]

        if b1_bear and b2_doji and b3_bull and b3c > ev:
            p_low = min(b1l, b2l, b3l)
            sigs.iloc[i-1] = 1;  stops.iloc[i-1] = p_low
        elif b1_bull and b2_doji and b3_bear and b3c < ev:
            p_high = max(b1h, b2h, b3h)
            sigs.iloc[i-1] = -1; stops.iloc[i-1] = p_high

    return _signals_to_list(sigs, stops)




# ─── LOOKAHEAD VALIDATOR ─────────────────────────────────────────
def validate_no_lookahead(signals: List[Dict], n_bars: int) -> List[Dict]:
    """
    Sanity check: remove any signal where bar_index >= n_bars-1
    (can't trade the last bar since we need next-bar entry).
    Also remove bar_index 0 (no previous bar available).
    """
    return [s for s in signals if 1 <= s['bar_index'] < n_bars - 1]

# ─── REGISTRY ────────────────────────────────────────────────────
STRATEGY_REGISTRY = {
    "VCB":               {"func": strategy_vcb,              "params": {"atr_short":[3,5,7],     "atr_long":[14,20],    "compression":[0.6,0.7,0.8], "range_len":[3,4,5]}},
    "InsideBar":         {"func": strategy_inside_bar,       "params": {"min_body_pct":[0.4,0.5,0.6], "ema_confirm":[0,21,50]}},
    "Engulfing":         {"func": strategy_engulfing,        "params": {"ema_trend":[21,50,100], "require_trend":[True,False]}},
    "PinBar":            {"func": strategy_pin_bar,          "params": {"wick_ratio":[1.5,2.0,2.5], "ema_trend":[21,50], "require_trend":[True,False]}},
    "OutsideBar":        {"func": strategy_outside_bar,      "params": {"ema_trend":[21,50,100]}},
    "Fakey":             {"func": strategy_fakey,            "params": {"range_len":[3,5,7]}},
    "VCB_RSI":           {"func": strategy_vcb_rsi,          "params": {"atr_short":[5,7], "atr_long":[20], "compression":[0.65,0.75], "range_len":[3,5], "rsi_period":[10,14], "rsi_bull":[45,55], "rsi_bear":[45,55]}},
    "VCB_EMA":           {"func": strategy_vcb_ema,          "params": {"atr_short":[5,7], "atr_long":[20], "compression":[0.65,0.75], "range_len":[3,5], "ema_period":[21,50,100]}},
    "Engulfing_Volume":  {"func": strategy_engulfing_volume, "params": {"vol_period":[10,20], "vol_mult":[1.3,1.5,2.0], "ema_trend":[21,50]}},
    "ThreeBarPlay":      {"func": strategy_three_bar_play,   "params": {"body_pct":[0.5,0.6,0.7], "ema_trend":[21,50]}},
    "PinBar_SR":         {"func": strategy_pin_bar_sr,       "params": {"wick_ratio":[1.5,2.0,2.5], "sr_lookback":[10,20], "sr_tol":[0.003,0.006]}},
    "StarPatterns":      {"func": strategy_star_patterns,    "params": {"doji_ratio":[0.2,0.3], "ema_trend":[21,50]}},
}


def get_all_param_combinations(strategy_name: str, max_combos: int = 20) -> List[Dict]:
    if strategy_name not in STRATEGY_REGISTRY:
        return []
    grid = STRATEGY_REGISTRY[strategy_name]["params"]
    keys, values = list(grid.keys()), list(grid.values())
    all_combos = list(itertools.product(*values))
    if len(all_combos) > max_combos:
        step = max(1, len(all_combos) // max_combos)
        all_combos = all_combos[::step][:max_combos]
    return [dict(zip(keys, combo)) for combo in all_combos]


# ─── CUSTOM STRATEGY MANAGER ──────────────────────────────────────
"""
Custom strategies uploaded by user at runtime.
Format required in uploaded .py file:

    def get_signals(df: pd.DataFrame, **params) -> List[Dict]:
        # df has columns: date, open, high, low, close, volume
        # Return list of: {'bar_index': int, 'signal': 1 or -1, 'stop_price': float}
        # signal = 1 (long), -1 (short)
        # bar_index = index of signal bar (entry will be next bar's open)
        pass

    PARAMS = {
        "param1": [val1, val2],   # param grid for backtesting
        "param2": [val1, val2],
    }

    NAME = "MyStrategy"   # optional, defaults to filename
"""

import importlib.util
import os
import traceback

_CUSTOM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom")
os.makedirs(_CUSTOM_DIR, exist_ok=True)


def load_custom_strategies():
    """Load all .py files from strategies/custom/ into STRATEGY_REGISTRY."""
    loaded = []
    errors = []
    for fname in os.listdir(_CUSTOM_DIR):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(_CUSTOM_DIR, fname)
        strat_name = fname[:-3]  # strip .py
        try:
            spec = importlib.util.spec_from_file_location(strat_name, fpath)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # Get function — must be named get_signals
            if not hasattr(mod, "get_signals"):
                errors.append(f"{fname}: missing get_signals() function")
                continue

            fn     = mod.get_signals
            params = getattr(mod, "PARAMS", {})
            name   = getattr(mod, "NAME", strat_name)

            STRATEGY_REGISTRY[name] = {"func": fn, "params": params, "custom": True, "filename": fname}
            loaded.append(name)
            print(f"[STRATEGY] Loaded custom: {name} from {fname}")
        except Exception as e:
            errors.append(f"{fname}: {e}")
            print(f"[STRATEGY] Error loading {fname}: {traceback.format_exc()}")

    return {"loaded": loaded, "errors": errors}


def remove_custom_strategy(name: str) -> bool:
    """Remove any strategy (built-in or custom) from the active registry.
    Built-ins are only removed from memory (reloaded on restart).
    Custom file is deleted from disk permanently.
    """
    if name not in STRATEGY_REGISTRY:
        return False
    entry = STRATEGY_REGISTRY[name]
    # If it's a custom file, delete from disk too
    if entry.get("custom"):
        fname = entry.get("filename", name + ".py")
        fpath = os.path.join(_CUSTOM_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
    del STRATEGY_REGISTRY[name]
    print(f"[STRATEGY] Removed from registry: {name}")
    return True


def save_custom_strategy(filename: str, code: str) -> dict:
    """Save uploaded strategy file and load it into registry."""
    if not filename.endswith(".py"):
        filename += ".py"
    fpath = os.path.join(_CUSTOM_DIR, filename)
    with open(fpath, "w") as f:
        f.write(code)
    result = load_custom_strategies()
    return result


def get_strategy_list():
    """Return list of all strategies with metadata."""
    out = []
    for name, entry in STRATEGY_REGISTRY.items():
        out.append({
            "name":     name,
            "custom":   entry.get("custom", False),
            "filename": entry.get("filename", "built-in"),
            "params":   list(entry["params"].keys()) if entry["params"] else [],
            "n_combos": len(get_all_param_combinations(name, 100)),
        })
    return out


# Auto-load custom strategies on import
load_custom_strategies()
