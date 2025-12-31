from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging
import uuid

# ================== APP ==================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ================== ENV ==================
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

BASE_URL = "https://api.topstepx.com"

cached_token = None
cached_account_id = None

# ================== SYMBOL MAP ==================
SYMBOL_MAP = {
    "MGC": "CON.F.US.MGC.G26",
    "MNQ": "CON.F.US.MNQ.H26",
}

# ================== TELEGRAM ==================
def send_telegram(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": message
        }, timeout=5)
    except Exception as e:
        logging.error(f"Telegram error: {e}")

# ================== UTILS ==================
def normalize_symbol(raw_symbol: str) -> str:
    raw_symbol = raw_symbol.upper()
    if raw_symbol.startswith("MGC"):
        return "MGC"
    if raw_symbol.startswith("MNQ"):
        return "MNQ"
    return ""

def connect_topstep():
    global cached_token, cached_account_id

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY}
    ).json()

    if not login.get("success"):
        raise Exception(f"Login failed: {login}")

    validate = requests.post(
        f"{BASE_URL}/api/Auth/validate",
        headers={"Authorization": f"Bearer {login['token']}"}
    ).json()

    if not validate.get("success"):
        raise Exception("Token validation failed")

    cached_token = validate["newToken"]

    accounts = requests.post(
        f"{BASE_URL}/api/Account/search",
        headers={"Authorization": f"Bearer {cached_token}"},
        json={"onlyActiveAccounts": True}
    ).json().get("accounts", [])

    match = next(
        (a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
        None
    )

    if not match:
        raise Exception("Target account not found")

    cached_account_id = match["id"]

# ================== ROUTES ==================
@app.route("/", methods=["GET"])
def health():
    try:
        connect_topstep()
        return jsonify({"status": "connected", "accountId": cached_account_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    try:
        if not cached_token or not cached_account_id:
            connect_topstep()

        data = request.get_json(force=True)
        logging.info(f"Webhook received: {data}")

        raw_symbol = str(data.get("symbol", ""))
        action_raw = str(data.get("data", "")).lower()
        qty = int(float(data.get("quantity", 0)))

        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            return jsonify({"error": "Unsupported symbol"}), 400

        contract_id = SYMBOL_MAP[symbol]

        action_map = {
            "buy": "buy",
            "sell": "sell",
            "close": "close",
            "exit": "close"
        }

        action = action_map.get(action_raw)
        if not action:
            return jsonify({"error": "Invalid action"}), 400

        # ===== TELEGRAM: SIGNAL RECEIVED =====
        send_telegram(
            f"📩 SIGNAL RECEIVED\n"
            f"Symbol: {symbol}\n"
            f"Action: {action.upper()}\n"
            f"Qty: {qty}"
        )

        # ---------- CLOSE ----------
        if action == "close":
            now = datetime.datetime.utcnow()
            start = (now - datetime.timedelta(hours=12)).isoformat() + "Z"
            end = now.isoformat() + "Z"

            resp = requests.post(
                f"{BASE_URL}/api/Order/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={
                    "accountId": cached_account_id,
                    "startTimestamp": start,
                    "endTimestamp": end
                }
            ).json()

            orders = resp.get("orders", [])
            active = [o for o in orders if o["contractId"] == contract_id and o["status"] in [1, 2]]

            if not active:
                send_telegram("ℹ️ Already flat")
                return jsonify({"status": "already_flat"}), 200

            last = active[-1]
            qty = int(last["size"])
            side_code = 1 if last["side"] == 0 else 0

        # ---------- ENTRY ----------
        else:
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if action == "buy" else 1

        # ===== UNIQUE customTag =====
        custom_tag = (
            f"{action}_"
            f"{int(datetime.datetime.utcnow().timestamp() * 1000)}_"
            f"{uuid.uuid4().hex[:6]}"
        )

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,
            "side": side_code,
            "size": qty,
            "customTag": custom_tag
        }

        send_telegram(
            f"🚀 ORDER SENDING\n"
            f"{symbol} {action.upper()} x{qty}\n"
            f"Tag: {custom_tag}"
        )

        r = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers={"Authorization": f"Bearer {cached_token}"},
            json=payload
        )

        result = r.json()

        if result.get("success"):
            send_telegram(
                f"✅ ORDER SUCCESS\n"
                f"{symbol} {action.upper()} x{qty}\n"
                f"OrderID: {result.get('orderId')}"
            )
            return jsonify({"status": "success", "orderId": result.get("orderId")})

        else:
            send_telegram(
                f"❌ ORDER FAILED\n"
                f"{symbol} {action.upper()} x{qty}\n"
                f"Error: {result}"
            )
            return jsonify({"status": "error", "details": result}), 400

    except Exception as e:
        logging.exception("Webhook error")
        send_telegram(f"🔥 SYSTEM ERROR\n{str(e)}")
        return jsonify({"error": str(e)}), 500


# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
