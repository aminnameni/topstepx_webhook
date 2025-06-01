@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id
    try:
        data = request.get_json()
        print(f"📨 پیام کامل دریافتی: {data}")

        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            return "❌ داده‌های ناقص دریافت شد.", 400

        symbol_clean = symbol.upper()
        if symbol_clean.startswith("MNQ"):
            contract_id = "CON.F.US.MNQ.M25"
        elif symbol_clean.startswith("NQ"):
            contract_id = "CON.F.US.ENQ.M25"
        elif symbol_clean.startswith("GC"):
            contract_id = "CON.F.US.GC.M25"
        elif symbol_clean.startswith("MGC"):
            contract_id = "CON.F.US.MGC.M25"
        elif symbol_clean.startswith("HG"):
            contract_id = "CON.F.US.HG.N25"
        elif symbol_clean.startswith("CL"):
            contract_id = "CON.F.US.CL.N25"
        elif symbol_clean.startswith("NG"):
            contract_id = "CON.F.US.NG.N25"
        else:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        side_clean = str(side).strip().lower()
        print(f"📨 side دریافت‌شده: {side_clean} (اصلی: {side})")

        # تعیین نوع سفارش خروج یا ورود
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

        print(f"📦 سفارش نهایی: {order_payload}")
        headers = {"Authorization": f"Bearer {cached_token}"}
        order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)
        print(f"🔁 پاسخ خام سفارش: {order_resp.text}")
        order_data = order_resp.json()

        if order_data.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {order_data.get('orderId')}"
        else:
            return f"❌ خطا در سفارش: {order_data.get('errorMessage')}"

    except Exception as e:
        return f"""
⚠️ خطای پردازش سفارش:
{e}

📄 Traceback:
{traceback.format_exc()}
""", 500
