# Breakout OS prototype

This is the first implementation slice of the supplied Automated Intraday Breakout Trading Platform plan. It is a dependency-free browser prototype that implements the shared visual system from the plan's 13 mock screens and provides navigable screens for the operating workflow.

## Run

Start the SQLite-backed local web application from the repository root:

```powershell
& "C:\Users\Sony\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" work\api_server.py --db work\breakout.db --port 8765
```

Then open `http://127.0.0.1:8765/work/app/index.html`. The dashboard reads its summary from `/api/summary?symbol=NIFTY50` and falls back to the mock layout if the API is unavailable.

The connected actions are:

- `GET /api/health`
- `GET /api/summary?symbol=NIFTY50`
- `POST /api/backtest`
- `POST /api/session/run`
- `POST /api/orders/approve`
- `GET /api/orders?symbol=NIFTY50`
- `GET /api/reconcile?symbol=NIFTY50`
- `POST /api/kill-switch`
- `GET /api/brokers/groww`
- `GET /api/readiness?symbol=NIFTY50`
- `POST /api/brokers/groww/reconcile`

`order_manager.py` is the broker-neutral execution boundary. It enforces client-reference idempotency, tracks normalized order states, supports cancellation and reconciliation, and provides a paper kill switch. Real Upstox/Groww adapters are intentionally not enabled until credentials, sandbox approval, and broker-specific compliance requirements are available.

`groww_adapter.py` implements the official Groww REST contract for order create/modify/cancel, status, trades, order list, and LTP. The Connections screen accepts the daily token through a password field and sends it to the local backend; the backend keeps it in memory only for the current server process. It is never stored in browser storage, SQLite, or logs. Restarting the server clears it.

`groww_reconciliation.py` adds a read-only reconciliation pass that imports Groww order/trade observations into `broker_events`, matches by Groww's `order_reference_id`, and reports unmatched records for review.

Offline validation is available through `validation.py`. It runs a separate paper replay, reports development/out-of-sample results, applies explicit slippage/brokerage/transaction-cost scenarios, checks duplicate client references and uncertain orders, and writes `validation_report.json`. These are replay gates, not a substitute for 20 live-market paper sessions.

## Mode behavior

- Paper/assisted mode keeps approval controls visible and records a deliberate approval action.
- Auto mode is enabled with the top-right toggle. Eligible signals show auto-execution copy and the approval action submits after server-side risk approval in the prototype flow.

The SQLite strategy engine is in `../sqlite_app.py`; the local API/static server is `../api_server.py`. The API exposes health, summary, signal, and backtest endpoints and implements the documented 15-minute opening range, completed 5-minute confirmation, VWAP/EMA trend checks, relative volume, extension guard, quantity sizing, risk limits, paper fills, protection/exit simulation, and audit events.

Example commands from the repository root:

```powershell
python work/sqlite_app.py --db work/breakout.db init
python work/sqlite_app.py --db work/breakout.db import --symbol NIFTY50 --csv work/NIFTY50_1min_2026-09.csv --csv work/NIFTY50_1min_2026-10.csv
python work/sqlite_app.py --db work/breakout.db aggregate --symbol NIFTY50
python work/sqlite_app.py --db work/breakout.db backtest --symbol NIFTY50 --mode auto --equity 500000
```

The engine is paper-only: it does not place real broker orders or store credentials. Auto mode means automatic simulated submission after risk approval; it is not a live-broker integration.
