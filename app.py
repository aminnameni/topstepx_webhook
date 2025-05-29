from flask import Flask, request
import requests
import os
import traceback

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
CONTRACT_SEARCH_URL = f"{BASE_URL}/api/Contract/search"

# کش توکن و شناسه حساب
cached_token = None
cached_account_id = None

@app.route("/", methods=["GET"])
def health_check():
    global cached_token, cached_account_id

    try:
        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()

        if not login_data.get("success"):
            return f"❌ ورود ناموفق: {login_data.get('errorMessage')}"

        token = login_data["token"]
        validate_headers = {"Authorization": f"Bearer {token}"}
        validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
        validate_data = validate_resp.json()

        if not validate_data.get("success"):
            return "❌ توکن نامعتبر است."

        cached_token = validate_data["newToken"]

        account_headers = {"Authorization": f"Bearer {cached_token}"}
        account_payload = {"onlyActiveAccounts": True}
        account_resp = requests.post(ACCOUNT_URL, headers=account_headers, json=account_payload)
        acc_data = account_resp.json()

        accounts = acc_data.get("accounts", [])
        output_lines = [f"➡️ name: '{acc.get('name')}', id: {acc.get('id')}, canTrade: {acc.get('canTrade')}" for acc in accounts]

        target = next((a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)
        if not target:
            return f"⚠️ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد."
        cached_account_id = target["id"]

        return f"""
✅ اتصال موفق انجام شد  
🟢 تعداد حساب‌ها: {len(accounts)}

🔎 TARGET_ACCOUNT: {TARGET_ACCOUNT_NAME}
🔐 USERNAME: {USERNAME}

📅 پاسخ خام:
{acc_data}

📋 حساب‌ها:
{chr(10).join(output_lines)}
"""

    except Exception as e:
        return f"""
❌ خطای اجرای توابع:
{e}

📄 Traceback:
{traceback.format_exc()}
"""

@app.route("/contracts", methods=["GET"])
def show_contracts():
    global cached_token, cached_account_id
    try:
        if not cached_token or not cached_account_id:
            return "❌ توکن یا شناسه حساب موجود نیست. ابتدا مسیر اصلی را صدا بزنید."

        headers = {"Authorization": f"Bearer {cached_token}"}
        payload = {
            "searchText": "NQ",
            "live": False
        }
        contract_resp = requests.post(CONTRACT_SEARCH_URL, headers=headers, json=payload)
        contract_data = contract_resp.json()

        lines = [f"📄 {c.get('symbol', 'نامشخص')} → {c.get('contractId', 'نامشخص')}" for c in contract_data.get("contracts", [])]
        if not lines or contract_data.get("contracts") == []:
            lines = ["⚠️ هیچ قراردادی پیدا نشد."]

        return f"""
✅ لیست قراردادهای قابل معامله:
{chr(10).join(lines)}

📅 پاسخ خام:
{contract_data}
"""

    except Exception as e:
        return f"""
❌ خطای بررسی قراردادها:
{e}

📄 Traceback:
{traceback.format_exc()}
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
