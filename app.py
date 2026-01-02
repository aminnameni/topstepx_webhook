from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging
import time

# ================== APP ==================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ================== ENV ==================
USERNAME = os.getenv("TOPSTEP_USER")
API_KEY = os.getenv("TOPSTEP_KEY")
TARGET_ACCOUNT_NAME = os.getenv("TARGET_ACCOUNT")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

BASE_URL = "https://api.topstepx.com"

cached_token = None
cached_account_id = None

# ================== SYMBOL MAP ==================
SYMBOL_MAP = {
    "MGC": "CON.F.US.MGC.G26",
    "MNQ": "CON.F.US.MNQ.H26",
}

# ================== TELEGRAM ==================
def tg_send(chat_id, text, keyboard=None):
    if not TG_BOT_TOKEN or not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=5
        )
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def tg_menu(chat_id):
    tg_send(
        chat_id,
        "🎛️ Trading Control Panel",
        {
            "keyboard": [
                ["💰 Balance"],
                ["📊 Open Orders", "📈 Trade History"],
                ["🟢 Status"]
            ],
            "resize_keyboard": True
        }
    )

# ================== UTILS ==================
def normalize_symbol(raw: str) -> str:
    raw = raw.upper()
    if raw.startswith("MGC"):
        return "MGC"
    if raw.startswith("MNQ"):
        return "MNQ"
    return ""

def connect_topstep():
    global cached_token, cached_account_id

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY}
    ).json()

    if not login.get("success"):
        raise Exception("Login failed")

    validate = requests.post(
        f"{BASE_URL}/api/Auth/validate",
        headers={"Authorization": f"Bearer {login['token']}"}
    ).json()

    cached_token = validate["newToken"]

    accounts = requests.post(
        f"{BASE_URL}/api/Account/search",
        headers={"Authorization": f"Bearer {cached_token}"},
        json={"onlyActiveAccounts": True}
    ).json().get("accounts", [])

    match = next(
        (a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
        None
    )

    if not match:
        raise Exception("Target account not found")

    cached_account_id = match["id"]

# ================== HEALTH ==================
@app.route("/", methods=["GET"])
def health():
    connect_topstep()
    return jsonify({"status": "connected", "accountId": cached_account_id})

# ================== TRADINGVIEW WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    global cached_token, cached_account_id

    try:
        if not cached_token or not cached_account_id:
            connect_topstep()

        data = request.get_json(force=True)
        logging.info(f"Webhook received: {data}")

        raw_symbol = str(data.get("symbol", ""))
        action_raw = str(data.get("data", "")).lower()
        qty = int(float(data.get("quantity", 0)))
        planned_entry = float(data.get("entry_price", 0))

        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            return jsonify({"error": "Unsupported symbol"}), 400

        if action_raw not in ["buy", "sell"]:
            return jsonify({"error": "Invalid action"}), 400

        side_code = 0 if action_raw == "buy" else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": SYMBOL_MAP[symbol],
            "type": 2,
            "side": side_code,
            "size": qty
        }

        r = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers={"Authorization": f"Bearer {cached_token}"},
            json=payload
        ).json()

        if not r.get("success"):
            tg_send(TG_CHAT_ID, f"❌ ORDER FAILED\n{r}")
            return jsonify(r), 400

        # ===== WAIT FOR BROKER FILL =====
        fill_price = None
        for _ in range(3):
            time.sleep(0.7)
            now = datetime.datetime.utcnow()
            resp = requests.post(
                f"{BASE_URL}/api/Order/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={
                    "accountId": cached_account_id,
                    "startTimestamp": (now - datetime.timedelta(seconds=5)).isoformat() + "Z",
                    "endTimestamp": now.isoformat() + "Z"
                }
            ).json()

            orders = resp.get("orders", [])
            if orders:
                last = orders[-1]
                if last.get("fillVolume", 0) > 0:
                    fill_price = last.get("filledPrice")
                    break

        slippage = None
        if fill_price:
            slippage = round(fill_price - planned_entry, 4)

        tg_send(
            TG_CHAT_ID,
            f"✅ ORDER EXECUTED\n"
            f"Symbol: {symbol}\n"
            f"Side: {action_raw.upper()}\n"
            f"Qty: {qty}\n\n"
            f"Planned Entry: {planned_entry}\n"
            f"Broker Fill: {fill_price}\n"
            f"Slippage: {slippage}"
        )

        return jsonify({"status": "success"})

    except Exception as e:
        logging.exception("Webhook error")
        tg_send(TG_CHAT_ID, f"🔥 SYSTEM ERROR\n{str(e)}")
        return jsonify({"error": str(e)}), 500

# ================== TELEGRAM WEBHOOK ==================
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    global cached_token, cached_account_id

    if not cached_token or not cached_account_id:
        connect_topstep()

    data = request.get_json()
    msg = data.get("message", {})
    text = msg.get("text", "")
    chat_id = msg.get("chat", {}).get("id")

    if not chat_id:
        return "ok"

    if text == "/menu":
        tg_menu(chat_id)

    elif text == "💰 Balance":
        accs = requests.post(
            f"{BASE_URL}/api/Account/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"onlyActiveAccounts": True}
        ).json()["accounts"]

        acc = next(a for a in accs if a["id"] == cached_account_id)
        balance = acc.get("balance", "N/A")
        tg_send(chat_id, f"💰 ACCOUNT BALANCE\nBalance: {balance}")

    elif text == "📊 Open Orders":
        resp = requests.post(
            f"{BASE_URL}/api/Order/searchOpen",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={"accountId": cached_account_id}
        ).json()

        orders = resp.get("orders", [])
        if not orders:
            tg_send(chat_id, "📊 Open Orders\nNo open orders")
        else:
            msg_txt = "📊 Open Orders:\n"
            for o in orders:
                side = "BUY" if o.get("side") == 0 else "SELL"
                msg_txt += (
                    f"- {o['contractId']} | {side} | "
                    f"Qty: {o['size']} | "
                    f"Limit: {o.get('limitPrice')} | "
                    f"Stop: {o.get('stopPrice')}\n"
                )
            tg_send(chat_id, msg_txt)

    elif text == "📈 Trade History":
        now = datetime.datetime.utcnow()
        resp = requests.post(
            f"{BASE_URL}/api/Order/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={
                "accountId": cached_account_id,
                "startTimestamp": (now - datetime.timedelta(hours=24)).isoformat() + "Z",
                "endTimestamp": now.isoformat() + "Z"
            }
        ).json()

        orders = resp.get("orders", [])
        if not orders:
            tg_send(chat_id, "📈 Trade History\nNo trades found")
        else:
            msg_txt = "📈 Trade History (24h):\n"
            for o in orders:
                if o.get("fillVolume", 0) > 0:
                    side = "BUY" if o.get("side") == 0 else "SELL"
                    msg_txt += (
                        f"- {o['contractId']} | {side} | "
                        f"Qty: {o['size']} | "
                        f"Fill: {o.get('filledPrice')} | "
                        f"Time: {o.get('updateTimestamp')}\n"
                    )
            tg_send(chat_id, msg_txt)

    elif text == "🟢 Status":
        tg_send(
            chat_id,
            f"🟢 SYSTEM STATUS\n"
            f"Token: {'OK' if cached_token else '❌'}\n"
            f"AccountID: {cached_account_id}"
        )

    else:
        tg_send(chat_id, "❓ Unknown command\n/menu")

    return "ok"

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
