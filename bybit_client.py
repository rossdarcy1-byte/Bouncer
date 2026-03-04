"""
Bybit V5 API client — testnet + mainnet
"""

import time
import hmac
import hashlib
import json
import os
import logging
import requests

log = logging.getLogger(__name__)

TESTNET_URL = "https://api-testnet.bybit.com"
MAINNET_URL = "https://api.bybit.com"
DEMO_URL    = "https://api-demo.bybit.com"


class BybitClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key     = api_key
        self.api_secret  = api_secret
        demo = os.environ.get("BYBIT_DEMO", "false").lower() == "true"
        self.base_url    = DEMO_URL if demo else (TESTNET_URL if testnet else MAINNET_URL)
        self.recv_window = "5000"
        log.info(f"BybitClient ready — {'TESTNET' if testnet else 'MAINNET'} | key={api_key[:8]}...")

    def _sign(self, body_str: str) -> tuple:
        ts      = str(int(time.time() * 1000))
        payload = ts + self.api_key + self.recv_window + body_str
        sig     = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return ts, sig

    def _headers(self, ts: str, sig: str) -> dict:
        return {
            "X-BAPI-API-KEY":     self.api_key,
            "X-BAPI-TIMESTAMP":   ts,
            "X-BAPI-SIGN":        sig,
            "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type":       "application/json"
        }

    # ── GET MARK PRICE (no auth needed) ──────────────────────────────────────
    def get_mark_price(self, symbol: str) -> float | None:
        try:
            url = f"{self.base_url}/v5/market/tickers"
            r   = requests.get(url, params={"category": "linear", "symbol": symbol}, timeout=10)
            log.info(f"Price response: {r.status_code} {r.text[:200]}")
            data  = r.json()
            price = float(data["result"]["list"][0]["markPrice"])
            return price
        except Exception as e:
            log.error(f"get_mark_price error: {e}")
            return None

    # ── PLACE ORDER ───────────────────────────────────────────────────────────
    def place_order(self, symbol: str, side: str, qty: float,
                    sl_price: float = None, tp_price: float = None) -> dict:

        body = {
            "category":    "linear",
            "symbol":      symbol,
            "side":        side,
            "orderType":   "Market",
            "qty":         str(qty),
            "positionIdx": 0,
            "timeInForce": "IOC",
        }
        if sl_price:
            body["stopLoss"]    = str(round(sl_price, 4))
            body["slTriggerBy"] = "MarkPrice"
        if tp_price:
            body["takeProfit"]  = str(round(tp_price, 4))
            body["tpTriggerBy"] = "MarkPrice"

        body_str = json.dumps(body)
        ts, sig  = self._sign(body_str)

        log.info(f"Placing order: {body_str}")
        try:
            r = requests.post(
                f"{self.base_url}/v5/order/create",
                headers=self._headers(ts, sig),
                data=body_str,
                timeout=10
            )
            log.info(f"Order response: {r.status_code} {r.text}")
            if not r.text:
                return {"error": "empty response from Bybit"}
            result = r.json()
            return result
        except Exception as e:
            log.error(f"place_order error: {e}")
            return {"error": str(e)}

    # ── CLOSE POSITION ────────────────────────────────────────────────────────
    def close_position(self, symbol: str) -> dict:
        pos = self._get_position(symbol)
        if not pos:
            return {"status": "no position found"}

        size = float(pos.get("size", 0))
        if size == 0:
            return {"status": "no open position"}

        side       = pos.get("side")
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
            log.info(f"Close response: {r.status_code} {r.text}")
            return r.json() if r.text else {"error": "empty response"}
        except Exception as e:
            return {"error": str(e)}

    # ── GET POSITION ─────────────────────────────────────────────────────────
    def _get_position(self, symbol: str) -> dict | None:
        params   = f"category=linear&symbol={symbol}"
        ts, sig  = self._sign(params)
        try:
            r = requests.get(
                f"{self.base_url}/v5/position/list",
                headers=self._headers(ts, sig),
                params={"category": "linear", "symbol": symbol},
                timeout=10
            )
            log.info(f"Position response: {r.status_code} {r.text[:300]}")
            positions = r.json()["result"]["list"]
            return positions[0] if positions else None
        except Exception as e:
            log.error(f"_get_position error: {e}")
            return None
