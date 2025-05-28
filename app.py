from flask import Flask
import requests
import os

app = Flask(__name__)

USERNAME = "aminnameni"  # ← جایگزین کن
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="  # ← جایگزین کن

LOGIN_URL = "https://api.topstepx.com/api/Auth/loginKey"
VALIDATE_URL = "https://api.topstepx.com/api/Auth/validate"
ACCOUNT_URL = "https://api.topstepx.com/api/Account/search"

@app.route("/")
def check_token_and_account():
    try:
        # === ورود و گرفتن توکن
        login_resp = requests.post(LOGIN_URL, json={
            "userName": USERNAME,
            "apiKey": API_KEY
        })
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if not login_data.get("success"):
            return "❌ ورود ناموفق! ایمیل یا API Key اشتباه است"

        token = login_data.get("token")

        # === بررسی اعتبار توکن
        validate_resp = requests.post(VALIDATE_URL, json={"token": token})
        validate_data = validate_resp.json()
        print("🟢 اعتبارسنجی:", validate_data)

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است!"

        # === گرفتن accountId
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        acc_resp = requests.post(ACCOUNT_URL, json={}, headers=headers)
        acc_data = acc_resp.json()
        print("🧾 لیست حساب‌ها:", acc_data)

        if not acc_data or len(acc_data) == 0:
            return "⚠️ حسابی یافت نشد."

        account_id = acc_data[0].get("accountId")
        account_number = acc_data[0].get("accountNumber")

        return f"✅ توکن معتبر است!\n\n🧾 Account ID: {account_id}\n📘 Account #: {account_number}"

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print("❗️ خطای کامل:\n", err)
        return f"<pre>⚠️ خطای سرور:\n\n{err}</pre>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
