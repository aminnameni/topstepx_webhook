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
# UTIL: CHECK OPEN POSITION
# ============================================================
def has_open_position(contract_id: str) -> bool:
    """
    بررسی می‌کند آیا برای این کانترکت پوزیشن باز وجود دارد یا نه
    """
    resp = requests.post(
        f"{BASE_URL}/api/Order/search",
        headers={"Authorization": f"Bearer {cached_token}"},
        json={
            "accountId": cached_account_id,
            "onlyOpenOrders": True
        },
        timeout=10
    ).json()

    orders = resp.get("orders", [])
    return any(o.get("contractId") == contract_id for o in orders)

# ============================================================
# MAIN: BRACKET MARKET ORDER
# ============================================================
def place_bracket_market_order(
    token: str,
    account_id: str,
    contract_id: str,
    side: str,           # buy / sell
    quantity: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
    tick_size: float,
) -> Dict[str, Any]:

    side_val = 0 if side == "buy" else 1

    sl_ticks = int(round((stop_price - entry_price) / tick_size))
    tp_ticks = int(round((target_price - entry_price) / tick_size))

    if side_val == 0:
        if sl_ticks >= 0 or tp_ticks <= 0:
            raise ValueError("Invalid LONG bracket ticks")
    else:
        if sl_ticks <= 0 or tp_ticks >= 0:
            raise ValueError("Invalid SHORT bracket ticks")

    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,  # MARKET
        "side": side_val,
        "size": quantity,
        "stopLossBracket": {"ticks": sl_ticks},
        "takeProfitBracket": {"ticks": tp_ticks},
        "customTag": "MAIN_BRACKET"
    }

    resp = requests.post(
        f"{BASE_URL}/api/Order/place",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=10
    )

    result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"MAIN order failed: {result}")

    return result

# ============================================================
# SCALE: MARKET ONLY
# ============================================================
def place_scale_market_order(
    token: str,
    account_id: str,
    contract_id: str,
    side: str,
    quantity: int,
) -> Dict[str, Any]:

    side_val = 0 if side == "buy" else 1

    payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,  # MARKET
        "side": side_val,
        "size": quantity,
        "customTag": "SCALE_IN"
    }

    resp = requests.post(
        f"{BASE_URL}/api/Order/place",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=10
    )

    result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"SCALE order failed: {result}")

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
    action = data.get("action", "").lower()   # main | scale
    side   = data.get("side", "").lower()     # buy | sell
    qty    = int(data.get("quantity", 0))
    entry  = float(data.get("entry_price", 0))

    if symbol not in SYMBOL_CONFIG:
        return jsonify({"error": "Unsupported symbol"}), 400

    cfg = SYMBOL_CONFIG[symbol]

    if action == "main":
        tick = cfg["tickSize"]
        if side == "buy":
            stop_price = entry - cfg["stopTicks"] * tick
            tp_price   = entry + cfg["tpTicks"]   * tick
        else:
            stop_price = entry + cfg["stopTicks"] * tick
            tp_price   = entry - cfg["tpTicks"]   * tick

        result = place_bracket_market_order(
            token=cached_token,
            account_id=cached_account_id,
            contract_id=cfg["contractId"],
            side=side,
            quantity=qty,
            entry_price=entry,
            stop_price=stop_price,
            target_price=tp_price,
            tick_size=tick,
        )

        return jsonify({"status": "MAIN_OK", "order": result})

    elif action == "scale":
        if not has_open_position(cfg["contractId"]):
            return jsonify({"status": "IGNORED", "reason": "No MAIN position"}), 200

        result = place_scale_market_order(
            token=cached_token,
            account_id=cached_account_id,
            contract_id=cfg["contractId"],
            side=side,
            quantity=qty,
        )

        return jsonify({"status": "SCALE_OK", "order": result})

    else:
        return jsonify({"error": "Invalid action"}), 400

# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
