from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)

# === لاگ‌گیری حرفه‌ای ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === اطلاعات اتصال ===
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")
BASE_URL = "https://api.topstepx.com"

cached_token = None
cached_account_id = None

# === نگاشت نمادها ===
symbol_map = {
    "MNQ": "CON.F.US.MNQ.M25",
    "MGC": "CON.F.US.MGC.Q25",
    "GC": "CON.F.US.GCE.Q25",
    "CL": "CON.F.US.CL.N25",
    "MCL": "CON.F.US.MCLE.N25",
    "NG": "CON.F.US.NGE.N25",
    "MNG": "CON.F.US.MNG.N25",
    "YM": "CON.F.US.YM.M25",
    "MYM": "CON.F.US.MYM.M25",
    "HG": "CON.F.US.CPE.N25",
    "MHG": "CON.F.US.MHG.N25"
}

# === اتصال اولیه و دریافت حساب ===
@app.route("/", methods=["GET"])
def initialize():
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

        accounts_resp = requests.post(
            f"{BASE_URL}/api/Account/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        ).json()

        accounts = accounts_resp.get("accounts", [])
        logger.info(f"Available accounts: {accounts}")

        match = next(
            (a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
            None
        )
        if not match:
            return jsonify({"error": "Account not found"}), 404

        cached_account_id = match["id"]
        logger.info(f"Connected to account: {match['name']} (ID: {cached_account_id})")
        return jsonify({"status": "connected", "accountId": cached_account_id})
    except Exception as e:
        logger.exception("Initialization failed")
        return jsonify({"error": str(e)}), 500

# === اجرای سیگنال ترید ===
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    if not cached_token or not cached_account_id:
        return jsonify({"error": "Connection not initialized. Call GET / first."}), 403

    try:
        data = request.get_json()
        logger.info(f"Received webhook data: {data}")

        symbol = data.get("symbol", "").upper()
        side = data.get("side", "").lower()

        contract_id = symbol_map.get(symbol)
        if not contract_id or side not in ["buy", "sell", "long", "short", "close_long", "close_short"]:
            return jsonify({"error": "Invalid symbol or side"}), 400

        # === خروج از پوزیشن ===
        if side in ["close_long", "close_short"]:
            pos_resp = requests.post(
                f"{BASE_URL}/api/Position/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={"accountId": cached_account_id}
            )

            if pos_resp.status_code != 200:
                logger.error(f"Failed to fetch positions: {pos_resp.status_code}, {pos_resp.text}")
                return jsonify({
                    "error": "Failed to fetch positions",
                    "status_code": pos_resp.status_code,
                    "response": pos_resp.text
                }), 500

            try:
                positions_data = pos_resp.json()
            except Exception:
                logger.exception("Failed to parse JSON from positions response")
                return jsonify({"error": "Invalid JSON response", "raw": pos_resp.text}), 500

            positions = positions_data.get("positions", [])
            logger.info(f"Fetched positions: {positions}")
            logger.info(f"Looking for contractId containing: {contract_id}")

            # تطبیق منعطف contractId
            position = next((p for p in positions if contract_id in p.get("contractId", "")), None)

            if not position:
                return jsonify({
                    "status": "no_position_to_close",
                    "message": f"No open position found for symbol {symbol} (contractId fragment: {contract_id})",
                    "available_contracts": [p.get("contractId") for p in positions]
                }), 200

            qty = int(position.get("netSize", 0))
            if qty == 0:
                return jsonify({
                    "status": "already_flat",
                    "message": f"Position for {contract_id} already closed"
                }), 200

            logger.info(f"Matched position: {position}")
            side_code = 1 if side == "close_long" else 0

        # === ورود به پوزیشن ===
        else:
            qty = int(data.get("qty", 0))
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if side in ["buy", "long"] else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,  # Market order
            "side": side_code,
            "size": qty,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": side,
            "linkedOrderId": None
        }

        logger.info(f"Placing order with payload: {payload}")
        resp = requests.post(
            f"{BASE_URL}/api/Order/place",
            json=payload,
            headers={"Authorization": f"Bearer {cached_token}"}
        )
        out = resp.json()
        logger.info(f"Order response: {out}")

        if out.get("success"):
            return jsonify({"status": "success", "orderId": out.get("orderId")})
        else:
            return jsonify({
                "status": "error",
                "errorCode": out.get("errorCode"),
                "message": out.get("errorMessage", "Unknown server error")
            }), 400

    except Exception as e:
        logger.exception("Webhook processing failed")
        return jsonify({"error": str(e)}), 500

# === اجرای سرور ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
