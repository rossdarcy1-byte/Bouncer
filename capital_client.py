"""
Capital.com REST API Client
Handles authentication, order placement and closing for all 3 demo accounts
"""

import requests
import logging

log = logging.getLogger(__name__)

# Demo API base URL
BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

# Capital.com epic names for our instruments
EPIC_MAP = {
    "GOLD":       "GOLD",
    "XAUUSD":     "GOLD",
    "SILVER":     "SILVER",
    "XAGUSD":     "SILVER",
    "COPPER":     "COPPER",
    "XUCUSD":     "COPPER",
    "NATURALGAS": "NATURALGAS",
    "NATGAS":     "NATURALGAS",
}


class CapitalClient:
    def __init__(self, api_key: str, password: str, identifier: str):
        """
        api_key    - the key generated in Capital.com settings
        password   - the custom password set when generating the key
        identifier - your Capital.com login email
        """
        self.api_key    = api_key
        self.password   = password
        self.identifier = identifier
        self.cst        = None
        self.security   = None

    # ─── AUTHENTICATION ───────────────────────────────────────────────────────

    def _session(self):
        """Create a session and store CST + X-SECURITY-TOKEN headers"""
        resp = requests.post(
            f"{BASE_URL}/session",
            json={
                "identifier":        self.identifier,
                "password":          self.password,
                "encryptedPassword": False
            },
            headers={
                "X-CAP-API-KEY": self.api_key,
                "Content-Type":  "application/json"
            },
            timeout=10
        )
        log.info(f"Session status: {resp.status_code}")
        log.info(f"Session response: {resp.text}")
        resp.raise_for_status()
        self.cst      = resp.headers.get("CST")
        self.security = resp.headers.get("X-SECURITY-TOKEN")
        log.info("Capital.com session created")
        return True

    def _headers(self):
        """Return auth headers, refreshing session if needed"""
        if not self.cst:
            self._session()
        return {
            "CST":               self.cst,
            "X-SECURITY-TOKEN":  self.security,
            "Content-Type":      "application/json"
        }

    # ─── ACCOUNTS ─────────────────────────────────────────────────────────────

    def get_accounts(self):
        """Fetch all accounts and their IDs - run once to discover IDs"""
        resp = requests.get(
            f"{BASE_URL}/accounts",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def switch_account(self, account_id: str):
        """Switch active account context"""
        resp = requests.put(
            f"{BASE_URL}/session",
            json={"accountId": account_id},
            headers=self._headers(),
            timeout=10
        )
        # Session tokens refresh on account switch
        self.cst      = resp.headers.get("CST",              self.cst)
        self.security = resp.headers.get("X-SECURITY-TOKEN", self.security)
        resp.raise_for_status()
        log.info(f"Switched to account {account_id}")

    # ─── POSITIONS ────────────────────────────────────────────────────────────

    def place_order(self,
                    account_id: str,
                    epic:       str,
                    direction:  str,   # "BUY" or "SELL"
                    size:       float,
                    sl_price:   float = None,
                    tp_price:   float = None):
        """
        Open a position on the specified account.
        size = number of units (e.g. 1 = 1 oz of Gold)
        """
        self._session()              # fresh session per trade for reliability
        self.switch_account(account_id)

        epic_code = EPIC_MAP.get(epic.upper(), epic.upper())

        body = {
            "epic":              epic_code,
            "direction":         direction.upper(),
            "size":              size,
            "guaranteedStop":    False,
            "trailingStop":      False,
        }

        if sl_price:
            body["stopLevel"] = sl_price
        if tp_price:
            body["profitLevel"] = tp_price

        resp = requests.post(
            f"{BASE_URL}/positions",
            json=body,
            headers=self._headers(),
            timeout=10
        )
        log.info(f"Place order response [{resp.status_code}]: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def close_all_positions(self, account_id: str, epic: str = None):
        """Close all open positions on an account (optionally filtered by epic)"""
        self._session()
        self.switch_account(account_id)

        # Get open positions
        resp = requests.get(
            f"{BASE_URL}/positions",
            headers=self._headers(),
            timeout=10
        )
        resp.raise_for_status()
        positions = resp.json().get("positions", [])

        closed = []
        for pos in positions:
            pos_epic = pos.get("market", {}).get("epic", "")
            if epic and EPIC_MAP.get(epic.upper()) != pos_epic:
                continue
            deal_id = pos.get("position", {}).get("dealId")
            if deal_id:
                close_resp = requests.delete(
                    f"{BASE_URL}/positions/{deal_id}",
                    headers=self._headers(),
                    timeout=10
                )
                log.info(f"Closed {deal_id}: {close_resp.status_code}")
                closed.append(deal_id)

        return {"closed": closed}
