"""
Gold Bouncer V3 - Webhook Bot Server
=====================================
Signal source: Heikin Ashi (HA) Pine Scripts
- Bot 1 (medium):     GoldBouncer_V3_Reversal_FixedSL.pine
- Bot 2 (aggressive): GoldBouncer_V3_Reversal_TrailingSL.pine
Pairs: XAUUSD, ETHUSD, BTCUSD, SOLUSDT, DOGEUSDT, RUNEUSDT
Risk:  2% per trade
"""

from flask import Flask, request, jsonify
import os
from pybit.unified_trading import HTTP

app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# BOT CONFIGURATION
# ═══════════════════════════════════════════════════════
BOT1_API_KEY    = os.environ.get("BOT1_API_KEY")
BOT1_API_SECRET = os.environ.get("BOT1_API_SECRET")
BOT2_API_KEY    = os.environ.get("BOT2_API_KEY")
BOT2_API_SECRET = os.environ.get("BOT2_API_SECRET")
WEBHOOK_TOKEN   = os.environ.get("WEBHOOK_TOKEN", "goldbouncerv3")
RISK_PERCENT    = 0.02

PAIR_MAP = {
    "XAUUSD":   "XAUUSDT",
    "ETHUSD":   "ETHUSDT",
    "BTCUSD":   "BTCUSDT",
    "SOLUSD":   "SOLUSDT",
    "DOGEUSD":  "DOGEUSDT",
    "RUNEUSD":  "RUNEUSDT",
    "ETHUSDT":  "ETHUSDT",
    "BTCUSDT":  "BTCUSDT",
    "SOLUSDT":  "SOLUSDT",
    "DOGEUSDT": "DOGEUSDT",
    "RUNEUSDT": "RUNEUSDT",
}

# ═══════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════
def get_client(bot_id):
    if bot_id == "medium":
        return HTTP(testnet=True, api_key=BOT1_API_KEY, api_secret=BOT1_API_SECRET)
    elif bot_id == "aggressive":
        return HTTP(testnet=True, api_key=BOT2_API_KEY, api_secret=BOT2_API_SECRET)
    return None

def get_balance(client):
    try:
        r = client.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        return float(r["result"]["list"][0]["totalAvailableBalance"])
    except Exception as e:
        print(f"Balance error: {e}")
        return 0

def calc_qty(balance, price, symbol):
    qty = (balance * RISK_PERCENT) / float(price)
    if   "BTC"  in symbol: qty = round(qty, 3)
    elif "ETH"  in symbol: qty = round(qty, 2)
    elif "SOL"  in symbol: qty = round(qty, 1)
    elif "XAU"  in symbol: qty = round(qty, 2)
    elif "RUNE" in symbol: qty = round(qty, 1)
    else:                  qty = round(qty, 0)
    return max(qty, 0.001)

def close_position(client, symbol):
    try:
        positions = client.get_positions(category="linear", symbol=symbol)
        for pos in positions["result"]["list"]:
            size = float(pos["size"])
            if size > 0:
                side = "Sell" if pos["side"] == "Buy" else "Buy"
                client.place_order(category="linear", symbol=symbol,
                    side=side, orderType="Market", qty=str(size), reduceOnly=True)
                print(f"Closed {pos['side']} on {symbol}")
    except Exception as e:
        print(f"Close error: {e}")

# ═══════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════
def execute_fixed_sl(client, symbol, side, price, sl, tp):
    try:
        bal = get_balance(client)
        if bal <= 0: return {"error": "No balance"}
        qty = calc_qty(bal, price, symbol)
        close_position(client, symbol)
        order = client.place_order(category="linear", symbol=symbol,
            side=side, orderType="Market", qty=str(qty),
            stopLoss=str(sl), takeProfit=str(tp),
            slTriggerBy="MarkPrice", tpTriggerBy="MarkPrice")
        print(f"MEDIUM [HA] | {side} {qty} {symbol} | SL:{sl} TP:{tp}")
        return order
    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}

def execute_trailing_sl(client, symbol, side, price, trail):
    try:
        bal = get_balance(client)
        if bal <= 0: return {"error": "No balance"}
        qty = calc_qty(bal, price, symbol)
        close_position(client, symbol)
        order = client.place_order(category="linear", symbol=symbol,
            side=side, orderType="Market", qty=str(qty),
            trailingStop=str(trail))
        print(f"AGGRESSIVE [HA] | {side} {qty} {symbol} | Trail:{trail}")
        return order
    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════════════════
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data   = request.get_json()
        print(f"Webhook received: {data}")

        if data.get("token") != WEBHOOK_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401

        bot_id = data.get("bot")
        signal = data.get("signal", "").lower()
        pair   = data.get("pair", "").upper()
        price  = float(data.get("price", 0))
        symbol = PAIR_MAP.get(pair, pair)
        side   = "Buy" if signal == "buy" else "Sell"
        client = get_client(bot_id)

        if not client:
            return jsonify({"error": f"Unknown bot: {bot_id}"}), 400

        if bot_id == "medium":
            result = execute_fixed_sl(client, symbol, side, price,
                float(data.get("sl", 0)), float(data.get("tp", 0)))
        elif bot_id == "aggressive":
            result = execute_trailing_sl(client, symbol, side, price,
                float(data.get("trail", 0)))
        else:
            return jsonify({"error": "Unknown bot"}), 400

        return jsonify({"status": "ok", "result": result}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "Gold Bouncer V3 Running",
        "signal_source": "Heikin Ashi",
        "bots": ["medium (fixed SL)", "aggressive (trailing SL)"],
        "pairs": list(PAIR_MAP.keys()),
        "risk": "2% per trade"
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
