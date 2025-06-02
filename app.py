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

        print(f"🔁 وضعیت پاسخ سفارش: {order_resp.status_code}")
        print(f"🔁 متن پاسخ: {order_resp.text}")

        try:
            order_data = order_resp.json()
        except Exception as e:
            return f"""
❌ خطا در تبدیل پاسخ به JSON:
{e}

🧾 متن کامل پاسخ:
{order_resp.text}
""", 500

        if order_data.get("success"):
            return f"✅ سفارش ارسال شد. ID: {order_data.get('orderId')}"
        else:
            return f"❌ خطا در سفارش: {order_data.get('errorMessage')}"

    except Exception as e:
        return f"""
⚠️ خطای پردازش کلی:
{e}

📄 Traceback:
{traceback.format_exc()}
""", 500
