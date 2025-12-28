from flask import Flask, request, jsonify
import requests
import os
import logging
from typing import Dict, Any

# ============================================================
# APP
# ============================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================
# TOPSTEPX CONFIG
# ============================================================
BASE_URL = "https://api.topstepx.com"

TOPSTEP_USER = os.getenv("TOPSTEP_USER")
TOPSTEP_KEY  = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

# ============================================================
# SYMBOL CONFIG (per contract)
# ============================================================
SYMBOL_CONFIG = {
    "MNQ": {
        "contractId": "CON.F.US.MNQ.H26",
        "tickSize": 0.25,
        "stopTicks": 120,
        "tpTicks": 180,
    },
    "MGC": {
        "contractId": "CON.F.US.MGC.G26",
        "tickSize": 0.10,
        "stopTicks": 80,
        "tpTicks": 120,
    }
}

# ============================================================
# CACHE
# ============================================================
cached_token = None
cached_account_id = None

# ============================================================
# AUTH
# ============================================================
def connect_topstep():
    global cached_token, cached_account_id

    logging.info("Connecting to TopstepX...")

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": TOPSTEP_USER, "apiKey": TOPSTEP_KEY},
        timeout=10
    ).json()

    if not login.get("success"):
        raise RuntimeError(f"Login failed: {login}")

    token = login["token"]

    validate = requests.post(
        f"{BASE_URL}/api/Auth/validate",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    ).json()

    if not validate.get("success"):
        raise RuntimeError("Token validation failed")

    cached_token = validate["newToken"]

    accounts = requests.post(
        f"{BASE_URL}/api/Account/search",
        headers={"Authorization": f"Bearer {cached_token}"},
        json={"onlyActiveAccounts": True},
        timeout=10
    ).json().get("accounts", [])

    match = next(
        (a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
        None
    )

    if not match:
        raise RuntimeError("Target account not found")

    cached_account_id = match["id"]
    logging.info(f"Connected to account: {match['name']}")

# ============================================================
# BRACKET MARKET ORDER (NATIVE TOPSTEPX)
# ============================================================
def place_bracket_market_order(
    token: str,
    account_id: str,
    contract_id: str,
    side: str,           # "buy" / "sell"
    quantity: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
    tick_size: float,
) -> Dict[str, Any]:

    # ---------- side ----------
    if side.lower() == "buy":
        side_val = 0   # LONG
    elif side.lower() == "sell":
        side_val = 1   # SHORT
    else:
        raise ValueError(f"Invalid side: {side}")

    if quantity <= 0:
        raise ValueError("quantity must be > 0")

    # ---------- tick offsets ----------
    delta_sl = (stop_price   - entry_price) / tick_size
    delta_tp = (target_price - entry_price) / tick_size

    sl_ticks = int(round(delta_sl))
    tp_ticks = int(round(delta_tp))

    # ---------- validation ----------
    if side_val == 0:
        # LONG
        if sl_ticks >= 0 or tp_ticks <= 0:
            raise ValueError(f"[LONG] invalid ticks sl={sl_ticks}, tp={tp_ticks}")
    else:
        # SHORT
        if sl_ticks <= 0 or tp_ticks >= 0:
            raise ValueError(f"[SHORT] invalid ticks sl={sl_ticks}, tp={tp_ticks}")

    logging.info(
        "Bracket ticks OK | side=%s sl=%d tp=%d",
        "LONG" if side_val == 0 else "SHORT",
        sl_ticks,
        tp_ticks
    )

    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,        # MARKET
        "side": side_val,
        "size": quantity,
        "stopLossBracket": {
            "ticks": sl_ticks
        },
        "takeProfitBracket": {
            "ticks": tp_ticks
        },
        "customTag": "TV_BRACKET"
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    resp = requests.post(
        f"{BASE_URL}/api/Order/place",
        headers=headers,
        json=payload,
        timeout=10
    )

    result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"Bracket order failed: {result}")

    return result

# ============================================================
# WEBHOOK
# ============================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    if not cached_token or not cached_account_id:
        connect_topstep()

    data = request.get_json(force=True)
    logging.info(f"Webhook received: {data}")

    symbol = data.get("symbol", "").upper()
    side = data.get("side", "").lower()
    quantity = int(data.get("quantity", 0))
    entry_price = float(data.get("entry_price", 0))

    if symbol not in SYMBOL_CONFIG:
        return jsonify({"error": f"Unsupported symbol {symbol}"}), 400

    cfg = SYMBOL_CONFIG[symbol]

    tick_size = cfg["tickSize"]
    stop_ticks = cfg["stopTicks"]
    tp_ticks   = cfg["tpTicks"]

    if side == "buy":
        stop_price = entry_price - stop_ticks * tick_size
        target_price = entry_price + tp_ticks * tick_size
    elif side == "sell":
        stop_price = entry_price + stop_ticks * tick_size
        target_price = entry_price - tp_ticks * tick_size
    else:
        return jsonify({"error": "Invalid side"}), 400

    result = place_bracket_market_order(
        token=cached_token,
        account_id=cached_account_id,
        contract_id=cfg["contractId"],
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        tick_size=tick_size,
    )

    return jsonify({
        "status": "BRACKET_MARKET_SENT",
        "symbol": symbol,
        "side": side,
        "qty": quantity,
        "entry": entry_price,
        "stop": stop_price,
        "target": target_price,
        "order": result
    })

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
