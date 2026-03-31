"""
Database Manager — SQLite schema, read/write helpers.
Tables: stocks, ohlc_data, backtest_results, strategy_files
"""

import sqlite3
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "algo_machine.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS stocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT UNIQUE NOT NULL,
        exchange TEXT DEFAULT 'NSE',
        security_id TEXT,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS ohlc_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        UNIQUE(symbol, timeframe, date)
    );

    CREATE TABLE IF NOT EXISTS backtest_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        params TEXT NOT NULL,
        rr REAL DEFAULT 2.0,
        risk_pct REAL DEFAULT 1.0,
        capital_tested REAL DEFAULT 100000,
        total_trades INTEGER,
        win_rate REAL,
        expectancy REAL,
        sharpe REAL,
        max_drawdown REAL,
        max_losing_streak INTEGER,
        max_winning_streak INTEGER,
        profit_factor REAL,
        cagr REAL,
        calmar REAL,
        avg_win REAL,
        avg_loss REAL,
        gross_profit REAL,
        gross_loss REAL,
        net_pnl REAL,
        recovery_factor REAL,
        regime TEXT,
        composite_score REAL,
        strategy_file TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS regime_analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        params TEXT NOT NULL,
        trending_up_winrate REAL,
        trending_down_winrate REAL,
        ranging_winrate REAL,
        volatile_winrate REAL,
        best_regime TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtest_results(symbol);
    CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_name);
    CREATE INDEX IF NOT EXISTS idx_backtest_score ON backtest_results(composite_score DESC);
    CREATE INDEX IF NOT EXISTS idx_ohlc ON ohlc_data(symbol, timeframe, date);
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")



def save_stock(symbol: str, exchange: str = "NSE", security_id: str = ""):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO stocks (symbol, exchange, security_id) VALUES (?,?,?)",
            (symbol.upper(), exchange, security_id)
        )
        conn.commit()
    finally:
        conn.close()


def save_ohlc(symbol: str, timeframe: str, df):
    """Save OHLC dataframe to DB."""
    conn = get_conn()
    try:
        for _, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO ohlc_data
                (symbol, timeframe, date, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                symbol.upper(), timeframe, str(row['date']),
                float(row['open']), float(row['high']),
                float(row['low']), float(row['close']),
                float(row.get('volume', 0))
            ))
        conn.commit()
    finally:
        conn.close()


def load_ohlc(symbol: str, timeframe: str):
    import pandas as pd
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT date, open, high, low, close, volume
            FROM ohlc_data WHERE symbol=? AND timeframe=?
            ORDER BY date ASC
        """, (symbol.upper(), timeframe)).fetchall()
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df['date'] = pd.to_datetime(df['date'])
        return df
    finally:
        conn.close()


def save_backtest_result(result: dict):
    conn = get_conn()
    params_str = json.dumps(result.get('params', {}))
    try:
        conn.execute("""
            INSERT INTO backtest_results
             (run_id, symbol, timeframe, strategy_name, params,
              rr, risk_pct, capital_tested,
              total_trades, win_rate, expectancy, sharpe,
              max_drawdown, max_losing_streak, max_winning_streak,
              profit_factor, cagr, calmar,
              avg_win, avg_loss, gross_profit, gross_loss, net_pnl,
              recovery_factor, regime, composite_score, strategy_file)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            result.get('run_id', ''),
            result.get('symbol', ''),
            result.get('timeframe', ''),
            result.get('strategy_name', ''),
            params_str,
            result.get('rr', 2.0),
            result.get('risk_pct', 1.0),
            result.get('capital_tested', 100000),
            result.get('total_trades', 0),
            result.get('win_rate', 0),
            result.get('expectancy', 0),
            result.get('sharpe', 0),
            result.get('max_drawdown', 0),
            result.get('max_losing_streak', 0),
            result.get('max_winning_streak', 0),
            result.get('profit_factor', 0),
            result.get('cagr', 0),
            result.get('calmar', 0),
            result.get('avg_win', 0),
            result.get('avg_loss', 0),
            result.get('gross_profit', 0),
            result.get('gross_loss', 0),
            result.get('net_pnl', 0),
            result.get('recovery_factor', 0),
            result.get('regime', 'all'),
            result.get('composite_score', 0),
            result.get('strategy_file', '')
        ))
        conn.commit()
    except Exception as e:
        print(f"[DB] save error: {e}")
    finally:
        conn.close()


def get_top_strategies(limit=50, min_trades=20):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM backtest_results
            WHERE total_trades >= ? AND win_rate > 0
            ORDER BY composite_score DESC
            LIMIT ?
        """, (min_trades, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_strategies_by_symbol(symbol: str):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM backtest_results
            WHERE symbol=? AND total_trades >= 10
            ORDER BY composite_score DESC
            LIMIT 30
        """, (symbol.upper(),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_symbols():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT symbol FROM backtest_results ORDER BY symbol").fetchall()
        return [r['symbol'] for r in rows]
    finally:
        conn.close()


def get_run_stats():
    conn = get_conn()
    try:
        stats = conn.execute("""
            SELECT
                COUNT(*) as total_backtests,
                COUNT(DISTINCT symbol) as symbols_tested,
                COUNT(DISTINCT strategy_name) as strategies_tested,
                MAX(composite_score) as best_score,
                MAX(win_rate) as best_winrate
            FROM backtest_results WHERE total_trades >= 10
        """).fetchone()
        return dict(stats) if stats else {}
    finally:
        conn.close()


def delete_strategy(strategy_id: int):
    """Delete a strategy by its DB id."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM backtest_results WHERE id=?", (strategy_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] delete error: {e}")
        return False
    finally:
        conn.close()


def delete_strategies_by_symbol(symbol: str):
    """Delete all strategies for a symbol."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM backtest_results WHERE symbol=?", (symbol.upper(),))
        conn.commit()
        return True
    finally:
        conn.close()


def get_leaderboard():
    """Top strategy per category for leaderboard display."""
    conn = get_conn()
    try:
        categories = {
            "highest_score":    ("composite_score DESC", "Best Overall Score"),
            "highest_winrate":  ("win_rate DESC", "Highest Win Rate"),
            "best_rr":          ("rr DESC", "Best RR Ratio"),
            "most_trades":      ("total_trades DESC", "Most Trades"),
            "best_calmar":      ("calmar DESC", "Best Calmar"),
            "best_pf":          ("profit_factor DESC", "Best Profit Factor"),
        }
        results = {}
        for key, (order, label) in categories.items():
            row = conn.execute(f"""
                SELECT *, '{label}' as category_label
                FROM backtest_results
                WHERE total_trades >= 10 AND win_rate > 0
                ORDER BY {order} LIMIT 10
            """).fetchall()
            results[key] = [dict(r) for r in row]
        return results
    finally:
        conn.close()


def get_dashboard_stats():
    """Aggregated stats for the dashboard."""
    conn = get_conn()
    try:
        stats = conn.execute("""
            SELECT
                COUNT(*) as total_strategies,
                COUNT(DISTINCT symbol) as symbols_tested,
                COUNT(DISTINCT strategy_name) as unique_strategies,
                COUNT(DISTINCT timeframe) as timeframes_used,
                ROUND(AVG(win_rate), 1) as avg_win_rate,
                ROUND(AVG(profit_factor), 2) as avg_profit_factor,
                ROUND(MAX(composite_score), 3) as best_score,
                ROUND(MAX(win_rate), 1) as best_win_rate,
                ROUND(MAX(net_pnl), 0) as best_net_pnl,
                SUM(CASE WHEN win_rate >= 55 THEN 1 ELSE 0 END) as high_wr_count
            FROM backtest_results WHERE total_trades >= 10
        """).fetchone()

        by_strategy = conn.execute("""
            SELECT strategy_name,
                   COUNT(*) as count,
                   ROUND(AVG(win_rate),1) as avg_wr,
                   ROUND(AVG(composite_score),3) as avg_score
            FROM backtest_results WHERE total_trades >= 10
            GROUP BY strategy_name ORDER BY avg_score DESC
        """).fetchall()

        by_symbol = conn.execute("""
            SELECT symbol,
                   COUNT(*) as count,
                   ROUND(AVG(win_rate),1) as avg_wr,
                   ROUND(MAX(composite_score),3) as best_score
            FROM backtest_results WHERE total_trades >= 10
            GROUP BY symbol ORDER BY best_score DESC LIMIT 15
        """).fetchall()

        by_tf = conn.execute("""
            SELECT timeframe,
                   COUNT(*) as count,
                   ROUND(AVG(win_rate),1) as avg_wr
            FROM backtest_results WHERE total_trades >= 10
            GROUP BY timeframe
        """).fetchall()

        return {
            "summary":     dict(stats) if stats else {},
            "by_strategy": [dict(r) for r in by_strategy],
            "by_symbol":   [dict(r) for r in by_symbol],
            "by_tf":       [dict(r) for r in by_tf],
        }
    finally:
        conn.close()


def get_filtered_strategies(
    limit=100, min_trades=8, sort_by="composite_score",
    min_winrate=0, symbol=None, strategy_name=None,
    timeframe=None, regime=None
):
    conn = get_conn()
    try:
        wheres = ["total_trades >= ?", "win_rate >= ?"]
        params = [min_trades, min_winrate]
        if symbol:
            wheres.append("symbol = ?"); params.append(symbol.upper())
        if strategy_name:
            wheres.append("strategy_name = ?"); params.append(strategy_name)
        if timeframe:
            wheres.append("timeframe = ?"); params.append(timeframe)
        if regime:
            wheres.append("regime = ?"); params.append(regime)

        safe_sort = sort_by if sort_by in (
            "composite_score","win_rate","total_trades","net_pnl",
            "profit_factor","calmar","sharpe","rr","cagr"
        ) else "composite_score"

        q = f"""
            SELECT * FROM backtest_results
            WHERE {" AND ".join(wheres)}
            ORDER BY {safe_sort} DESC
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
