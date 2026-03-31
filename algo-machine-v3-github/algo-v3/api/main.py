"""
FastAPI Backend — REST API for the Algo Machine.
Endpoints: run machine, get strategies, download files, stream logs.
"""

import os
import sys
import json
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
IST = ZoneInfo('Asia/Kolkata')
from typing import Optional, List
from pathlib import Path

# Project root is one level up from api/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, Query, BackgroundTasks, Request
from fastapi.responses import (FileResponse, StreamingResponse,
                                HTMLResponse, JSONResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

from core.database import (init_db, get_top_strategies, get_strategies_by_symbol,
                            get_all_symbols, get_run_stats, get_conn,
                            delete_strategy, delete_strategies_by_symbol,
                            get_leaderboard, get_dashboard_stats, get_filtered_strategies)
from core.backtest_engine import (run_full_machine, run_quick,
                                  set_progress_callback, STRATEGY_REGISTRY)
from strategies.strategy_library import (get_strategy_list, save_custom_strategy,
                                         remove_custom_strategy, load_custom_strategies)
from data.dhan_fetcher import STOCK_UNIVERSE

app = FastAPI(title="Algo Machine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
# Resolved from project root — works locally and inside Docker
frontend_path = os.path.join(PROJECT_ROOT, "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# Global run state
run_state = {
    "is_running": False,
    "logs": [],
    "progress": {},
    "last_run": None,
}
log_queue = asyncio.Queue()


def push_log(event: dict):
    """Thread-safe log pusher — captures all event types including overall_progress."""
    run_state["logs"].append(event)
    if len(run_state["logs"]) > 500:
        run_state["logs"] = run_state["logs"][-500:]
    # Engine sends "overall_progress" — capture it
    if event.get("type") in ("progress", "overall_progress"):
        run_state["progress"].update(event)
    if event.get("type") == "complete":
        run_state["is_running"] = False
        run_state["last_run"] = datetime.now(IST).isoformat()
        run_state["progress"]["pct"] = 100


# ── Root → serve dashboard ──────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = os.path.join(PROJECT_ROOT, "frontend", "index.html")
    if os.path.exists(html_path):
        async with aiofiles.open(html_path, 'r') as f:
            return await f.read()
    # Debug: show what path was checked
    return HTMLResponse(f"<h1>Algo Machine API</h1><p>Frontend not found at: {html_path}</p>")


# ── Health ──────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ── Run Machine ─────────────────────────────────────────────────
@app.post("/api/run")
def start_run(
    symbols: Optional[str] = Query(None, description="Comma-separated symbols, or 'all'"),
    timeframes: Optional[str] = Query("1D", description="Comma-separated timeframes"),
    quick: bool = Query(False, description="Quick test with 5 symbols"),
    n_symbols: int = Query(5, description="Symbols for quick run"),
    capital: float = Query(100000, description="Starting capital in INR"),
    risk_pct: float = Query(1.0, description="Risk % per trade (e.g. 1.0 = 1%)")
):
    if run_state["is_running"]:
        return JSONResponse({"error": "Machine already running"}, status_code=409)

    run_state["is_running"] = True
    run_state["logs"] = []
    run_state["progress"] = {}

    set_progress_callback(push_log)

    symbol_list = None
    if symbols and symbols != "all":
        symbol_list = [s.strip().upper() for s in symbols.split(",")]

    tf_list = [t.strip() for t in timeframes.split(",")]

    def _run():
        try:
            if quick:
                run_quick(n_symbols=n_symbols, capital=capital, risk_pct=risk_pct)
            else:
                run_full_machine(symbols=symbol_list, timeframes=tf_list,
                                 capital=capital, risk_pct=risk_pct)
        except Exception as e:
            push_log({"type": "error", "message": str(e)})
            run_state["is_running"] = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"status": "started", "quick": quick, "capital": capital, "risk_pct": risk_pct}


# ── Run Status ──────────────────────────────────────────────────
@app.get("/api/status")
def get_status():
    return {
        "is_running": run_state["is_running"],
        "last_run": run_state["last_run"],
        "progress": run_state["progress"],
        "log_count": len(run_state["logs"]),
        "recent_logs": run_state["logs"][-20:],
    }


# ── SSE Log Stream ──────────────────────────────────────────────
@app.get("/api/logs/stream")
async def stream_logs():
    """Server-Sent Events stream for real-time logs."""
    async def event_generator():
        sent_idx = 0
        while True:
            logs = run_state["logs"]
            if sent_idx < len(logs):
                for log in logs[sent_idx:]:
                    yield f"data: {json.dumps(log)}\n\n"
                sent_idx = len(logs)
            if not run_state["is_running"] and sent_idx >= len(logs):
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")



# ── Stats ────────────────────────────────────────────────────────
@app.get("/api/stats")
def stats():
    init_db()
    db_stats = get_run_stats()
    symbols = get_all_symbols()
    return {
        "db_stats": db_stats,
        "symbols_in_db": symbols,
        "available_symbols": list(STOCK_UNIVERSE.keys()),
        "available_strategies": list(STRATEGY_REGISTRY.keys()),
        "is_running": run_state["is_running"],
    }


@app.get("/api/dashboard")
def dashboard():
    return get_dashboard_stats()


@app.get("/api/leaderboard")
def leaderboard():
    return get_leaderboard()


@app.delete("/api/db/clear")
def clear_db():
    conn = get_conn()
    try:
        conn.execute("DELETE FROM backtest_results")
        conn.execute("DELETE FROM ohlc_data")
        conn.commit()
        return {"status": "cleared"}
    finally:
        conn.close()


# ── Strategies — fixed paths MUST come before {param} wildcards ──

@app.get("/api/strategies/top")
def top_strategies(
    limit: int = Query(50, le=200),
    min_trades: int = Query(8),
    min_winrate: float = Query(0),
    strategy_name: Optional[str] = None,
    symbol: Optional[str] = None,
    regime: Optional[str] = None,
    sort_by: str = Query("composite_score")
):
    init_db()
    conn = get_conn()
    try:
        query = "SELECT * FROM backtest_results WHERE total_trades >= ? AND win_rate >= ?"
        args = [min_trades, min_winrate]
        if strategy_name:
            query += " AND strategy_name = ?"; args.append(strategy_name)
        if symbol:
            query += " AND symbol = ?"; args.append(symbol.upper())
        if regime:
            query += " AND regime = ?"; args.append(regime)
        valid_sorts = ["composite_score","win_rate","sharpe","cagr","profit_factor","calmar","net_pnl","total_trades"]
        if sort_by not in valid_sorts: sort_by = "composite_score"
        query += f" ORDER BY {sort_by} DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(query, args).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try: d['params'] = json.loads(d['params'])
            except: pass
            results.append(d)
        return {"strategies": results, "count": len(results)}
    finally:
        conn.close()


@app.get("/api/strategies/filter")
def filter_strategies(
    limit: int = Query(100),
    min_trades: int = Query(8),
    sort_by: str = Query("composite_score"),
    min_winrate: float = Query(0),
    symbol: Optional[str] = Query(None),
    strategy_name: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
):
    return get_filtered_strategies(limit, min_trades, sort_by, min_winrate,
                                   symbol, strategy_name, timeframe, regime)


@app.get("/api/strategies/library")
def strategy_library():
    return get_strategy_list()


@app.get("/api/strategies/names")
def strategy_names():
    return list(STRATEGY_REGISTRY.keys())


@app.post("/api/strategies/upload")
async def upload_strategy(request: Request):
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "No file in request"}, status_code=400)
    filename = file.filename
    if not filename.endswith(".py"):
        return JSONResponse({"error": "File must be a .py file"}, status_code=400)
    code = (await file.read()).decode("utf-8")
    if "get_signals" not in code:
        return JSONResponse({"error": "Strategy file must contain a get_signals(df, **params) function"}, status_code=400)
    result = save_custom_strategy(filename, code)
    return {"status": "ok", "filename": filename, "loaded": result["loaded"], "errors": result["errors"]}


@app.post("/api/strategies/reload")
def reload_strategies():
    result = load_custom_strategies()
    return {"status": "ok", **result}


@app.post("/api/strategies/restore-builtins")
def restore_builtins():
    import importlib
    import strategies.strategy_library as sl
    importlib.reload(sl)
    STRATEGY_REGISTRY.clear()
    STRATEGY_REGISTRY.update(sl.STRATEGY_REGISTRY)
    return {"status": "ok", "strategies": list(STRATEGY_REGISTRY.keys())}


# ── DELETE fixed paths before wildcard ───────────────────────────

@app.delete("/api/strategies/custom/{name}")
def remove_custom(name: str):
    ok = remove_custom_strategy(name)
    if ok:
        return {"removed": name}
    return JSONResponse({"error": f"'{name}' not found"}, status_code=404)


@app.delete("/api/strategies/symbol/{symbol}")
def delete_by_symbol(symbol: str):
    delete_strategies_by_symbol(symbol)
    return {"deleted_symbol": symbol}


# ── Wildcard routes LAST ─────────────────────────────────────────

@app.get("/api/strategies/symbol/{symbol}")
def strategies_by_symbol(symbol: str):
    init_db()
    results = get_strategies_by_symbol(symbol)
    for r in results:
        try: r['params'] = json.loads(r['params'])
        except: pass
    return {"symbol": symbol, "strategies": results}


@app.get("/api/strategies/download/{strategy_id}")
def download_strategy(strategy_id: int):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT strategy_file, symbol, strategy_name FROM backtest_results WHERE id=?",
            (strategy_id,)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "Strategy not found"}, status_code=404)
        filepath = row['strategy_file']
        if not filepath or not os.path.exists(filepath):
            return JSONResponse({"error": f"File not found: {filepath}"}, status_code=404)
        return FileResponse(filepath, media_type="text/x-python",
                            filename=os.path.basename(filepath),
                            headers={"Content-Disposition": f'attachment; filename="{os.path.basename(filepath)}"'})
    finally:
        conn.close()


@app.get("/api/strategies/code/{strategy_id}")
async def preview_strategy_code(strategy_id: int):
    conn = get_conn()
    try:
        row = conn.execute("SELECT strategy_file FROM backtest_results WHERE id=?", (strategy_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        filepath = row['strategy_file']
        if not filepath or not os.path.exists(filepath):
            return JSONResponse({"error": "File not on disk"}, status_code=404)
        async with aiofiles.open(filepath, 'r') as f:
            code = await f.read()
        return {"code": code, "filepath": filepath}
    finally:
        conn.close()


@app.delete("/api/strategies/{strategy_id}")
def delete_strategy_by_id(strategy_id: int):
    ok = delete_strategy(strategy_id)
    if ok:
        return {"deleted": strategy_id}
    return JSONResponse({"error": "Not found"}, status_code=404)


@app.get("/api/symbols/available")
def available_symbols():
    return list(STOCK_UNIVERSE.keys())


@app.on_event("startup")
def startup():
    init_db()
    os.makedirs(os.getenv("OUTPUT_DIR", "output_strategies"), exist_ok=True)
    print("[API] Algo Machine API started")
