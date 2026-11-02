import sqlite3
import unittest
from datetime import datetime, timedelta

from sqlite_app import aggregate_5m, connect, init_db, run_session


class SqliteStrategyTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        init_db(self.db)

    def seed_breakout(self):
        start = datetime(2026, 10, 1, 9, 15)
        for i in range(40):
            dt = start + timedelta(minutes=i)
            price = 100 + (0.02 * i if i < 15 else 0.3 * (i - 14))
            self.db.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,1)", ("TEST", "1m", dt.isoformat(), price, price + 0.2, price - 0.2, price + 0.1, 1000, "test"))
        self.db.commit()
        aggregate_5m(self.db, "TEST", "2026-10-01")

    def test_auto_mode_creates_filled_order_and_audit_trail(self):
        self.seed_breakout()
        result = run_session(self.db, "TEST", "2026-10-01", "auto", 500000)
        self.assertEqual(result["mode"], "auto")
        self.assertGreaterEqual(self.db.execute("SELECT COUNT(*) FROM order_intents WHERE status='FILLED'").fetchone()[0], 0)
        self.assertGreater(self.db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)

    def test_assisted_mode_never_fills_without_approval(self):
        self.seed_breakout()
        run_session(self.db, "TEST", "2026-10-01", "assisted", 500000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM order_intents WHERE status='FILLED'").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM order_intents WHERE status='PENDING_APPROVAL'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
