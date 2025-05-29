from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی (.env در لوکال / محیط در Render)
load_dotenv()

app = Flask(__name__)

# گرفتن اطلاعات حساس از محیط
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

# آدرس‌های API
BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"
ORDER_URL = f"{BASE_URL}/api/Order/place"

# حافظه توکن و آیدی حساب
cached_token = None
cached_account_id = None


# تابع گرفتن توکن جدید و آیدی حساب
def refresh_token_and_account():
    global cached_token, cached_account_id

    login_payload = {"userName": USERNAME, "apiKey": API_KEY}
    login_resp = requests.post(LOGIN_URL, json=login_payload)
    login_data = login_resp.json()

    if not login_data.get("success"):
        raise Exception(f"❌ ورود ناموفق: {login_data.get('errorMessage')}")

    token = login_data["token"]
    validate_headers = {"Authorization": f"Bearer {token}"}
    validate_resp = requests.post(VALIDATE_URL, headers=validate_headers)
    validate_data = validate_resp.json()

    if not validate_data.get("success"):
        raise Exception("❌ توکن نامعتبر است.")

    cached_token = validate_data["newToken"]

    account_headers = {"Authorization": f"Bearer {cached_token}"}
    account_resp = requests.post(ACCOUNT_URL, headers=account_headers)
    acc_data = account_resp.json()

    target_account = next(
        (acc for acc in acc_data.get("accounts", [])
         if acc.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.lower()),
        None
    )

    if not target_account:
        raise Exception("⚠️ حساب مورد نظر یافت نشد.")

    cached_account_id = target_account["id"]


# مسیر تست سلامت و بررسی توکن
@app.route("/", methods=["GET"])
def health_check():
    try:
        refresh_token_and_account()
        return f"✅ Token & Account آماده است\n📘 ID: {cached_account_id}"
    except Exception as e:
        return f"❌ خطا:\n{e}"


# مسیر دریافت سیگنال و ارسال سفارش
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

        # نگاشت نمادها به contractId
        contract_map = {
            "MNQ": "CON.F.US.NQ3.M25",
            "MGC": "CON.F.US.GC.M25",
            "MBT": "CON.F.CME.BTC.M25"
        }
        contract_id = contract_map.get(symbol.upper())
        if not contract_id:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        def place_order():
            global cached_token, cached_account_id
            if not cached_token or not cached_account_id:
                refresh_token_and_account()

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
            resp = requests.post(ORDER_URL, json=payload, headers=headers)
            return resp.json()

        result = place_order()

        # اگر سفارش موفق نبود، یک بار دیگر با توکن جدید تلاش کن
        if not result.get("success"):
            print("⚠️ تلاش مجدد با توکن جدید...")
            refresh_token_and_account()
            result = place_order()

        if result.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {result.get('orderId')}"
        else:
            return f"❌ خطا: {result.get('errorMessage')}", 500

    except Exception as e:
        return f"⚠️ خطای کلی:\n{e}", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
