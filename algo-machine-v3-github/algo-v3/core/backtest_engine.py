"""
Backtest Engine v3
==================
Fixes applied:
  1. PARALLEL EXECUTION  — ProcessPoolExecutor, N_WORKERS = cpu_count
  2. NEXT-BAR ENTRY      — entry at OPEN of bar after signal, not signal bar close
  3. TRANSACTION COSTS   — brokerage 0.03% + slippage 0.02% per side = 0.05% per side
  4. LOOKAHEAD-FREE      — strategy library uses shifted data; engine respects bar_index+1

Architecture:
  run_full_machine()
      → builds flat task list: (symbol, tf, strategy, params, rr)
      → submits all tasks to ProcessPoolExecutor
      → workers call _worker_task() independently
      → results collected, saved to DB, progress reported via shared counter
"""

import uuid, time, traceback, math, os, sys
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager, cpu_count
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import init_db, save_stock, save_ohlc, load_ohlc, save_backtest_result, get_run_stats
from core.metrics import compute_metrics
from core.regime_filter import label_regimes, get_regime_breakdown
from data.dhan_fetcher import fetch_dhan_ohlc, STOCK_UNIVERSE
from strategies.strategy_library import STRATEGY_REGISTRY, get_all_param_combinations
from strategies.strategy_generator import generate_strategy_file

# ── Config ────────────────────────────────────────────────────────
DEFAULT_TIMEFRAMES  = ["1D"]
RR_RATIOS           = [1.0, 1.5, 2.0, 3.0, 4.0]
MIN_TRADES          = 10
MIN_SCORE           = 0.18
N_WORKERS           = max(2, cpu_count() - 1)   # leave 1 core for OS/API

# ── Transaction costs (India, realistic) ─────────────────────────
# Zerodha intraday: 0.03% brokerage, ~0.02% slippage/spread per side
COST_PER_SIDE_PCT   = 0.05   # 0.05% per side = 0.10% round trip
# For swing/daily, slippage lower:
COST_SWING_PCT      = 0.03   # 0.03% per side = 0.06% round trip

PROGRESS_CALLBACK   = None

def set_progress_callback(fn):
    global PROGRESS_CALLBACK
    PROGRESS_CALLBACK = fn

def _log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    if PROGRESS_CALLBACK:
        PROGRESS_CALLBACK({"type": "log", "message": line})


# ── Position Sizing ───────────────────────────────────────────────
def calc_qty(capital: float, risk_pct: float,
             entry_price: float, stop_price: float) -> int:
    """
    qty = floor( (capital × risk%) / SL_distance )
    Capped at 100% capital deployed.
    """
    sl_dist = abs(entry_price - stop_price)
    if sl_dist <= 0:
        return 0
    risk_amt = capital * (risk_pct / 100.0)
    qty = math.floor(risk_amt / sl_dist)
    max_qty = math.floor(capital / entry_price) if entry_price > 0 else 0
    return max(min(qty, max_qty), 0)


# ── Execute Signals ───────────────────────────────────────────────
def execute_signals(df, signals: List[Dict], rr: float,
                    capital: float, risk_pct: float,
                    timeframe: str = "1D") -> List[Dict]:
    """
    KEY FIXES:
      - Entry at OPEN of bar_index + 1 (next bar after signal)
      - Transaction cost deducted from PnL on every trade
      - SL/TP checked against bar high/low (realistic fill)
    
    Cost model:
      - entry_cost  = entry_price  × qty × COST_PER_SIDE_PCT/100
      - exit_cost   = exit_price   × qty × COST_PER_SIDE_PCT/100
      - total_cost  = entry_cost + exit_cost
      - net_pnl     = gross_pnl - total_cost
    """
    # Intraday gets higher cost, daily/weekly gets lower
    cost_pct = COST_PER_SIDE_PCT if timeframe in ("5M","15M","1H") else COST_SWING_PCT

    trades  = []
    equity  = capital
    in_trade = False
    meta    = {}

    # Map: bar_index (signal bar) → signal dict
    sig_map = {s['bar_index']: s for s in signals}

    for i in range(len(df)):
        bar = df.iloc[i]

        # ── Check open trade ──────────────────────────────────────
        if in_trade:
            entry  = meta['entry_price']
            sl     = meta['stop_price']
            tp     = meta['tp_price']
            side   = meta['signal']
            qty    = meta['qty']

            exit_price  = None
            exit_reason = None

            if side == 1:   # Long
                if bar['low'] <= sl:
                    exit_price  = sl
                    exit_reason = 'SL'
                elif bar['high'] >= tp:
                    exit_price  = tp
                    exit_reason = 'TP'
            else:           # Short
                if bar['high'] >= sl:
                    exit_price  = sl
                    exit_reason = 'SL'
                elif bar['low'] <= tp:
                    exit_price  = tp
                    exit_reason = 'TP'

            if exit_price is not None:
                gross_pnl  = side * (exit_price - entry) * qty
                # Transaction costs: entry + exit side
                entry_cost = meta['entry_price'] * qty * (cost_pct / 100)
                exit_cost  = exit_price * qty * (cost_pct / 100)
                total_cost = entry_cost + exit_cost
                net_pnl    = gross_pnl - total_cost

                equity += net_pnl
                pnl_pct = side * (exit_price - entry) / entry * 100

                trades.append({
                    'entry_date':    str(meta['entry_date']),
                    'exit_date':     str(bar['date']),
                    'entry_price':   round(entry, 4),
                    'exit_price':    round(exit_price, 4),
                    'stop_price':    round(sl, 4),
                    'tp_price':      round(tp, 4),
                    'side':          'LONG' if side == 1 else 'SHORT',
                    'qty':           qty,
                    'gross_pnl':     round(gross_pnl, 2),
                    'cost':          round(total_cost, 2),
                    'pnl':           round(net_pnl, 2),
                    'pnl_pct':       round(pnl_pct, 3),
                    'exit_reason':   exit_reason,
                    'rr':            rr,
                    'equity_after':  round(equity, 2),
                })
                in_trade = False

        # ── Check for new signal — enter at NEXT BAR OPEN ─────────
        # Signal was at bar i-1, so we enter at open of bar i
        if not in_trade and i > 0 and (i - 1) in sig_map:
            sig         = sig_map[i - 1]
            # *** NEXT BAR OPEN ENTRY — key fix ***
            entry_price = float(bar['open'])
            stop_price  = sig['stop_price']
            direction   = sig['signal']

            sl_dist = abs(entry_price - stop_price)
            if sl_dist <= 0:
                continue

            # Skip if SL is unrealistically wide (>12%)
            if sl_dist / entry_price > 0.12:
                continue

            # Verify direction still valid after gap open
            if direction == 1 and entry_price < stop_price:
                continue   # gapped down through stop — skip
            if direction == -1 and entry_price > stop_price:
                continue   # gapped up through stop — skip

            tp_price = entry_price + direction * sl_dist * rr
            qty      = calc_qty(equity, risk_pct, entry_price, stop_price)
            if qty <= 0:
                continue

            in_trade = True
            meta = {
                'entry_price': entry_price,
                'stop_price':  stop_price,
                'tp_price':    tp_price,
                'signal':      direction,
                'qty':         qty,
                'entry_date':  bar['date'],
            }

    return trades


# ── Worker task (runs in subprocess) ─────────────────────────────
def _worker_task(args: Tuple) -> Optional[Dict]:
    """
    Single unit of work: one strategy + one param combo + one RR on one symbol/tf.
    Runs in a worker process — must be fully self-contained.
    Returns best-RR result dict or None.
    """
    symbol, timeframe, strategy_name, params, capital, risk_pct, run_id, df_records = args

    try:
        import pandas as pd
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from strategies.strategy_library import STRATEGY_REGISTRY
        from core.metrics import compute_metrics
        from core.regime_filter import label_regimes, get_regime_breakdown
        from strategies.strategy_generator import generate_strategy_file

        df = pd.DataFrame(df_records)

        fn      = STRATEGY_REGISTRY[strategy_name]['func']
        signals = fn(df, **params)
        if not signals:
            return None

        best_result = None
        best_score  = 0.0

        for rr in RR_RATIOS:
            trades = execute_signals(df, signals, rr, capital, risk_pct, timeframe)
            if len(trades) < MIN_TRADES:
                continue
            metrics = compute_metrics(trades)
            if metrics['composite_score'] > best_score:
                best_score  = metrics['composite_score']
                best_result = (rr, trades, metrics)

        if best_result is None or best_score < MIN_SCORE:
            return None

        best_rr, best_trades, best_metrics = best_result

        df_r = label_regimes(df)
        regime_info  = get_regime_breakdown(best_trades, df_r)
        best_regime  = regime_info.get('best_regime', 'all')

        strategy_file = generate_strategy_file(
            strategy_name, params, symbol, timeframe,
            best_metrics, best_rr, risk_pct
        )

        return {
            'run_id':         run_id,
            'symbol':         symbol,
            'timeframe':      timeframe,
            'strategy_name':  strategy_name,
            'params':         params,
            'rr':             best_rr,
            'risk_pct':       risk_pct,
            'capital_tested': capital,
            'regime':         best_regime,
            'strategy_file':  strategy_file,
            **best_metrics
        }

    except Exception as e:
        return None


# ── Build flat task list ──────────────────────────────────────────
def _build_tasks(symbols, timeframes, capital, risk_pct, run_id,
                 df_cache: Dict) -> List[Tuple]:
    """
    Flatten symbol × tf × strategy × params into individual tasks.
    df passed as records (list of dicts) for pickle-safe inter-process transfer.
    """
    tasks = []
    for symbol in symbols:
        for tf in timeframes:
            key = f"{symbol}_{tf}"
            if key not in df_cache:
                continue
            df_records = df_cache[key]

            for strategy_name in STRATEGY_REGISTRY:
                combos = get_all_param_combinations(strategy_name, max_combos=15)
                for params in combos:
                    tasks.append((
                        symbol, tf, strategy_name, params,
                        capital, risk_pct, run_id, df_records
                    ))
    return tasks


# ── Fetch & cache all data upfront ───────────────────────────────
def _fetch_all_data(symbols, timeframes) -> Dict:
    """
    Fetch / load all OHLC data before parallelising.
    Returns dict key='SYMBOL_TF' → list of row dicts (pickle-safe).
    """
    cache = {}
    for symbol in symbols:
        save_stock(symbol)
        for tf in timeframes:
            key = f"{symbol}_{tf}"
            df = load_ohlc(symbol, tf)
            if df is None or len(df) < 100:
                _log(f"Fetching {symbol} [{tf}]...")
                df = fetch_dhan_ohlc(symbol, tf)
                if df is not None and len(df) >= 100:
                    save_ohlc(symbol, tf, df)
            if df is not None and len(df) >= 100:
                cache[key] = df.to_dict('records')
                _log(f"  ✓ {symbol} [{tf}] — {len(df)} bars")
            else:
                _log(f"  ✗ {symbol} [{tf}] — insufficient data", "WARN")
    return cache


# ── Full Machine Run ──────────────────────────────────────────────
def run_full_machine(symbols=None, timeframes=None,
                     capital=100000, risk_pct=1.0) -> Dict:
    init_db()
    run_id = str(uuid.uuid4())[:8]
    start  = time.time()

    symbols    = symbols    or list(STOCK_UNIVERSE.keys())
    timeframes = timeframes or DEFAULT_TIMEFRAMES

    n_strats  = sum(len(get_all_param_combinations(s, 15)) for s in STRATEGY_REGISTRY)
    total_est = len(symbols) * len(timeframes) * n_strats * len(RR_RATIOS)

    _log(f"═══ RUN {run_id} ═══")
    _log(f"Symbols={len(symbols)} | TFs={timeframes} | Workers={N_WORKERS}")
    _log(f"Capital=₹{capital:,.0f} | Risk={risk_pct}% per trade")
    _log(f"Cost model: {COST_SWING_PCT}% swing / {COST_PER_SIDE_PCT}% intraday per side")
    _log(f"Estimated tasks ~{total_est:,} (RR variants: {RR_RATIOS})")

    # Step 1: fetch all data sequentially (avoids N workers × M API calls)
    _log("Fetching market data...")
    df_cache = _fetch_all_data(symbols, timeframes)
    _log(f"Data ready: {len(df_cache)} symbol/tf combos")

    # Step 2: build flat task list
    tasks = _build_tasks(symbols, timeframes, capital, risk_pct, run_id, df_cache)
    total = len(tasks)
    _log(f"Submitting {total:,} tasks to {N_WORKERS} workers...")

    if PROGRESS_CALLBACK:
        PROGRESS_CALLBACK({"type": "overall_progress",
                           "completed": 0, "total": total, "pct": 0,
                           "found": 0, "run_id": run_id})

    # Step 3: parallel execution
    all_results = []
    done = 0

    with ProcessPoolExecutor(max_workers=N_WORKERS) as executor:
        futures = {executor.submit(_worker_task, t): t for t in tasks}

        for future in as_completed(futures):
            done += 1
            result = future.result()

            if result:
                save_backtest_result(result)
                all_results.append(result)
                _log(
                    f"✓ {result['symbol']} | {result['strategy_name']} | "
                    f"RR 1:{result['rr']} | WR={result['win_rate']:.1f}% | "
                    f"Score={result['composite_score']:.3f} | "
                    f"Trades={result['total_trades']} | TF={result['timeframe']}"
                )

            if done % 50 == 0 or result:
                pct = round(done / total * 100, 1)
                t = futures[future]
                if PROGRESS_CALLBACK:
                    PROGRESS_CALLBACK({
                        "type": "overall_progress",
                        "completed": done, "total": total,
                        "pct": pct, "found": len(all_results),
                        "symbol": t[0], "strategy": t[2],
                        "run_id": run_id
                    })

    elapsed = time.time() - start
    stats   = get_run_stats()
    summary = {
        "run_id":               run_id,
        "elapsed_seconds":      round(elapsed, 1),
        "total_tasks":          total,
        "total_valid_results":  len(all_results),
        "workers_used":         N_WORKERS,
        "db_stats":             stats,
    }
    _log(f"═══ COMPLETE in {elapsed:.1f}s | {len(all_results)} strategies found ═══")
    _log(f"Workers: {N_WORKERS} | Tasks: {total:,} | Speed: {total/elapsed:.0f} tasks/sec")

    if PROGRESS_CALLBACK:
        PROGRESS_CALLBACK({"type": "complete", "summary": summary})
    return summary


def run_quick(n_symbols=5, capital=100000, risk_pct=1.0):
    symbols = list(STOCK_UNIVERSE.keys())[:n_symbols]
    return run_full_machine(symbols=symbols, timeframes=["1D"],
                            capital=capital, risk_pct=risk_pct)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run_quick(n_symbols=2)
