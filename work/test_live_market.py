import sqlite3
import unittest

from live_market import poll_quotes
from sqlite_app import connect, init_db


class FakeClient:
    def ltp(self, symbols, segment="CASH"):
        return {"status": "SUCCESS", "payload": {symbol: 100.0 + i for i, symbol in enumerate(symbols)}}


class LiveMarketTests(unittest.TestCase):
    def test_poll_stores_read_only_quotes(self):
        conn = connect(":memory:")
        init_db(conn)
        result = poll_quotes(conn, FakeClient(), ["NSE_RELIANCE", "NSE_SBIN"])
        self.assertEqual(result["updated"], 2)
        self.assertFalse(result["signals_ready"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_quotes").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM order_intents").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
