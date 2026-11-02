"""SQLite-backed paper implementation of the documented 15-minute ORB strategy.

This module deliberately has no broker/network dependency. It turns normalized CSV
candles into durable SQLite records, evaluates signals on completed 5-minute bars,
applies the plan's risk rules, and simulates paper fills/protection/exits.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Iterable

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS strategy_versions(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, config_json TEXT NOT NULL,
 checksum TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candles(
 symbol TEXT NOT NULL, interval TEXT NOT NULL, ts TEXT NOT NULL,
 open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
 volume REAL NOT NULL DEFAULT 0, source TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(symbol, interval, ts));
CREATE TABLE IF NOT EXISTS sessions(
 id INTEGER PRIMARY KEY, session_date TEXT NOT NULL, symbol TEXT NOT NULL, mode TEXT NOT NULL,
 account_equity REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(session_date, mode, symbol));
CREATE TABLE IF NOT EXISTS session_settings(
 id INTEGER PRIMARY KEY CHECK(id=1), account_balance REAL NOT NULL, trading_capital REAL NOT NULL,
 risk_per_trade_pct REAL NOT NULL, daily_loss_pct REAL NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS premarket_context(
 id INTEGER PRIMARY KEY, context_date TEXT NOT NULL UNIQUE, market_regime TEXT NOT NULL,
 index_bias TEXT NOT NULL, volatility TEXT NOT NULL, event_risk TEXT NOT NULL,
 liquidity TEXT NOT NULL, broker_data_ready INTEGER NOT NULL DEFAULT 0,
 news_reviewed INTEGER NOT NULL DEFAULT 0, no_trade INTEGER NOT NULL DEFAULT 0,
 notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals(
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
 symbol TEXT NOT NULL, candle_ts TEXT NOT NULL, direction TEXT NOT NULL,
 entry_price REAL NOT NULL, opening_high REAL NOT NULL, opening_low REAL NOT NULL,
 vwap REAL NOT NULL, relative_volume REAL NOT NULL, index_aligned INTEGER NOT NULL,
 extension_ok INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL,
 UNIQUE(session_id, symbol, candle_ts, direction));
CREATE TABLE IF NOT EXISTS risk_decisions(
 id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL UNIQUE REFERENCES signals(id),
 approved INTEGER NOT NULL, proposed_qty INTEGER NOT NULL, approved_qty INTEGER NOT NULL,
 allowed_risk REAL NOT NULL, stop_price REAL NOT NULL, target_price REAL NOT NULL,
 reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_intents(
 id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL UNIQUE REFERENCES signals(id),
 client_ref TEXT NOT NULL UNIQUE, symbol TEXT NOT NULL, side TEXT NOT NULL,
 quantity INTEGER NOT NULL, requested_price REAL NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fills(
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES order_intents(id),
 fill_ts TEXT NOT NULL, price REAL NOT NULL, quantity INTEGER NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades(
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
 signal_id INTEGER NOT NULL REFERENCES signals(id), symbol TEXT NOT NULL, direction TEXT NOT NULL,
 quantity INTEGER NOT NULL, entry_price REAL NOT NULL, exit_price REAL NOT NULL,
 realized_pnl REAL NOT NULL, result TEXT NOT NULL, entry_ts TEXT NOT NULL, exit_ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(
 id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id), event_type TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id INTEGER, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broker_events(
 id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES order_intents(id), broker TEXT NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_quotes(
 exchange_symbol TEXT PRIMARY KEY, exchange TEXT NOT NULL, segment TEXT NOT NULL,
 trading_symbol TEXT NOT NULL, last_price REAL NOT NULL, received_at TEXT NOT NULL,
 source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live_quote_ticks(
 id INTEGER PRIMARY KEY, exchange_symbol TEXT NOT NULL, trading_symbol TEXT NOT NULL,
 segment TEXT NOT NULL, price REAL NOT NULL, tick_ts TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles(symbol, interval, ts);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id, id);
CREATE INDEX IF NOT EXISTS idx_live_quotes_received ON live_quotes(received_at);
"""

DEFAULT_CONFIG = {
    "opening_range_minutes": 15,
    "confirmation_minutes": 5,
    "entry_start": "09:30",
    "entry_cutoff": "14:45",
    "square_off": "15:15",
    "risk_per_trade_pct": 0.0025,
    "daily_loss_pct": 0.01,
    "max_losing_trades": 3,
    "max_concurrent_positions": 3,
    "exposure_per_symbol_pct": 0.20,
    "max_stop_distance_pct": 0.008,
    "relative_volume_min": 1.8,
    "relative_volume_lookback": 5,
    "extension_guard_pct": 0.0025,
    "ema_period": 20,
    "partial_exit_r": 1.0,
    "final_target_r": 2.0,
}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = conn.execute("SELECT id FROM strategy_versions WHERE active=1 LIMIT 1").fetchone()
    if existing is None:
        cfg = json.dumps(DEFAULT_CONFIG, sort_keys=True)
        conn.execute("INSERT INTO strategy_versions(name,config_json,checksum,active,created_at) VALUES(?,?,?,?,?)",
                     ("ORB Cash v1.0", cfg, "orb-cash-v1.0", 1, now()))
    conn.commit()


def active_strategy_config(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT config_json FROM strategy_versions WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    config = dict(DEFAULT_CONFIG)
    if row:
        config.update(json.loads(row["config_json"]))
    return config


def get_session_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT account_balance,trading_capital,risk_per_trade_pct,daily_loss_pct,updated_at FROM session_settings WHERE id=1").fetchone()
    if row is None:
        return {"account_balance": 500000.0, "trading_capital": 500000.0,
                "risk_per_trade_pct": DEFAULT_CONFIG["risk_per_trade_pct"] * 100,
                "daily_loss_pct": DEFAULT_CONFIG["daily_loss_pct"] * 100, "updated_at": None}
    return dict(row)


def save_session_settings(conn: sqlite3.Connection, account_balance: float, trading_capital: float,
                          risk_per_trade_pct: float, daily_loss_pct: float) -> dict:
    values = [account_balance, trading_capital, risk_per_trade_pct, daily_loss_pct]
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("session settings must be finite numbers")
    if account_balance <= 0 or trading_capital <= 0:
        raise ValueError("account balance and trading capital must be greater than zero")
    if trading_capital > account_balance:
        raise ValueError("trading capital cannot exceed account balance")
    if not 0 < risk_per_trade_pct <= 5 or not 0 < daily_loss_pct <= 20:
        raise ValueError("risk per trade must be 0-5% and daily loss must be 0-20%")
    conn.execute("""INSERT INTO session_settings(id,account_balance,trading_capital,risk_per_trade_pct,daily_loss_pct,updated_at)
        VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET account_balance=excluded.account_balance,
        trading_capital=excluded.trading_capital,risk_per_trade_pct=excluded.risk_per_trade_pct,
        daily_loss_pct=excluded.daily_loss_pct,updated_at=excluded.updated_at""",
        (account_balance, trading_capital, risk_per_trade_pct, daily_loss_pct, now()))
    conn.commit()
    return get_session_settings(conn)


def parse_timestamp(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(value).replace(tzinfo=None)


def load_csv(conn: sqlite3.Connection, path: str | Path, symbol: str) -> int:
    count = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw_ts = row.get("Timestamp") or f"{row['Date']}T{row['Time']}"
            dt = parse_timestamp(raw_ts)
            if dt.time() < time(9, 15) or dt.time() > time(15, 29):
                continue
            conn.execute("""INSERT OR REPLACE INTO candles
                (symbol,interval,ts,open,high,low,close,volume,source,completed)
                VALUES(?,?,?,?,?,?,?,?,?,1)""", (symbol, "1m", dt.isoformat(), float(row["Open"]),
                float(row["High"]), float(row["Low"]), float(row["Close"]),
                float(row.get("Volume") or 0), Path(path).name))
            count += 1
    conn.commit()
    return count


def aggregate_5m(conn: sqlite3.Connection, symbol: str, session_date: str | None = None) -> int:
    query = "SELECT * FROM candles WHERE symbol=? AND interval='1m'"
    args: list[object] = [symbol]
    if session_date:
        query += " AND substr(ts,1,10)=?"
        args.append(session_date)
    rows = conn.execute(query + " ORDER BY ts", args).fetchall()
    grouped: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        dt = parse_timestamp(row["ts"])
        offset = (dt.hour * 60 + dt.minute) - (9 * 60 + 15)
        grouped[(dt.date().isoformat(), offset // 5)].append(row)
    for (day, bucket), items in grouped.items():
        items.sort(key=lambda x: x["ts"])
        first, last = items[0], items[-1]
        ts = last["ts"]
        conn.execute("""INSERT OR REPLACE INTO candles
            (symbol,interval,ts,open,high,low,close,volume,source,completed)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (symbol, "5m", ts, first["open"], max(x["high"] for x in items),
            min(x["low"] for x in items), last["close"], sum(x["volume"] for x in items), "aggregated-1m", int(len(items) >= 5)))
    conn.commit()
    return len(grouped)


def ema(values: Iterable[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    out: list[float] = []
    current = None
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        out.append(current)
    return out


def _session_rows(conn: sqlite3.Connection, symbol: str, day: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM candles WHERE symbol=? AND interval='5m' AND completed=1 AND substr(ts,1,10)=? AND substr(ts,12,5)>='09:15' AND substr(ts,12,5)<='15:15' ORDER BY ts",
                        (symbol, day)).fetchall()


def _audit(conn, session_id: int, event_type: str, entity_type: str, entity_id: int | None, payload: dict) -> None:
    conn.execute("INSERT INTO audit_events(session_id,event_type,entity_type,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                 (session_id, event_type, entity_type, entity_id, json.dumps(payload, sort_keys=True), now()))


def _price_round(value: float, tick: float = 0.05) -> float:
    return round(math.floor(value / tick + 0.5) * tick, 2)


def run_session(conn: sqlite3.Connection, symbol: str, day: str, mode: str = "auto", equity: float = 500_000,
                risk_overrides: dict | None = None) -> dict:
    if mode not in {"paper", "assisted", "auto"}:
        raise ValueError("mode must be paper, assisted, or auto")
    rows = _session_rows(conn, symbol, day)
    if len(rows) < 5:
        raise ValueError(f"not enough completed 5-minute candles for {symbol} {day}")
    cfg = active_strategy_config(conn)
    if risk_overrides:
        cfg.update({"risk_per_trade_pct": float(risk_overrides["risk_per_trade_pct"]) / 100,
                    "daily_loss_pct": float(risk_overrides["daily_loss_pct"]) / 100})
    n_opening = cfg["opening_range_minutes"] // cfg["confirmation_minutes"]
    opening = rows[:n_opening]
    opening_high = max(x["high"] for x in opening)
    opening_low = min(x["low"] for x in opening)
    closes = [x["close"] for x in rows]
    ema_values = ema(closes, cfg["ema_period"])
    existing = conn.execute("SELECT * FROM sessions WHERE session_date=? AND mode=? AND symbol=?", (day, mode, symbol)).fetchone()
    if existing and existing["status"] == "COMPLETED":
        trade_rows = conn.execute("SELECT realized_pnl FROM trades WHERE session_id=?", (existing["id"],)).fetchall()
        return {"session_id": existing["id"], "symbol": symbol, "date": day, "mode": mode,
                "signals": conn.execute("SELECT COUNT(*) FROM signals WHERE session_id=?", (existing["id"],)).fetchone()[0],
                "trades": len(trade_rows), "daily_pnl": round(sum(x["realized_pnl"] for x in trade_rows), 2)}
    conn.execute("INSERT OR IGNORE INTO sessions(session_date,symbol,mode,account_equity,status,created_at) VALUES(?,?,?,?,?,?)",
                 (day, symbol, mode, equity, "RUNNING", now()))
    conn.commit()
    session_row = conn.execute("SELECT * FROM sessions WHERE session_date=? AND mode=? AND symbol=?", (day, mode, symbol)).fetchone()
    session_id = session_row["id"]
    _audit(conn, session_id, "SESSION_STARTED", "session", session_id, {"symbol": symbol, "mode": mode, "equity": equity})
    daily_pnl = 0.0
    losing_trades = 0
    signal_count = 0
    qualified_found = False
    trade_count = 0
    for idx in range(n_opening, len(rows) - 1):
        row = rows[idx]
        candle_dt = parse_timestamp(row["ts"])
        candle_time = candle_dt.time()
        if candle_time < time.fromisoformat(cfg["entry_start"]) or candle_time >= time.fromisoformat(cfg["entry_cutoff"]):
            continue
        prior_vols = [x["volume"] for x in rows[max(0, idx - cfg["relative_volume_lookback"]):idx] if x["volume"] > 0]
        relative_volume = row["volume"] / (sum(prior_vols) / len(prior_vols)) if prior_vols else 0.0
        vwap_volume = sum(x["volume"] for x in rows[:idx + 1])
        vwap = sum(((x["high"] + x["low"] + x["close"]) / 3) * x["volume"] for x in rows[:idx + 1]) / vwap_volume if vwap_volume else row["close"]
        long = row["close"] > opening_high and row["close"] > vwap and row["close"] > ema_values[idx]
        short = row["close"] < opening_low and row["close"] < vwap and row["close"] < ema_values[idx]
        # A single instrument/session accepts only its first qualified signal.
        if not (long or short) or qualified_found:
            continue
        direction = "LONG" if long else "SHORT"
        breakout = opening_high if long else opening_low
        extension = abs(row["close"] - breakout) / breakout
        extension_ok = extension <= cfg["extension_guard_pct"]
        signal_status = "QUALIFIED" if extension_ok and relative_volume >= cfg["relative_volume_min"] else "REJECTED"
        reason = "qualified" if signal_status == "QUALIFIED" else " or ".join(x for x, bad in [
            ("relative volume below 1.8x", relative_volume < cfg["relative_volume_min"]),
            ("extension guard exceeded", not extension_ok)]) if signal_status == "REJECTED" else ""
        signal = conn.execute("""INSERT INTO signals(session_id,symbol,candle_ts,direction,entry_price,opening_high,opening_low,vwap,relative_volume,index_aligned,extension_ok,status,reason)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (session_id, symbol, row["ts"], direction, rows[idx + 1]["open"], opening_high, opening_low,
            vwap, relative_volume, 1, int(extension_ok), signal_status, reason)).lastrowid
        signal_count += 1
        _audit(conn, session_id, "SIGNAL_EVALUATED", "signal", signal, {"direction": direction, "status": signal_status, "relative_volume": relative_volume, "vwap": vwap})
        if signal_status != "QUALIFIED":
            continue
        qualified_found = True
        entry = rows[idx + 1]["open"]
        technical_stop = row["low"] if long else row["high"]
        max_distance = entry * cfg["max_stop_distance_pct"]
        stop = max(technical_stop, entry - max_distance) if long else min(technical_stop, entry + max_distance)
        risk_per_unit = abs(entry - stop)
        allowed_risk = equity * cfg["risk_per_trade_pct"]
        proposed_qty = math.floor(allowed_risk / risk_per_unit) if risk_per_unit else 0
        exposure_qty = math.floor((equity * cfg["exposure_per_symbol_pct"]) / entry) if entry else 0
        approved = proposed_qty > 0 and exposure_qty > 0 and daily_pnl > -(equity * cfg["daily_loss_pct"]) and losing_trades < cfg["max_losing_trades"]
        approved_qty = min(proposed_qty, exposure_qty) if approved else 0
        target = entry + risk_per_unit * cfg["final_target_r"] if long else entry - risk_per_unit * cfg["final_target_r"]
        risk_reason = "approved" if approved and approved_qty == proposed_qty else ("approved and reduced by exposure cap" if approved else "risk limit, exposure cap, invalid stop distance, or zero quantity")
        risk_id = conn.execute("""INSERT INTO risk_decisions(signal_id,approved,proposed_qty,approved_qty,allowed_risk,stop_price,target_price,reason)
            VALUES(?,?,?,?,?,?,?,?)""", (signal, int(approved), proposed_qty, approved_qty, allowed_risk, _price_round(stop), _price_round(target), risk_reason)).lastrowid
        _audit(conn, session_id, "RISK_DECISION", "risk_decision", risk_id, {"approved": approved, "qty": approved_qty, "reason": risk_reason})
        if not approved:
            continue
        if mode == "paper":
            order_status = "PAPER_READY"
        elif mode == "assisted":
            order_status = "PENDING_APPROVAL"
        else:
            order_status = "SUBMITTED"
        client_ref = f"{day}-{symbol}-{signal}-{uuid.uuid4().hex[:8]}"
        order_id = conn.execute("""INSERT INTO order_intents(signal_id,client_ref,symbol,side,quantity,requested_price,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)""", (signal, client_ref, symbol, "BUY" if long else "SELL", approved_qty, entry, order_status, now())).lastrowid
        _audit(conn, session_id, "ORDER_INTENT_CREATED", "order_intent", order_id, {"mode": mode, "status": order_status, "client_ref": client_ref})
        if mode == "assisted":
            continue
        # Paper and auto both simulate a broker fill; auto skips approval.
        conn.execute("UPDATE order_intents SET status='FILLED' WHERE id=?", (order_id,))
        conn.execute("INSERT INTO fills(order_id,fill_ts,price,quantity,role) VALUES(?,?,?,?,?)", (order_id, rows[idx + 1]["ts"], entry, approved_qty, "ENTRY"))
        trade = _simulate_trade(rows, idx + 1, symbol, direction, approved_qty, entry, stop, target, cfg, session_id, signal, conn)
        daily_pnl += trade["realized_pnl"]
        trade_count += 1
        losing_trades += int(trade["realized_pnl"] <= 0)
        _audit(conn, session_id, "TRADE_CLOSED", "trade", trade["id"], trade)
        break
    conn.execute("UPDATE sessions SET status='COMPLETED' WHERE id=?", (session_id,))
    _audit(conn, session_id, "SESSION_COMPLETED", "session", session_id, {"signals": signal_count, "trades": trade_count, "daily_pnl": daily_pnl})
    conn.commit()
    return {"session_id": session_id, "symbol": symbol, "date": day, "mode": mode, "signals": signal_count, "trades": trade_count, "daily_pnl": round(daily_pnl, 2)}


def _simulate_trade(rows, entry_idx, symbol, direction, quantity, entry, stop, target, cfg, session_id, signal_id, conn):
    remaining = quantity
    pnl = 0.0
    exits = []
    half = max(1, quantity // 2)
    partial_done = False
    risk = abs(entry - stop)
    first_target = entry + risk * cfg["partial_exit_r"] if direction == "LONG" else entry - risk * cfg["partial_exit_r"]
    entry_ts = rows[entry_idx]["ts"]
    for idx in range(entry_idx, len(rows)):
        row = rows[idx]
        dt = parse_timestamp(row["ts"])
        if dt.time() >= time.fromisoformat(cfg["square_off"]):
            exit_price, role, exit_qty = row["open"], "TIME", remaining
        else:
            hit_stop = row["low"] <= stop if direction == "LONG" else row["high"] >= stop
            hit_partial = row["high"] >= first_target if direction == "LONG" else row["low"] <= first_target
            hit_final = row["high"] >= target if direction == "LONG" else row["low"] <= target
            if hit_stop:
                exit_price, role, exit_qty = stop, "STOP", remaining
            elif not partial_done and hit_partial:
                exit_price, role, exit_qty = first_target, "PARTIAL_TARGET", half
                partial_done = True
            elif hit_final:
                exit_price, role, exit_qty = target, "TARGET", remaining
            else:
                continue
        pnl += (exit_price - entry) * exit_qty if direction == "LONG" else (entry - exit_price) * exit_qty
        exits.append((row["ts"], exit_price, exit_qty, role))
        remaining -= exit_qty
        if role == "PARTIAL_TARGET":
            continue
        if remaining == 0:
            break
        break
    if not exits:
        row = rows[-1]
        exit_price = row["close"]
        exit_ts = row["ts"]
        pnl = (exit_price - entry) * remaining if direction == "LONG" else (entry - exit_price) * remaining
        exits = [(exit_ts, exit_price, remaining, "TIME")]
    exit_ts, exit_price, _, role = exits[-1]
    result = "TP" if "TARGET" in role else role
    trade_id = conn.execute("""INSERT INTO trades(session_id,signal_id,symbol,direction,quantity,entry_price,exit_price,realized_pnl,result,entry_ts,exit_ts)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (session_id, signal_id, symbol, direction, quantity, entry, exit_price, round(pnl, 2), result, entry_ts, exit_ts)).lastrowid
    return {"id": trade_id, "realized_pnl": round(pnl, 2), "result": result, "exit_ts": exit_ts}


def backtest(conn: sqlite3.Connection, symbol: str, mode: str, equity: float) -> dict:
    days = [r[0] for r in conn.execute("SELECT DISTINCT substr(ts,1,10) FROM candles WHERE symbol=? AND interval='5m' ORDER BY 1", (symbol,))]
    results = [run_session(conn, symbol, day, mode, equity) for day in days]
    trades = conn.execute("SELECT realized_pnl,result FROM trades WHERE symbol=? ORDER BY id", (symbol,)).fetchall()
    pnl = sum(r["realized_pnl"] for r in trades)
    wins = sum(r["realized_pnl"] > 0 for r in trades)
    return {"symbol": symbol, "mode": mode, "sessions": len(results), "trades": len(trades), "wins": wins,
            "losses": len(trades) - wins, "win_rate_pct": round(100 * wins / len(trades), 1) if trades else 0,
            "net_pnl": round(pnl, 2), "session_results": results}


def approve_order(conn: sqlite3.Connection, order_id: int | None = None) -> dict:
    if order_id is None:
        row = conn.execute("SELECT * FROM order_intents WHERE status='PENDING_APPROVAL' ORDER BY id DESC LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT * FROM order_intents WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise ValueError("no pending approval order found")
    if row["status"] != "PENDING_APPROVAL":
        raise ValueError(f"order {row['id']} is {row['status']}, not PENDING_APPROVAL")
    conn.execute("UPDATE order_intents SET status='APPROVED' WHERE id=?", (row["id"],))
    session_id = conn.execute("SELECT session_id FROM signals WHERE id=?", (row["signal_id"],)).fetchone()[0]
    _audit(conn, session_id, "ORDER_APPROVED", "order_intent", row["id"], {"client_ref": row["client_ref"]})
    conn.commit()
    return {"order_id": row["id"], "client_ref": row["client_ref"], "status": "APPROVED"}


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite paper engine for Breakout OS")
    parser.add_argument("--db", default=str(Path(__file__).with_name("breakout.db")))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    imp = sub.add_parser("import"); imp.add_argument("--symbol", required=True); imp.add_argument("--csv", action="append", required=True)
    agg = sub.add_parser("aggregate"); agg.add_argument("--symbol", required=True)
    run = sub.add_parser("run"); run.add_argument("--symbol", required=True); run.add_argument("--date", required=True); run.add_argument("--mode", choices=["paper", "assisted", "auto"], default="auto"); run.add_argument("--equity", type=float, default=500000)
    bt = sub.add_parser("backtest"); bt.add_argument("--symbol", required=True); bt.add_argument("--mode", choices=["paper", "assisted", "auto"], default="auto"); bt.add_argument("--equity", type=float, default=500000)
    approve = sub.add_parser("approve"); approve.add_argument("--order-id", type=int)
    args = parser.parse_args(); conn = connect(args.db); init_db(conn)
    if args.command == "init": result = {"db": args.db, "status": "initialized"}
    elif args.command == "import": result = {"rows": sum(load_csv(conn, p, args.symbol) for p in args.csv)}
    elif args.command == "aggregate": result = {"bars_5m": aggregate_5m(conn, args.symbol)}
    elif args.command == "run": result = run_session(conn, args.symbol, args.date, args.mode, args.equity)
    elif args.command == "approve": result = approve_order(conn, args.order_id)
    else: result = backtest(conn, args.symbol, args.mode, args.equity)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
