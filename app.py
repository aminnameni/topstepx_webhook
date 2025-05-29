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

        if not result.get("success"):
            print("⚠️ تلاش مجدد با توکن جدید...")
            refresh_token_and_account()
            result = place_order()

        if result.get("success"):
            return f"✅ سفارش ارسال شد! Order ID: {result.get('orderId')}"
        else:
            return f"❌ خطا: {result.get('errorMessage')}", 500

    except Exception as e:
        return f"⚠️ خطای پردازش سفارش:\n{e}", 500
