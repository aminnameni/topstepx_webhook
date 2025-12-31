from flask import Flask, request, jsonify
import requests
import os
import datetime
import logging
import uuid

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

# ================== TELEGRAM CORE ==================
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
                ["💰 Balance", "📊 Positions"],
                ["🟢 Status"]
            ],
            "resize_keyboard": True
        }
    )

# ================== UTILS ==================
def normalize_symbol(raw_symbol: str) -> str:
    raw_symbol = raw_symbol.upper()
    if raw_symbol.startswith("MGC"):
        return "MGC"
    if raw_symbol.startswith("MNQ"):
        return "MNQ"
    return ""

def connect_topstep():
    global cached_token, cached_account_id

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY}
    ).json()

    if not login.get("success"):
        raise Exception(f"Login failed: {login}")

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

# ================== ROUTES ==================
@app.route("/", methods=["GET"])
def health():
    connect_topstep()
    return jsonify({"status": "connected", "accountId": cached_account_id})


# ================== TRADINGVIEW WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    try:
        if not cached_token or not cached_account_id:
            connect_topstep()

        data = request.get_json(force=True)
        logging.info(f"Webhook received: {data}")

        raw_symbol = str(data.get("symbol", ""))
        action_raw = str(data.get("data", "")).lower()
        qty = int(float(data.get("quantity", 0)))

        symbol = normalize_symbol(raw_symbol)
        if not symbol:
            return jsonify({"error": "Unsupported symbol"}), 400

        contract_id = SYMBOL_MAP[symbol]

        action_map = {
            "buy": "buy",
            "sell": "sell",
            "close": "close",
            "exit": "close"
        }

        action = action_map.get(action_raw)
        if not action:
            return jsonify({"error": "Invalid action"}), 400

        tg_send(
            TG_CHAT_ID,
            f"📩 SIGNAL RECEIVED\nSymbol: {symbol}\nAction: {action.upper()}\nQty: {qty}"
        )

        # ---------- CLOSE ----------
        if action == "close":
            now = datetime.datetime.utcnow()
            resp = requests.post(
                f"{BASE_URL}/api/Order/search",
                headers={"Authorization": f"Bearer {cached_token}"},
                json={
                    "accountId": cached_account_id,
                    "startTimestamp": (now - datetime.timedelta(hours=12)).isoformat()+"Z",
                    "endTimestamp": now.isoformat()+"Z"
                }
            ).json()

            active = [
                o for o in resp.get("orders", [])
                if o["contractId"] == contract_id and o["status"] in [1, 2]
            ]

            if not active:
                tg_send(TG_CHAT_ID, "ℹ️ Already flat")
                return jsonify({"status": "already_flat"}), 200

            last = active[-1]
            qty = int(last["size"])
            side_code = 1 if last["side"] == 0 else 0

        else:
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if action == "buy" else 1

        custom_tag = f"{action}_{int(datetime.datetime.utcnow().timestamp()*1000)}_{uuid.uuid4().hex[:6]}"

        payload = {
            "accountId": cached_account_id,
            "contractId": contract_id,
            "type": 2,
            "side": side_code,
            "size": qty,
            "customTag": custom_tag
        }

        tg_send(
            TG_CHAT_ID,
            f"🚀 ORDER SENDING\n{symbol} {action.upper()} x{qty}\nTag: {custom_tag}"
        )

        r = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers={"Authorization": f"Bearer {cached_token}"},
            json=payload
        ).json()

        if r.get("success"):
            tg_send(
                TG_CHAT_ID,
                f"✅ ORDER SUCCESS\n{symbol} {action.upper()} x{qty}\nOrderID: {r.get('orderId')}"
            )
            return jsonify({"status": "success"})

        tg_send(TG_CHAT_ID, f"❌ ORDER FAILED\n{r}")
        return jsonify(r), 400

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
        tg_send(
            chat_id,
            f"💰 Balance\nBalance: {acc['balance']}\nEquity: {acc['equity']}\nDay PnL: {acc['dayProfitLoss']}"
        )

    elif text == "📊 Positions":
        now = datetime.datetime.utcnow()
        resp = requests.post(
            f"{BASE_URL}/api/Order/search",
            headers={"Authorization": f"Bearer {cached_token}"},
            json={
                "accountId": cached_account_id,
                "startTimestamp": (now - datetime.timedelta(hours=12)).isoformat()+"Z",
                "endTimestamp": now.isoformat()+"Z"
            }
        ).json()

        active = [o for o in resp.get("orders", []) if o["status"] in [1, 2]]

        if not active:
            tg_send(chat_id, "📭 No open positions")
        else:
            msg = "📊 Open Positions:\n"
            for o in active:
                msg += f"- {o['contractId']} | Qty: {o['size']}\n"
            tg_send(chat_id, msg)

    elif text == "🟢 Status":
        tg_send(
            chat_id,
            f"🟢 SYSTEM STATUS\nToken: {'OK' if cached_token else '❌'}\nAccountID: {cached_account_id}"
        )

    else:
        tg_send(chat_id, "❓ Unknown command\n/menu")

    return "ok"


# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
