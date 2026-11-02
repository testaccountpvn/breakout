"""Offline release-gate validation for the SQLite paper engine.

This does not contact a broker. Cost assumptions are explicit CLI inputs because
brokerage, taxes and exchange charges must be confirmed for the account/broker.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlite_app import backtest, connect, init_db


def costed_trade(row, slippage_bps, brokerage_per_order, transaction_cost_bps):
    turnover = (float(row["entry_price"]) + float(row["exit_price"])) * int(row["quantity"])
    slippage = turnover * slippage_bps / 10000
    transaction = turnover * transaction_cost_bps / 10000
    brokerage = brokerage_per_order * 2
    return round(float(row["realized_pnl"]) - slippage - transaction - brokerage, 2)


def summarize(rows, slippage_bps, brokerage_per_order, transaction_cost_bps):
    values = [costed_trade(row, slippage_bps, brokerage_per_order, transaction_cost_bps) for row in rows]
    wins = sum(value > 0 for value in values)
    return {"trades": len(values), "wins": wins, "losses": len(values) - wins,
            "win_rate_pct": round(100 * wins / len(values), 1) if values else 0,
            "net_pnl_after_costs": round(sum(values), 2),
            "avg_pnl_after_costs": round(sum(values) / len(values), 2) if values else 0}


def validate(conn, symbol, slippage_bps, brokerage_per_order, transaction_cost_bps):
    sessions = [row[0] for row in conn.execute("SELECT DISTINCT session_date FROM sessions WHERE symbol=? ORDER BY session_date", (symbol,))]
    paper_sessions = conn.execute("SELECT COUNT(*) FROM sessions WHERE symbol=? AND mode='paper' AND status='COMPLETED'", (symbol,)).fetchone()[0]
    rows = conn.execute("SELECT * FROM trades WHERE symbol=? ORDER BY entry_ts", (symbol,)).fetchall()
    split = min(20, len(sessions))
    train_dates, oos_dates = set(sessions[:split]), set(sessions[split:])
    train_rows = [row for row in rows if row["entry_ts"][:10] in train_dates]
    oos_rows = [row for row in rows if row["entry_ts"][:10] in oos_dates]
    duplicates = conn.execute("SELECT client_ref,COUNT(*) c FROM order_intents GROUP BY client_ref HAVING c>1").fetchall()
    uncertain = conn.execute("SELECT COUNT(*) FROM order_intents WHERE status='UNCERTAIN'").fetchone()[0]
    audit_count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    sensitivity = []
    for slip in (0, 2, 5, 10):
        for brokerage in (0, brokerage_per_order, brokerage_per_order * 2):
            result = summarize(rows, slip, brokerage, transaction_cost_bps)
            sensitivity.append({"slippage_bps": slip, "brokerage_per_order": brokerage, **result})
    return {"symbol": symbol, "sessions": len(sessions), "paper_sessions_completed": paper_sessions,
            "cost_model": {"slippage_bps": slippage_bps, "brokerage_per_order": brokerage_per_order, "transaction_cost_bps": transaction_cost_bps},
            "all_sessions": summarize(rows, slippage_bps, brokerage_per_order, transaction_cost_bps),
            "development": summarize(train_rows, slippage_bps, brokerage_per_order, transaction_cost_bps),
            "out_of_sample": summarize(oos_rows, slippage_bps, brokerage_per_order, transaction_cost_bps),
            "sensitivity": sensitivity,
            "safety_checks": {"duplicate_client_refs": len(duplicates), "uncertain_orders": uncertain,
                              "audit_events": audit_count, "no_duplicate_orders": not duplicates,
                              "no_uncertain_orders": uncertain == 0, "audit_present": audit_count > 0},
            "gates": {"minimum_20_sessions": paper_sessions >= 20, "oos_available": bool(oos_rows),
                      "safety_checks_pass": not duplicates and uncertain == 0 and audit_count > 0,
                      "cost_model_configured": slippage_bps > 0 or brokerage_per_order > 0 or transaction_cost_bps > 0}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path(__file__).with_name("breakout.db")))
    parser.add_argument("--symbol", default="NIFTY50")
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--brokerage-per-order", type=float, default=20.0)
    parser.add_argument("--transaction-cost-bps", type=float, default=0.0)
    parser.add_argument("--out", default=str(Path(__file__).with_name("validation_report.json")))
    args = parser.parse_args()
    conn = connect(args.db)
    init_db(conn)
    # Populate a distinct paper-mode replay only if it has not already been run.
    backtest(conn, args.symbol, "paper", 500000)
    report = validate(conn, args.symbol, args.slippage_bps, args.brokerage_per_order, args.transaction_cost_bps)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
