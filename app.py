from flask import Flask
import requests
import os

app = Flask(__name__)

# === مقدارهای احراز هویت
USERNAME = "aminnameni"  # ← ایمیل TopStepX شما
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="  # ← ProjectX API key

# === آدرس‌ها
LOGIN_URL = "https://api.topstepx.com/api/Auth/loginKey"
VALIDATE_URL = "https://api.topstepx.com/api/Auth/validate"
ACCOUNT_URL = "https://api.topstepx.com/api/Account/search"

@app.route("/")
def check_token_and_account():
    try:
        # === مرحله 1: ورود و گرفتن توکن
        login_resp = requests.post(LOGIN_URL, json={
            "userName": USERNAME,
            "apiKey": API_KEY
        })
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if not login_data.get("success"):
            return "❌ ورود ناموفق! ایمیل یا API Key اشتباه است"

        token = login_data.get("token")

        # === مرحله 2: بررسی اعتبار توکن
        validate_resp = requests.post(VALIDATE_URL, json={
            "token": token
        })
        validate_data = validate_resp.json()
        print("🟢 پاسخ اعتبارسنجی:", validate_data)

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است!"

        # === مرحله 3: دریافت accountId
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        account_resp = requests.post(ACCOUNT_URL, json={}, headers=headers)
        account_data = account_resp.json()
        print("🟢 حساب‌های فعال:", account_data)

        if not account_data or len(account_data) == 0:
            return "⚠️ هیچ حساب فعالی پیدا نشد."

        # گرفتن اولین accountId
        account_id = account_data[0].get("accountId")
        account_number = account_data[0].get("accountNumber")

        return f"✅ توکن معتبر است!\n🧾 Account ID: {account_id}\n📘 Account #: {account_number}"

    except Exception as e:
        print("❗️ خطا:", str(e))
        return "⚠️ خطای سرور"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
