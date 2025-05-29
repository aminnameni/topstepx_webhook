@app.route("/webhook", methods=["POST"])
def webhook():
    global cached_token, cached_account_id

    try:
        data = request.get_json()
        print("📥 Webhook Received:", data)

        symbol = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")

        if not all([symbol, side, qty]):
            return "❌ داده‌های ناقص دریافت شد.", 400

        contract_map = {
            "MNQ": "CON.F.US.NQ3.M25",
            "MGC": "CON.F.US.GC.M25"
        }
        contract_id = contract_map.get(symbol.upper())
        if not contract_id:
            return f"❌ Contract ID برای {symbol} تعریف نشده.", 400

        # تابع داخلی برای ارسال سفارش با retry در صورت نیاز
        def place_order_with_retry():
            global cached_token, cached_account_id
            if not cached_token or not cached_account_id:
                print("🔁 در حال درخواست توکن جدید...")
                # دستی simulate route "/" برای گرفتن توکن جدید
                check_token_and_account()

            order_payload = {
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
            headers = {"Authorization": f"Bearer {cached_token}"}
            order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)
            order_data = order_resp.json()
            print("📤 پاسخ سفارش:", order_data)

            # اگر موفق نبود، یک بار دیگر با توکن جدید تلاش کن
            if not order_data.get("success"):
                print("⚠️ خطا در سفارش. تلاش دوباره پس از به‌روزرسانی توکن...")
                check_token_and_account()
                headers["Authorization"] = f"Bearer {cached_token}"
                order_resp = requests.post(ORDER_URL, json=order_payload, headers=headers)
                order_data = order_resp.json()
                print("🔁 پاسخ سفارش بعد از ری‌تری:", order_data)

            return order_data

        result = place_order_with_retry()

        if result.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {result.get('orderId')}"
        else:
            return f"❌ خطا در سفارش بعد از تلاش مجدد: {result.get('errorMessage')}"

    except Exception as e:
        return f"⚠️ خطای پردازش سفارش:\n{e}", 500
