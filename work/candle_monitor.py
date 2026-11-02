"""Read-only, India-time view of the stored Groww capture pipeline."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from live_market import DEFAULT_EXCHANGE_SYMBOLS, latest_quotes

IST = ZoneInfo("Asia/Kolkata")


def candle_snapshot(conn, symbol="RELIANCE", now=None):
    now = (now or datetime.now(IST)).astimezone(IST)
    symbols = [item.split("_", 1)[1] for item in DEFAULT_EXCHANGE_SYMBOLS]
    if symbol not in symbols:
        raise ValueError("Select a configured capture symbol")
    day = now.date().isoformat()
    start, end = day + "T09:15:00", day + "T15:30:00"
    current_minute = now.replace(second=0, microsecond=0, tzinfo=None).isoformat()
    rows = [dict(row) for row in conn.execute(
        """SELECT ts,open,high,low,close,volume,completed FROM candles
        WHERE symbol=? AND interval='1m' AND source='GROWW_LTP'
        AND completed=1 AND ts>=? AND ts<? AND ts<? ORDER BY ts""",
        (symbol, start, end, current_minute))]
    for row in rows:
        row["ts"] += "+05:30"
    # Current bar is derived from captured ticks, never inserted by a UI read.
    ticks = conn.execute("""SELECT price,received_at FROM live_quote_ticks
        WHERE trading_symbol=? AND tick_ts=? AND tick_ts>=? AND tick_ts<?
        ORDER BY id""", (symbol, current_minute, start, end)).fetchall()
    forming = None
    if ticks:
        prices = [float(row["price"]) for row in ticks]
        forming = {"ts": current_minute + "+05:30", "open": prices[0],
                   "high": max(prices), "low": min(prices), "close": prices[-1],
                   "volume": None, "completed": False, "samples": len(prices)}
    quotes = {row["trading_symbol"]: row for row in latest_quotes(conn)}
    summaries = []
    for item in symbols:
        counts = conn.execute("""SELECT interval,COUNT(*) AS n FROM candles
            WHERE symbol=? AND completed=1 AND ts>=? AND ts<? AND ts<?
            AND (source='GROWW_LTP' OR (interval='5m' AND source='aggregated-1m'))
            GROUP BY interval""", (item, start, end, current_minute)).fetchall()
        counts = {row["interval"]: row["n"] for row in counts}
        samples = conn.execute("""SELECT COUNT(*) FROM live_quote_ticks
            WHERE trading_symbol=? AND tick_ts>=? AND tick_ts<?""", (item, start, end)).fetchone()[0]
        summaries.append({"symbol": item, "quote": quotes.get(item),
                          "completed_1m": counts.get("1m", 0),
                          "completed_5m": counts.get("5m", 0), "samples": samples})
    minutes = [datetime.fromisoformat(row["ts"]) for row in rows]
    gaps = sum(max(0, int((b-a).total_seconds() // 60)-1) for a,b in zip(minutes, minutes[1:]))
    opening = sum(start <= row["ts"][:19] < day + "T09:30:00" for row in rows)
    # Weekday clock state; exchange holiday detection is not configured.
    phase = "WEEKEND" if now.weekday() >= 5 else "BEFORE_OPEN" if now.time() < time(9,15) else "AFTER_CLOSE" if now.time() >= time(15,30) else "MARKET_WINDOW"
    return {"date": day, "server_now": now.isoformat(), "timezone": "Asia/Kolkata",
            "symbol": symbol, "symbols": symbols, "phase": phase,
            "candles": rows, "forming": forming, "summaries": summaries,
            "opening_minutes": opening, "missing_minutes": gaps,
            "source": "GROWW_LTP", "sampling_seconds": 60,
            "volume_available": False,
            "quality_note": "Sampled Groww prices, not exchange OHLCV. One-minute sampling can miss intraminute highs/lows; volume is unavailable."}
