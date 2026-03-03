"""
TradingView → Bybit Webhook Server
5 Pairs: ETH 8hr | BTC 12hr | SOL 8hr | RUNE 3hr | DOGE 5hr
"""

import os
import logging
from flask import Flask, request, jsonify
from bybit_client import BybitClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

client = BybitClient(
    api_key    = os.environ.get("BOT1_API_KEY", ""),
    api_secret = os.environ.get("BOT1_API_SECRET", ""),
    testnet    = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"
)

SYMBOL_MAP = {
    "ETHUSDT":   ("ETHUSDT",        500),
    "BTCUSDT":   ("BTCUSDT",        500),
    "SOLUSDT":   ("SOLUSDT",        500),
    "RUNEUSDT":  ("1000RUNEUSDT",   500),
    "DOGEUSDT":  ("1000DOGEUSDT",   500),
}

WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "changeme")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    TradingView payload:
    {
      "token":  "ross_bot_2026",
      "ticker": "ETHUSDT",
      "action": "buy" | "sell" | "close",
      "price":  "2033.00",   ← current price (include this in TV alert)
      "sl":     "1900.00",
      "tp":     "2200.00"    ← optional
    }
    """
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"error": "empty payload"}), 400

    if data.get("token") != WEBHOOK_TOKEN:
        log.warning("Invalid token")
        return jsonify({"error": "unauthorized"}), 401

    ticker = data.get("ticker", "").upper().replace("/", "").replace("PERP", "")
    action = data.get("action", "").lower()
    sl     = data.get("sl")
    tp     = data.get("tp")
    price  = data.get("price")   # price sent from TradingView alert

    log.info(f"Signal → {ticker} {action} price={price} sl={sl} tp={tp}")

    if ticker not in SYMBOL_MAP:
        return jsonify({"error": f"unknown ticker {ticker}"}), 400

    bybit_symbol, risk_usdt = SYMBOL_MAP[ticker]

    if action == "close":
        result = client.close_position(bybit_symbol)
        return jsonify({"status": "closed", "result": result}), 200

    if action not in ("buy", "sell"):
        return jsonify({"error": f"unknown action {action}"}), 400

    side = "Buy" if action == "buy" else "Sell"

    # Use price from alert, fallback to live fetch
    if price:
        cur_price = float(price)
    else:
        cur_price = client.get_mark_price(bybit_symbol)
        if not cur_price:
            # Last resort — use fixed qty if price unavailable
            cur_price = None

    # Calculate qty from risk / SL distance
    if sl and cur_price:
        sl_price   = float(sl)
        sl_dist    = abs(cur_price - sl_price)
        qty        = round(risk_usdt / sl_dist, 3) if sl_dist > 0 else 0.01
    else:
        # No price info — use minimum qty
        sl_price = float(sl) if sl else None
        qty      = 0.1

    log.info(f"Order → {side} {bybit_symbol} qty={qty} sl={sl_price} tp={tp}")

    result = client.place_order(
        symbol   = bybit_symbol,
        side     = side,
        qty      = qty,
        sl_price = sl_price,
        tp_price = float(tp) if tp else None
    )

    log.info(f"Result: {result}")
    return jsonify({"status": "placed", "result": result}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
