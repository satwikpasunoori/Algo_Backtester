# ALGO MACHINE 🤖
### Autonomous Strategy Discovery & Backtesting Platform

---

## What It Does
This machine autonomously:
1. **Fetches OHLC data** from Dhan API (5 years, 30 NSE stocks)
2. **Discovers strategies** — 15 strategy families × parameter grids = 3,000+ backtests
3. **Backtests everything** with full metrics: Win Rate, Sharpe, CAGR, Max Drawdown, Losing Streak, Profit Factor, Calmar, Expectancy, and more
4. **Applies Regime Filter** — labels market as Trending Up/Down, Ranging, Volatile using ADX + ATR + Bollinger Width
5. **Scores & ranks** strategies using a composite score
6. **Saves to SQLite DB** — all results persisted
7. **Generates deployable `.py` files** — ready to plug into live Dhan trading
8. **Shows everything in a dashboard** — filter, sort, download strategy code

---

## Project Structure

```
algo-machine/
├── run_server.py          ← START HERE
├── requirements.txt
├── .env                   ← Your Dhan credentials
├── Dockerfile
├── docker-compose.yml
│
├── core/
│   ├── database.py        ← SQLite DB manager
│   ├── metrics.py         ← All performance metrics
│   ├── regime_filter.py   ← Market regime classifier
│   └── backtest_engine.py ← Main orchestrator
│
├── data/
│   └── dhan_fetcher.py    ← Dhan API + synthetic fallback
│
├── strategies/
│   ├── strategy_library.py   ← 15 strategies + param grids
│   └── strategy_generator.py ← Deployable .py file builder
│
├── api/
│   └── main.py            ← FastAPI backend
│
├── frontend/
│   └── index.html         ← Full dashboard UI
│
└── output_strategies/     ← Generated .py strategy files
```

---

## Quick Start — Docker (Recommended)

> **Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running. That's it.

### Step 1 — Add your Dhan credentials
```bash
cp .env.example .env
# Open .env and fill in:
#   DHAN_CLIENT_ID=your_client_id
#   DHAN_ACCESS_TOKEN=your_access_token
```
> **No credentials?** Leave them blank — the machine runs on synthetic data for testing.

### Step 2 — Launch (one command)

**Mac / Linux:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:** Double-click `start.bat`

**Or manually:**
```bash
docker compose up -d --build
```

### Step 3 — Open the dashboard
```
http://localhost:8000
```

### Step 4 — Run the machine
- Click **"Run Machine"** tab → choose Quick (5 stocks) or Full (30 stocks)
- Hit **START MACHINE** — fully autonomous from here
- Watch live logs stream in real time
- Check **Strategies** and **Leaderboard** tabs for results

### Useful Docker commands
```bash
docker compose logs -f       # View live logs
docker compose restart       # Restart (keeps DB and strategies)
docker compose down          # Stop
docker compose down -v       # Full reset (wipes DB and strategies)

# Copy generated strategy files to your machine:
docker cp algo-machine:/data/strategies ./my-strategies
```

---

## Quick Start — Without Docker (Python)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Add Dhan credentials
```bash
cp .env.example .env
# Edit .env and add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN
```
> Without credentials, synthetic data is used for testing.

### 3. Start the server
```bash
python run_server.py
```

### 4. Open dashboard → `http://localhost:8000`

---

## Strategies Included

| Strategy | Type | Parameters |
|---|---|---|
| EMA Crossover | Trend | fast, slow periods |
| RSI Mean Reversion | MeanRev | period, oversold, overbought |
| MACD | Momentum | fast, slow, signal |
| Bollinger Breakout | Breakout | period, std_dev |
| Bollinger Reversion | MeanRev | period, std_dev |
| Supertrend | Trend | atr_period, multiplier |
| Donchian Channel | Breakout | period |
| Stochastic | Oscillator | k_period, d_period |
| Volume Breakout | Volume | vol_period, vol_mult |
| Triple EMA | Trend | fast, mid, slow |
| RSI + EMA Combo | Combo | rsi_period, ema_period |
| Inside Bar | Price Action | — |
| Momentum ROC | Momentum | period, threshold |
| VWAP Reversion | MeanRev | period, deviation |
| Keltner Channel | Breakout | ema_period, multiplier |

---

## Metrics Computed

| Metric | Description |
|---|---|
| Win Rate | % of winning trades |
| Total Trades | Number of completed trades |
| Expectancy | Average P&L per trade |
| Sharpe Ratio | Risk-adjusted return (annualized) |
| Max Drawdown | Worst peak-to-trough decline |
| Max Losing Streak | Worst consecutive losses |
| Profit Factor | Gross profit / Gross loss |
| CAGR | Compound Annual Growth Rate |
| Calmar Ratio | CAGR / Max Drawdown |
| Avg Win / Avg Loss | Average trade size |
| Recovery Factor | Net P&L / Max Drawdown |
| Composite Score | Weighted ranking score (0–1) |

---

## Regime Filter

Each bar is labeled as:
- **TRENDING_UP** — ADX > 25 + EMA slope positive
- **TRENDING_DOWN** — ADX > 25 + EMA slope negative
- **RANGING** — ADX < 25, low volatility
- **VOLATILE** — ATR spike or BB width expansion

The system tells you which regime each strategy performs best in.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/run` | Start the machine |
| GET | `/api/status` | Get run status + logs |
| GET | `/api/strategies/top` | Get ranked strategies |
| GET | `/api/strategies/symbol/{sym}` | Strategies for one stock |
| GET | `/api/strategies/download/{id}` | Download `.py` strategy file |
| GET | `/api/leaderboard` | Top 10 per metric category |
| GET | `/api/stats` | DB summary stats |
| DELETE | `/api/db/clear` | Clear all results |

---

## Cloud Deployment

### Docker
```bash
docker-compose up -d
```

### Railway / Render / Fly.io
```bash
# Set env vars: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
# Start command: python run_server.py
# Port: 8000
```

### VPS (Ubuntu)
```bash
pip install -r requirements.txt
nohup python run_server.py &
# Or use systemd / supervisor for production
```

---

## Adding Your Own Strategy

1. Add function to `strategies/strategy_library.py`:
```python
def strategy_my_custom(df, param1=10, param2=20, stop_loss_pct=2.0, target_pct=4.0):
    # Your signal logic → return _execute_signals(df, signals, ...)
    pass
```

2. Register it:
```python
STRATEGY_REGISTRY["My_Custom"] = {
    "func": strategy_my_custom,
    "params": {
        "param1": [5, 10, 20],
        "param2": [15, 20, 30],
        "stop_loss_pct": [1.5, 2.0],
        "target_pct": [3.0, 5.0],
    }
}
```

3. Re-run the machine — it auto-discovers everything.

---

## Deploying a Strategy to Live Trading

1. Go to **Strategies** tab → find a top strategy
2. Click **VIEW** → click **DOWNLOAD .PY FILE**
3. Edit the downloaded file:
   - Set `SECURITY_ID` for your symbol (from Dhan instrument list)
   - Uncomment the `client.place_order()` lines
4. Run: `python YOUR_STRATEGY_FILE.py`

---

## License
Internal use only. Trade at your own risk.
