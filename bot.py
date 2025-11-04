import os
import requests
import time
import json
from datetime import datetime
import logging
import traceback
from flask import Flask, request

# ==================== SAFE CONFIGURATION ====================
print("🛒 Starting FreshMart Grocery Delivery Bot...")

# Environment variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SHEET_URL = os.environ.get('SHEET_URL')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Validate environment variables
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN environment variable not set!")
    exit(1)

if not ADMIN_CHAT_ID:
    logger.warning("⚠️ ADMIN_CHAT_ID not set, admin features disabled")

if not SHEET_URL:
    logger.warning("⚠️ SHEET_URL not set, Google Sheets disabled")

# Google Sheets setup
sheet = None
try:
    if SHEET_URL:
        import gspread
        from google.oauth2.service_account import Credentials
        
        service_account_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            try:
                creds_dict = json.loads(service_account_json)
                scope = ['https://www.googleapis.com/auth/spreadsheets']
                creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
                client = gspread.authorize(creds)
                spreadsheet = client.open_by_url(SHEET_URL)
                sheet = spreadsheet.sheet1
                sheet.get_all_records()
                logger.info("✅ Google Sheets connected successfully!")
            except Exception as e:
                logger.error(f"❌ Google Sheets authentication failed: {e}")
        else:
            logger.warning("⚠️ GOOGLE_SERVICE_ACCOUNT_JSON not provided - Google Sheets disabled")
except ImportError:
    logger.error("❌ gspread not installed. Install with: pip install gspread")
except Exception as e:
    logger.error(f"❌ Google Sheets setup failed: {e}")

# Initialize sheet headers if needed
if sheet:
    try:
        existing_headers = sheet.row_values(1)
        expected_headers = [
            'Order Date', 'Chat ID', 'Customer Name', 'Phone', 'Address',
            'Items', 'Quantities', 'Subtotal', 'Delivery Fee', 'Total',
            'Status', 'Special Instructions', 'Payment Method', 'Source', 'Order ID'
        ]
        if not existing_headers or existing_headers[0] != 'Order Date':
            sheet.insert_row(expected_headers, 1)
            logger.info("✅ Google Sheets headers initialized!")
    except Exception as e:
        logger.error(f"❌ Failed to initialize sheet headers: {e}")

# ==================== GROCERY DATA ====================
grocery_categories = {
    '🥦 Fresh Produce': {
        '🍎 Apples': {'price': 3.99, 'unit': 'kg'},
        '🍌 Bananas': {'price': 1.99, 'unit': 'kg'},
        '🥕 Carrots': {'price': 2.49, 'unit': 'kg'},
        '🥬 Spinach': {'price': 4.99, 'unit': 'bunch'},
        '🍅 Tomatoes': {'price': 3.49, 'unit': 'kg'}
    },
    '🥩 Meat & Poultry': {
        '🍗 Chicken Breast': {'price': 12.99, 'unit': 'kg'},
        '🥩 Beef Steak': {'price': 24.99, 'unit': 'kg'},
        '🐟 Salmon Fillet': {'price': 18.99, 'unit': 'kg'},
        '🥓 Bacon': {'price': 8.99, 'unit': 'pack'}
    },
    '🥛 Dairy & Eggs': {
        '🥛 Milk': {'price': 2.99, 'unit': 'liter'},
        '🧀 Cheese': {'price': 6.99, 'unit': 'block'},
        '🍳 Eggs': {'price': 4.99, 'unit': 'dozen'},
        '🧈 Butter': {'price': 3.99, 'unit': 'block'}
    }
}

user_carts = {}
user_sessions = {}
order_tracking = {}
last_update_id = 0

# ==================== HELPER FUNCTIONS ====================
def generate_order_id():
    return f"ORD{int(time.time())}"

def send_message(chat_id, text, keyboard=None, inline_keyboard=None, parse_mode='HTML'):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if keyboard:
            payload['reply_markup'] = json.dumps({'keyboard': keyboard, 'resize_keyboard': True, 'one_time_keyboard': False})
        elif inline_keyboard:
            payload['reply_markup'] = json.dumps({'inline_keyboard': inline_keyboard})
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending message: {e}")
        return False

def save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total, status="Pending"):
    order_tracking[order_id] = {
        'chat_id': chat_id,
        'customer_name': customer_name,
        'phone': phone,
        'address': address,
        'cart': cart.copy(),
        'total': total,
        'status': status,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return order_id

def update_order_status(order_id, new_status, admin_note=""):
    if order_id not in order_tracking:
        return False
    order = order_tracking[order_id]
    old_status = order['status']
    order['status'] = new_status
    order['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Update Google Sheet
    if sheet:
        try:
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if record.get('Order ID') == order_id:
                    sheet.update_cell(i, 11, new_status)
                    break
        except Exception as e:
            logger.error(f"❌ Failed to update Google Sheets: {e}")

    # Notify user
    send_message(order['chat_id'], f"📦 Your order {order_id} status changed: {new_status}\n{admin_note}")
    logger.info(f"✅ Order {order_id} status updated: {old_status} -> {new_status}")
    return True

def create_order_summary(customer_name, phone, address, cart, special_instructions=""):
    subtotal = sum(details['price']*details['quantity'] for details in cart.values())
    delivery_fee = 0 if subtotal >= 50 else 5
    total = subtotal + delivery_fee
    items_text = "\n".join([f"{k} x {v['quantity']} = ${v['price']*v['quantity']:.2f}" for k,v in cart.items()])
    summary = f"""🛒 ORDER SUMMARY

👤 {customer_name}
📞 {phone}
📍 {address}

📦 Items:
{items_text}

💵 Subtotal: ${subtotal:.2f}
🚚 Delivery: ${delivery_fee:.2f}
💰 Total: ${total:.2f}

📝 Instructions: {special_instructions or 'None'}
⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    return summary, total

def save_order_to_sheet(chat_id, customer_name, phone, address, cart, special_instructions="", order_id=""):
    if not sheet:
        return True
    try:
        subtotal = sum(details['price']*details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        total = subtotal + delivery_fee
        items_list = [k for k in cart.keys()]
        quantities_list = [f"{v['quantity']} {v['unit']}" for v in cart.values()]
        order_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(chat_id), customer_name, phone, address,
            ", ".join(items_list), ", ".join(quantities_list),
            f"${subtotal:.2f}", f"${delivery_fee:.2f}", f"${total:.2f}", "Pending",
            special_instructions, "Cash on Delivery", "Telegram Bot", order_id
        ]
        sheet.append_row(order_data)
        return True
    except Exception as e:
        logger.error(f"❌ Google Sheets save failed: {e}")
        return False

def process_cod_order(chat_id, customer_name, phone, address, cart, special_instructions):
    summary, total = create_order_summary(customer_name, phone, address, cart, special_instructions)
    order_id = generate_order_id()
    save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total, "Pending")
    save_order_to_sheet(chat_id, customer_name, phone, address, cart, special_instructions, order_id)
    send_message(chat_id, f"✅ Order Confirmed!\n\n{summary}\nOrder ID: {order_id}\nPayment: Cash on Delivery")
    # Clear cart
    user_carts[chat_id] = {}
    user_sessions[chat_id] = {'step':'main_menu'}
    # Notify admin
    send_admin_orders(ADMIN_CHAT_ID)
    return True

# ==================== ADMIN DASHBOARD ====================
def send_admin_orders(chat_id):
    if not order_tracking:
        send_message(chat_id, "📭 No orders yet.")
        return
    for order_id, order in order_tracking.items():
        send_message(chat_id, f"🆔 {order_id} | Status: {order['status']}", inline_keyboard=[
            [
                {'text':'View','callback_data':f'admin_view_{order_id}'},
                {'text':'Ship','callback_data':f'admin_ship_{order_id}'},
                {'text':'Deliver','callback_data':f'admin_deliver_{order_id}'},
                {'text':'Cancel','callback_data':f'admin_cancel_{order_id}'}
            ]
        ])

def handle_admin_callback(chat_id, callback_data):
    if not ADMIN_CHAT_ID or str(chat_id) != ADMIN_CHAT_ID:
        send_message(chat_id, "❌ Unauthorized access.")
        return
    parts = callback_data.split('_')
    action = parts[1]  # view, ship, deliver, cancel
    order_id = parts[2]
    if order_id not in order_tracking:
        send_message(chat_id, f"❌ Order {order_id} not found.")
        return
    order = order_tracking[order_id]

    if action == 'view':
        items_text = "\n".join([f"{k} x {v['quantity']} = ${v['price']*v['quantity']:.2f}" for k,v in order['cart'].items()])
        send_message(chat_id, f"📝 Order {order_id} Details\nCustomer: {order['customer_name']}\nPhone: {order['phone']}\nAddress: {order['address']}\nItems:\n{items_text}\nTotal: ${order['total']:.2f}\nStatus: {order['status']}")
    elif action == 'ship':
        update_order_status(order_id, 'Shipped', 'Your order is on the way!')
    elif action == 'deliver':
        update_order_status(order_id, 'Delivered')
    elif action == 'cancel':
        update_order_status(order_id, 'Cancelled', 'Order cancelled by admin')

# ==================== FLASK WEBHOOK ====================
app = Flask(__name__)

@app.route(f"/webhook/{TELEGRAM_TOKEN}", methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if 'message' in update:
            chat_id = update['message']['chat']['id']
            text = update['message'].get('text')
            if text:
                handle_user_message(chat_id, text)
        elif 'callback_query' in update:
            chat_id = update['callback_query']['message']['chat']['id']
            callback_data = update['callback_query']['data']
            if callback_data.startswith('admin_'):
                handle_admin_callback(chat_id, callback_data)
            else:
                handle_user_callback(chat_id, callback_data)
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return {"ok": False}

# ==================== USER MESSAGE HANDLERS ====================
def handle_user_message(chat_id, text):
    try:
        if text == '/start':
            if str(chat_id) == ADMIN_CHAT_ID:
                keyboard = [
                    [{'text':'📊 View Orders'}]
                ]
                send_message(chat_id, "🛠 Admin Dashboard", keyboard=keyboard)
            else:
                send_main_menu(chat_id)
        elif text == '📊 View Orders' and str(chat_id) == ADMIN_CHAT_ID:
            send_admin_orders(chat_id)
        else:
            # Add your existing shopping/cart/checkout message handlers here
            pass
    except Exception as e:
        logger.error(f"❌ Error handling user message: {e}")

def handle_user_callback(chat_id, callback_data):
    # Add your existing inline button logic for shopping/cart here
    pass

def send_main_menu(chat_id):
    welcome = """🛒 Welcome to FreshMart Grocery Delivery!"""
    keyboard = [
        [{'text': '🛍️ Shop Groceries'}, {'text': '🛒 My Cart'}],
        [{'text': '📦 Track Order'}, {'text': '📞 Contact Store'}],
        [{'text': 'ℹ️ Store Info'}]
    ]
    send_message(chat_id, welcome, keyboard=keyboard)
    user_sessions[chat_id] = {'step':'main_menu'}

# ==================== RUN FLASK ====================
if __name__ == "__main__":
    logger.info("🚀 FreshMart Bot started with Flask webhook!")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
