"""
Gold Bouncer V3 - Webhook Bot Server
=====================================
Receives TradingView alerts and executes trades on Bybit Testnet.

IMPORTANT: All signals must be fired from the Heikin Ashi (HA) versions
of the Gold Bouncer V3 Pine Scripts:
  - GoldBouncer_V3_Reversal_FixedSL.pine     (Bot 1 - medium)
  - GoldBouncer_V3_Reversal_TrailingSL.pine   (Bot 2 - aggressive)

Both Pine Scripts calculate signals internally using Heikin Ashi candles
regardless of chart candle type. Do NOT use non-HA versions with this bot.

Supported pairs: XAUUSD, ETHUSD, BTCUSD, SOLUSDT, DOGEUSDT, RUNEUSDT
Position sizing: 2% of account balance per trade
"""

from flask import Flask, request, jsonify
import os
from pybit.unified_trading import HTTP

app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# BOT CONFIGURATION
# ═══════════════════════════════════════════════════════

# Bot 1 - Medium: Reversal with Fixed SL (Heikin Ashi signals)
BOT1_API_KEY    = os.environ.get("BOT1_API_KEY")
BOT1_API_SECRET = os.environ.get("BOT1_API_SECRET")

# Bot 2 - Aggressive: Reversal with Trailing SL (Heikin Ashi signals)
BOT2_API_KEY    = os.environ.get("BOT2_API_KEY")
BOT2_API_SECRET = os.environ.get("BOT2_API_SECRET")

# Security token - must match what TradingView sends
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "goldbouncerv3")

# Position size (2% of account per trade)
RISK_PERCENT = 0.02

# Pair mapping: TradingView symbol -> Bybit symbol
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
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════

def get_client(bot_id):
    """Get Bybit client for the specified bot"""
    if bot_id == "medium":
        return HTTP(testnet=True, api_key=BOT1_API_KEY, api_secret=BOT1_API_SECRET)
    elif bot_id == "aggressive":
        return HTTP(testnet=True, api_key=BOT2_API_KEY, api_secret=BOT2_API_SECRET)
    return None


def get_account_balance(client):
    """Get available USDT balance from Unified Trading Account"""
    try:
        resp    = client.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        balance = float(resp["result"]["list"][0]["totalAvailableBalance"])
        return balance
    except Exception as e:
        print(f"Balance error: {e}")
        return 0


def calculate_qty(balance, price, symbol):
    """Calculate position size based on 2% risk of account balance"""
    usdt_to_use = balance * RISK_PERCENT
    qty = usdt_to_use / float(price)
    if   "BTC"  in symbol: qty = round(qty, 3)
    elif "ETH"  in symbol: qty = round(qty, 2)
    elif "SOL"  in symbol: qty = round(qty, 1)
    elif "XAU"  in symbol: qty = round(qty, 2)
    elif "RUNE" in symbol: qty = round(qty, 1)
    else:                  qty = round(qty, 0)
    return max(qty, 0.001)


def close_existing_position(client, symbol):
    """Close any existing position before entering new one (reversal logic)"""
    try:
        positions = client.get_positions(category="linear", symbol=symbol)
        for pos in positions["result"]["list"]:
            size = float(pos["size"])
            if size > 0:
                side = "Sell" if pos["side"] == "Buy" else "Buy"
                client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Market",
                    qty=str(size),
                    reduceOnly=True
                )
                print(f"Closed existing {pos['side']} position on {symbol}")
    except Exception as e:
        print(f"Close position error: {e}")


# ═══════════════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════════════

def execute_fixed_sl(client, symbol, side, price, sl_price, tp_price):
    """
    Bot 1 - Medium: Fixed SL + TP
    Signal source: GoldBouncer_V3_Reversal_FixedSL.pine (Heikin Ashi)
    """
    try:
        balance = get_account_balance(client)
        if balance <= 0:
            return {"error": "Insufficient balance"}

        qty = calculate_qty(balance, price, symbol)
        close_existing_position(client, symbol)

        order = client.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            stopLoss=str(sl_price),
            takeProfit=str(tp_price),
            slTriggerBy="MarkPrice",
            tpTriggerBy="MarkPrice"
        )
        print(f"BOT1 Fixed SL [HA] | {side} {qty} {symbol} | SL: {sl_price} | TP: {tp_price}")
        return order

    except Exception as e:
        print(f"Fixed SL execution error: {e}")
        return {"error": str(e)}


def execute_trailing_sl(client, symbol, side, price, trail_distance):
    """
    Bot 2 - Aggressive: Trailing SL
    Signal source: GoldBouncer_V3_Reversal_TrailingSL.pine (Heikin Ashi)
    """
    try:
        balance = get_account_balance(client)
        if balance <= 0:
            return {"error": "Insufficient balance"}

        qty = calculate_qty(balance, price, symbol)
        close_existing_position(client, symbol)

        order = client.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            trailingStop=str(trail_distance)
        )
        print(f"BOT2 Trailing SL [HA] | {side} {qty} {symbol} | Trail: {trail_distance}")
        return order

    except Exception as e:
        print(f"Trailing SL execution error: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════
# WEBHOOK ENDPOINT
# ═══════════════════════════════════════════════════════

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Expected JSON payload from TradingView alert:

    Bot 1 (Medium - Fixed SL) - from GoldBouncer_V3_Reversal_FixedSL.pine [HA]:
    {
        "token":  "goldbouncerv3",
        "bot":    "medium",
        "signal": "buy" or "sell",
        "pair":   "BTCUSD",
        "price":  "{{close}}",
        "sl":     "{{plot_0}}",
        "tp":     "{{plot_1}}"
    }

    Bot 2 (Aggressive - Trailing SL) - from GoldBouncer_V3_Reversal_TrailingSL.pine [HA]:
    {
        "token":  "goldbouncerv3",
        "bot":    "aggressive",
        "signal": "buy" or "sell",
        "pair":   "BTCUSD",
        "price":  "{{close}}",
        "trail":  "500"
    }
    """
    try:
        data = request.get_json()
        print(f"Received webhook: {data}")

        # Validate security token
        if data.get("token") != WEBHOOK_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401

        # Parse payload
        bot_id = data.get("bot")
        signal = data.get("signal", "").lower()
        pair   = data.get("pair", "").upper()
        price  = float(data.get("price", 0))

        # Map to Bybit symbol
        symbol = PAIR_MAP.get(pair, pair)

        # Determine order side
        side = "Buy" if signal == "buy" else "Sell"

        # Get correct API client
        client = get_client(bot_id)
        if not client:
            return jsonify({"error": f"Unknown bot: {bot_id}"}), 400

        # Execute trade
        if bot_id == "medium":
            sl_price = float(data.get("sl", 0))
            tp_price = float(data.get("tp", 0))
            result   = execute_fixed_sl(client, symbol, side, price, sl_price, tp_price)

        elif bot_id == "aggressive":
            trail  = float(data.get("trail", 0))
            result = execute_trailing_sl(client, symbol, side, price, trail)

        else:
            return jsonify({"error": "Unknown bot type"}), 400

        return jsonify({"status": "ok", "result": result}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "Gold Bouncer V3 Bot Running",
        "signal_source": "Heikin Ashi (HA) Pine Scripts",
        "bots": ["medium (fixed SL)", "aggressive (trailing SL)"],
        "pairs": list(PAIR_MAP.keys()),
        "risk_per_trade": "2%"
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
