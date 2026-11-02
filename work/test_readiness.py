import unittest

from readiness import report
from sqlite_app import connect, init_db


class ReadinessTests(unittest.TestCase):
    def test_live_is_blocked_without_external_requirements(self):
        conn = connect(":memory:")
        init_db(conn)
        result = report(conn)
        self.assertFalse(result["ready_for_live"])
        self.assertFalse(result["checks"]["groww_token_configured"])
        self.assertFalse(result["checks"]["broker_approved"])


if __name__ == '__main__': unittest.main()
