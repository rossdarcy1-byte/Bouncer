"""
Bybit Unified Margin API client
Supports both testnet and mainnet
"""

import time
import hmac
import hashlib
import logging
import requests

log = logging.getLogger(__name__)

TESTNET_URL = "https://api-testnet.bybit.com"
MAINNET_URL = "https://api.bybit.com"


class BybitClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = TESTNET_URL if testnet else MAINNET_URL
        self.recv_window = 5000
        env = "TESTNET" if testnet else "MAINNET"
        log.info(f"BybitClient initialised [{env}]")

    # ─── SIGNING ─────────────────────────────────────────────────────────────
    def _sign(self, params: str) -> str:
        ts = str(int(time.time() * 1000))
        payload = ts + self.api_key + str(self.recv_window) + params
        sig = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return ts, sig

    def _headers(self, ts: str, sig: str) -> dict:
        return {
            "X-BAPI-API-KEY":     self.api_key,
            "X-BAPI-TIMESTAMP":   ts,
            "X-BAPI-SIGN":        sig,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "Content-Type":       "application/json"
        }

    # ─── GET MARK PRICE ───────────────────────────────────────────────────────
    def get_mark_price(self, symbol: str) -> float | None:
        try:
            url = f"{self.base_url}/v5/market/tickers"
            r = requests.get(url, params={"category": "linear", "symbol": symbol}, timeout=5)
            data = r.json()
            price = float(data["result"]["list"][0]["markPrice"])
            log.info(f"Mark price {symbol}: {price}")
            return price
        except Exception as e:
            log.error(f"get_mark_price error: {e}")
            return None

    # ─── PLACE ORDER ──────────────────────────────────────────────────────────
    def place_order(self, symbol: str, side: str, qty: float,
                    sl_price: float = None, tp_price: float = None) -> dict:
        import json

        # Close any existing position in opposite direction first
        self._cancel_all_orders(symbol)

        body = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        side,
            "orderType":   "Market",
            "qty":         str(qty),
            "positionIdx": 0,   # one-way mode
            "timeInForce": "IOC"
        }

        if sl_price:
            body["stopLoss"]   = str(round(sl_price, 4))
            body["slTriggerBy"] = "MarkPrice"
        if tp_price:
            body["takeProfit"]  = str(round(tp_price, 4))
            body["tpTriggerBy"] = "MarkPrice"

        body_str = json.dumps(body)
        ts, sig  = self._sign(body_str)

        try:
            r = requests.post(
                f"{self.base_url}/v5/order/create",
                headers=self._headers(ts, sig),
                data=body_str,
                timeout=10
            )
            result = r.json()
            if result.get("retCode") != 0:
                log.error(f"Order failed: {result}")
            else:
                log.info(f"Order placed: {result['result']}")
            return result
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"error": str(e)}

    # ─── CLOSE POSITION ───────────────────────────────────────────────────────
    def close_position(self, symbol: str) -> dict:
        import json

        # Get current position
        pos = self._get_position(symbol)
        if not pos:
            return {"status": "no position"}

        size = float(pos.get("size", 0))
        if size == 0:
            return {"status": "no position"}

        side = pos.get("side")  # "Buy" or "Sell"
        close_side = "Sell" if side == "Buy" else "Buy"

        body = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        close_side,
            "orderType":   "Market",
            "qty":         str(size),
            "positionIdx": 0,
            "timeInForce": "IOC",
            "reduceOnly":  True
        }

        body_str = json.dumps(body)
        ts, sig  = self._sign(body_str)

        try:
            r = requests.post(
                f"{self.base_url}/v5/order/create",
                headers=self._headers(ts, sig),
                data=body_str,
                timeout=10
            )
            return r.json()
        except Exception as e:
            log.error(f"close_position error: {e}")
            return {"error": str(e)}

    # ─── HELPERS ──────────────────────────────────────────────────────────────
    def _get_position(self, symbol: str) -> dict | None:
        import json
        params = f"category=linear&symbol={symbol}"
        ts, sig = self._sign(params)
        try:
            r = requests.get(
                f"{self.base_url}/v5/position/list",
                headers=self._headers(ts, sig),
                params={"category": "linear", "symbol": symbol},
                timeout=5
            )
            positions = r.json()["result"]["list"]
            return positions[0] if positions else None
        except Exception as e:
            log.error(f"_get_position error: {e}")
            return None

    def _cancel_all_orders(self, symbol: str):
        import json
        body = {"category": "linear", "symbol": symbol}
        body_str = json.dumps(body)
        ts, sig = self._sign(body_str)
        try:
            requests.post(
                f"{self.base_url}/v5/order/cancel-all",
                headers=self._headers(ts, sig),
                data=body_str,
                timeout=5
            )
        except Exception as e:
            log.error(f"_cancel_all_orders error: {e}")
