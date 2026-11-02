import unittest

from order_manager import OrderManager
from sqlite_app import connect, init_db


class OrderManagerTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.conn.execute("INSERT INTO sessions(session_date,symbol,mode,account_equity,status,created_at) VALUES('2026-10-01','TEST','paper',500000,'RUNNING','now')")
        session_id = self.conn.execute("SELECT id FROM sessions").fetchone()[0]
        self.conn.execute("INSERT INTO signals(session_id,symbol,candle_ts,direction,entry_price,opening_high,opening_low,vwap,relative_volume,index_aligned,extension_ok,status,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (session_id,'TEST','2026-10-01T09:45:00','LONG',100,99,98,99,2,1,1,'QUALIFIED','qualified'))
        self.conn.commit()
        self.session_id = session_id
        self.signal_id = self.conn.execute("SELECT id FROM signals").fetchone()[0]

    def test_place_is_idempotent(self):
        manager = OrderManager(self.conn)
        first, created = manager.place(session_id=self.session_id, signal_id=self.signal_id, symbol='TEST', side='BUY', quantity=10, requested_price=100, client_ref='same-ref')
        second, created_again = manager.place(session_id=self.session_id, signal_id=self.signal_id, symbol='TEST', side='BUY', quantity=10, requested_price=100, client_ref='same-ref')
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM order_intents').fetchone()[0], 1)

    def test_kill_switch_cancels_active_orders(self):
        manager = OrderManager(self.conn)
        manager.place(session_id=self.session_id, signal_id=self.signal_id, symbol='TEST', side='BUY', quantity=10, requested_price=100, client_ref='kill-ref')
        result = manager.kill_switch(self.session_id)
        self.assertEqual(result['status'], 'PAUSED_KILL_SWITCH')
        self.assertEqual(self.conn.execute("SELECT status FROM order_intents").fetchone()[0], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
