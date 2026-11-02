# Validation and remaining implementation roadmap

Reviewed: 2 November 2026. Priorities follow dependencies, not fixed delivery dates.

## Current evidence

The Python suite contains 14 passing tests at this review. These exercise parts
of the SQLite strategy, order manager, Groww adapter/reconciliation, cost model,
readiness, capture storage, and candle snapshot. Some assertions are weak; for
example, a nonnegative order count does not demonstrate that a valid breakout
creates exactly one order. Strengthen behavior evidence before acceptance.

The candle browser check exists but has no recorded successful run from the
latest attempt. JavaScript syntax and HTTP/static delivery checks are narrower
than a full browser or market-session validation.

## Priority backlog

| Priority | Deliverable | Acceptance evidence |
| --- | --- | --- |
| P0 | Normalize candle open/close timestamps and fix opening-range guard | Exact 09:15–09:30 fixtures aggregate into three correctly labelled bars; entry and close boundaries pass. |
| P0 | Obtain validated 1m OHLCV/history with gap backfill | Provider-confirmed timestamps/volume, duplicate handling, gap detection, and comparisons to reference bars. |
| P0 | Incremental live paper evaluation | New completed bars evaluate once; pre-existing completed sessions do not freeze the day; positions remain open until a real simulated exit event. |
| P0 | Unify manual/automatic policy and daily gates | Persist backend mode; manual creates pending intent, Auto skips approval; scheduled and explicit entry paths share gates and pause state. |
| P0 | Portfolio-wide capital and risk | Multiple symbols cannot exceed shared allocation, daily loss, loss count, or concurrent positions. |
| P0 | Correct paper exits and P&L | Test partial target then stop/time/final target, residual quantity, same-bar ambiguity, costs, and end-of-day closure. |
| P1 | Instrument master and actual index filters | Configured universe, valid instruments/ticks/lots, independent index data, liquidity/spread checks. |
| P1 | Reliable capture/recovery | Aligned cycle timing, holiday calendar, bounded retry/backoff, missing-bar recovery, measured status retained across checks. |
| P1 | Finish data-backed screens | Replace static strategy/replay/journal/health/alert/ticket values and align equity universe with API symbols. |
| P1 | Daily context correctness | Ordered returns, explicit data freshness, actual event/news input if required, no fabricated classifications. |
| P1 | Better historical validation | Isolated datasets/modes, corporate-action review, realistic costs/fills, OOS and walk-forward sensitivity. |
| P2 | Broker lifecycle and protection | Approved test path for create/modify/cancel, uncertain outcomes, partial fills, stop/target supervision, reconciliation, and restart recovery. |
| P2 | Emergency and observability | Global pause latch, controlled broker exits, persisted alerts, acknowledgements, measured latency/freshness, audit export. |
| P2 | Remote/cloud operation | Owner authentication, HTTPS, secret lifecycle, supervised process, persistent storage/backups, approved broker networking. |
| P3 | Restricted production decision | Closed critical defects, accepted session evidence, broker/account prerequisites, and explicit owner live activation. |

Upstox remains part of the original overall plan but is not an implemented
adapter. Its sandbox/live completion requires its own acceptance evidence.

## Local regression commands

From the repository root:

```sh
python -m unittest discover -s work -p "test_*.py" -q
node --check work/app/app.js
node --check work/app/candles.js
```

These do not require a broker token. The optional browser test requires adapting
`work/check_candle_ui.cjs` to an installed Playwright environment and Edge. It
uses isolated response fixtures; a successful fixture run would still need a
separate check against actual stored market captures.

## Historical replay procedure

Use a separate local database such as `work/replay.db`; do not mix a validation
experiment with the active capture database. Obtain a permitted historical CSV
with genuine volume and review timestamp/session conventions first.

```sh
python work/sqlite_app.py --db work/replay.db init
python work/sqlite_app.py --db work/replay.db import --symbol RELIANCE --csv PATH_TO_OHLCV.csv
python work/sqlite_app.py --db work/replay.db aggregate --symbol RELIANCE
python work/sqlite_app.py --db work/replay.db backtest --symbol RELIANCE --mode paper --equity 50000
python work/validation.py --db work/replay.db --symbol RELIANCE --slippage-bps 5 --brokerage-per-order 20 --transaction-cost-bps 0 --out work/validation_report.json
```

The cost numbers above are examples for exercising the command, not verified
Groww charges. Replace them with appropriate account/market assumptions. The
importer expects case-sensitive `Timestamp`, or separate `Date` and `Time`
columns, plus `Open`, `High`, `Low`, `Close`, and `Volume`. Missing `Volume`
defaults to zero, which is unsuitable for volume-based validation. Normalize
timestamps to India-local time before importing: the current parser strips a
timezone offset rather than converting it. Datasets are not bundled here.

Current validation applies a simple two-sided turnover/slippage and two-order
brokerage adjustment. It does not fully model partial-exit fees, spread, all
taxes, execution uncertainty, or order-book liquidity. The first twenty session
dates form the development split; later dates form OOS. This is not trained AI,
walk-forward evaluation, or proof of no look-ahead.

## Paper-session evidence to record

For each observed trading day, record the capture start, token state, expected
and received bars, gaps, rule evaluations, order/fill/exit decisions, costs,
reconciliation, failures, and corrective actions. Keep private trading records
outside the public source repository. A no-trade day can be a valid session if
its data and decisions were verified.

Twenty database replay sessions do not substitute for twenty observed paper
trading days. Increasing win rate alone is not acceptance: also inspect net
results after costs, drawdown, trade count, stability, and execution failures.

## Release gates still requiring evidence

- Stale/missing data and expired tokens cannot cause an entry.
- Forced timeouts/duplicate events never create a duplicate broker order.
- Restart rebuilds positions, reservations, and confirmed protection before resuming.
- Every fill has confirmed protection or an immediate critical failure response.
- Daily/account limits and the global pause/kill path cannot be bypassed by a request.
- Partial fills, cancellation races, 429 responses, and outages have bounded recovery.
- End-of-day broker and internal positions/orders/trades reconcile.
- At least twenty observed paper sessions complete with no unresolved critical defect.
- All thirteen target interface areas show accurate state and actionable errors.
- Any required broker/account deployment prerequisites are confirmed and recorded.

The API currently supplies false for external static-IP and broker-approval
flags to its readiness report. Setting an adapter environment switch alone is
not a completed application live-execution implementation or acceptance result.
