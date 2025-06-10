from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# === اطلاعات اتصال از متغیرهای محیطی ===
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")
BASE_URL = "https://api.topstepx.com"

# === کش توکن و آیدی حساب ===
cached_token = None
cached_account_id = None

# === نگاشت نمادها به شناسه‌های قرارداد ===
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

# === تست اتصال و راه‌اندازی اولیه ===
@app.route("/", methods=["GET"])
def initialize():
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

        acc_resp = requests.post(
            f"{BASE_URL}/api/Account/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        ).json()

        account = next((a for a in acc_resp.get("accounts", []) if a["name"].lower() == TARGET_ACCOUNT_NAME.lower()), None)
        if not account:
            return jsonify({"error": "Account not found"}), 404

        cached_account_id = account["id"]
        return jsonify({"status": "connected", "accountId": cached_account_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === دریافت سیگنال ترید از Pine Script ===
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    if not cached_token or not cached_account_id:
        return jsonify({"error": "Connection not initialized. Call GET / first."}), 403

    try:
        data = request.get_json()
        print("Received webhook data:", data)

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
                return jsonify({"error": "Failed to fetch positions", "detail": pos_resp.text}), 500

            positions = pos_resp.json().get("positions", [])
            print("Fetched positions:", positions)
            print("Looking for contractId:", contract_id)

            position = next((p for p in positions if p.get("contractId") == contract_id), None)
            if not position:
                return jsonify({
                    "status": "no_position_to_close",
                    "message": f"No open position found for {contract_id}"
                }), 200

            qty = int(position.get("netSize", 0))
            if qty == 0:
                return jsonify({
                    "status": "already_flat",
                    "message": f"Position for {contract_id} already closed"
                }), 200

            side_code = 1 if side == "close_long" else 0

        # === ورود به پوزیشن ===
        else:
            qty = int(data.get("qty", 0))
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if side in ["buy", "long"] else 1

        # === ساخت سفارش مارکت ===
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

        resp = requests.post(f"{BASE_URL}/api/Order/place", json=payload, headers={"Authorization": f"Bearer {cached_token}"})
        out = resp.json()

        if out.get("success"):
            return jsonify({"status": "success", "orderId": out.get("orderId")})
        else:
            return jsonify({
                "status": "error",
                "errorCode": out.get("errorCode"),
                "message": out.get("errorMessage", "Unknown server error")
            }), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === اجرای سرور فلاسک ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
