from flask import Flask, request
import requests

app = Flask(__name__)

# اطلاعات ورود (جایگزین کن با اطلاعات واقعی خودت)
USERNAME = "aminnameni"
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="

# آدرس‌های API
BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"

@app.route("/", methods=["GET"])
def check_token_and_account():
    try:
        # ورود با کلید API
        login_payload = {
            "userName": USERNAME,
            "apiKey": API_KEY
        }
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()
        print("🟢 پاسخ ورود:", login_data)

        if not login_data.get("success"):
            return f"❌ ورود ناموفق: {login_data.get('errorMessage')}"

        token = login_data["token"]

        # اعتبارسنجی توکن
        validate_headers = {"Authorization": f"Bearer {token}"}
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()
        print("🟢 اعتبارسنجی:", validate_data)

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است."

        new_token = validate_data["newToken"]

        # دریافت لیست حساب‌ها
        account_headers = {"Authorization": f"Bearer {new_token}"}
        account_resp = requests.post(ACCOUNT_URL, headers=account_headers)
        acc_data = account_resp.json()
        print("🧾 لیست حساب‌ها:", acc_data)

        accounts = acc_data.get("accounts", [])
        if not accounts:
            return "⚠️ هیچ حسابی یافت نشد."

        # فقط حساب‌هایی که میشه باهاش ترید کرد
        tradable_accounts = [acc for acc in accounts if acc.get("canTrade")]

        if not tradable_accounts:
            return "⚠️ هیچ حساب قابل تریدی یافت نشد."

        account_id = tradable_accounts[0]["id"]
        account_name = tradable_accounts[0]["name"]

        return f"""
✅ توکن معتبر است!
🧾 Account ID: {account_id}
📘 Account Name: {account_name}
"""

    except Exception as e:
        return f"⚠️ خطای سرور:\n{e}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
