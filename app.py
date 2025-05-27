from flask import Flask, request
import os
import json
import requests

app = Flask(__name__)

# ⚙️ اطلاعات شما
USERNAME = "amin.nameni@ymail.com"
API_KEY = "wSKjn1H8w/klZ8zIybGxSR3Xf8K2O+pQdy3S9Rsah8I="

# 🔐 مرحله اول: ورود به سیستم
def get_auth_token():
    login_url = "https://api.topstepx.com/api/Auth/loginKey"
    payload = {
        "userName": USERNAME,
        "apiKey": API_KEY
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain"
    }
    response = requests.post(login_url, json=payload, headers=headers)
    result = response.json()
    return result.get("token") if result.get("success") else None

# 📒 گرفتن AccountId
def get_account_id(token):
    url = "https://api.topstepx.com/api/Account/search"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url, json={}, headers=headers)
    accounts = response.json()
    if isinstance(accounts, list) and accounts:
        return accounts[0]["accountId"]  # اولین حساب فعال
    return None

# 🔀 نگاشت ساده symbol به contractId (فعلاً دستی)
symbol_to_contract = {
    "MNQ": "CON.F.US.NQ.M25",
    "MGC": "CON.F.US.GC.M25",
    "MYM": "CON.F.US.DJ.M25",
    "MCL": "CON.F.US.CL.M25"
}

# 🟢 روت اصلی
@app.route('/')
def home():
    return "✅ TopStepX Webhook Server is Live!"

# 📥 روت وبهوک
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("📥 Webhook received:\n", json.dumps(data, indent=2))

    symbol = data.get("symbol")
    side_text = data.get("side")
    qty = data.get("qty")

    # نگاشت side از متن به عدد
    side = 1 if side_text.lower() == "buy" else 2

    contract_id = symbol_to_contract.get(symbol.upper())
    if not contract_id:
        return f"❌ Unknown symbol: {symbol}", 400

    # گرفتن توکن
    token = get_auth_token()
    if not token:
        return "❌ Failed to get auth token", 401

    # گرفتن اکانت آیدی
    account_id = get_account_id(token)
    if not account_id:
        return "❌ No account found", 404

    # سفارش بازار
    order_payload = {
        "accountId": account_id,
        "contractId": contract_id,
        "type": 2,
        "side": side,
        "size": qty,
        "limitPrice": None,
        "stopPrice": None,
        "trailPrice": None,
        "customTag": None,
        "linkedOrderId": None
    }

    order_url = "https://api.topstepx.com/api/Order/place"
    order_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    order_response = requests.post(order_url, json=order_payload, headers=order_headers)
    print("📤 Order response:", order_response.status_code, order_response.text)
    return "✅ Order sent", 200

# اجرای سرور
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

