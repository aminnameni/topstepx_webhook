from flask import Flask, request
import requests
import os

app = Flask(__name__)

# اطلاعات محیطی
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

# آدرس‌های API
BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"
ORDER_URL = f"{BASE_URL}/api/Order/place"

# کش توکن و شناسه حساب
cached_token = None
cached_account_id = None

# ========================
# 📍 مسیر بررسی اتصال
# ========================
@app.route("/", methods=["GET"])
def health_check():
    global cached_token, cached_account_id
    try:
        # ورود
        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()
        if not login_data.get("success"):
            return f"❌ ورود ناموفق: {login_data.get('errorMessage')}"
        token = login_data["token"]

        # اعتبارسنجی
        validate_headers = {"Authorization": f"Bearer {token}"}
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()
        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است."
        cached_token = validate_data["newToken"]

        # دریافت حساب‌ها
        account_headers = {"Authorization": f"Bearer {cached_token}"}
        account_payload = {"onlyActiveAccounts": True}
        account_resp = requests.post(ACCOUNT_URL, headers=account_headers, json=account_payload)
        acc_data = account_resp.json()
        accounts = acc_data.get("accounts", [])

        # پیدا کردن حساب هدف (با strip و lower)
        target = next(
            (a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
            None
        )
        if not target:
            return f"⚠️ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد."
        cached_account_id = target["id"]

        # گزارش
        output_lines = [f"➡️ name: '{a['name']}', id: {a['id']}, canTrade: {a['canTrade']}" for a in accounts]
        return f"""
✅ اتصال موفق انجام شد
🟢 تعداد حساب‌ها: {len(accounts)}
🔎 TARGET_ACCOUNT: {TARGET_ACCOUNT_NAME}
🔐 USERNAME: {USERNAME}

📥 پاسخ خام:
{acc_data}

📋 حساب‌ها:
{chr(10).join(output_lines)}
"""

    except Exception as e:
        import traceback
        return f"❌ خطای اجرای توابع:\n{e}\n\n📄 Traceback:\n{traceback.format_exc()}"

# ========================
# 📍 مسیر webhook برای ارسال سفارش
# ========================
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            return "❌ داده ناقص است", 400

        # نگاشت symbol به contractId
        contract_map = {
            "MNQ": "CON.F.US.NQ3.M25",
            "MGC": "CON.F.US.GC.M25",
            "MBT": "CON.F.CME.BTC.M25"
        }
        contract_id = contract_map.get(symbol.upper())
        if not contract_id:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        def refresh_token_and_account():
            global cached_token, cached_account_id
            login_payload = {"userName": USERNAME, "apiKey": API_KEY}
            token = requests.post(LOGIN_URL, json=login_payload).json().get("token")

            validate_headers = {"Authorization": f"Bearer {token}"}
            cached_token = requests.post(VALIDATE_URL, headers=validate_headers).json().get("newToken")

            account_headers = {"Authorization": f"Bearer {cached_token}"}
            account_payload = {"onlyActiveAccounts": True}
            accounts = requests.post(ACCOUNT_URL, headers=account_headers, json=account_payload).json().get("accounts", [])

            target = next(
                (a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
                None
            )
            if not target:
                raise Exception(f"⚠️ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد.")
            cached_account_id = target["id"]

        def place_order():
            headers = {"Authorization": f"Bearer {cached_token}"}
            payload = {
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
            return requests.post(ORDER_URL, json=payload, headers=headers).json()

        # تلاش اول
        result = place_order()

        # اگر ناموفق بود، یک بار دیگر با توکن تازه
        if not result.get("success"):
            refresh_token_and_account()
            result = place_order()

        if result.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {result.get('orderId')}"
        else:
            return f"❌ خطا در سفارش: {result.get('errorMessage')}", 500

    except Exception as e:
        import traceback
        return f"⚠️ خطای غیرمنتظره:\n{e}\n\n📄 Traceback:\n{traceback.format_exc()}", 500

# ========================
# اجرای سرور
# ========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
