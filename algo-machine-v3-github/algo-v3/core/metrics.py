"""
Metrics Engine — computes all backtest performance metrics from trade list.
"""

import numpy as np
import pandas as pd
from typing import List, Dict


def compute_metrics(trades: List[Dict], initial_capital: float = 100000) -> Dict:
    """
    Compute full set of metrics from trade list.
    Each trade dict: {entry_date, exit_date, entry_price, exit_price, side, pnl, pnl_pct}
    """
    if not trades or len(trades) < 3:
        return _empty_metrics()

    df = pd.DataFrame(trades)
    pnls = df['pnl'].values
    pnl_pcts = df['pnl_pct'].values

    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    total_trades = len(trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total_trades if total_trades else 0

    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0
    gross_loss = float(np.sum(losses)) if len(losses) > 0 else 0
    net_pnl = gross_profit + gross_loss

    profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else 999.0

    # Expectancy per trade
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # Sharpe Ratio (annualized, daily returns assumption)
    if len(pnl_pcts) > 1:
        mean_ret = np.mean(pnl_pcts)
        std_ret = np.std(pnl_pcts, ddof=1)
        sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0
    else:
        sharpe = 0

    # Max Drawdown
    equity = np.cumsum(pnls) + initial_capital
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_drawdown = float(np.min(drawdown)) * 100  # as percentage

    # Max Losing Streak
    max_losing_streak = 0
    current_streak = 0
    for pnl in pnls:
        if pnl < 0:
            current_streak += 1
            max_losing_streak = max(max_losing_streak, current_streak)
        else:
            current_streak = 0

    # Max Winning Streak
    max_winning_streak = 0
    current_streak = 0
    for pnl in pnls:
        if pnl > 0:
            current_streak += 1
            max_winning_streak = max(max_winning_streak, current_streak)
        else:
            current_streak = 0

    # CAGR
    try:
        start_dt = pd.to_datetime(trades[0]['entry_date'])
        end_dt = pd.to_datetime(trades[-1]['exit_date'])
        years = (end_dt - start_dt).days / 365.25
        final_equity = initial_capital + net_pnl
        if years > 0.1 and final_equity > 0:
            cagr = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
        else:
            cagr = 0
    except Exception:
        cagr = 0

    # Calmar Ratio
    calmar = abs(cagr / max_drawdown) if max_drawdown != 0 else 0

    # Recovery Factor
    recovery_factor = abs(net_pnl / (max_drawdown / 100 * initial_capital)) if max_drawdown != 0 else 0

    # Composite Score (weighted ranking metric)
    composite_score = _compute_composite_score(
        win_rate, sharpe, profit_factor, max_drawdown, cagr, total_trades, calmar
    )

    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate * 100, 2),
        "expectancy": round(expectancy, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_drawdown, 2),
        "max_losing_streak": max_losing_streak,
        "max_winning_streak": max_winning_streak,
        "profit_factor": round(profit_factor, 3),
        "cagr": round(cagr, 2),
        "calmar": round(calmar, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "recovery_factor": round(recovery_factor, 3),
        "composite_score": round(composite_score, 4),
        "equity_curve": equity.tolist(),
    }


def _compute_composite_score(win_rate, sharpe, profit_factor, max_drawdown, cagr, total_trades, calmar):
    """
    Weighted composite score for ranking strategies.
    Higher is better.
    """
    # Normalize components (0-1 scale)
    wr_score = min(win_rate / 100, 1.0)                          # 0-100% → 0-1
    sharpe_score = min(max(sharpe, 0) / 3.0, 1.0)               # 0-3 → 0-1
    pf_score = min(max(profit_factor - 1, 0) / 3.0, 1.0)        # 1-4 → 0-1
    dd_score = max(1 + max_drawdown / 100, 0)                    # smaller DD → higher score
    cagr_score = min(max(cagr, 0) / 50.0, 1.0)                  # 0-50% → 0-1
    trade_score = min(total_trades / 100, 1.0)                   # more trades = more confidence
    calmar_score = min(max(calmar, 0) / 3.0, 1.0)

    # Weights
    score = (
        wr_score    * 0.20 +
        sharpe_score * 0.20 +
        pf_score    * 0.15 +
        dd_score    * 0.15 +
        cagr_score  * 0.15 +
        calmar_score * 0.10 +
        trade_score * 0.05
    )
    return score


def _empty_metrics():
    return {
        "total_trades": 0, "win_count": 0, "loss_count": 0,
        "win_rate": 0, "expectancy": 0, "sharpe": 0,
        "max_drawdown": 0, "max_losing_streak": 0, "max_winning_streak": 0,
        "profit_factor": 0, "cagr": 0, "calmar": 0,
        "avg_win": 0, "avg_loss": 0, "gross_profit": 0,
        "gross_loss": 0, "net_pnl": 0, "recovery_factor": 0,
        "composite_score": 0, "equity_curve": [],
    }
