"""Read-only Groww-to-SQLite reconciliation."""
from __future__ import annotations

import json
from datetime import datetime, timezone


STATUS_MAP = {
    "OPEN": "ACKNOWLEDGED", "PENDING": "SUBMITTED", "EXECUTED": "FILLED",
    "COMPLETED": "FILLED", "CANCELLED": "CANCELLED", "REJECTED": "REJECTED",
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def reconcile_groww(conn, client, *, segment="CASH", page_size=100):
    """Import Groww order/trade observations without submitting any order."""
    response = client.list_orders(segment=segment, page=0, page_size=page_size)
    payload = response.get("payload") or {}
    broker_orders = payload.get("order_list") or []
    matched = 0
    unmatched = 0
    updated = 0
    for broker_order in broker_orders:
        reference = broker_order.get("order_reference_id")
        groww_id = broker_order.get("groww_order_id")
        local = conn.execute("SELECT * FROM order_intents WHERE client_ref=?", (reference,)).fetchone() if reference else None
        local_id = local["id"] if local else None
        if local:
            matched += 1
            normalized = STATUS_MAP.get(str(broker_order.get("order_status", "")).upper(), "UNCERTAIN")
            if local["status"] != normalized and normalized not in {"UNCERTAIN", "FILLED"}:
                conn.execute("UPDATE order_intents SET status=? WHERE id=?", (normalized, local_id))
                updated += 1
        else:
            unmatched += 1
        conn.execute("INSERT INTO broker_events(order_id,broker,event_type,payload_json,received_at) VALUES(?,?,?,?,?)",
                     (local_id, "GROWW", "ORDER_SNAPSHOT", json.dumps(broker_order, sort_keys=True), utc_now()))
        if groww_id:
            try:
                trades = client.trades_for_order(groww_id, segment=segment).get("payload", {}).get("trade_list", [])
            except Exception:
                trades = []
            for trade in trades:
                conn.execute("INSERT INTO broker_events(order_id,broker,event_type,payload_json,received_at) VALUES(?,?,?,?,?)",
                             (local_id, "GROWW", "TRADE_SNAPSHOT", json.dumps(trade, sort_keys=True), utc_now()))
    conn.commit()
    return {"broker": "GROWW", "orders_checked": len(broker_orders), "matched": matched, "unmatched": unmatched, "updated": updated, "status": "MATCHED" if unmatched == 0 else "REVIEW"}
