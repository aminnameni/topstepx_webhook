from flask import Flask, request
import requests
import os

app = Flask(__name__)

# اطلاعات از محیط
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

# مسیر بررسی و چاپ لیست حساب‌ها
@app.route("/", methods=["GET"])
def health_check():
    global cached_token, cached_account_id

    try:
        # مرحله ورود
        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()

        if not login_data.get("success"):
            return f"❌ ورود ناموفق: {login_data.get('errorMessage')}"

        token = login_data["token"]

        # مرحله اعتبارسنجی
        validate_headers = {"Authorization": f"Bearer {token}"}
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است."

        cached_token = validate_data["newToken"]

        # مرحله گرفتن لیست حساب‌ها
        account_headers = {"Authorization": f"Bearer {cached_token}"}
        account_payload = {"onlyActiveAccounts": True}
        account_resp = requests.post(ACCOUNT_URL, headers=account_headers, json=account_payload)
        acc_data = account_resp.json()

        accounts = acc_data.get("accounts", [])
        output_lines = [f"➡️ name: '{acc.get('name')}', id: {acc.get('id')}, canTrade: {acc.get('canTrade')}" for acc in accounts]

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
        tb = traceback.format_exc()
        return f"""
❌ خطای اجرای توابع:
{e}

📄 Traceback:
{tb}
"""

# اگر نیاز به webhook هم داری بگو تا اضافه کنم


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
