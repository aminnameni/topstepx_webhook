from flask import Flask, request
import requests

app = Flask(__name__)

# اطلاعات ورود
USERNAME = "aminnameni"
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="

# آدرس‌های API
BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"
ORDER_URL = f"{BASE_URL}/api/Order/place"

# ذخیره توکن و accountId برای استفاده در سفارش‌ها
cached_token = None
cached_account_id = None
TARGET_ACCOUNT_NAME = "S1MAY2814229370"

@app.route("/", methods=["GET"])
def check_token_and_account():
    global cached_token, cached_account_id
    try:
        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if not login_data.get("success"):
            return f"❌ ورود ناموفق: {login_data.get('errorMessage')}"

        token = login_data["token"]
        validate_headers = {"Authorization": f"Bearer {token}"}
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()
        print("🟢 اعتبارسنجی:", validate_data)

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است."

        new_token = validate_data["newToken"]
        cached_token = new_token

        account_headers = {"Authorization": f"Bearer {new_token}"}
        account_resp = requests.post(ACCOUNT_URL, headers=account_headers)
        acc_data = account_resp.json()
        print("🧾 لیست حساب‌ها:", acc_data)

        accounts = acc_data.get("accounts", [])
        print("🔍 نام حساب‌ها:", [acc.get("name") for acc in accounts])
        for acc in accounts:
            print(f"🔎 بررسی: '{acc.get('name')}' ← ID: {acc.get('id')} / canTrade: {acc.get('canTrade')}")

        target_account = next((acc for acc in accounts if acc.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.lower()), None)

        if not target_account:
            return "⚠️ حساب مورد نظر یافت نشد."

        cached_account_id = target_account["id"]
        account_name = target_account["name"]

        return f"""
✅ توکن معتبر است!
🧾 Account ID: {cached_account_id}
📘 Account Name: {account_name}
"""

    except Exception as e:
        return f"⚠️ خطای سرور:\n{e}"

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    try:
        data = request.get_json()
        print("📥 Webhook Received:", data)

        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            return "❌ داده‌های ناقص دریافت شد.", 400

        if not cached_token or not cached_account_id:
            return "❌ توکن یا حساب تنظیم نشده. لطفاً مسیر اصلی را صدا بزنید.", 403

        contract_map = {
            "MNQ": "CON.F.US.NQ3.M25",
            "MGC": "CON.F.US.GC.M25"
        }
        contract_id = contract_map.get(symbol.upper())
        if not contract_id:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        order_payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,
            "side": 1 if side.lower() == "buy" else 2,
            "size": qty,
            "limitPrice": None,
            "stopPrice": None,
            "trailPrice": None,
            "customTag": None,
            "linkedOrderId": None
        }
        headers = {"Authorization": f"Bearer {cached_token}"}
        order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)
        order_data = order_resp.json()

        print("📤 پاسخ سفارش:", order_data)
        if order_data.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {order_data.get('orderId')}"
        else:
            return f"❌ خطا در سفارش: {order_data.get('errorMessage')}"

    except Exception as e:
        return f"⚠️ خطای پردازش سفارش:\n{e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
