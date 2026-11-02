import json
import os
import unittest

from groww_adapter import GrowwAPIError, GrowwClient, GrowwConfigError, GrowwOrder


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()


class GrowwAdapterTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        def opener(request, timeout=10):
            self.requests.append(request)
            return FakeResponse({"status": "SUCCESS", "payload": {"groww_order_id": "G-1"}})
        self.client = GrowwClient("token", live_enabled=True, opener=opener)

    def test_order_payload_and_headers(self):
        self.client.place_order(GrowwOrder("RELIANCE", 10, "BUY", "REF-1234"))
        request = self.requests[0]
        self.assertEqual(request.full_url, "https://api.groww.in/v1/order/create")
        self.assertEqual(request.get_header("X-api-version"), "1.0")
        body = json.loads(request.data.decode())
        self.assertEqual(body["order_reference_id"], "REF-1234")
        self.assertEqual(body["segment"], "CASH")

    def test_live_order_is_guarded(self):
        client = GrowwClient("token", live_enabled=False, opener=lambda *args: None)
        with self.assertRaises(GrowwConfigError):
            client.place_order(GrowwOrder("RELIANCE", 10, "BUY", "REF-1234"))

    def test_error_category_is_preserved(self):
        def opener(*args, **kwargs): return FakeResponse({"status": "FAILURE", "payload": {"error_code": "GA003"}})
        client = GrowwClient("token", live_enabled=True, opener=opener)
        with self.assertRaises(GrowwAPIError) as ctx:
            client.order_status("G-1")
        self.assertEqual(ctx.exception.code, "GA003")
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__": unittest.main()
