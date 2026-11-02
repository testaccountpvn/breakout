# Running and monitoring the application

Reviewed: 2 November 2026. Times below are Asia/Kolkata.

## First startup

Install Python 3.10 or newer, clone the repository, and run from its root:

```sh
python -m pip install -r requirements.txt
python work/api_server.py --db work/breakout.db --port 8765
```

Open <http://127.0.0.1:8765/work/app/index.html>. The server initializes an empty
local database. Existing history, credentials, historical CSVs, and generated
reports are intentionally absent from the repository.

If Windows reports that Python was not found, install/configure a Python runtime
or invoke an already installed interpreter by its full path. The Microsoft Store
alias alone is not an installed Python runtime.

## Daily capture workflow

1. Start the local server and keep the computer awake with working internet.
2. Before 09:10, open Connections, paste the day's Groww token, and choose
   Authorize & verify. Confirm a successful verification response.
3. Open Market Scanner or Live Quotes. Before 09:15, a verified connection should
   show the waiting-for-open state. A pre-open quote is not an opening candle.
4. From 09:15, monitor the last-received time and forming minute. The previous
   minute is stored when a later polling cycle flushes it; allow for polling
   and network delay before its saved count advances.
5. Check the selected symbol's 1m/5m counts and the opening capture progress.
   Selecting a symbol changes the chart; it does not change the capture universe.
6. Refresh daily pre-market context if needed, and review capital/risk on Daily
   session. Its automatic news-dependent context is currently incomplete; do
   not mark it complete solely because quotes were returned.

Capture is independent of the browser tab. The UI reads stored data every five
seconds while the capture pages are visible; the backend samples roughly every
sixty seconds during weekday market hours. The loop does not detect holidays.
Manual Poll now can store a quote outside those hours, but the candle monitor
filters its chart to the day's market window.

## Interpreting the monitor

| State/value | Meaning |
| --- | --- |
| Token required | The runtime connection is not verified; use Connections. |
| Ready for 09:15 | Before the weekday capture window with a verified token and running scheduler. |
| Receiving prices | Selected quote is within the monitor's two-minute freshness allowance. |
| Feed delayed | No current quote inside that allowance; investigate connection/capture. |
| Forming | Values from captured samples in the current minute, still changing. |
| Saved | A completed sampled 1m record exists in SQLite. |
| Opening range N / 15 | Captured saved minutes during 09:15–09:30, not validation of exchange OHLCV quality. |
| Gaps | Missing minutes between existing saved bars; this does not count all missing leading/trailing minutes. |
| Volume unavailable | Expected for the current LTP feed; zero stored volume is not actual market volume. |

With one price sample in a minute, open/high/low/close can all be identical. This
does not prove the exchange price was flat throughout the minute.

## Paper and approval behavior

The backend capture evaluator currently uses paper mode regardless of the
browser's Auto toggle. The explicit session action and assisted pending-order
path are not yet fully aligned with the toggle. A successful token check or
increasing candle count therefore does not prove an eligible call will execute.

Use [implementation status](IMPLEMENTATION_STATUS.md) for the timestamp and
incremental-evaluation blockers. Do not wait for a guaranteed trade at 09:30 or
09:40: eligibility requires valid inputs and a qualifying rule outcome, and the
current implementation still needs those blockers resolved.

## Diagnostics

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
Invoke-RestMethod http://127.0.0.1:8765/api/live-data/status
Invoke-RestMethod 'http://127.0.0.1:8765/api/live-data/candles?symbol=RELIANCE'
Invoke-RestMethod http://127.0.0.1:8765/api/premarket
```

The health route only confirms the HTTP service. Inspect scheduler metadata,
verification, receipt times, captured candles, and evaluation messages separately.
Avoid posting complete API responses containing private trading data publicly.

| Symptom | Check/action |
| --- | --- |
| Site unavailable / Failed to fetch | Confirm server process, port 8765, and the HTTP URL; do not open the HTML directly as a file. |
| HTTP 401 | Replace the rejected/expired Groww token and verify again. |
| Token lost after restart | Expected with server-memory credentials; re-enter on Connections. Page refresh alone should not clear the server token. |
| Counts stop advancing | Check laptop sleep, server process, receipt times, market window, network, and scheduler error state. |
| Opening-range unavailable | Capture may have begun late; also check the known 5m timestamp mismatch. Do not manufacture opening candles. |
| Same paper evaluation repeatedly | Check the completed-session short-circuit described in the implementation status. |
| News/context incomplete | No real news integration is configured; automatic refresh cannot validate news. |

## Stop, backup, and privacy

Stopping the server stops capture and clears the runtime token. It does not
close broker positions. The current local kill switch is not a live flatten-all.

Keep backups outside Git. With the server stopped and SQLite connections closed,
copy the database and any still-present WAL/SHM companions together to a dated
backup folder. For online backups use SQLite's supported backup mechanism;
copying only a live WAL database file may omit recent changes.

Do not expose port 8765 directly to the internet. Remote access and a hosted
deployment are separate workstreams with authentication and recovery requirements.
