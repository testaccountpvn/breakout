# Breakout OS

Local Python/SQLite application for capturing Groww price samples, monitoring
one-minute candles, and evaluating an intraday opening-range breakout strategy
in paper mode. The browser interface is served by the Python backend.

## Project documentation

- [Documentation index](docs/README.md)
- [Overall project plan and agreed scope](docs/PROJECT_PLAN.md)
- [Implemented features and known gaps](docs/IMPLEMENTATION_STATUS.md)
- [Architecture, modules, data, and API](docs/ARCHITECTURE.md)
- [Daily operation and troubleshooting](docs/OPERATIONS.md)
- [Validation plan and remaining roadmap](docs/VALIDATION_AND_ROADMAP.md)

The implementation status is the source of truth for completion. The project
plan describes the target product, including work that has not been delivered.

## Run locally

Requires Python 3.10 or newer. From the repository root:

```sh
python -m pip install -r requirements.txt
python work/api_server.py --db work/breakout.db --port 8765
```

Open <http://127.0.0.1:8765/work/app/index.html>. The database is created locally
on first startup. Add and verify your Groww token on the Connections page.
Tokens are kept in server memory; restarting the server requires re-entry.

## Capture and monitoring

The backend scheduler samples the six configured Groww symbols every 60 seconds
on weekdays between 09:15 and 15:30 Asia/Kolkata time, after token verification.
Exchange holidays are not currently detected. Keep the server running and the
computer awake. The browser does not need to remain open for backend capture.

Market Scanner and Live Quotes display today's sampled candles, the current
forming minute, freshness, capture counts, and opening-range progress. Their
display checks stored data every five seconds without triggering a capture.

The feed uses sampled last-traded prices, not exchange OHLCV: it may miss
intraminute highs/lows and does not provide volume. Valid volume-based strategy
testing requires an appropriate historical or live OHLCV source. Paper results
and prototype screens are not evidence of live broker execution. Broker order
submission is not enabled by the app's Auto toggle.

## Checks

```sh
python -m unittest discover -s work -p "test_*.py" -q
node --check work/app/app.js
node --check work/app/candles.js
```

The optional `work/check_candle_ui.cjs` browser check currently uses the
development machine's Playwright installation path and Microsoft Edge. Its
test responses are isolated from SQLite.

## Repository contents

Source code, UI files, tests, and the blank Groww environment example belong
in Git. Local SQLite databases, credentials, data imports, generated reports,
screenshots, and Python caches are excluded by `.gitignore`. Keep local data
backups separately; cloning the repository does not restore trading history.
