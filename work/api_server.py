"""Local SQLite API and static server for Breakout OS.

Run from the repository root with the bundled Python runtime:
python work/api_server.py --db work/breakout.db --port 8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
import threading
import time as time_module
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlite_app import approve_order, backtest, connect, get_session_settings, init_db, run_session, save_session_settings
from order_manager import OrderManager
from groww_adapter import GrowwAPIError, GrowwClient, GrowwConfigError
from groww_reconciliation import reconcile_groww
from live_market import evaluate_live_paper, latest_quotes, poll_quotes
from readiness import report as readiness_report
from premarket import auto_refresh_context, get_context, save_context
from candle_monitor import candle_snapshot

ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = ROOT / "work" / "app"
RUNTIME_GROWW_TOKEN = None
RUNTIME_GROWW_STATUS = {"state": "NOT_CONNECTED", "message": "Token not verified"}
MARKET_TZ = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
MARKET_POLL_INTERVAL_SECONDS = 60
SCHEDULER_STARTED = False
RUNTIME_LIVE_EVALUATION = None


def query_rows(conn, sql, args=()):
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def _market_scheduler(db_path):
    """Capture Groww quotes in the backend while the market is open.

    The browser is only a monitor. This daemon intentionally does nothing until
    a verified token is present, and never submits broker orders.
    """
    global RUNTIME_GROWW_STATUS, RUNTIME_LIVE_EVALUATION
    while True:
        now = datetime.now(MARKET_TZ)
        is_weekday = now.weekday() < 5
        in_window = MARKET_OPEN <= now.time() <= MARKET_CLOSE
        if is_weekday and in_window and RUNTIME_GROWW_TOKEN and RUNTIME_GROWW_STATUS.get("state") == "VERIFIED":
            conn = None
            try:
                conn = connect(db_path)
                init_db(conn)
                market = poll_quotes(conn, GrowwClient(access_token=RUNTIME_GROWW_TOKEN))
                RUNTIME_LIVE_EVALUATION = evaluate_live_paper(conn)
                RUNTIME_GROWW_STATUS["last_poll_at"] = market.get("received_at")
                RUNTIME_GROWW_STATUS["scheduler"] = "ACTIVE"
            except GrowwAPIError as exc:
                if "HTTP 401" in str(exc) or exc.code in {401, "401"}:
                    RUNTIME_GROWW_STATUS = {"state": "EXPIRED", "message": "Groww token expired or rejected. Update today’s token in Connections.", "scheduler": "PAUSED"}
                else:
                    RUNTIME_GROWW_STATUS["scheduler"] = "ERROR"
                    RUNTIME_GROWW_STATUS["last_error"] = str(exc)
            except Exception as exc:  # keep the scheduler alive after one bad cycle
                RUNTIME_GROWW_STATUS["scheduler"] = "ERROR"
                RUNTIME_GROWW_STATUS["last_error"] = str(exc)
            finally:
                if conn is not None:
                    conn.close()
        elif not in_window and RUNTIME_GROWW_STATUS.get("scheduler") == "ACTIVE":
            RUNTIME_GROWW_STATUS["scheduler"] = "OUTSIDE_MARKET_WINDOW"
        time_module.sleep(MARKET_POLL_INTERVAL_SECONDS)


def start_market_scheduler(db_path):
    global SCHEDULER_STARTED
    if SCHEDULER_STARTED:
        return
    SCHEDULER_STARTED = True
    threading.Thread(target=_market_scheduler, args=(db_path,), name="market-capture", daemon=True).start()


def summary(conn, symbol):
    trades = query_rows(conn, "SELECT realized_pnl,result,entry_ts,exit_ts,direction,quantity FROM trades WHERE symbol=? ORDER BY id DESC", (symbol,))
    signals = query_rows(conn, """SELECT symbol,candle_ts,direction,entry_price,opening_high,opening_low,vwap,relative_volume,status,reason
        FROM signals WHERE symbol=? ORDER BY id DESC LIMIT 25""", (symbol,))
    sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE symbol=?", (symbol,)).fetchone()[0]
    pnl = round(sum(float(row["realized_pnl"]) for row in trades), 2)
    wins = sum(float(row["realized_pnl"]) > 0 for row in trades)
    audits = query_rows(conn, "SELECT event_type,entity_type,payload_json,created_at FROM audit_events ORDER BY id DESC LIMIT 12")
    paper_positions = query_rows(conn, """SELECT o.id,o.symbol,o.side,o.quantity,o.requested_price,o.status,o.created_at,
        COALESCE(q.last_price,o.requested_price) AS ltp,
        s.direction,s.entry_price,s.reason
        FROM order_intents o JOIN signals s ON s.id=o.signal_id
        LEFT JOIN live_quotes q ON q.trading_symbol=o.symbol
        WHERE o.status IN ('PAPER_READY','PENDING_APPROVAL','SUBMITTED','ACKNOWLEDGED')
        ORDER BY o.id DESC""")
    paper_orders = query_rows(conn, """SELECT o.id,o.symbol,o.side,o.quantity,o.requested_price,o.status,o.created_at,
        s.direction,s.reason FROM order_intents o JOIN signals s ON s.id=o.signal_id ORDER BY o.id DESC LIMIT 25""")
    return {
        "symbol": symbol,
        "sessions": sessions,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate_pct": round(100 * wins / len(trades), 1) if trades else 0,
        "net_pnl": pnl,
        "signals": signals,
        "trades_detail": trades[:20],
        "paper_positions": paper_positions,
        "paper_orders": paper_orders,
        "audit": audits,
    }


class Handler(BaseHTTPRequestHandler):
    db_path: str = ""

    def log_message(self, fmt, *args):
        print(fmt % args)

    def send_json(self, value, status=200):
        body = json.dumps(value, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        global RUNTIME_GROWW_STATUS
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "healthy", "service": "breakout-os-local-api"})
            return
        if parsed.path == "/api/brokers/groww":
            result = GrowwClient(access_token=RUNTIME_GROWW_TOKEN).configuration()
            if RUNTIME_GROWW_TOKEN:
                try:
                    quote = GrowwClient(access_token=RUNTIME_GROWW_TOKEN).ltp(["NSE_RELIANCE"], segment="CASH")
                    price = (quote.get("payload") or {}).get("NSE_RELIANCE")
                    RUNTIME_GROWW_STATUS = {"state": "VERIFIED", "message": "Read-only Groww market-data check passed", "verified_symbol": "NSE_RELIANCE", "verified_ltp": price}
                except GrowwAPIError as exc:
                    expired = "HTTP 401" in str(exc) or exc.code in {401, "401"}
                    RUNTIME_GROWW_STATUS = {"state": "EXPIRED" if expired else "ERROR",
                                            "message": "Groww token expired or rejected. Update today’s token in Connections." if expired else str(exc)}
            result.update(RUNTIME_GROWW_STATUS)
            self.send_json(result)
            return
        if parsed.path == "/api/readiness":
            conn = connect(self.db_path)
            init_db(conn)
            symbol = parse_qs(parsed.query).get("symbol", ["NIFTY50"])[0]
            self.send_json(readiness_report(conn, symbol, bool(RUNTIME_GROWW_TOKEN), False, False))
            conn.close()
            return
        if parsed.path == "/api/session/config":
            conn = connect(self.db_path)
            init_db(conn)
            self.send_json(get_session_settings(conn))
            conn.close()
            return
        if parsed.path == "/api/premarket":
            conn = connect(self.db_path)
            init_db(conn)
            self.send_json(get_context(conn, parse_qs(parsed.query).get("date", [None])[0]))
            conn.close()
            return
        if parsed.path == "/api/live-data/status":
            conn = connect(self.db_path)
            init_db(conn)
            now = datetime.now(MARKET_TZ)
            self.send_json({"provider": "groww", "token_configured": bool(RUNTIME_GROWW_TOKEN),
                            "verification": RUNTIME_GROWW_STATUS, "quotes": latest_quotes(conn),
                            "scheduler": {"running": SCHEDULER_STARTED, "timezone": "Asia/Kolkata", "market_open": "09:15", "market_close": "15:30", "now": now.isoformat()},
                            "signals_ready": False,
                            "message": "Backend capture runs every 60 seconds during the NSE market window after Groww verification."})
            conn.close()
            return
        if parsed.path == "/api/live-data/candles":
            conn = connect(self.db_path)
            try:
                symbol = parse_qs(parsed.query).get("symbol", ["RELIANCE"])[0]
                result = candle_snapshot(conn, symbol)
                result["verification"] = RUNTIME_GROWW_STATUS
                result["scheduler_running"] = SCHEDULER_STARTED
                result["evaluation"] = RUNTIME_LIVE_EVALUATION
                self.send_json(result)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            finally:
                conn.close()
            return
        if parsed.path.startswith("/api/"):
            conn = connect(self.db_path)
            init_db(conn)
            symbol = parse_qs(parsed.query).get("symbol", ["NIFTY50"])[0]
            try:
                if parsed.path == "/api/summary":
                    self.send_json(summary(conn, symbol))
                elif parsed.path == "/api/signals":
                    self.send_json({"signals": summary(conn, symbol)["signals"]})
                elif parsed.path == "/api/orders":
                    self.send_json({"orders": query_rows(conn, "SELECT * FROM order_intents WHERE symbol=? ORDER BY id DESC", (symbol,))})
                elif parsed.path == "/api/reconcile":
                    self.send_json(OrderManager(conn).reconcile(symbol))
                else:
                    self.send_json({"error": "not found"}, 404)
            finally:
                conn.close()
            return
        self.serve_static(parsed.path)

    def do_POST(self):
        global RUNTIME_GROWW_TOKEN, RUNTIME_GROWW_STATUS, RUNTIME_LIVE_EVALUATION
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/backtest", "/api/session/config", "/api/session/run", "/api/orders/approve", "/api/orders/reject", "/api/orders/approve-all", "/api/orders/reject-all", "/api/kill-switch", "/api/brokers/groww/reconcile", "/api/brokers/groww/configure", "/api/brokers/groww/verify", "/api/live-data/poll", "/api/live-data/evaluate", "/api/premarket", "/api/premarket/refresh"}:
            self.send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            symbol = payload.get("symbol", "NIFTY50")
            mode = payload.get("mode", "auto")
            equity = float(payload.get("equity", 500000))
            conn = connect(self.db_path)
            init_db(conn)
            if parsed.path == "/api/session/config":
                result = save_session_settings(conn, float(payload["account_balance"]), float(payload["trading_capital"]),
                                               float(payload["risk_per_trade_pct"]), float(payload["daily_loss_pct"]))
            elif parsed.path == "/api/premarket":
                result = save_context(conn, payload)
            elif parsed.path == "/api/premarket/refresh":
                if not RUNTIME_GROWW_TOKEN:
                    raise GrowwConfigError("Authorize and verify a Groww token first")
                client = GrowwClient(access_token=RUNTIME_GROWW_TOKEN)
                market = poll_quotes(conn, client)
                result = auto_refresh_context(conn, market.get("quotes", []))
            elif parsed.path == "/api/backtest":
                result = backtest(conn, symbol, mode, equity)
            elif parsed.path == "/api/session/run":
                day = payload.get("date") or conn.execute("SELECT substr(MAX(ts),1,10) FROM candles WHERE symbol=? AND interval='5m'", (symbol,)).fetchone()[0]
                if not day:
                    raise ValueError(f"no 5-minute data available for {symbol}")
                context = get_context(conn, day)
                if not context["ready"]:
                    raise ValueError(f"daily pre-market gate is {context['status'].lower()}: complete and save today’s context first")
                if RUNTIME_GROWW_STATUS.get("state") != "VERIFIED":
                    raise GrowwConfigError("Groww token expired or is not verified. Update today’s token in Connections before starting the session")
                settings = get_session_settings(conn)
                result = run_session(conn, symbol, day, mode, float(settings["trading_capital"]), settings)
            else:
                if parsed.path == "/api/orders/approve":
                    result = approve_order(conn, payload.get("order_id"))
                elif parsed.path == "/api/orders/reject":
                    order_id = payload.get("order_id")
                    if order_id is None:
                        raise ValueError("order_id is required")
                    result = OrderManager(conn).cancel(int(order_id))
                elif parsed.path in {"/api/orders/approve-all", "/api/orders/reject-all"}:
                    pending_ids = [row[0] for row in conn.execute("SELECT id FROM order_intents WHERE status='PENDING_APPROVAL' ORDER BY id").fetchall()]
                    results = []
                    for pending_id in pending_ids:
                        results.append(approve_order(conn, pending_id) if parsed.path.endswith("approve-all") else OrderManager(conn).cancel(pending_id))
                    result = {"count": len(results), "action": "approved" if parsed.path.endswith("approve-all") else "rejected", "orders": results}
                elif parsed.path == "/api/brokers/groww/configure":
                    token = str(payload.get("access_token") or "").strip()
                    if not token:
                        raise ValueError("access_token is required")
                    RUNTIME_GROWW_TOKEN = token
                    RUNTIME_GROWW_STATUS = {"state": "TOKEN_RECEIVED", "message": "Token received; verification pending"}
                    result = {"provider": "groww", "token_configured": True, "live_enabled": False, "storage": "server-memory", **RUNTIME_GROWW_STATUS}
                elif parsed.path == "/api/brokers/groww/verify":
                    if not RUNTIME_GROWW_TOKEN:
                        raise ValueError("Authorize a Groww token first")
                    client = GrowwClient(access_token=RUNTIME_GROWW_TOKEN)
                    quote = client.ltp(["NSE_RELIANCE"], segment="CASH")
                    price = (quote.get("payload") or {}).get("NSE_RELIANCE")
                    RUNTIME_GROWW_STATUS = {"state": "VERIFIED", "message": "Read-only Groww market-data check passed", "verified_symbol": "NSE_RELIANCE", "verified_ltp": price}
                    result = {"provider": "groww", "token_configured": True, "live_enabled": False, **RUNTIME_GROWW_STATUS}
                elif parsed.path == "/api/live-data/poll":
                    if not RUNTIME_GROWW_TOKEN:
                        raise GrowwConfigError("Authorize and verify a Groww token first")
                    client = GrowwClient(access_token=RUNTIME_GROWW_TOKEN)
                    result = poll_quotes(conn, client, payload.get("exchange_symbols"))
                elif parsed.path == "/api/live-data/evaluate":
                    if not RUNTIME_GROWW_TOKEN:
                        raise GrowwConfigError("Authorize and verify a Groww token first")
                    result = evaluate_live_paper(conn)
                    RUNTIME_LIVE_EVALUATION = result
                elif parsed.path == "/api/brokers/groww/reconcile":
                    client = GrowwClient(access_token=RUNTIME_GROWW_TOKEN)
                    if not client.access_token:
                        raise ValueError("GROWW_ACCESS_TOKEN is not configured")
                    result = reconcile_groww(conn, client, segment=payload.get("segment", "CASH"))
                else:
                    result = OrderManager(conn).kill_switch(payload.get("session_id"))
            conn.close()
            self.send_json(result)
        except GrowwConfigError as exc:
            self.send_json({"error": str(exc), "category": "configuration"}, 400)
        except GrowwAPIError as exc:
            if "HTTP 401" in str(exc) or exc.code in {401, "401"}:
                RUNTIME_GROWW_STATUS = {"state": "EXPIRED", "message": "Groww token expired or rejected. Update today’s token in Connections."}
            self.send_json({"error": str(exc), "category": "groww_api", "retryable": bool(exc.retryable), "code": exc.code}, 502)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc), "category": "validation"}, 400)

    def serve_static(self, request_path):
        relative = "index.html" if request_path in {"", "/"} else request_path.removeprefix("/")
        candidate = (ROOT / relative).resolve()
        if APP_ROOT not in candidate.parents and candidate != APP_ROOT:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "work" / "breakout.db"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    conn = connect(args.db)
    init_db(conn)
    conn.close()
    Handler.db_path = args.db
    start_market_scheduler(args.db)
    print(f"Breakout OS API serving http://127.0.0.1:{args.port}/work/app/index.html")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
