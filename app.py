from flask import Flask, request
import requests
import os
import traceback

app = Flask(__name__)

# اطلاعات محیطی (از طریق Render یا .env قابل تنظیم)
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

# کش توکن و حساب
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
        output_lines = [f"➔ name: '{acc.get('name')}', id: {acc.get('id')}, canTrade: {acc.get('canTrade')}" for acc in accounts]

        target = next((a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)
        if not target:
            return f"⚠️ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد."
        cached_account_id = target["id"]

        return f"""
✅ اتصال موفق انجام شد  
🟢 تعداد حساب‌ها: {len(accounts)}

🖎 TARGET_ACCOUNT: {TARGET_ACCOUNT_NAME}
🔐 USERNAME: {USERNAME}

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

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    try:
        data = request.get_json()
        print(f"📨 پیام دریافتی: {data}")

        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            return "❌ داده‌های ناقص.", 400

        # تعیین contractId بر اساس symbol
        symbol_clean = symbol.upper()
        if symbol_clean.startswith("MNQ"):
            contract_id = "CON.F.US.MNQ.M25"
        elif symbol_clean.startswith("GC"):
            contract_id = "CON.F.US.GC.M25"
        elif symbol_clean.startswith("MGC"):
            contract_id = "CON.F.US.MGC.M25"
        elif symbol_clean.startswith("CL"):
            contract_id = "CON.F.US.CL.N25"
        elif symbol_clean.startswith("NG"):
            contract_id = "CON.F.US.NG.N25"
        else:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        side_clean = side.strip().lower()
        if side_clean in ["buy", "long", "close_short"]:
            side_code = 0  # خرید
        elif side_clean in ["sell", "short", "close_long"]:
            side_code = 1  # فروش
        else:
            return f"❌ مقدار side نامعتبر است: {side}", 400

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

        headers = {"Authorization": f"Bearer {cached_token}"}
        order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)
        print(f"🔁 پاسخ سفارش: {order_resp.text}")
        order_data = order_resp.json()

        if order_data.get("success"):
            return f"✅ سفارش ارسال شد. ID: {order_data.get('orderId')}"
        else:
            return f"❌ خطا در سفارش: {order_data.get('errorMessage')}"

    except Exception as e:
        return f"""
⚠️ خطای پردازش:
{e}

📄 Traceback:
{traceback.format_exc()}
""", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
