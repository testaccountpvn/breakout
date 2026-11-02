import unittest

from validation import summarize


class ValidationTests(unittest.TestCase):
    def test_cost_model_reduces_pnl(self):
        rows = [{"entry_price": 100, "exit_price": 102, "quantity": 10, "realized_pnl": 20}]
        free = summarize(rows, 0, 0, 0)
        costed = summarize(rows, 5, 20, 0)
        self.assertEqual(free["net_pnl_after_costs"], 20)
        self.assertLess(costed["net_pnl_after_costs"], free["net_pnl_after_costs"])


if __name__ == "__main__": unittest.main()
