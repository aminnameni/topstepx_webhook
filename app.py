from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

BASE_URL = "https://api.topstepx.com"
cached_token = None
cached_account_id = None

symbol_map = {
    "MNQ": "CON.F.US.MNQ.M5",
    "MGC": "CON.F.US.MGC.Q5",
    "GC": "CON.F.US.GCE.Q5",
    "CL": "CON.F.US.CLE.N5",
    "MCL": "CON.F.US.MCLE.N5",
    "NG": "CON.F.US.NGE.N5",
    "MNG": "CON.F.US.MNG.N5",
    "YM": "CON.F.US.YM.M5",
    "MYM": "CON.F.US.MYM.M5",
    "HG": "CON.F.US.CPE.N25",
    "MHG": "CON.F.US.MHG.N25"
}

@app.route("/", methods=["GET"])
def initialize():
    global cached_token, cached_account_id
    try:
        # مرحله لاگین
        login = requests.post(f"{BASE_URL}/api/Auth/loginKey", json={"userName": USERNAME, "apiKey": API_KEY}).json()
        if not login.get("success"): return jsonify({"error": login.get("errorMessage")}), 401
        token = login["token"]

        # اعتبارسنجی
        validate = requests.post(f"{BASE_URL}/api/Auth/validate", headers={"Authorization": f"Bearer {token}"}).json()
        if not validate.get("success"): return jsonify({"error": "Invalid token"}), 401
        cached_token = validate["newToken"]

        # دریافت حساب
        accounts = requests.post(f"{BASE_URL}/api/Account/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        ).json().get("accounts", [])
        match = next((a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)
        if not match: return jsonify({"error": "Account not found"}), 404

        cached_account_id = match["id"]
        return jsonify({"status": "success", "accountId": cached_account_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    if not cached_token or not cached_account_id:
        return jsonify({"error": "Connection not initialized. Call GET / first."}), 403

    try:
        data = request.get_json()
        symbol = data.get("symbol", "").upper()
        side = data.get("side", "").lower()
        qty = int(data.get("qty", 0))

        contract_id = symbol_map.get(symbol)
        if not contract_id or side not in ["buy", "sell", "long", "short", "close_long", "close_short"]:
            return jsonify({"error": "Invalid symbol or side"}), 400

        side_code = 0 if side in ["buy", "long", "close_short"] else 1

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

        resp = requests.post(f"{BASE_URL}/api/Order/place", json=payload, headers={"Authorization": f"Bearer {cached_token}"})
        out = resp.json()

        if out.get("success"):
            return jsonify({"status": "success", "orderId": out.get("orderId")})
        else:
            return jsonify({
                "status": "error",
                "errorCode": out.get("errorCode"),
                "message": out.get("errorMessage", "Server returned error")
            }), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
