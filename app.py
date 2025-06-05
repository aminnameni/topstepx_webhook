from flask import Flask, request, jsonify
import requests
import os
import traceback

app = Flask(__name__)

# اطلاعات لاگین و اتصال
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"
ORDER_URL = f"{BASE_URL}/api/Order/place"

# کش توکن و حساب
cached_token = None
cached_account_id = None

# نگاشت نمادها به شناسه کانترکت فعال
symbol_map = {
    "MNQ": {"contractId": "CON.F.US.MNQ.M5"},
    "MGC": {"contractId": "CON.F.US.MGC.Q5"},
    "GC": {"contractId": "CON.F.US.GCE.Q5"},
    "CL": {"contractId": "CON.F.US.CLE.N5"},
    "MCL": {"contractId": "CON.F.US.MCLE.N5"},
    "NG": {"contractId": "CON.F.US.NGE.N5"},
    "MNG": {"contractId": "CON.F.US.MNG.N5"},
    "YM": {"contractId": "CON.F.US.YM.M5"},
    "MYM": {"contractId": "CON.F.US.MYM.M5"},
    "HG": {"contractId": "CON.F.US.CPE.N25"},
    "MHG": {"contractId": "CON.F.US.MHG.N25"}
}

@app.route("/", methods=["GET"])
def health_check():
    global cached_token, cached_account_id
    try:
        print("🔐 اجرای مرحله لاگین...")

        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()

        if not login_data.get("success"):
            print("❌ خطا در لاگین:", login_data.get("errorMessage"))
            return jsonify({"status": "error", "message": login_data.get("errorMessage")}), 401

        token = login_data["token"]
        validate_resp = requests.post(VALIDATE_URL, headers={"Authorization": f"Bearer {token}"})
        validate_data = validate_resp.json()

        if not validate_data.get("success"):
            print("❌ توکن نامعتبر")
            return jsonify({"status": "error", "message": "توکن نامعتبر است."}), 401

        cached_token = validate_data["newToken"]
        print("✅ توکن جدید دریافت شد.")

        account_resp = requests.post(
            ACCOUNT_URL,
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        )
        acc_data = account_resp.json()

        accounts = acc_data.get("accounts", [])
        target = next((a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)
        if not target:
            print(f"❌ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد.")
            return jsonify({"status": "error", "message": f"حساب '{TARGET_ACCOUNT_NAME}' یافت نشد."}), 404

        cached_account_id = target["id"]
        print(f"✅ اتصال برقرار شد. accountId: {cached_account_id}")
        return jsonify({"status": "success", "accountId": cached_account_id})

    except Exception as e:
        print("❌ خطای عمومی:", traceback.format_exc())
        return jsonify({"status": "error", "message": str(e), "traceback": traceback.format_exc()}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    print("🚀 اجرای webhook")
    print(f"توکن: {cached_token}")
    print(f"حساب: {cached_account_id}")

    try:
        if not cached_token or not cached_account_id:
            print("⚠️ ابتدا باید اتصال اولیه برقرار شود.")
            return jsonify({"status": "error", "message": "ابتدا اتصال اولیه از طریق GET / برقرار شود."}), 403

        data = request.get_json()
        print(f"📨 پیام دریافتی: {data}")

        symbol = data.get("symbol", "").upper()
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            print("⚠️ پیام ناقص:", data)
            return jsonify({"status": "error", "message": "داده‌های ناقص."}), 400

        try:
            qty = int(qty)
        except:
            return jsonify({"status": "error", "message": f"qty نامعتبر: {qty}"}), 400

        mapped = symbol_map.get(symbol)
        if not mapped:
            return jsonify({"status": "error", "message": f"نماد پشتیبانی نمی‌شود: {symbol}"}), 400

        contract_id = mapped["contractId"]
        side_clean = side.strip().lower()

        if side_clean in ["buy", "long", "close_short"]:
            side_code = 0
        elif side_clean in ["sell", "short", "close_long"]:
            side_code = 1
        else:
            return jsonify({"status": "error", "message": f"مقدار side نامعتبر: {side}"}), 400

        order_payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,
            "side": side_code,
            "size": qty,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": side_clean,
            "linkedOrderId": None
        }

        print("🛠 داده نهایی برای سفارش:")
        for k, v in order_payload.items():
            print(f"{k}: {v}")

        headers = {"Authorization": f"Bearer {cached_token}"}
        order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)

        print(f"🔁 وضعیت پاسخ: {order_resp.status_code}")
        print(f"🔁 متن پاسخ: {order_resp.text}")

        try:
            order_data = order_resp.json()
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": "خطا در تبدیل پاسخ به JSON",
                "detail": str(e),
                "response": order_resp.text
            }), 500

        if order_data.get("success"):
            return jsonify({"status": "success", "orderId": order_data.get("orderId")})
        else:
            return jsonify({
                "status": "error",
                "message": order_data.get("errorMessage", "❌ خطای ناشناخته از سمت سرور"),
                "full_response": order_data
            })

    except Exception as e:
        print("❌ خطای عمومی در webhook:", traceback.format_exc())
        return jsonify({"status": "error", "message": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
