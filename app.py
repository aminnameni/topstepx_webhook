from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging

# ================== APP ==================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ================== ENV ==================
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")
BASE_URL = "https://api.topstepx.com"

cached_token = None
cached_account_id = None

# ================== SYMBOL MAP ==================
SYMBOL_MAP = {
    "MGC": "CON.F.US.MGC.G26",
    "MNQ": "CON.F.US.MNQ.H26",
}

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

    logging.info("Connecting to TopstepX...")

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY}
    ).json()

    if not login.get("success"):
        raise Exception(f"Login failed: {login}")

    token = login["token"]

    validate = requests.post(
        f"{BASE_URL}/api/Auth/validate",
        headers={"Authorization": f"Bearer {token}"}
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
    logging.info(f"Connected to account: {match['name']}")

# ================== ROUTES ==================
@app.route("/", methods=["GET"])
def health():
    try:
        connect_topstep()
        return jsonify({"status": "connected", "accountId": cached_account_id})
    except Exception as e:
        logging.error(str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    try:
        # ---------- Ensure connection ----------
        if not cached_token or not cached_account_id:
            connect_topstep()

        data = request.get_json(force=True)
        logging.info(f"Webhook received: {data}")

        raw_symbol = str(data.get("symbol", ""))
        action_raw = str(data.get("data", "")).lower()
        qty = int(float(data.get("quantity", 0)))

        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            return jsonify({"error": f"Unsupported symbol: {raw_symbol}"}), 400

        contract_id = SYMBOL_MAP[symbol]

        action_map = {
            "buy": "buy",
            "sell": "sell",
            "close": "close",
            "exit": "close"
        }

        action = action_map.get(action_raw)
        if not action:
            return jsonify({"error": f"Invalid action: {action_raw}"}), 400

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
                return jsonify({"status": "already_flat"}), 200

            last = active[-1]
            qty = int(last["size"])
            side_code = 1 if last["side"] == 0 else 0

        # ---------- ENTRY ----------
        else:
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400

            side_code = 0 if action == "buy" else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,  # Market
            "side": side_code,
            "size": qty,
            "customTag": action
        }

        logging.info(f"Placing order payload: {payload}")

        r = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers={"Authorization": f"Bearer {cached_token}"},
            json=payload
        )

        logging.info(f"TopstepX response: {r.status_code} {r.text}")

        result = r.json()
        if result.get("success"):
            return jsonify({"status": "success", "orderId": result.get("orderId")})
        else:
            return jsonify({"status": "error", "details": result}), 400

    except Exception as e:
        logging.exception("Webhook error")
        return jsonify({"error": str(e)}), 500


# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
