"""
Gold Bouncer V3 - Webhook Server
Routes TradingView signals to:
  - Capital.com demo (metals: Gold, Silver, Copper, Nat Gas) → 3 bots
  - Bybit demo      (crypto: ETH, BTC, SOL, RUNE, DOGE)     → existing
"""

import os
import json
import time
import hmac
import hashlib
import logging
import requests
from flask import Flask, request, jsonify
from capital_client import CapitalClient

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── SECURITY ────────────────────────────────────────────────────────────────
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "ross_bot_2026")

# ═══════════════════════════════════════════════════════════════════════════════
# CAPITAL.COM CONFIG  (metals bots)
# ═══════════════════════════════════════════════════════════════════════════════

capital = CapitalClient(
    api_key    = os.environ.get("CAPITAL_API_KEY",    ""),
    password   = os.environ.get("CAPITAL_PASSWORD",   ""),
    identifier = os.environ.get("CAPITAL_EMAIL",      "")
)

# Account IDs for each bot — populated automatically on first /setup call
# Or set them manually as env vars after running /setup
CAPITAL_ACCOUNTS = {
    "conservative": os.environ.get("CAPITAL_ACCOUNT_CONSERVATIVE", ""),
    "medium":       os.environ.get("CAPITAL_ACCOUNT_MEDIUM",       ""),
    "aggressive":   os.environ.get("CAPITAL_ACCOUNT_AGGRESSIVE",   ""),
}

# Position size per trade per instrument (units)
# Gold = oz, Silver = oz, Copper = lots, NatGas = lots
CAPITAL_SIZE = {
    "conservative": {"GOLD": 0.5, "SILVER": 5.0, "COPPER": 0.5, "NATURALGAS": 5.0},
    "medium":       {"GOLD": 1.0, "SILVER": 10.0,"COPPER": 1.0, "NATURALGAS": 10.0},
    "aggressive":   {"GOLD": 2.0, "SILVER": 20.0,"COPPER": 2.0, "NATURALGAS": 20.0},
}

# ═══════════════════════════════════════════════════════════════════════════════
# BYBIT CONFIG  (crypto bots - existing)
# ═══════════════════════════════════════════════════════════════════════════════

BYBIT_BASE    = "https://api-demo.bybit.com"
BYBIT_KEY     = os.environ.get("BYBIT_API_KEY",    "")
BYBIT_SECRET  = os.environ.get("BYBIT_API_SECRET", "")
RECV_WINDOW   = "5000"

BYBIT_SYMBOL_MAP = {
    "ETHUSDT":  ("ETHUSDT",       0.2),
    "BTCUSDT":  ("BTCUSDT",       0.01),
    "SOLUSDT":  ("SOLUSDT",       1.0),
    "RUNEUSDT": ("1000RUNEUSDT",  10.0),
    "DOGEUSDT": ("1000DOGEUSDT",  100.0),
}

# ─── BYBIT HELPERS ───────────────────────────────────────────────────────────

def bybit_sign(body_str):
    ts = str(int(time.time() * 1000))
    payload = ts + BYBIT_KEY + RECV_WINDOW + body_str
    sig = hmac.new(BYBIT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return ts, sig

def bybit_headers(ts, sig):
    return {
        "X-BAPI-API-KEY":      BYBIT_KEY,
        "X-BAPI-TIMESTAMP":    ts,
        "X-BAPI-SIGN":         sig,
        "X-BAPI-RECV-WINDOW":  RECV_WINDOW,
        "Content-Type":        "application/json"
    }

def bybit_place(ticker, action, sl=None, tp=None):
    if ticker not in BYBIT_SYMBOL_MAP:
        return {"error": f"unknown ticker {ticker}"}
    bybit_symbol, qty = BYBIT_SYMBOL_MAP[ticker]
    side = "Buy" if action == "buy" else "Sell"
    body = {
        "category":    "linear",
        "symbol":      bybit_symbol,
        "side":        side,
        "orderType":   "Market",
        "qty":         str(qty),
        "positionIdx": 0,
        "timeInForce": "IOC"
    }
    if sl:
        body["stopLoss"]    = str(sl)
        body["slTriggerBy"] = "MarkPrice"
    if tp:
        body["takeProfit"]  = str(tp)
        body["tpTriggerBy"] = "MarkPrice"
    body_str = json.dumps(body)
    ts, sig  = bybit_sign(body_str)
    r = requests.post(
        f"{BYBIT_BASE}/v5/order/create",
        headers=bybit_headers(ts, sig),
        data=body_str,
        timeout=10
    )
    log.info(f"Bybit [{ticker}]: {r.text}")
    return r.json()

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bots": "conservative+medium+aggressive"}), 200


@app.route("/setup", methods=["GET"])
def setup():
    """
    Call this once after deployment to discover your Capital.com account IDs.
    Visit: https://your-railway-url.up.railway.app/setup
    Copy the 3 account IDs and add them as Railway env vars.
    """
    try:
        accounts = capital.get_accounts()
        return jsonify(accounts), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    TradingView alert payload format:

    For METALS (Capital.com):
    {
      "token":  "ross_bot_2026",
      "source": "capital",
      "bot":    "conservative",
      "ticker": "GOLD",
      "action": "buy",
      "sl":     "2950.00",
      "tp":     "3100.00"
    }

    For CRYPTO (Bybit - existing):
    {
      "token":  "ross_bot_2026",
      "source": "bybit",
      "ticker": "ETHUSDT",
      "action": "buy",
      "sl":     "1800.00",
      "tp":     "2200.00"
    }

    action can be: buy | sell | close
    """
    data = request.get_json(silent=True)

    if not data:
        log.warning("Empty payload received")
        return jsonify({"error": "empty payload"}), 400

    if data.get("token") != WEBHOOK_TOKEN:
        log.warning("Invalid token")
        return jsonify({"error": "unauthorized"}), 401

    source = data.get("source", "").lower()
    action = data.get("action", "").lower()
    ticker = data.get("ticker", "").upper().strip()
    sl     = data.get("sl")
    tp     = data.get("tp")

    log.info(f"Signal: source={source} ticker={ticker} action={action} sl={sl} tp={tp}")

    # ── CAPITAL.COM METALS ───────────────────────────────────────────────────
    if source == "capital":
        bot = data.get("bot", "conservative").lower()

        if bot not in CAPITAL_ACCOUNTS:
            return jsonify({"error": f"unknown bot: {bot}"}), 400

        account_id = CAPITAL_ACCOUNTS[bot]
        if not account_id:
            return jsonify({
                "error": f"No account ID set for {bot}. Run /setup first and add CAPITAL_ACCOUNT_{bot.upper()} to Railway env vars."
            }), 500

        if action == "close":
            result = capital.close_all_positions(account_id, epic=ticker)
            return jsonify({"status": "closed", "result": result}), 200

        direction = "BUY" if action == "buy" else "SELL"
        size      = CAPITAL_SIZE.get(bot, {}).get(ticker, 1.0)

        try:
            result = capital.place_order(
                account_id = account_id,
                epic       = ticker,
                direction  = direction,
                size       = size,
                sl_price   = float(sl) if sl else None,
                tp_price   = float(tp) if tp else None
            )
            return jsonify({"status": "placed", "bot": bot, "ticker": ticker, "result": result}), 200
        except Exception as e:
            log.error(f"Capital.com error: {e}")
            return jsonify({"error": str(e)}), 500

    # ── BYBIT CRYPTO ─────────────────────────────────────────────────────────
    elif source == "bybit":
        if action not in ("buy", "sell"):
            return jsonify({"error": f"unknown action: {action}"}), 400
        result = bybit_place(ticker, action, sl=sl, tp=tp)
        return jsonify({"status": "placed", "result": result}), 200

    else:
        return jsonify({"error": "source must be 'capital' or 'bybit'"}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
