"""Guarded Groww REST adapter.

No credentials are read from SQLite or the browser. Live order placement is
disabled unless both GROWW_ACCESS_TOKEN and GROWW_LIVE_TRADING=1 are present.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class GrowwConfigError(RuntimeError):
    pass


class GrowwAPIError(RuntimeError):
    def __init__(self, message, code=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class GrowwOrder:
    trading_symbol: str
    quantity: int
    transaction_type: str
    order_reference_id: str
    exchange: str = "NSE"
    segment: str = "CASH"
    product: str = "MIS"
    order_type: str = "MARKET"
    validity: str = "DAY"
    price: float = 0
    trigger_price: float = 0


class GrowwClient:
    BASE_URL = "https://api.groww.in"

    def __init__(self, access_token=None, *, base_url=None, live_enabled=None, opener=None):
        self.access_token = access_token or os.environ.get("GROWW_ACCESS_TOKEN")
        self.base_url = (base_url or os.environ.get("GROWW_BASE_URL") or self.BASE_URL).rstrip("/")
        self.live_enabled = (os.environ.get("GROWW_LIVE_TRADING") == "1") if live_enabled is None else live_enabled
        self.opener = opener or urllib.request.urlopen

    def configuration(self):
        return {"provider": "groww", "token_configured": bool(self.access_token), "live_enabled": bool(self.live_enabled), "base_url": self.base_url}

    def _request(self, method, path, *, query=None, payload=None, allow_live=False):
        if not self.access_token:
            raise GrowwConfigError("GROWW_ACCESS_TOKEN is not configured")
        if allow_live and not self.live_enabled:
            raise GrowwConfigError("Groww live trading is disabled; set GROWW_LIVE_TRADING=1 only after approval")
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method, headers={
            "Accept": "application/json", "Authorization": f"Bearer {self.access_token}",
            "X-API-VERSION": "1.0", **({"Content-Type": "application/json"} if body else {})})
        try:
            with self.opener(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise GrowwAPIError(f"Groww HTTP {exc.code}", retryable=exc.code in {408, 429, 500, 502, 503, 504}) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GrowwAPIError("Groww network error", retryable=True) from exc
        if data.get("status") != "SUCCESS":
            payload_data = data.get("payload") or {}
            code = payload_data.get("error_code") or data.get("error_code")
            raise GrowwAPIError(data.get("message") or payload_data.get("remark") or "Groww request failed", code=code, retryable=code in {"GA003"})
        return data

    def place_order(self, order: GrowwOrder):
        payload = {"trading_symbol": order.trading_symbol, "quantity": order.quantity, "price": order.price,
                   "trigger_price": order.trigger_price, "validity": order.validity, "exchange": order.exchange,
                   "segment": order.segment, "product": order.product, "order_type": order.order_type,
                   "transaction_type": order.transaction_type, "order_reference_id": order.order_reference_id}
        return self._request("POST", "/v1/order/create", payload=payload, allow_live=True)

    def cancel_order(self, groww_order_id, segment="CASH"):
        return self._request("POST", "/v1/order/cancel", payload={"segment": segment, "groww_order_id": groww_order_id}, allow_live=True)

    def modify_order(self, groww_order_id, *, quantity, order_type, segment="CASH", price=0, trigger_price=0):
        payload = {"quantity": quantity, "price": price, "trigger_price": trigger_price, "order_type": order_type,
                   "segment": segment, "groww_order_id": groww_order_id}
        return self._request("POST", "/v1/order/modify", payload=payload, allow_live=True)

    def order_status(self, groww_order_id, segment="CASH"):
        return self._request("GET", f"/v1/order/status/{urllib.parse.quote(groww_order_id, safe='')}", query={"segment": segment})

    def order_status_by_reference(self, order_reference_id, segment="CASH"):
        return self._request("GET", f"/v1/order/status/reference/{urllib.parse.quote(order_reference_id, safe='')}", query={"segment": segment})

    def list_orders(self, segment="CASH", page=0, page_size=100):
        return self._request("GET", "/v1/order/list", query={"segment": segment, "page": page, "page_size": page_size})

    def trades_for_order(self, groww_order_id, segment="CASH", page=0, page_size=50):
        return self._request("GET", f"/v1/order/trades/{urllib.parse.quote(groww_order_id, safe='')}", query={"segment": segment, "page": page, "page_size": page_size})

    def ltp(self, exchange_symbols, segment="CASH"):
        return self._request("GET", "/v1/live-data/ltp", query={"segment": segment, "exchange_symbols": exchange_symbols})
