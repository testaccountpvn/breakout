# Implemented features and current limitations

Reviewed against source revision `f06c21c` on 2 November 2026. This describes
code capability, not the current token/server state or trading performance.

## Working foundation

| Capability | Status | Evidence and limits |
| --- | --- | --- |
| Local API and static UI | Implemented | `work/api_server.py`; local bind on 127.0.0.1:8765. No owner login/HTTPS deployment layer. |
| SQLite persistence | Implemented | `work/sqlite_app.py`; schema initialization, WAL, foreign keys, candles, sessions, signals, risk decisions, orders, fills, trades, and audit events. |
| Groww token entry/verification | Implemented | Configure/verify routes and Connections controls; read-only LTP verification and HTTP 401 expiry state. Server restart clears the runtime token. |
| Backend capture loop | Implemented with limits | Weekdays 09:15–15:30 IST, approximately 60 seconds between cycles after verified token; no OS startup, holiday calendar, or gap recovery. |
| Capture universe | Implemented | RELIANCE, SBIN, LT, MARUTI, SUNPHARMA, HEROMOTOCO. Full Nifty 200 discovery is pending. |
| Tick and sampled-candle storage | Implemented with limits | `live_quotes`, `live_quote_ticks`, sampled 1m bars, and 5m aggregation. Captured prices use receipt time and carry zero volume. |
| Candle monitor | Implemented | `candle_monitor.py`, `app/candles.js`, `app/candles.css`; read-only snapshot, current-minute bar, symbol selection, OHLC chart/table, freshness, counts, opening progress, five-second display refresh. |
| Capital/risk configuration | Implemented with limits | Daily balance, allocation, risk percentage, and daily loss percentage persist on the server. Balance is owner-entered rather than broker-synchronized. |
| Replay strategy | Partial | ORB, VWAP, instrument EMA, relative volume, extension, risk sizing, simulated fills/exits. See correctness issues below. |
| Paper order controls | Implemented with limits | Individual/bulk pending-order approve/reject and reason columns; these affect SQLite state, not live holdings. |
| Groww adapter | Partial | Guarded REST methods for LTP and order operations; live execution is not wired into the application order workflow. |
| Reconciliation | Partial | Local uncertain-state checks plus a read-only Groww order/trade import; full positions/protection reconciliation is pending. |
| Pre-market context | Partial | Separate daily rules module and persistence; real news/events are absent. No trained prediction model. |
| Historical validation | Partial | CSV import, 5m aggregation, replay, date-based development/OOS split, simple cost sensitivity, duplicate/uncertain checks. |
| Git repository | Implemented | Source, tests, blank env example, and documentation; local credentials, database, datasets, and generated artifacts are ignored. |

## UI data provenance

| Page/area | Current source and caveat |
| --- | --- |
| Dashboard | SQLite paper totals/order intents and captured Groww quotes. Default summary symbol is NIFTY50 while capture uses six equities; this is not a complete account dashboard. |
| Market Scanner / Live Quotes | Today's stored Groww-derived sampled candles and quote snapshots. Monitor freshness is not an execution freshness guarantee. |
| Signal Analysis | Available runtime evaluation results; not a fully persisted cross-session signal browser. |
| Positions & Orders | SQLite paper intents and reasons/actions, with captured LTP where available. It does not establish broker position truth. |
| Connections | Groww verification is real; Upstox connection and example latency/status presentation remain prototype. |
| Daily session | Persisted capital/risk and pre-market results; some broker/readiness presentation remains prototype. |
| Strategy | Prototype version labels/edit controls; active backend defaults initialize as ORB Cash v1.0, while UI displays v1.4/Nifty 200. |
| Paper Replay | Backtest button calls the API; shown period, performance cards, curve, and some validation labels remain examples and are not bound to that result. |
| Risk Management | Defaults and emergency UI are mixed with partial backend behavior; the full policy editor and global enforcement are not delivered. |
| Trade Approval | Original illustrative ticket remains; use pending SQLite row actions as the current implemented approval path. |
| Journal / Alerts / System Health | Significant prototype analytics, notifications, service names, latency numbers, and events remain. Consult real API/data records instead. |
| Header | Some market/simulation badges remain presentation text rather than measured state. |

## Known correctness and completion blockers

These findings come from source inspection. They are not fixed by this documentation update.

1. **OHLCV quality:** one sample per minute misses intraminute extremes; zero
   volume prevents meaningful volume confirmation and volume-weighted calculations.
2. **5m timestamp mismatch:** `aggregate_5m()` labels bars using the last 1m
   timestamp (for example, 09:19 for the 09:15 bucket). The live opening-range
   guard expects a first 5m timestamp no later than 09:15. Normal aggregated
   opening bars therefore fail that guard. Standardize open/close timestamps and
   test the boundary before promising automatic evaluation.
3. **Continuous evaluation:** `run_session()` marks a session COMPLETED after
   evaluating the available rows. Later calls return its previous result rather
   than evaluating newly arriving bars. A continuous paper engine needs an
   incremental cursor and durable open-position state.
4. **Approval policy:** live evaluation always requests `paper`. The browser
   stores the Auto toggle locally, but that setting does not configure backend
   scheduled evaluation. The Daily session UI chooses `auto` or `paper`, whereas
   backend pending approvals are created by `assisted`. These paths need alignment.
5. **Readiness paths:** the explicit session route checks pre-market readiness;
   the scheduler's direct evaluation path does not use the same gate. Readiness
   reporting itself does not authorize a live order path.
6. **Portfolio risk:** daily P&L/loss counts are local replay variables, and the
   concurrent-position default is not an account-wide enforcement mechanism.
   Cross-symbol capital, losses, reservations, and position count remain pending.
7. **Index confirmation:** replay checks the instrument's EMA and writes
   `index_aligned=1`; an independent index feed/alignment check is absent.
8. **Simulation accuracy:** stop-distance handling adjusts the stop rather than
   explicitly rejecting all oversized technical stops. Partial-exit accounting,
   remaining-quantity closure, bar-path assumptions, and live time exits need
   stronger tests. Scheduled broker square-off is not implemented.
9. **Pre-market inference:** current movement uses MIN/MAX sampled prices, not
   an ordered first-to-last return. It cannot establish a reliable bearish bias.
   News remains unknown and the automatic context remains incomplete.
10. **Recovery and protection:** the local kill switch cancels active intents;
    it does not flatten real broker positions or implement a global scheduler
    latch. Restart reconciliation and confirmed broker protection are pending.
11. **Scheduling reliability:** sleep occurs after each cycle, so the minute
    interval can drift. Weekday checks do not establish exchange opening on a
    holiday. The monitor's gap count only covers gaps between existing saved bars.
12. **Readiness evidence:** the twenty-session check counts completed database
    sessions, including replay; it does not prove twenty observed live paper days.
    Backtest trade aggregation can combine stored results from different modes.

## Verification evidence

The existing Python suite reports **14 tests passing**. JavaScript syntax checks
were run for `app.js` and `candles.js` during the candle-monitor implementation.
The health endpoint, candle endpoint, invalid-symbol handling through unit
coverage, and static asset delivery have been checked locally as recorded in
the project work.

`check_candle_ui.cjs` contains an isolated browser check, but its latest attempted
run was blocked at browser launch/approval review; a successful visual regression
run has not been recorded. It also needs portable Playwright dependency setup.

Passing these tests does not close the listed strategy, data, recovery, or live
acceptance gaps. No defect-free or production-live claim is made.
