"""Read-only Groww quote polling and SQLite storage.

This module intentionally does not create, modify, or cancel broker orders.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlite_app import aggregate_5m, get_session_settings, run_session


DEFAULT_EXCHANGE_SYMBOLS = [
    "NSE_RELIANCE", "NSE_SBIN", "NSE_LT", "NSE_MARUTI",
    "NSE_SUNPHARMA", "NSE_HEROMOTOCO",
]


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def poll_quotes(conn, client, exchange_symbols=None, segment="CASH"):
    symbols = list(exchange_symbols or DEFAULT_EXCHANGE_SYMBOLS)
    if not symbols or len(symbols) > 50:
        raise ValueError("quote polling supports between 1 and 50 exchange symbols")
    response = client.ltp(symbols, segment=segment)
    payload = response.get("payload") or {}
    received_at = utc_now()
    local_minute = datetime.now(ZoneInfo("Asia/Kolkata")).replace(second=0, microsecond=0, tzinfo=None)
    stored = []
    for exchange_symbol in symbols:
        if exchange_symbol not in payload or payload[exchange_symbol] is None:
            continue
        price = float(payload[exchange_symbol])
        if price <= 0:
            continue
        exchange, trading_symbol = exchange_symbol.split("_", 1)
        conn.execute("""INSERT INTO live_quotes(exchange_symbol,exchange,segment,trading_symbol,last_price,received_at,source)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(exchange_symbol) DO UPDATE SET exchange=excluded.exchange,
            segment=excluded.segment,trading_symbol=excluded.trading_symbol,last_price=excluded.last_price,
            received_at=excluded.received_at,source=excluded.source""",
            (exchange_symbol, exchange, segment, trading_symbol, price, received_at, "GROWW_LTP"))
        conn.execute("""INSERT INTO live_quote_ticks(exchange_symbol,trading_symbol,segment,price,tick_ts,received_at)
            VALUES(?,?,?,?,?,?)""", (exchange_symbol, trading_symbol, segment, price, local_minute.isoformat(), received_at))
        stored.append({"exchange_symbol": exchange_symbol, "trading_symbol": trading_symbol,
                       "exchange": exchange, "segment": segment, "last_price": price,
                       "received_at": received_at, "source": "GROWW_LTP"})
    _flush_completed_minutes(conn, local_minute)
    conn.commit()
    completed_5m = sum(aggregate_5m(conn, symbol, local_minute.date().isoformat()) for symbol in {item["trading_symbol"] for item in stored})
    return {"status": "UPDATED", "received_at": received_at, "requested": len(symbols),
            "updated": len(stored), "quotes": stored,
            "completed_5m_candles": completed_5m, "signals_ready": False,
            "message": "Live quotes and completed-minute candles stored; breakout signals remain disabled until the live-session gate is complete."}


def _flush_completed_minutes(conn, current_minute):
    rows = conn.execute("SELECT trading_symbol,tick_ts,price FROM live_quote_ticks ORDER BY tick_ts,id").fetchall()
    grouped = defaultdict(list)
    for row in rows:
        minute = datetime.fromisoformat(row["tick_ts"])
        if minute < current_minute:
            grouped[(row["trading_symbol"], minute)].append(float(row["price"]))
    for (symbol, minute), prices in grouped.items():
        conn.execute("""INSERT OR REPLACE INTO candles(symbol,interval,ts,open,high,low,close,volume,source,completed)
            VALUES(?,?,?,?,?,?,?,?,?,1)""", (symbol, "1m", minute.isoformat(), prices[0], max(prices), min(prices), prices[-1], 0, "GROWW_LTP"))


def latest_quotes(conn):
    return [dict(row) for row in conn.execute(
        "SELECT exchange_symbol,exchange,segment,trading_symbol,last_price,received_at,source FROM live_quotes ORDER BY trading_symbol"
    ).fetchall()]


def evaluate_live_paper(conn):
    """Evaluate today's completed live candles in paper mode only."""
    day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    settings = get_session_settings(conn)
    symbols = [row[0] for row in conn.execute("SELECT DISTINCT trading_symbol FROM live_quote_ticks")]
    evaluations = []
    for symbol in symbols:
        candles = conn.execute("SELECT COUNT(*) FROM candles WHERE symbol=? AND interval='5m' AND completed=1 AND substr(ts,1,10)=? AND substr(ts,12,5)>='09:15' AND substr(ts,12,5)<='15:15'",
                               (symbol, day)).fetchone()[0]
        if candles < 5:
            evaluations.append({"symbol": symbol, "status": "WAITING", "completed_5m_candles": candles,
                                 "message": "Need at least 5 completed 5-minute candles."})
            continue
        first_candle = conn.execute("SELECT MIN(ts) FROM candles WHERE symbol=? AND interval='5m' AND completed=1 AND substr(ts,1,10)=? AND substr(ts,12,5)>='09:15' AND substr(ts,12,5)<='15:15'",
                                    (symbol, day)).fetchone()[0]
        opening_candles = conn.execute("SELECT COUNT(*) FROM candles WHERE symbol=? AND interval='5m' AND completed=1 AND substr(ts,1,10)=? AND substr(ts,12,5)>='09:15' AND substr(ts,12,5)<'09:30'",
                                       (symbol, day)).fetchone()[0]
        if not first_candle or datetime.fromisoformat(first_candle).time() > time(9, 15) or opening_candles < 3:
            evaluations.append({"symbol": symbol, "status": "WAITING", "completed_5m_candles": candles,
                                "message": "Complete 09:15–09:30 IST opening-range candles are unavailable; no safe live evaluation for this session."})
            continue
        result = run_session(conn, symbol, day, "paper", float(settings["trading_capital"]), settings)
        signals = [dict(row) for row in conn.execute(
            "SELECT symbol,candle_ts,direction,entry_price,opening_high,opening_low,vwap,relative_volume,status,reason FROM signals WHERE session_id=? ORDER BY id DESC",
            (result["session_id"],)).fetchall()]
        evaluations.append({"symbol": symbol, "status": "EVALUATED", "completed_5m_candles": candles,
                            "signals": signals, "session": result})
    conn.commit()
    return {"date": day, "mode": "paper", "evaluations": evaluations,
            "signals_ready": any(item.get("signals") for item in evaluations),
            "message": "Live paper strategy evaluation completed; no broker orders were submitted."}
