from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# اطلاعات ورود ثابت
USERNAME = "aminnameni"
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="
ACCOUNT_ID = 8167809  # حساب قابل معامله

# آدرس‌های API
LOGIN_URL = "https://api.topstepx.com/api/Auth/loginKey"
VALIDATE_URL = "https://api.topstepx.com/api/Auth/validate"
ORDER_URL = "https://api.topstepx.com/api/Order/place"

# متغیر توکن
session_token = None

# === توابع ===

def login_and_validate():
    global session_token

    login_payload = {"userName": USERNAME, "apiKey": API_KEY}
    try:
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if login_data["success"]:
            token = login_data["token"]
            # اعتبارسنجی
            validate_headers = {"Authorization": f"Bearer {token}"}
            validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
            validate_data = validate_resp.json()
            print("🟢 اعتبارسنجی:", validate_data)

            if validate_data["success"]:
                session_token = validate_data["newToken"]
                return True
        return False
    except Exception as e:
        print("❗️ خطا در ورود:", e)
        return False

@app.route("/", methods=["GET"])
def home():
    return "✅ سرور Flask برای TopstepX آماده است."

@app.route("/webhook", methods=["POST"])
def webhook():
    global session_token

    if session_token is None:
        print("🔁 تلاش برای دریافت توکن...")
        if not login_and_validate():
            return "❌ ورود یا اعتبارسنجی شکست خورد.", 401

    data = request.json
    print("📥 Webhook Received:", data)

    try:
        contract_id = data["symbol"]  # مثال: CON.F.US.MNQ.M25
        side = 1 if data["side"].lower() == "buy" else 2
        qty = int(data["qty"])

        order_payload = {
            "accountId": ACCOUNT_ID,
            "contractId": contract_id,
            "type": 2,          # Market Order
            "side": side,
            "size": qty,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": "WebhookOrder",
            "linkedOrderId": None
        }

        order_headers = {
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json"
        }

        order_resp = requests.post(ORDER_URL, headers=order_headers, json=order_payload)
        order_data = order_resp.json()
        print("📤 پاسخ سفارش:", order_data)

        if order_data.get("success"):
            return jsonify({"status": "✅ سفارش ارسال شد", "orderId": order_data.get("orderId")}), 200
        else:
            return jsonify({"status": "❌ سفارش ناموفق", "error": order_data.get("errorMessage")}), 400

    except Exception as e:
        print("❗️ خطا در ارسال سفارش:", e)
        return "❌ خطای داخلی سرور", 500

# اجرای محلی فقط برای تست
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=10000)
