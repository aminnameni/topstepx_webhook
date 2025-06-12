from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

BASE_URL = "https://api.topstepx.com"
cached_token = None
cached_account_id = None

symbol_map = {
    "MGC": "CON.F.US.MGC.Q25",
    "MNQ": "CON.F.US.MNQ.M25",
    "CL": "CON.F.US.CL.N25",
    # Add others as needed
}

@app.route("/", methods=["GET"])
def connect():
    global cached_token, cached_account_id
    try:
        login = requests.post(f"{BASE_URL}/api/Auth/loginKey", json={"userName": USERNAME, "apiKey": API_KEY}).json()
        if not login.get("success"):
            return jsonify({"error": login.get("errorMessage")}), 401

        token = login["token"]
        validate = requests.post(f"{BASE_URL}/api/Auth/validate", headers={"Authorization": f"Bearer {token}"}).json()
        if not validate.get("success"):
            return jsonify({"error": "Token validation failed"}), 401

        cached_token = validate["newToken"]

        accounts = requests.post(f"{BASE_URL}/api/Account/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}).json().get("accounts", [])

        match = next((a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)
        if not match:
            return jsonify({"error": "Account not found"}), 404

        cached_account_id = match["id"]
        logging.info(f"Connected to account: {match['name']} (ID: {cached_account_id})")
        return jsonify({"status": "connected", "accountId": cached_account_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    if not cached_token or not cached_account_id:
        return jsonify({"error": "Not connected. Call GET / first."}), 403

    try:
        data = request.get_json()
        logging.info(f"Received: {data}")

        symbol = data.get("symbol", "").upper()
        side = data.get("side", "").lower()
        qty = int(data.get("qty", 0))

        contract_id = symbol_map.get(symbol)
        if not contract_id or side not in ["buy", "sell", "close_long", "close_short"]:
            return jsonify({"error": "Invalid symbol or side"}), 400

        if side in ["close_long", "close_short"]:
            now = datetime.datetime.utcnow()
            start_ts = (now - datetime.timedelta(hours=12)).isoformat() + "Z"
            end_ts = now.isoformat() + "Z"

            resp = requests.post(f"{BASE_URL}/api/Order/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={"accountId": cached_account_id, "startTimestamp": start_ts, "endTimestamp": end_ts})

            if resp.status_code != 200:
                return jsonify({"error": "Failed to fetch orders", "response": resp.text, "status_code": resp.status_code}), 500

            orders = resp.json().get("orders", [])
            for i, o in enumerate(orders):
                logging.info(f"[Order {i+1}] contractId={o['contractId']}, status={o['status']}, side={o['side']}, qty={o['size']}, raw={o}")

            matched = [o for o in orders if o.get("contractId") == contract_id and o.get("status") in [1, 2]]
            if not matched:
                return jsonify({"message": f"No active orders found for {contract_id}", "status": "no_position_to_close"}), 200

            last_order = matched[-1]
            qty = int(last_order.get("size", 0))
            if qty == 0:
                return jsonify({"message": "Position already flat", "status": "already_flat"}), 200

            side_code = 1 if side == "close_long" else 0
        else:
            if qty <= 0:
                return jsonify({"error": "Invalid qty"}), 400
            side_code = 0 if side == "buy" else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,
            "side": side_code,
            "size": qty,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": side,
            "linkedOrderId": None
        }

        logging.info(f"Placing order: {payload}")
        order_resp = requests.post(f"{BASE_URL}/api/Order/place", json=payload, headers={"Authorization": f"Bearer {cached_token}"})
        out = order_resp.json()
        logging.info(f"Exit order response: {out}")

        if out.get("success"):
            return jsonify({"status": "success", "orderId": out.get("orderId")})
        else:
            return jsonify({"status": "error", "details": out}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
