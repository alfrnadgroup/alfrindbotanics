from flask import Flask, request, jsonify, send_file
import sqlite3
import os
import requests
from datetime import datetime

app = Flask(__name__)

DB_NAME = "orders.db"

# PayPal
PAYPAL_CLIENT = os.environ.get("PAYPAL_CLIENT", "AdAZZJ6hx9Dp_cz_e506XL770LMrBhzaepLYQhloCBMxn8JAN85AYlpBVLS-PwLnMcG5sFm2uCRgZrYH")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "EDa0pdNGmpAQcu8ETAZsTp4awM15QbmtzwIyiREd2LyVVNvWRvL663QI-ewys-0llVK5eZLmXyMrH_x3")
PAYPAL_API = "https://api-m.paypal.com"

# WhatsApp Business API
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "EAATDkqdl5CQBRo22tAhuZCwbaCn76H7AfTZBQ2GH7tlo5fDRFQjcbyjHC3TpQnK2sUJBWw0qNi4jG6YSnSc6z76JbIC6s09H0DwlJ8LndRq8kfJJkfg6ZB3k4gZCvOrtZBrr1MiNrM2ZAgNLKSYqGKsYIUJkLJUKex933y3A9saZBXQoCZAo7G6KVImPh77z5LXc5yguAaqwVMRFvhhHwHnouYmPzcngME3IZAZAnh5W8G1QHji3ZAtZAwrJpQZDZD")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "1159465090580320")
ADMIN_WHATSAPP = os.environ.get("ADMIN_WHATSAPP", "96876976795")

PENDING_ORDERS = {}


def init_db():
    conn = sqlite3.connect(DB_NAME)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        address TEXT,
        items TEXT,
        total REAL,
        status TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


def send_whatsapp_admin(order_data):

    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print("WhatsApp API not configured")
        return

    message = f"""
طلب جديد - الفرند بوتانيك

الاسم: {order_data.get('name', '')}
الهاتف: {order_data.get('phone', '')}
العنوان: {order_data.get('address', '')}

المنتجات:
{order_data.get('items', '')}

الإجمالي:
{order_data.get('total', '')}

الحالة:
{order_data.get('status', 'Pending')}
"""

    try:

        response = requests.post(
            f"https://graph.facebook.com/v23.0/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "to": ADMIN_WHATSAPP,
                "type": "text",
                "text": {
                    "body": message
                }
            },
            timeout=30
        )

        print("WhatsApp Response:", response.text)

    except Exception as e:
        print("WHATSAPP ERROR:", str(e))


def get_paypal_token():

    response = requests.post(
        PAYPAL_API + "/v1/oauth2/token",
        auth=(PAYPAL_CLIENT, PAYPAL_SECRET),
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data="grant_type=client_credentials"
    )

    response.raise_for_status()

    return response.json()["access_token"]


@app.route("/")
def home():
    return send_file("index.html")


@app.route("/admin")
def admin():
    return send_file("admin.html")


@app.route("/create-payment", methods=["POST"])
def create_payment():

    try:

        data = request.get_json()

        token = get_paypal_token()

        response = requests.post(
            PAYPAL_API + "/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {
                        "currency_code": "USD",
                        "value": str(data["total"])
                    }
                }]
            }
        )

        response.raise_for_status()

        order = response.json()

        PENDING_ORDERS[order["id"]] = data

        return jsonify({
            "id": order["id"]
        })

    except Exception as e:

        print("CREATE PAYMENT ERROR:", str(e))

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/capture-payment", methods=["POST"])
def capture_payment():

    try:

        body = request.get_json()

        order_id = body["orderID"]

        token = get_paypal_token()

        response = requests.post(
            f"{PAYPAL_API}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )

        response.raise_for_status()

        result = response.json()

        status = (
            result["purchase_units"][0]
            ["payments"]["captures"][0]
            ["status"]
        )

        if status == "COMPLETED":

            order = PENDING_ORDERS.get(order_id)

            if order:

                conn = sqlite3.connect(DB_NAME)

                conn.execute(
                    """
                    INSERT INTO orders
                    (
                        name,
                        phone,
                        address,
                        items,
                        total,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order.get("name"),
                        order.get("phone"),
                        order.get("address"),
                        order.get("items"),
                        float(order.get("total", 0)),
                        "Paid",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                )

                conn.commit()
                conn.close()

                try:
                    order["status"] = "Paid"
                    send_whatsapp_admin(order)
                except Exception as e:
                    print(e)

                if order_id in PENDING_ORDERS:
                    del PENDING_ORDERS[order_id]

            return jsonify({
                "paid": True
            })

        return jsonify({
            "paid": False
        })

    except Exception as e:

        print("CAPTURE PAYMENT ERROR:", str(e))

        return jsonify({
            "paid": False,
            "error": str(e)
        }), 500


@app.route("/save-order", methods=["POST"])
def save_order():

    data = request.get_json()

    payment_status = data.get(
        "status",
        "Phone Payment"
    )

    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        """
        INSERT INTO orders
        (
            name,
            phone,
            address,
            items,
            total,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("name"),
            data.get("phone"),
            data.get("address"),
            data.get("items"),
            float(data.get("total", 0)),
            payment_status,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()

    try:
        send_whatsapp_admin(data)
    except Exception as e:
        print(e)

    return jsonify({
        "success": True
    })


@app.route("/orders")
def orders():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return jsonify([
        {
            "id": row["id"],
            "name": row["name"],
            "phone": row["phone"],
            "address": row["address"],
            "items": row["items"],
            "total": row["total"],
            "status": row["status"],
            "created_at": row["created_at"]
        }
        for row in rows
    ])


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
        )
