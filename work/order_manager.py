"""Broker-neutral order boundary for paper execution.

The same normalized contract can later be implemented by Upstox/Groww adapters.
This module intentionally never makes network calls.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class OrderManager:
    ACTIVE = ("PAPER_READY", "PENDING_APPROVAL", "SUBMITTED", "ACKNOWLEDGED")

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _audit(self, session_id, event, entity, entity_id, payload):
        self.conn.execute("INSERT INTO audit_events(session_id,event_type,entity_type,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                          (session_id, event, entity, entity_id, json.dumps(payload, sort_keys=True), utc_now()))

    def place(self, *, session_id, signal_id, symbol, side, quantity, requested_price, client_ref, mode="paper"):
        """Create an order intent exactly once for a client reference."""
        existing = self.conn.execute("SELECT * FROM order_intents WHERE client_ref=?", (client_ref,)).fetchone()
        if existing:
            return dict(existing), False
        status = "PENDING_APPROVAL" if mode == "assisted" else ("SUBMITTED" if mode == "auto" else "PAPER_READY")
        order_id = self.conn.execute("""INSERT INTO order_intents
            (signal_id,client_ref,symbol,side,quantity,requested_price,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)""", (signal_id, client_ref, symbol, side, quantity, requested_price, status, utc_now())).lastrowid
        self._audit(session_id, "ORDER_INTENT_CREATED", "order_intent", order_id,
                    {"client_ref": client_ref, "mode": mode, "status": status})
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM order_intents WHERE id=?", (order_id,)).fetchone()), True

    def cancel(self, order_id):
        row = self.conn.execute("SELECT * FROM order_intents WHERE id=?", (order_id,)).fetchone()
        if not row:
            raise ValueError(f"order {order_id} not found")
        if row["status"] not in self.ACTIVE:
            return dict(row)
        self.conn.execute("UPDATE order_intents SET status='CANCELLED' WHERE id=?", (order_id,))
        session_id = self.conn.execute("SELECT session_id FROM signals WHERE id=?", (row["signal_id"],)).fetchone()[0]
        self._audit(session_id, "ORDER_CANCELLED", "order_intent", order_id, {"client_ref": row["client_ref"]})
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM order_intents WHERE id=?", (order_id,)).fetchone())

    def kill_switch(self, session_id=None):
        query = "SELECT id FROM order_intents WHERE status IN ('PAPER_READY','PENDING_APPROVAL','SUBMITTED','ACKNOWLEDGED')"
        args = ()
        if session_id is not None:
            query += " AND signal_id IN (SELECT id FROM signals WHERE session_id=?)"
            args = (session_id,)
        ids = [row[0] for row in self.conn.execute(query, args).fetchall()]
        for order_id in ids:
            self.cancel(order_id)
        if session_id is not None:
            self.conn.execute("UPDATE sessions SET status='PAUSED_KILL_SWITCH' WHERE id=?", (session_id,))
            self._audit(session_id, "KILL_SWITCH", "session", session_id, {"cancelled_orders": ids})
        self.conn.commit()
        return {"cancelled_orders": ids, "session_id": session_id, "status": "PAUSED_KILL_SWITCH"}

    def reconcile(self, symbol=None):
        query = "SELECT * FROM order_intents"
        args = ()
        if symbol:
            query += " WHERE symbol=?"
            args = (symbol,)
        orders = [dict(row) for row in self.conn.execute(query + " ORDER BY id DESC", args).fetchall()]
        mismatches = [row for row in orders if row["status"] == "UNCERTAIN"]
        return {"orders_checked": len(orders), "mismatches": mismatches, "status": "MATCHED" if not mismatches else "PAUSED"}
