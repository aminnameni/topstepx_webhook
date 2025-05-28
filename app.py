from flask import Flask
import requests
import os

app = Flask(__name__)

# 🔒 اطلاعات کاربری خودت رو اینجا وارد کن:
USERNAME = "aminnameni"       # ← نام کاربری شما در TopStepX (ایمیل یا نام‌کاربری متنی)
API_KEY  = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="    # ← توکن گرفته‌شده از ProjectX

# 🔗 آدرس‌های API
LOGIN_URL    = "https://api.topstepx.com/api/Auth/loginKey"
VALIDATE_URL = "https://api.topstepx.com/api/Auth/validate"
ACCOUNT_URL  = "https://api.topstepx.com/api/Account/search"

@app.route("/")
def check_token_and_account():
    try:
        # === مرحله 1: گرفتن توکن ورود
        login_resp = requests.post(LOGIN_URL, json={
            "userName": USERNAME,
            "apiKey": API_KEY
        })
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if not login_data.get("success"):
            return "❌ ورود ناموفق! لطفاً USERNAME یا API_KEY را بررسی کن."

        token = login_data.get("token")

        # === مرحله 2: اعتبارسنجی توکن با هدر مناسب
        validate_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()
        print("🟢 اعتبارسنجی:", validate_data)

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است!"

        # === مرحله 3: گرفتن اطلاعات حساب
        acc_resp = requests.post(ACCOUNT_URL, json={}, headers=validate_headers)
        acc_data = acc_resp.json()
        print("🧾 لیست حساب‌ها:", acc_data)

        if not acc_data or len(acc_data) == 0:
            return "⚠️ حساب فعالی یافت نشد."

        account_id = acc_data[0].get("accountId")
        account_number = acc_data[0].get("accountNumber")

        return f"""
✅ توکن معتبر است!
🧾 Account ID: {account_id}
📘 Account Number: {account_number}
"""

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print("❗️ خطای کامل:\n", err)
        return f"<pre>⚠️ خطای سرور:\n\n{err}</pre>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
