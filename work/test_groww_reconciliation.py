import unittest

from groww_reconciliation import reconcile_groww
from sqlite_app import connect, init_db


class FakeGroww:
    def list_orders(self, **kwargs):
        return {"status": "SUCCESS", "payload": {"order_list": [{"groww_order_id": "G-1", "order_reference_id": "REF-1", "order_status": "OPEN"}, {"groww_order_id": "G-2", "order_reference_id": "FOREIGN", "order_status": "EXECUTED"}]}}

    def trades_for_order(self, groww_order_id, **kwargs):
        return {"status": "SUCCESS", "payload": {"trade_list": [{"groww_order_id": groww_order_id, "quantity": 10, "price": 100}]}}


class ReconciliationTests(unittest.TestCase):
    def test_records_matches_and_unmatched_orders(self):
        conn = connect(":memory:")
        init_db(conn)
        conn.execute("INSERT INTO sessions(session_date,symbol,mode,account_equity,status,created_at) VALUES('2026-10-01','TEST','paper',500000,'RUNNING','now')")
        session_id = conn.execute("SELECT id FROM sessions").fetchone()[0]
        conn.execute("INSERT INTO signals(session_id,symbol,candle_ts,direction,entry_price,opening_high,opening_low,vwap,relative_volume,index_aligned,extension_ok,status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (session_id,'TEST','2026-10-01T09:45:00','LONG',100,99,98,99,2,1,1,'QUALIFIED','qualified'))
        signal_id = conn.execute("SELECT id FROM signals").fetchone()[0]
        conn.execute("INSERT INTO order_intents(signal_id,client_ref,symbol,side,quantity,requested_price,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (signal_id,'REF-1','TEST','BUY',10,100,'SUBMITTED','now'))
        conn.commit()
        result = reconcile_groww(conn, FakeGroww())
        self.assertEqual(result['matched'], 1)
        self.assertEqual(result['unmatched'], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM broker_events").fetchone()[0], 4)


if __name__ == '__main__': unittest.main()
