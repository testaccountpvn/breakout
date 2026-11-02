import unittest
from datetime import datetime

from candle_monitor import IST, candle_snapshot
from sqlite_app import connect, init_db


class CandleMonitorTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def bar(self, stamp, source="GROWW_LTP", completed=1):
        self.conn.execute("INSERT INTO candles VALUES(?,?,?,?,?,?,?,?,?,?)",
                          ("RELIANCE", "1m", stamp, 100, 102, 99, 101, 0, source, completed))

    def test_only_today_market_minutes_from_live_source_and_read_is_nonmutating(self):
        for stamp in ["2026-10-30T09:15:00", "2026-11-02T08:00:00",
                      "2026-11-02T09:15:00", "2026-11-02T09:17:00",
                      "2026-11-02T15:30:00"]:
            self.bar(stamp)
        self.bar("2026-11-02T09:18:00", source="csv")
        self.bar("2026-11-02T09:19:00", completed=0)
        self.bar("2026-11-02T09:20:00")
        before = self.conn.total_changes
        result = candle_snapshot(self.conn, now=datetime(2026,11,2,9,20,30,tzinfo=IST))
        self.assertEqual([b["ts"] for b in result["candles"]],
                         ["2026-11-02T09:15:00+05:30", "2026-11-02T09:17:00+05:30"])
        self.assertEqual(result["missing_minutes"], 1)
        self.assertEqual(result["opening_minutes"], 2)
        self.assertEqual(result["summaries"][0]["completed_1m"], 2)
        self.assertEqual(self.conn.total_changes, before)

    def test_forming_candle_uses_ordered_ticks_and_does_not_claim_volume(self):
        for price in [100, 105, 98, 102]:
            self.conn.execute("INSERT INTO live_quote_ticks(exchange_symbol,trading_symbol,segment,price,tick_ts,received_at) VALUES(?,?,?,?,?,?)",
                              ("NSE_RELIANCE", "RELIANCE", "CASH", price, "2026-11-02T09:15:00", "2026-11-02T03:45:01Z"))
        result = candle_snapshot(self.conn, now=datetime(2026,11,2,9,15,30,tzinfo=IST))
        forming = result["forming"]
        self.assertEqual([forming[k] for k in ["open","high","low","close"]], [100,105,98,102])
        self.assertFalse(forming["completed"])
        self.assertIsNone(forming["volume"])
        self.assertEqual(result["candles"], [])

    def test_before_open_and_unknown_symbol(self):
        result = candle_snapshot(self.conn, now=datetime(2026,11,2,8,0,tzinfo=IST))
        self.assertEqual(result["phase"], "BEFORE_OPEN")
        self.assertIsNone(result["forming"])
        self.assertFalse(result["volume_available"])
        with self.assertRaises(ValueError):
            candle_snapshot(self.conn, symbol="INVALID")


if __name__ == "__main__":
    unittest.main()
