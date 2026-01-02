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

# ================== RUNTIME STATE (Telegram utilities) ==================
SERVER_START_UTC = datetime.datetime.utcnow()

LAST_SIGNAL_UTC = None
LAST_SIGNAL = None  # dict: symbol/action/qty/planned_entry/raw

LAST_EXEC_UTC = None
LAST_EXEC = None    # dict: symbol/side/qty/planned_entry/fill_price/slippage

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
            timeout=8
        )
    except Exception as e:
        logging.error(f"Telegram error: {e}")

def tg_menu(chat_id):
    # حرفه‌ای‌تر: ردیف‌های منظم + دکمه‌های کاربردی
    tg_send(
        chat_id,
        "🎛️ Trading Control Panel v2.0",
        {
            "keyboard": [
                ["💰 Balance", "🟢 Status"],
                ["📊 Open Orders", "📈 Trade History"],
                ["📌 Last Trade", "💥 Last Slippage"],
                ["📊 Today Stats", "⏱️ Uptime / Last Signal"],
                ["🚫 Cancel ALL Open Orders", "🔄 Refresh Menu"],
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

def utc_now():
    return datetime.datetime.utcnow()

def fmt_dt(dt):
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def fmt_ago(dt):
    if not dt:
        return "N/A"
    delta = utc_now() - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    return f"{h}h ago"

def ny_today_start_utc():
    # ساده و عملی (برای ژانویه: نیویورک UTC-5)
    # NY now = UTC - 5h
    now_utc = utc_now()
    ny_now = now_utc - datetime.timedelta(hours=5)
    ny_start = datetime.datetime(ny_now.year, ny_now.month, ny_now.day, 0, 0, 0)
    # تبدیل به UTC: +5h
    return ny_start + datetime.timedelta(hours=5)

def connect_topstep():
    global cached_token, cached_account_id

    login = requests.post(
        f"{BASE_URL}/api/Auth/loginKey",
        json={"userName": USERNAME, "apiKey": API_KEY},
        timeout=15
    ).json()

    if not login.get("success"):
        raise Exception("Login failed")

    validate = requests.post(
        f"{BASE_URL}/api/Auth/validate",
        headers={"Authorization": f"Bearer {login['token']}"},
        timeout=15
    ).json()

    cached_token = validate["newToken"]

    accounts = requests.post(
        f"{BASE_URL}/api/Account/search",
        headers={"Authorization": f"Bearer {cached_token}"},
        json={"onlyActiveAccounts": True},
        timeout=15
    ).json().get("accounts", [])

    match = next(
        (a for a in accounts if a["name"].strip().lower() == TARGET_ACCOUNT_NAME.strip().lower()),
        None
    )

    if not match:
        raise Exception("Target account not found")

    cached_account_id = match["id"]

def ts_headers():
    return {"Authorization": f"Bearer {cached_token}"}

def search_orders_window(start_utc: datetime.datetime, end_utc: datetime.datetime):
    return requests.post(
        f"{BASE_URL}/api/Order/search",
        headers=ts_headers(),
        json={
            "accountId": cached_account_id,
            "startTimestamp": start_utc.isoformat() + "Z",
            "endTimestamp": end_utc.isoformat() + "Z"
        },
        timeout=20
    ).json()

def search_open_orders():
    return requests.post(
        f"{BASE_URL}/api/Order/searchOpen",
        headers=ts_headers(),
        json={"accountId": cached_account_id},
        timeout=20
    ).json()

def cancel_order(order_id: int):
    # طبق صحبت‌های قبلی شما: /api/Order/cancel
    return requests.post(
        f"{BASE_URL}/api/Order/cancel",
        headers=ts_headers(),
        json={"accountId": cached_account_id, "orderId": order_id},
        timeout=20
    ).json()

# ================== HEALTH ==================
@app.route("/", methods=["GET"])
def health():
    connect_topstep()
    return jsonify({"status": "connected", "accountId": cached_account_id})

# ================== TRADINGVIEW WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def tradingview_webhook():
    global cached_token, cached_account_id
    global LAST_SIGNAL_UTC, LAST_SIGNAL, LAST_EXEC_UTC, LAST_EXEC

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

        action_map = {"buy": "buy", "sell": "sell", "close": "close", "exit": "close"}
        action = action_map.get(action_raw)
        if not action:
            return jsonify({"error": "Invalid action"}), 400

        # ذخیره آخرین سیگنال
        LAST_SIGNAL_UTC = utc_now()
        LAST_SIGNAL = {
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "planned_entry": planned_entry,
            "raw": data
        }

        # ---- CLOSE ----
        if action == "close":
            now = utc_now()
            resp = search_orders_window(now - datetime.timedelta(hours=12), now)
            orders = resp.get("orders", [])
            if not orders:
                tg_send(TG_CHAT_ID, "ℹ️ Already flat")
                return jsonify({"status": "already_flat"}), 200

            last = orders[-1]
            qty = int(last.get("size", 0) or 0)
            side_code = 1 if last.get("side") == 0 else 0  # reverse
        else:
            if qty <= 0:
                return jsonify({"error": "Invalid quantity"}), 400
            side_code = 0 if action == "buy" else 1

        payload = {
            "accountId": cached_account_id,
            "contractId": SYMBOL_MAP[symbol],
            "type": 2,  # MARKET
            "side": side_code,
            "size": qty
        }

        r = requests.post(
            f"{BASE_URL}/api/Order/place",
            headers=ts_headers(),
            json=payload,
            timeout=20
        ).json()

        if not r.get("success"):
            tg_send(TG_CHAT_ID, f"❌ ORDER FAILED\n{r}")
            return jsonify(r), 400

        # ===== WAIT FOR BROKER FILL (filledPrice) =====
        fill_price = None
        for _ in range(3):
            time.sleep(0.7)
            now = utc_now()
            resp = search_orders_window(now - datetime.timedelta(seconds=5), now)
            orders = resp.get("orders", [])
            if orders:
                last = orders[-1]
                if last.get("fillVolume", 0) and last.get("filledPrice") is not None:
                    fill_price = last.get("filledPrice")
                    break

        slippage = None
        if fill_price is not None:
            slippage = round(fill_price - planned_entry, 4)

        # ذخیره آخرین اجرا
        LAST_EXEC_UTC = utc_now()
        LAST_EXEC = {
            "symbol": symbol,
            "side": action.upper(),
            "qty": qty,
            "planned_entry": planned_entry,
            "fill_price": fill_price,
            "slippage": slippage
        }

        tg_send(
            TG_CHAT_ID,
            f"✅ ORDER EXECUTED\n"
            f"Symbol: {symbol}\n"
            f"Side: {action.upper()}\n"
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

    if text in ["/menu", "🔄 Refresh Menu"]:
        tg_menu(chat_id)

    elif text == "💰 Balance":
        accs = requests.post(
            f"{BASE_URL}/api/Account/search",
            headers=ts_headers(),
            json={"onlyActiveAccounts": True},
            timeout=20
        ).json().get("accounts", [])

        acc = next(a for a in accs if a["id"] == cached_account_id)
        balance = acc.get("balance", "N/A")
        tg_send(chat_id, f"💰 ACCOUNT BALANCE\nBalance: {balance}")

    elif text == "🟢 Status":
        tg_send(
            chat_id,
            f"🟢 SYSTEM STATUS\n"
            f"Token: {'OK' if cached_token else '❌'}\n"
            f"AccountID: {cached_account_id}\n"
            f"Started: {fmt_dt(SERVER_START_UTC)}"
        )

    elif text == "📊 Open Orders":
        resp = search_open_orders()
        orders = resp.get("orders", [])
        if not orders:
            tg_send(chat_id, "📊 Open Orders\nNo open orders")
        else:
            msg_txt = "📊 Open Orders:\n"
            for o in orders:
                side = "BUY" if o.get("side") == 0 else "SELL"
                msg_txt += (
                    f"- ID:{o.get('id')} | {o.get('contractId')} | {side} | "
                    f"Qty:{o.get('size')} | Limit:{o.get('limitPrice')} | Stop:{o.get('stopPrice')}\n"
                )
            tg_send(chat_id, msg_txt)

    elif text == "📈 Trade History":
        now = utc_now()
        resp = search_orders_window(now - datetime.timedelta(hours=24), now)
        orders = resp.get("orders", [])
        if not orders:
            tg_send(chat_id, "📈 Trade History\nNo trades found")
        else:
            msg_txt = "📈 Trade History (24h):\n"
            for o in orders:
                if o.get("fillVolume", 0) and o.get("filledPrice") is not None:
                    side = "BUY" if o.get("side") == 0 else "SELL"
                    msg_txt += (
                        f"- {o.get('contractId')} | {side} | "
                        f"Qty:{o.get('size')} | Fill:{o.get('filledPrice')} | "
                        f"Time:{o.get('updateTimestamp')}\n"
                    )
            tg_send(chat_id, msg_txt)

    elif text == "📌 Last Trade":
        if not LAST_EXEC:
            tg_send(chat_id, "📌 Last Trade\nNo executions recorded yet")
        else:
            tg_send(
                chat_id,
                "📌 Last Trade\n"
                f"Time: {fmt_dt(LAST_EXEC_UTC)} ({fmt_ago(LAST_EXEC_UTC)})\n"
                f"Symbol: {LAST_EXEC.get('symbol')}\n"
                f"Side: {LAST_EXEC.get('side')}\n"
                f"Qty: {LAST_EXEC.get('qty')}\n"
                f"Fill: {LAST_EXEC.get('fill_price')}"
            )

    elif text == "💥 Last Slippage":
        if not LAST_EXEC:
            tg_send(chat_id, "💥 Last Slippage\nNo executions recorded yet")
        else:
            tg_send(
                chat_id,
                "💥 Last Slippage\n"
                f"Time: {fmt_dt(LAST_EXEC_UTC)} ({fmt_ago(LAST_EXEC_UTC)})\n"
                f"Symbol: {LAST_EXEC.get('symbol')}\n"
                f"Planned: {LAST_EXEC.get('planned_entry')}\n"
                f"Fill: {LAST_EXEC.get('fill_price')}\n"
                f"Slippage: {LAST_EXEC.get('slippage')}"
            )

    elif text == "📊 Today Stats":
        start_utc = ny_today_start_utc()
        now = utc_now()
        resp = search_orders_window(start_utc, now)
        orders = resp.get("orders", [])

        filled = [
            o for o in orders
            if o.get("fillVolume", 0) and o.get("filledPrice") is not None
        ]

        buy_count = sum(1 for o in filled if o.get("side") == 0)
        sell_count = sum(1 for o in filled if o.get("side") == 1)

        first_time = filled[0].get("updateTimestamp") if filled else "N/A"
        last_time = filled[-1].get("updateTimestamp") if filled else "N/A"

        tg_send(
            chat_id,
            "📊 Today Stats (NY day)\n"
            f"Filled trades: {len(filled)}\n"
            f"BUY: {buy_count} | SELL: {sell_count}\n"
            f"First: {first_time}\n"
            f"Last: {last_time}\n"
            f"Window: {start_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC → Now"
        )

    elif text == "⏱️ Uptime / Last Signal":
        uptime = utc_now() - SERVER_START_UTC
        uptime_s = int(uptime.total_seconds())
        uptime_h = uptime_s // 3600
        uptime_m = (uptime_s % 3600) // 60

        if not LAST_SIGNAL:
            signal_txt = "No signals yet"
        else:
            signal_txt = (
                f"{LAST_SIGNAL.get('symbol')} {LAST_SIGNAL.get('action', '').upper()} x{LAST_SIGNAL.get('qty')}\n"
                f"Planned Entry: {LAST_SIGNAL.get('planned_entry')}\n"
                f"Time: {fmt_dt(LAST_SIGNAL_UTC)} ({fmt_ago(LAST_SIGNAL_UTC)})"
            )

        tg_send(
            chat_id,
            "⏱️ Uptime / Last Signal\n"
            f"Uptime: {uptime_h}h {uptime_m}m\n"
            f"Started: {fmt_dt(SERVER_START_UTC)}\n\n"
            f"Last Signal:\n{signal_txt}"
        )

    elif text == "🚫 Cancel ALL Open Orders":
        resp = search_open_orders()
        orders = resp.get("orders", [])

        if not orders:
            tg_send(chat_id, "🚫 Cancel ALL Open Orders\nNo open orders to cancel")
        else:
            ok = 0
            fail = 0
            for o in orders:
                oid = o.get("id")
                if oid is None:
                    fail += 1
                    continue
                cr = cancel_order(int(oid))
                if cr.get("success"):
                    ok += 1
                else:
                    fail += 1

            tg_send(
                chat_id,
                "🚫 Cancel ALL Open Orders\n"
                f"Requested: {len(orders)}\n"
                f"Cancelled OK: {ok}\n"
                f"Failed: {fail}"
            )

    else:
        tg_send(chat_id, "❓ Unknown command\n/menu")

    return "ok"

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
