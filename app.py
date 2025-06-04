from flask import Flask, request, jsonify
import requests
import os
import traceback

app = Flask(__name__)

# اطلاعات لاگین و اتصال
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

BASE_URL = "https://api.topstepx.com"
LOGIN_URL = f"{BASE_URL}/api/Auth/loginKey"
VALIDATE_URL = f"{BASE_URL}/api/Auth/validate"
ACCOUNT_URL = f"{BASE_URL}/api/Account/search"
ORDER_URL = f"{BASE_URL}/api/Order/place"

# کش توکن و حساب
cached_token = None
cached_account_id = None

@app.route("/", methods=["GET"])
def health_check():
    global cached_token, cached_account_id
    try:
        if not USERNAME or not API_KEY or not TARGET_ACCOUNT_NAME:
            msg = "❌ اطلاعات لاگین یا نام حساب تنظیم نشده‌اند."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 500

        login_payload = {"userName": USERNAME, "apiKey": API_KEY}
        login_resp = requests.post(LOGIN_URL, json=login_payload)
        login_data = login_resp.json()

        if not login_data.get("success"):
            msg = f"❌ خطای لاگین: {login_data.get('errorMessage')}"
            print(msg)
            return jsonify({"status": "error", "message": msg}), 401

        token = login_data["token"]
        validate_resp = requests.post(VALIDATE_URL, headers={"Authorization": f"Bearer {token}"})
        validate_data = validate_resp.json()

        if not validate_data.get("success"):
            msg = "❌ توکن نامعتبر است."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 401

        cached_token = validate_data["newToken"]

        account_resp = requests.post(
            ACCOUNT_URL,
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        )
        acc_data = account_resp.json()
        accounts = acc_data.get("accounts", [])
        target = next((a for a in accounts if a.get("name", "").strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()), None)

        if not target:
            msg = f"❌ حساب '{TARGET_ACCOUNT_NAME}' یافت نشد."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 404

        cached_account_id = target["id"]
        print(f"✅ اتصال موفق - accountId: {cached_account_id}")
        return jsonify({"status": "success", "accountId": cached_account_id})

    except Exception as e:
        print("🔥 خطای داخلی در health_check:", str(e))
        print("🧵 Traceback:", traceback.format_exc())
        return jsonify({"status": "error", "message": str(e), "traceback": traceback.format_exc()}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    try:
        if not cached_token or not cached_account_id:
            msg = "⛔ ابتدا اتصال اولیه از طریق GET / برقرار شود."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 403

        data = request.get_json()
        print(f"📨 پیام دریافتی: {data}")

        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            msg = "⚠️ داده‌های ناقص: symbol یا side یا qty مشخص نشده."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 400

        try:
            qty = int(qty)
        except:
            msg = f"⚠️ مقدار qty نامعتبر: {qty}"
            print(msg)
            return jsonify({"status": "error", "message": msg}), 400

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
        elif symbol_clean.startswith("HG"):
            contract_id = "CON.F.US.HG.N25"
        else:
            msg = f"⚠️ Contract ID برای {symbol} تعریف نشده."
            print(msg)
            return jsonify({"status": "error", "message": msg}), 400

        side_clean = side.strip().lower()
        if side_clean in ["buy", "long", "close_short"]:
            side_code = 0
        elif side_clean in ["sell", "short", "close_long"]:
            side_code = 1
        else:
            msg = f"⚠️ مقدار side نامعتبر: {side}"
            print(msg)
            return jsonify({"status": "error", "message": msg}), 400

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

        print("🛠 داده نهایی برای سفارش:")
        for k, v in order_payload.items():
            print(f"{k}: {v}")

        headers = {"Authorization": f"Bearer {cached_token}"}
        order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)

        print(f"🔁 وضعیت پاسخ API: {order_resp.status_code}")
        print(f"🔁 متن پاسخ: {order_resp.text}")

        try:
            order_data = order_resp.json()
        except Exception as e:
            print("❌ خطا در تبدیل پاسخ به JSON:", str(e))
            return jsonify({
                "status": "error",
                "message": "خطا در تبدیل پاسخ به JSON",
                "detail": str(e),
                "response": order_resp.text
            }), 500

        if order_data.get("success"):
            print(f"✅ سفارش موفق - orderId: {order_data.get('orderId')}")
            return jsonify({"status": "success", "orderId": order_data.get("orderId")})
        else:
            msg = f"❌ سفارش ناموفق: {order_data.get('errorMessage', 'خطای ناشناخته در سفارش')}"
            print(msg)
            return jsonify({"status": "error", "message": msg})

    except Exception as e:
        print("🔥 خطای داخلی در webhook:", str(e))
        print("🧵 Traceback:", traceback.format_exc())
        return jsonify({"status": "error", "message": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
