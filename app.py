from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging

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
symbol_map = {
    "MNQ": "CON.F.US.MNQ.H26",
    "MGC": "CON.F.US.MGC.G26",
}

# ================== CONNECT ==================
@app.route("/", methods=["GET"])
def connect():
    global cached_token, cached_account_id
    try:
        login = requests.post(
            f"{BASE_URL}/api/Auth/loginKey",
            json={"userName": USERNAME, "apiKey": API_KEY}
        ).json()

        if not login.get("success"):
            return jsonify({"error": login.get("errorMessage")}), 401

        token = login["token"]

        validate = requests.post(
            f"{BASE_URL}/api/Auth/validate",
            headers={"Authorization": f"Bearer {token}"}
        ).json()

        if not validate.get("success"):
            return jsonify({"error": "Token validation failed"}), 401

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
            return jsonify({"error": "Account not found"}), 404

        cached_account_id = match["id"]
        logging.info(f"Connected to account: {match['name']}")

        return jsonify({"status": "connected", "accountId": cached_account_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    if not cached_token or not cached_account_id:
        return jsonify({"error": "Not connected. Call GET / first."}), 403

    try:
        data = request.get_json(force=True)
        logging.info(f"Webhook received: {data}")

        symbol = str(data.get("symbol", "")).upper()
        action_raw = str(data.get("data", "")).lower()
        qty = int(float(data.get("quantity", 0)))

        contract_id = symbol_map.get(symbol)
        if not contract_id:
            return jsonify({"error": f"Unknown symbol: {symbol}"}), 400

        action_map = {
            "buy": "buy",
            "sell": "sell",
            "close": "close",
            "exit": "close"
        }

        side = action_map.get(action_raw)
        if not side:
            return jsonify({"error": f"Invalid action: {action_raw}"}), 400

        # -------- CLOSE LOGIC --------
        if side == "close":
            now = datetime.datetime.utcnow()
            start_ts = (now - datetime.timedelta(hours=12)).isoformat() + "Z"
            end_ts = now.isoformat() + "Z"

            resp = requests.post(
                f"{BASE_URL}/api/Order/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={
                    "accountId": cached_account_id,
                    "startTimestamp": start_ts,
                    "endTimestamp": end_ts
                }
            )

            orders = resp.json().get("orders", [])
            active = [o for o in orders if o["contractId"] == contract_id and o["status"] in [1, 2]]

            if not active:
                return jsonify({"status": "already_flat"}), 200

            last = active[-1]
            qty = int(last.get("size", 0))
            side_code = 1 if last["side"] == 0 else 0

        # -------- ENTRY LOGIC --------
        else:
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if side == "buy" else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,  # Market Order
            "side": side_code,
            "size": qty,
            "customTag": side
        }

        logging.info(f"Placing order: {payload}")

        result = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers={"Authorization": f"Bearer {cached_token}"},
            json=payload
        ).json()

        if result.get("success"):
            return jsonify({"status": "success", "orderId": result.get("orderId")})
        else:
            return jsonify({"status": "error", "details": result}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
