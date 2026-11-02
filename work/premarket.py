"""Daily pre-market context kept separate from the deterministic ORB strategy."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CHOICES = {
    "market_regime": {"TRENDING", "RANGE", "MIXED", "UNKNOWN"},
    "index_bias": {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"},
    "volatility": {"LOW", "NORMAL", "HIGH", "UNKNOWN"},
    "event_risk": {"LOW", "MEDIUM", "HIGH", "UNKNOWN"},
    "liquidity": {"GOOD", "THIN", "UNKNOWN"},
}


def today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def _defaults(context_date: str) -> dict:
    return {"context_date": context_date, "market_regime": "UNKNOWN", "index_bias": "UNKNOWN",
            "volatility": "UNKNOWN", "event_risk": "UNKNOWN", "liquidity": "UNKNOWN",
            "broker_data_ready": False, "news_reviewed": False, "no_trade": False,
            "notes": "", "updated_at": None, "fresh": False, "ready": False,
            "status": "INCOMPLETE", "message": "Complete the daily pre-market checklist before starting a session."}


def get_context(conn, context_date: str | None = None) -> dict:
    day = context_date or today_ist()
    row = conn.execute("SELECT * FROM premarket_context WHERE context_date=?", (day,)).fetchone()
    if row is None:
        return _defaults(day)
    result = dict(row)
    for key in ("broker_data_ready", "news_reviewed", "no_trade"):
        result[key] = bool(result[key])
    result["fresh"] = True
    result["ready"] = (not result["no_trade"] and result["broker_data_ready"] and result["news_reviewed"]
                        and all(result[k] != "UNKNOWN" for k in CHOICES))
    result["status"] = "NO-TRADE" if result["no_trade"] else ("READY" if result["ready"] else "INCOMPLETE")
    result["message"] = ("No-trade gate is active for this date." if result["no_trade"] else
                          "Daily context is complete; the ORB strategy may evaluate signals." if result["ready"] else
                          "Complete all required checks before starting a trading session.")
    return result


def save_context(conn, payload: dict) -> dict:
    day = str(payload.get("context_date") or today_ist())
    values = {key: str(payload.get(key, "UNKNOWN")).upper() for key in CHOICES}
    for key, allowed in CHOICES.items():
        if values[key] not in allowed:
            raise ValueError(f"invalid {key}")
    notes = str(payload.get("notes") or "").strip()[:1000]
    flags = (int(bool(payload.get("broker_data_ready"))), int(bool(payload.get("news_reviewed"))),
             int(bool(payload.get("no_trade"))))
    updated = datetime.now(IST).replace(microsecond=0).isoformat()
    conn.execute("""INSERT INTO premarket_context(context_date,market_regime,index_bias,volatility,event_risk,liquidity,
        broker_data_ready,news_reviewed,no_trade,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(context_date) DO UPDATE SET market_regime=excluded.market_regime,index_bias=excluded.index_bias,
        volatility=excluded.volatility,event_risk=excluded.event_risk,liquidity=excluded.liquidity,
        broker_data_ready=excluded.broker_data_ready,news_reviewed=excluded.news_reviewed,no_trade=excluded.no_trade,
        notes=excluded.notes,updated_at=excluded.updated_at""",
        (day, values["market_regime"], values["index_bias"], values["volatility"], values["event_risk"],
         values["liquidity"], *flags, notes, updated))
    conn.commit()
    return get_context(conn, day)


def auto_refresh_context(conn, quote_rows: list[dict]) -> dict:
    """Infer a readable daily context from observed Groww quote movement.

    This is deliberately a transparent rules model, not an invented AI/news score.
    News remains unavailable until a real approved news source is connected.
    """
    day = today_ist()
    prices = {str(row.get("trading_symbol")): float(row["last_price"]) for row in quote_rows if row.get("last_price")}
    moves = []
    for symbol, first, last in conn.execute(
        "SELECT trading_symbol,MIN(price),MAX(price) FROM live_quote_ticks WHERE substr(tick_ts,1,10)=? GROUP BY trading_symbol", (day,)
    ).fetchall():
        if first and last and first > 0:
            moves.append((float(last) - float(first)) / float(first))
    if not moves and prices:
        moves = [0.0 for _ in prices]
    if not moves:
        return get_context(conn, day)
    average = sum(moves) / len(moves)
    directional = sum(1 for move in moves if move * average >= 0) / len(moves)
    average_abs = sum(abs(move) for move in moves) / len(moves)
    bias = "BULLISH" if average >= 0.003 else "BEARISH" if average <= -0.003 else "NEUTRAL"
    regime = "TRENDING" if abs(average) >= 0.003 and directional >= 0.6 else "RANGE" if average_abs < 0.0015 else "MIXED"
    volatility = "HIGH" if average_abs >= 0.01 else "NORMAL" if average_abs >= 0.003 else "LOW"
    result = save_context(conn, {"context_date": day, "market_regime": regime, "index_bias": bias,
        "volatility": volatility, "event_risk": "UNKNOWN", "liquidity": "GOOD" if len(prices) >= 3 else "THIN",
        "broker_data_ready": bool(prices), "news_reviewed": False, "no_trade": False,
        "notes": f"Auto analysis from {len(prices)} Groww quotes; news source not connected."})
    result.update({"analysis_source": "GROWW_LTP_RULES", "observations": len(prices), "news_source": "NOT_CONNECTED"})
    return result
