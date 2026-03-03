"""
TradingView → Bybit Webhook Server
5 Pairs: ETH 8hr | BTC 12hr | SOL 8hr | RUNE 3hr | DOGE 5hr
"""

import os
import logging
from flask import Flask, request, jsonify
from bybit_client import BybitClient

# ─── LOGGING ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ─── BYBIT CLIENT ────────────────────────────────────────────────────────────
client = BybitClient(
    api_key    = os.environ.get("BOT1_API_KEY", ""),
    api_secret = os.environ.get("BOT1_API_SECRET", ""),
    testnet    = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"
)

# ─── SYMBOL MAP ──────────────────────────────────────────────────────────────
# Maps TradingView ticker → Bybit symbol + risk per trade (USDT)
SYMBOL_MAP = {
    # TV ticker      Bybit symbol    Risk USDT
    "ETHUSDT":    ("ETHUSDT",       50),
    "BTCUSDT":    ("BTCUSDT",       50),
    "SOLUSDT":    ("SOLUSDT",       50),
    "RUNEUSDT":   ("1000RUNEUSDT",  50),   # adjust if Bybit uses 1000 prefix
    "DOGEUSDT":   ("1000DOGEUSDT",  50),   # Bybit uses 1000DOGE for perps
}

# ─── SECURITY TOKEN ──────────────────────────────────────────────────────────
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "changeme")

# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Expected JSON payload from TradingView alert:
    {
      "token":    "your_secret_token",
      "ticker":   "ETHUSDT",
      "action":   "buy"  | "sell" | "close",
      "sl":       "1900.00",    ← stop loss price (optional, uses default if missing)
      "tp":       "2100.00"     ← take profit price (optional)
    }
    """
    data = request.get_json(silent=True)

    if not data:
        log.warning("Empty payload received")
        return jsonify({"error": "empty payload"}), 400

    # Token check
    if data.get("token") != WEBHOOK_TOKEN:
        log.warning("Invalid token received")
        return jsonify({"error": "unauthorized"}), 401

    ticker = data.get("ticker", "").upper().replace("/", "").replace("PERP", "")
    action = data.get("action", "").lower()
    sl     = data.get("sl")
    tp     = data.get("tp")

    log.info(f"Signal received → ticker={ticker} action={action} sl={sl} tp={tp}")

    if ticker not in SYMBOL_MAP:
        log.error(f"Unknown ticker: {ticker}")
        return jsonify({"error": f"unknown ticker {ticker}"}), 400

    bybit_symbol, risk_usdt = SYMBOL_MAP[ticker]

    # ── CLOSE ────────────────────────────────────────────────────────────────
    if action == "close":
        result = client.close_position(bybit_symbol)
        log.info(f"Close result: {result}")
        return jsonify({"status": "closed", "result": result}), 200

    # ── OPEN LONG / SHORT ─────────────────────────────────────────────────────
    if action not in ("buy", "sell"):
        return jsonify({"error": f"unknown action {action}"}), 400

    side = "Buy" if action == "buy" else "Sell"

    # Get current price to calculate position size
    price = client.get_mark_price(bybit_symbol)
    if not price:
        return jsonify({"error": "could not fetch price"}), 500

    # Position size = risk_usdt / distance_to_SL
    # If no SL given, default to 1% of price
    if sl:
        sl_price = float(sl)
        sl_distance = abs(price - sl_price)
    else:
        sl_distance = price * 0.01   # default 1% SL
        sl_price = price - sl_distance if side == "Buy" else price + sl_distance

    qty = round(risk_usdt / sl_distance, 3) if sl_distance > 0 else 0.01

    log.info(f"Placing {side} {bybit_symbol} | qty={qty} | price={price} | sl={sl_price} | tp={tp}")

    result = client.place_order(
        symbol   = bybit_symbol,
        side     = side,
        qty      = qty,
        sl_price = sl_price,
        tp_price = float(tp) if tp else None
    )

    log.info(f"Order result: {result}")
    return jsonify({"status": "placed", "result": result}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
