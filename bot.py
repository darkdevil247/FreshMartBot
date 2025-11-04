import os
import requests
import time
import json
from datetime import datetime
import logging
import traceback
import csv
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ==================== CONFIGURATION ====================
print("🚀 Starting FreshMart Grocery Delivery Bot on Railway...")

# Get credentials from environment (Railway Environment Variables)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')
PORT = int(os.environ.get('PORT', 8000))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Check if environment variables are set
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN environment variable not set!")
    logger.error("💡 Set it in Railway → Variables tab")
    exit(1)

if not ADMIN_CHAT_ID:
    logger.warning("⚠️ ADMIN_CHAT_ID not set, admin features disabled")

# CSV file paths
ORDERS_CSV = 'orders.csv'
PRICES_CSV = 'prices.csv'

# Initialize CSV files
def initialize_csv_files():
    """Initialize CSV files with headers if they don't exist"""
    try:
        # Orders CSV
        if not os.path.exists(ORDERS_CSV):
            with open(ORDERS_CSV, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([
                    'Order ID', 'Order Date', 'Chat ID', 'Customer Name', 'Phone', 'Address',
                    'Items', 'Quantities', 'Subtotal', 'Delivery Fee', 'Total',
                    'Status', 'Special Instructions', 'Payment Method', 'Source'
                ])
            logger.info("✅ Orders CSV initialized!")
        
        # Prices CSV
        if not os.path.exists(PRICES_CSV):
            save_prices_to_csv()
            logger.info("✅ Prices CSV initialized!")
            
    except Exception as e:
        logger.error(f"❌ CSV initialization failed: {e}")

# Grocery database - Default items
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

def load_prices_from_csv():
    """Load prices from CSV file"""
    global grocery_categories
    try:
        if os.path.exists(PRICES_CSV):
            with open(PRICES_CSV, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                loaded_categories = {}
                
                for row in reader:
                    category = row['Category']
                    item_name = row['Item Name']
                    price = float(row['Price'])
                    unit = row['Unit']
                    
                    if category not in loaded_categories:
                        loaded_categories[category] = {}
                    
                    loaded_categories[category][item_name] = {
                        'price': price,
                        'unit': unit
                    }
                
                # Only update if we successfully loaded data
                if loaded_categories:
                    grocery_categories = loaded_categories
            
            logger.info("✅ Prices loaded from CSV successfully!")
            return True
    except Exception as e:
        logger.error(f"❌ Failed to load prices from CSV: {e}")
        # Keep existing categories if loading fails
    return False

def save_prices_to_csv():
    """Save current prices to CSV file"""
    try:
        with open(PRICES_CSV, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['Category', 'Item Name', 'Price', 'Unit'])
            
            for category, items in grocery_categories.items():
                for item_name, details in items.items():
                    writer.writerow([
                        category,
                        item_name,
                        details['price'],
                        details['unit']
                    ])
        
        logger.info("✅ Prices saved to CSV successfully!")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save prices to CSV: {e}")
        return False

# Initialize CSV files and load prices
initialize_csv_files()
load_prices_from_csv()

user_carts = {}
user_sessions = {}
order_tracking = {}
last_update_id = 0

# ==================== HEALTH CHECK ENDPOINT ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'FreshMart Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        logger.info("🩺 Health check from %s", self.address_string())

def start_health_check_server():
    """Start a simple HTTP server for health checks"""
    try:
        server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
        logger.info(f"🩺 Health check server running on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Health check server failed: {e}")

# ==================== ORDER TRACKING SYSTEM ====================
def generate_order_id():
    """Generate unique order ID"""
    return f"ORD{int(time.time())}"

def save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total, status="Pending"):
    """Save order to tracking system"""
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
    """Update order status and notify customer"""
    if order_id not in order_tracking:
        return False
    
    order = order_tracking[order_id]
    old_status = order['status']
    order['status'] = new_status
    order['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Update CSV file
    update_order_in_csv(order_id, 'Status', new_status)
    
    # Notify customer
    notify_customer_order_update(order_id, new_status, admin_note)
    
    logger.info(f"✅ Order {order_id} status updated: {old_status} → {new_status}")
    return True

def notify_customer_order_update(order_id, new_status, admin_note=""):
    """Notify customer about order status update"""
    order = order_tracking.get(order_id)
    if not order:
        return
    
    chat_id = order['chat_id']
    customer_name = order['customer_name']
    
    status_messages = {
        'Shipped': f"""🚚 Order Shipped! 

Hi {customer_name},

Your order #{order_id} is on the way! 

📦 Delivery Details:
• Order will arrive within 2 hours
• Please have ${order['total']:.2f} ready for cash payment
• Contact: 555-1234 if any issues

{f'📝 Note from store: {admin_note}' if admin_note else ''}

Thank you for choosing FreshMart! 🛒""",
        
        'Cancelled': f"""❌ Order Cancelled

Hi {customer_name},

We're sorry to inform you that your order #{order_id} has been cancelled.

{f'📝 Reason: {admin_note}' if admin_note else '📝 Reason: Unable to fulfill order at this time'}

We apologize for the inconvenience.

FreshMart Team 🛒""",
        
        'Delivered': f"""✅ Order Delivered! 

Hi {customer_name},

Your order #{order_id} has been successfully delivered!

Thank you for shopping with FreshMart! 🛒

We hope to serve you again soon! 🌟"""
    }
    
    message = status_messages.get(new_status)
    if message:
        send_message(chat_id, message)

# ==================== CSV ORDER MANAGEMENT ====================
def save_order_to_csv(chat_id, customer_name, phone, address, cart, special_instructions="", order_id=""):
    """Save order to CSV file"""
    logger.info(f"📦 Order received: {customer_name}, ${sum(details['price'] * details['quantity'] for details in cart.values()):.2f}")
    
    try:
        subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        total = subtotal + delivery_fee

        # Format items and quantities
        items_list = []
        quantities_list = []
        for item_name, details in cart.items():
            items_list.append(item_name)
            quantities_list.append(f"{details['quantity']} {details['unit']}")

        # Prepare order data
        order_data = [
            order_id,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(chat_id),
            customer_name,
            phone,
            address,
            ", ".join(items_list),
            ", ".join(quantities_list),
            f"{subtotal:.2f}",
            f"{delivery_fee:.2f}",
            f"{total:.2f}",
            "Pending",
            special_instructions,
            "Cash on Delivery",
            "Telegram Bot"
        ]

        # Append to CSV
        with open(ORDERS_CSV, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(order_data)
        
        logger.info("✅ Order saved to CSV successfully!")
        return True
        
    except Exception as e:
        logger.error(f"❌ CSV save failed: {e}")
        return False

def update_order_in_csv(order_id, field, new_value):
    """Update specific field of an order in CSV"""
    try:
        # Read all orders
        orders = []
        with open(ORDERS_CSV, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            orders = list(reader)
        
        # Find and update the order
        for order in orders:
            if order['Order ID'] == order_id:
                if field == 'Status':
                    order['Status'] = new_value
                break
        
        # Write back to CSV
        with open(ORDERS_CSV, 'w', newline='', encoding='utf-8') as file:
            if orders:
                writer = csv.DictWriter(file, fieldnames=orders[0].keys())
                writer.writeheader()
                writer.writerows(orders)
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update order in CSV: {e}")
        return False

def get_csv_file(file_type):
    """Get CSV file as bytes for download"""
    try:
        if file_type == 'orders':
            filename = ORDERS_CSV
        elif file_type == 'prices':
            filename = PRICES_CSV
        else:
            return None
        
        with open(filename, 'rb') as file:
            return file.read()
    except Exception as e:
        logger.error(f"❌ Failed to read CSV file: {e}")
        return None

# ==================== ADMIN ORDER MANAGEMENT ====================
def send_admin_order_notification(order_id, order_data):
    """Send new order notification to admin with action buttons"""
    if not ADMIN_CHAT_ID:
        return
        
    order_summary = create_admin_order_summary(order_id, order_data)
    
    admin_message = f"""🆕 NEW ORDER #{order_id}

{order_summary}

⏰ Order Time: {order_data['created_at']}
📊 Status: {order_data['status']}

Choose action:"""
    
    inline_keyboard = [
        [
            {'text': '🚚 Mark as Shipped', 'callback_data': f'ship_{order_id}'},
            {'text': '❌ Cancel Order', 'callback_data': f'cancel_{order_id}'}
        ],
        [
            {'text': '✅ Mark Delivered', 'callback_data': f'deliver_{order_id}'},
            {'text': '📋 View Details', 'callback_data': f'details_{order_id}'}
        ]
    ]
    
    send_message(ADMIN_CHAT_ID, admin_message, inline_keyboard=inline_keyboard)

def create_admin_order_summary(order_id, order_data):
    """Create order summary for admin"""
    cart = order_data['cart']
    items_text = ""
    for item_name, details in cart.items():
        items_text += f"• {item_name} - {details['quantity']} {details['unit']}\n"
    
    summary = f"""👤 Customer: {order_data['customer_name']}
📞 Phone: {order_data['phone']}
📍 Address: {order_data['address']}

📦 Order Items:
{items_text}
💰 Total: ${order_data['total']:.2f}"""
    
    return summary

def handle_admin_callback(chat_id, callback_data):
    """Handle admin action callbacks"""
    if not is_admin(chat_id):
        send_message(chat_id, "❌ Unauthorized access.")
        return
    
    try:
        if callback_data.startswith('ship_'):
            order_id = callback_data[5:]
            if update_order_status(order_id, 'Shipped', 'Your order is on the way!'):
                send_message(chat_id, f"✅ Order #{order_id} marked as shipped! Customer notified.")
            else:
                send_message(chat_id, f"❌ Order #{order_id} not found.")
                
        elif callback_data.startswith('cancel_'):
            order_id = callback_data[7:]
            # Ask for cancellation reason
            user_sessions[chat_id] = {
                'step': 'awaiting_cancel_reason',
                'order_id': order_id
            }
            send_message(chat_id, f"📝 Please provide reason for cancelling order #{order_id}:")
            
        elif callback_data.startswith('deliver_'):
            order_id = callback_data[8:]
            if update_order_status(order_id, 'Delivered'):
                send_message(chat_id, f"✅ Order #{order_id} marked as delivered! Customer notified.")
            else:
                send_message(chat_id, f"❌ Order #{order_id} not found.")
                
        elif callback_data.startswith('details_'):
            order_id = callback_data[8:]
            order = order_tracking.get(order_id)
            if order:
                details = f"""📋 Order Details #{order_id}

Customer: {order['customer_name']}
Phone: {order['phone']}
Address: {order['address']}
Status: {order['status']}
Total: ${order['total']:.2f}
Created: {order['created_at']}
Updated: {order['updated_at']}

Items:"""
                for item_name, details in order['cart'].items():
                    details += f"\n• {item_name} - {order['cart'][item_name]['quantity']} {order['cart'][item_name]['unit']}"
                
                send_message(chat_id, details)
            else:
                send_message(chat_id, f"❌ Order #{order_id} not found.")
                
    except Exception as e:
        logger.error(f"❌ Admin callback error: {e}")
        send_message(chat_id, "❌ Error processing admin action.")

# ==================== ADMIN PRICE & INVENTORY MANAGEMENT ====================
def is_admin(chat_id):
    """Check if user is admin"""
    return ADMIN_CHAT_ID and str(chat_id) == ADMIN_CHAT_ID

def show_admin_panel(chat_id):
    """Show admin management panel"""
    if not is_admin(chat_id):
        send_message(chat_id, "❌ Unauthorized access.")
        return
    
    admin_menu = """👨‍💼 **ADMIN PANEL** - FreshMart Management

Choose an action:"""
    
    keyboard = [
        [{'text': '📊 View All Items'}, {'text': '💰 Update Price'}],
        [{'text': '🆕 Add New Item'}, {'text': '🗑️ Remove Item'}],
        [{'text': '📦 View Orders'}, {'text': '📥 Download Data'}],
        [{'text': '🔄 Refresh Menu'}, {'text': '🔙 Main Menu'}]
    ]
    
    send_message(chat_id, admin_menu, keyboard=keyboard)
    user_sessions[chat_id] = {'step': 'admin_panel'}

def show_download_panel(chat_id):
    """Show data download options"""
    if not is_admin(chat_id):
        return
    
    download_menu = """📥 **DOWNLOAD DATA**

Choose which data to download:"""
    
    inline_keyboard = [
        [
            {'text': '📦 Orders CSV', 'callback_data': 'download_orders'},
            {'text': '💰 Prices CSV', 'callback_data': 'download_prices'}
        ],
        [
            {'text': '📊 Both Files', 'callback_data': 'download_both'},
            {'text': '🔙 Back', 'callback_data': 'admin_back'}
        ]
    ]
    
    send_message(chat_id, download_menu, inline_keyboard=inline_keyboard)

def handle_admin_price_update(chat_id, item_name):
    """Start price update process for specific item"""
    if not is_admin(chat_id):
        return
    
    item_found = False
    for category, items in grocery_categories.items():
        if item_name in items:
            item_found = True
            current_price = items[item_name]['price']
            current_unit = items[item_name]['unit']
            
            user_sessions[chat_id] = {
                'step': 'awaiting_new_price',
                'editing_item': item_name,
                'item_category': category
            }
            
            send_message(chat_id, 
                f"💰 Updating Price for: {item_name}\n"
                f"Current Price: ${current_price}/{current_unit}\n\n"
                f"Please enter the new price (numbers only):"
            )
            break
    
    if not item_found:
        send_message(chat_id, "❌ Item not found!")

def handle_admin_new_item(chat_id):
    """Start process to add new item"""
    if not is_admin(chat_id):
        return
    
    user_sessions[chat_id] = {'step': 'awaiting_new_item_category'}
    
    categories_text = "📋 Select category for new item:"
    inline_keyboard = []
    
    for category in grocery_categories.keys():
        inline_keyboard.append([{
            'text': category,
            'callback_data': f"newitem_cat_{category}"
        }])
    
    inline_keyboard.append([{'text': '❌ Cancel', 'callback_data': 'admin_cancel'}])
    
    send_message(chat_id, categories_text, inline_keyboard=inline_keyboard)

def handle_admin_remove_item(chat_id):
    """Start process to remove item"""
    if not is_admin(chat_id):
        return
    
    user_sessions[chat_id] = {'step': 'awaiting_remove_item_category'}
    
    categories_text = "🗑️ Select category to remove item from:"
    inline_keyboard = []
    
    for category in grocery_categories.keys():
        inline_keyboard.append([{
            'text': category,
            'callback_data': f"remove_cat_{category}"
        }])
    
    inline_keyboard.append([{'text': '❌ Cancel', 'callback_data': 'admin_cancel'}])
    
    send_message(chat_id, categories_text, inline_keyboard=inline_keyboard)

def show_remove_items_from_category(chat_id, category):
    """Show items to remove from a category"""
    if category not in grocery_categories:
        send_message(chat_id, "❌ Category not found!")
        return
    
    items = grocery_categories[category]
    if not items:
        send_message(chat_id, f"❌ No items in {category} to remove!")
        return
    
    items_text = f"🗑️ Remove Item from {category}\n\nSelect item to remove:"
    inline_keyboard = []
    
    for item_name in items.keys():
        inline_keyboard.append([{
            'text': f"❌ {item_name}",
            'callback_data': f"remove_item_{item_name}"
        }])
    
    inline_keyboard.append([{'text': '🔙 Back', 'callback_data': 'admin_back'}])
    
    send_message(chat_id, items_text, inline_keyboard=inline_keyboard)

def remove_item_from_category(chat_id, item_name):
    """Remove item from category"""
    try:
        item_found = False
        category_to_remove_from = None
        
        for category, items in grocery_categories.items():
            if item_name in items:
                item_found = True
                category_to_remove_from = category
                break
        
        if item_found and category_to_remove_from:
            # Remove the item
            del grocery_categories[category_to_remove_from][item_name]
            
            # Save changes to CSV
            save_prices_to_csv()
            
            send_message(chat_id, f"✅ Successfully removed: {item_name} from {category_to_remove_from}")
            show_admin_panel(chat_id)
        else:
            send_message(chat_id, "❌ Item not found!")
            
    except Exception as e:
        logger.error(f"❌ Error removing item: {e}")
        send_message(chat_id, "❌ Error removing item. Please try again.")
        show_admin_panel(chat_id)

def show_all_items_admin(chat_id):
    """Show all items with prices to admin"""
    items_text = "📊 **CURRENT INVENTORY & PRICING**\n\n"
    
    for category, items in grocery_categories.items():
        items_text += f"**{category}**\n"
        for item_name, details in items.items():
            items_text += f"• {item_name} - ${details['price']}/{details['unit']}\n"
        items_text += "\n"
    
    send_message(chat_id, items_text)
    show_admin_panel(chat_id)

def show_items_for_price_update(chat_id):
    """Show items with inline buttons for price updates"""
    items_text = "💰 **UPDATE ITEM PRICES**\n\nSelect item to update:"
    
    inline_keyboard = []
    
    for category, items in grocery_categories.items():
        for item_name, details in items.items():
            button_text = f"{item_name} - ${details['price']}/{details['unit']}"
            inline_keyboard.append([{
                'text': button_text,
                'callback_data': f"update_price_{item_name}"
            }])
    
    inline_keyboard.append([{'text': '🔙 Back to Admin Panel', 'callback_data': 'admin_back'}])
    
    send_message(chat_id, items_text, inline_keyboard=inline_keyboard)

def show_all_orders_admin(chat_id):
    """Show all orders to admin"""
    if not order_tracking:
        send_message(chat_id, "📦 No orders yet!")
        show_admin_panel(chat_id)
        return
    
    orders_text = "📦 **ALL ORDERS**\n\n"
    
    for order_id, order in order_tracking.items():
        status_emoji = {
            'Pending': '⏳',
            'Shipped': '🚚',
            'Delivered': '✅',
            'Cancelled': '❌'
        }.get(order['status'], '📦')
        
        orders_text += f"{status_emoji} **Order #{order_id}**\n"
        orders_text += f"👤 {order['customer_name']}\n"
        orders_text += f"📞 {order['phone']}\n"
        orders_text += f"💰 ${order['total']:.2f}\n"
        orders_text += f"📊 {order['status']}\n"
        orders_text += f"🕐 {order['created_at']}\n\n"
    
    send_message(chat_id, orders_text)
    show_admin_panel(chat_id)

# ==================== MESSAGE HANDLING ====================
def send_message(chat_id, text, keyboard=None, inline_keyboard=None, parse_mode='HTML'):
    """Enhanced message sending with comprehensive error handling"""
    if not TELEGRAM_TOKEN:
        logger.error("❌ Cannot send message: TELEGRAM_TOKEN not set")
        return False
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id, 
            'text': text,
            'parse_mode': parse_mode
        }

        if keyboard:
            payload['reply_markup'] = json.dumps({
                'keyboard': keyboard,
                'resize_keyboard': True,
                'one_time_keyboard': False
            })
        elif inline_keyboard:
            payload['reply_markup'] = json.dumps({
                'inline_keyboard': inline_keyboard
            })

        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"❌ Error sending message: {e}")
        return False

def send_document(chat_id, document_data, filename):
    """Send document/file to user"""
    if not TELEGRAM_TOKEN:
        return False
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        
        files = {
            'document': (filename, document_data, 'text/csv')
        }
        
        data = {
            'chat_id': chat_id,
            'caption': f'📊 {filename} - Generated on {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        }
        
        response = requests.post(url, files=files, data=data, timeout=30)
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"❌ Error sending document: {e}")
        return False

# ==================== ORDER SUMMARY ====================
def create_enhanced_order_summary(customer_name, phone, address, cart, special_instructions=""):
    """Create a beautifully formatted order summary"""
    
    subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
    delivery_fee = 0 if subtotal >= 50 else 5
    total = subtotal + delivery_fee
    
    items_text = ""
    for item_name, details in cart.items():
        item_total = details['price'] * details['quantity']
        items_text += f"• {item_name}\n"
        items_text += f"  ${details['price']}/{details['unit']} × {details['quantity']} = ${item_total:.2f}\n"
    
    summary = f"""🛒 ORDER SUMMARY

👤 Customer Details:
Name: {customer_name}
Phone: {phone}
Address: {address}

📦 Order Items:
{items_text}
💵 Pricing:
Subtotal: ${subtotal:.2f}
Delivery Fee: ${delivery_fee:.2f}
{'🎉 FREE DELIVERY (Order > $50)' if delivery_fee == 0 else f'🎯 Add ${50 - subtotal:.2f} more for FREE delivery!'}
💰 TOTAL: ${total:.2f}

{f'📝 Special Instructions: {special_instructions}' if special_instructions else '📝 Special Instructions: None'}
    
⏰ Expected Delivery: Within 2 hours
🕐 Order Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""
    
    return summary, total

# ==================== CASH ON DELIVERY PROCESSING ====================
def process_cash_on_delivery(chat_id, customer_name, phone, address, cart, special_instructions):
    """Process cash on delivery order"""
    try:
        order_summary, total = create_enhanced_order_summary(
            customer_name, phone, address, cart, special_instructions
        )
        
        order_id = generate_order_id()
        save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total, "Pending")
        
        csv_success = save_order_to_csv(
            chat_id, customer_name, phone, address, cart, 
            special_instructions, order_id
        )
        
        if not csv_success:
            logger.warning("⚠️ Order saved locally but CSV save failed")
        
        confirmation = f"""✅ Order Confirmed! 🎉

Thank you {customer_name}!

{order_summary}

📦 Order ID: #{order_id}
💵 Payment: Cash on Delivery
💸 Please have ${total:.2f} ready for our delivery driver.

We'll notify you when your order ships! 🚚

We're preparing your fresh groceries! 🥦"""
        
        send_message(chat_id, confirmation)
        
        try:
            order_data = order_tracking[order_id]
            send_admin_order_notification(order_id, order_data)
        except Exception as e:
            logger.warning(f"⚠️ Admin notification failed: {e}")
        
        if chat_id in user_carts:
            user_carts[chat_id] = {}
        user_sessions[chat_id] = {'step': 'main_menu'}
        
        logger.info(f"✅ COD order completed successfully for {customer_name}, Order ID: {order_id}")
        return True
            
    except Exception as e:
        logger.error(f"❌ Critical error in COD order: {e}")
        logger.error(traceback.format_exc())
        send_message(chat_id, "❌ Sorry, there was an error processing your order. Please try again.")
        return False

# ==================== BOT HANDLERS ====================
def handle_start(chat_id):
    welcome = """🛒 Welcome to FreshMart Grocery Delivery! 🛒

🌟 <b>Fresh Groceries Delivered to Your Doorstep!</b> 🌟

🚚 Free Delivery on orders over $50
⏰ Delivery Hours: 7 AM - 10 PM Daily  
💰 Payment: Cash on Delivery Only
📦 Real-time Order Tracking
📊 Automatic Order Logging

<b>What would you like to do?</b>"""

    keyboard = [
        [{'text': '🛍️ Shop Groceries'}, {'text': '🛒 My Cart'}],
        [{'text': '📦 Track Order'}, {'text': '📞 Contact Store'}],
        [{'text': 'ℹ️ Store Info'}, {'text': '👨‍💼 Admin Panel'}]
    ]

    send_message(chat_id, welcome, keyboard=keyboard)
    user_sessions[chat_id] = {'step': 'main_menu'}

def show_categories(chat_id):
    categories = """📋 Grocery Categories

Choose a category to start shopping:"""

    keyboard = [
        [{'text': '🥦 Fresh Produce'}, {'text': '🥩 Meat & Poultry'}],
        [{'text': '🥛 Dairy & Eggs'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, categories, keyboard=keyboard)

def show_category_items(chat_id, category):
    if category not in grocery_categories:
        send_message(chat_id, "Category not found. Please choose from the menu.")
        return

    items_text = f"{category}\n\nSelect an item to add to cart:"
    items = grocery_categories[category]
    inline_keyboard = []

    for item_name, details in items.items():
        button_text = f"{item_name} - ${details['price']}/{details['unit']}"
        inline_keyboard.append([{
            'text': button_text,
            'callback_data': f"add_{item_name}"
        }])

    inline_keyboard.append([
        {'text': '🔙 Back to Categories', 'callback_data': 'back_categories'},
        {'text': '🛒 View Cart', 'callback_data': 'view_cart'}
    ])

    send_message(chat_id, items_text, inline_keyboard=inline_keyboard)
    user_sessions[chat_id] = {'step': 'browsing_category', 'current_category': category}

def handle_add_to_cart(chat_id, item_name):
    item_details = None
    for category, items in grocery_categories.items():
        if item_name in items:
            item_details = items[item_name]
            break

    if not item_details:
        send_message(chat_id, "Item not found. Please select from the menu.")
        return

    if chat_id not in user_carts:
        user_carts[chat_id] = {}

    if item_name in user_carts[chat_id]:
        user_carts[chat_id][item_name]['quantity'] += 1
    else:
        user_carts[chat_id][item_name] = {
            'price': item_details['price'],
            'unit': item_details['unit'],
            'quantity': 1
        }

    response = f"✅ Added to Cart!\n\n{item_name}\n${item_details['price']}/{item_details['unit']}\n\nWhat would you like to do next?"

    keyboard = [
        [{'text': '🛒 View Cart'}, {'text': '📋 Continue Shopping'}],
        [{'text': '🚚 Checkout'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, response, keyboard=keyboard)

def show_cart(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        cart_text = "🛒 Your cart is empty!\n\nStart shopping to add some delicious groceries! 🥦"
        keyboard = [
            [{'text': '🛍️ Start Shopping'}, {'text': '🔙 Main Menu'}]
        ]
        send_message(chat_id, cart_text, keyboard=keyboard)
        return

    cart = user_carts[chat_id]
    total = 0
    cart_text = "🛒 Your Shopping Cart\n\n"

    for item_name, details in cart.items():
        item_total = details['price'] * details['quantity']
        total += item_total
        cart_text += f"• {item_name}\n"
        cart_text += f"  ${details['price']}/{details['unit']} × {details['quantity']} = ${item_total:.2f}\n\n"

    cart_text += f"💵 Subtotal: ${total:.2f}"
    delivery_fee = 0 if total >= 50 else 5
    final_total = total + delivery_fee

    cart_text += f"\n🚚 Delivery: ${delivery_fee:.2f}"
    cart_text += f"\n💰 Total: ${final_total:.2f}"

    if total < 50:
        cart_text += f"\n\n🎯 Add ${50 - total:.2f} more for FREE delivery!"
    else:
        cart_text += f"\n\n✅ You qualify for FREE delivery!"

    keyboard = [
        [{'text': '➕ Add More Items'}, {'text': '🗑️ Clear Cart'}],
        [{'text': '🚚 Checkout Now'}, {'text': '📋 Continue Shopping'}],
        [{'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, cart_text, keyboard=keyboard)

def handle_checkout(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        send_message(chat_id, "Your cart is empty! Please add items first.")
        show_categories(chat_id)
        return

    send_message(chat_id, "🚚 Let's get your order delivered!\n\nPlease provide your full name:")
    user_sessions[chat_id] = {'step': 'awaiting_name'}

# ==================== FIXED GET_UPDATES FUNCTION ====================
def get_updates(offset=None):
    """Get updates from Telegram with proper error handling and connection recovery"""
    global last_update_id
    
    if not TELEGRAM_TOKEN:
        return None
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {'timeout': 30, 'offset': offset or last_update_id + 1}
        
    try:
        response = requests.post(url, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') and data.get('result'):
                updates = data['result']
                if updates:
                    last_update_id = max(update['update_id'] for update in updates)
                return data
            return None
        elif response.status_code == 409:
            logger.error("❌ Another bot instance is running! This instance will pause for 30 seconds.")
            logger.info("💡 Solution: Stop other instances or wait for Railway to stabilize")
            time.sleep(30)  # Wait 30 seconds before retrying
            return None
        else:
            logger.error(f"Telegram API error: {response.status_code}")
            time.sleep(5)  # Shorter wait for other errors
            return None
    except Exception as e:
        logger.error(f"get_updates error: {e}")
        time.sleep(5)
        return None

# ==================== FIXED CALLBACK HANDLER ====================
def handle_callback_query(chat_id, callback_data):
    try:
        logger.info(f"🔘 Processing callback: {callback_data}")
        
        if callback_data.startswith('add_'):
            item_name = callback_data[4:]
            handle_add_to_cart(chat_id, item_name)
            
        elif callback_data == 'back_categories':
            show_categories(chat_id)
            
        elif callback_data == 'view_cart':
            show_cart(chat_id)
            
        elif callback_data.startswith(('ship_', 'cancel_', 'deliver_', 'details_')):
            handle_admin_callback(chat_id, callback_data)
            
        elif callback_data.startswith('update_price_'):
            item_name = callback_data[13:]
            handle_admin_price_update(chat_id, item_name)
            
        elif callback_data.startswith('newitem_cat_'):
            category = callback_data[12:]
            # Store the category in session with proper error handling
            if chat_id not in user_sessions:
                user_sessions[chat_id] = {}
            user_sessions[chat_id].update({
                'step': 'awaiting_new_item_name',
                'new_item_category': category
            })
            send_message(chat_id, f"📋 Category: {category}\n\nPlease enter the new item name:")
            
        elif callback_data.startswith('remove_cat_'):
            category = callback_data[11:]
            show_remove_items_from_category(chat_id, category)
            
        elif callback_data.startswith('remove_item_'):
            item_name = callback_data[12:]
            remove_item_from_category(chat_id, item_name)
            
        elif callback_data == 'admin_back' or callback_data == 'admin_cancel':
            show_admin_panel(chat_id)
            
        elif callback_data.startswith('download_'):
            handle_download_request(chat_id, callback_data)
            
        else:
            logger.warning(f"❌ Unknown callback data: {callback_data}")
            send_message(chat_id, "❌ Unknown action. Please try again.")
            
    except Exception as e:
        logger.error(f"❌ Callback query error: {e}")
        logger.error(traceback.format_exc())
        send_message(chat_id, "❌ Sorry, an error occurred. Please try again.")

def handle_download_request(chat_id, callback_data):
    """Handle CSV download requests"""
    if not is_admin(chat_id):
        return
    
    try:
        if callback_data == 'download_orders':
            file_data = get_csv_file('orders')
            if file_data:
                send_document(chat_id, file_data, 'freshmart_orders.csv')
            else:
                send_message(chat_id, "❌ Failed to generate orders CSV")
                
        elif callback_data == 'download_prices':
            file_data = get_csv_file('prices')
            if file_data:
                send_document(chat_id, file_data, 'freshmart_prices.csv')
            else:
                send_message(chat_id, "❌ Failed to generate prices CSV")
                
        elif callback_data == 'download_both':
            orders_data = get_csv_file('orders')
            prices_data = get_csv_file('prices')
            
            if orders_data:
                send_document(chat_id, orders_data, 'freshmart_orders.csv')
            if prices_data:
                send_document(chat_id, prices_data, 'freshmart_prices.csv')
                
            if not orders_data and not prices_data:
                send_message(chat_id, "❌ Failed to generate CSV files")
        
    except Exception as e:
        logger.error(f"❌ Download error: {e}")
        send_message(chat_id, "❌ Error generating download files")

# ==================== FIXED MESSAGE HANDLER ====================
def handle_message(chat_id, text):
    try:
        logger.info(f"📩 Processing message: {text}")
        
        if text == '/start':
            handle_start(chat_id)
            
        elif text == '🛍️ Shop Groceries':
            show_categories(chat_id)
            
        elif text == '🛒 My Cart':
            show_cart(chat_id)
            
        elif text == '📦 Track Order':
            user_orders = []
            for order_id, order in order_tracking.items():
                if order['chat_id'] == chat_id:
                    user_orders.append((order_id, order))
            
            if user_orders:
                track_text = "📦 Your Orders:\n\n"
                for order_id, order in user_orders[-5:]:
                    status_emoji = {
                        'Pending': '⏳',
                        'Shipped': '🚚', 
                        'Delivered': '✅',
                        'Cancelled': '❌'
                    }.get(order['status'], '📦')
                    
                    track_text += f"{status_emoji} Order #{order_id}\n"
                    track_text += f"Status: {order['status']}\n"
                    track_text += f"Total: ${order['total']:.2f}\n"
                    track_text += f"Date: {order['created_at']}\n\n"
                send_message(chat_id, track_text)
            else:
                send_message(chat_id, "📦 You don't have any orders yet. Start shopping! 🛍️")
                
        elif text == '🔙 Main Menu':
            handle_start(chat_id)
            
        elif text == '📋 Continue Shopping':
            show_categories(chat_id)
            
        elif text == '➕ Add More Items':
            show_categories(chat_id)
            
        elif text == '🗑️ Clear Cart':
            if chat_id in user_carts:
                user_carts[chat_id] = {}
            send_message(chat_id, "🛒 Your cart has been cleared!")
            show_categories(chat_id)
            
        elif text == '🚚 Checkout Now' or text == '🚚 Checkout':
            handle_checkout(chat_id)
            
        elif text in grocery_categories:
            show_category_items(chat_id, text)
            
        # ADMIN COMMANDS
        elif text == '/admin' or text == '👨‍💼 Admin Panel':
            show_admin_panel(chat_id)
            
        elif text == '📊 View All Items' and is_admin(chat_id):
            show_all_items_admin(chat_id)
            
        elif text == '💰 Update Price' and is_admin(chat_id):
            show_items_for_price_update(chat_id)
            
        elif text == '🆕 Add New Item' and is_admin(chat_id):
            handle_admin_new_item(chat_id)
            
        elif text == '🗑️ Remove Item' and is_admin(chat_id):
            handle_admin_remove_item(chat_id)
            
        elif text == '📦 View Orders' and is_admin(chat_id):
            show_all_orders_admin(chat_id)
            
        elif text == '📥 Download Data' and is_admin(chat_id):
            show_download_panel(chat_id)
            
        elif text == '🔄 Refresh Menu' and is_admin(chat_id):
            load_prices_from_csv()
            send_message(chat_id, "✅ Menu refreshed with latest prices!")
            show_admin_panel(chat_id)
            
        # ORDER SESSION HANDLING
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_name':
            customer_name = text
            user_sessions[chat_id] = {'step': 'awaiting_phone', 'customer_name': customer_name}
            send_message(chat_id, f"👋 Thanks {customer_name}! Now please provide your phone number for delivery updates:")
            
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_phone':
            user_phone = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_sessions[chat_id] = {'step': 'awaiting_address', 'customer_name': customer_name, 'phone': user_phone}
            send_message(chat_id, "📦 Great! Now please provide your delivery address:")
            
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_address':
            user_address = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_phone = user_sessions[chat_id]['phone']
            user_sessions[chat_id] = {'step': 'awaiting_instructions', 'customer_name': customer_name, 'phone': user_phone, 'address': user_address}
            send_message(chat_id, "📝 Any special delivery instructions?\n\n(e.g., 'Leave at door', 'Call before delivery', or type 'None'):")
            
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_instructions':
            special_instructions = text if text.lower() != 'none' else ""
            session_data = user_sessions[chat_id]
            process_cash_on_delivery(
                chat_id,
                session_data['customer_name'],
                session_data['phone'],
                session_data['address'],
                user_carts[chat_id],
                special_instructions
            )
            
        # ADMIN SESSION HANDLING
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_cancel_reason':
            order_id = user_sessions[chat_id].get('order_id')
            if order_id and update_order_status(order_id, 'Cancelled', text):
                send_message(chat_id, f"✅ Order #{order_id} cancelled! Customer notified with your reason.")
            else:
                send_message(chat_id, f"❌ Failed to cancel order #{order_id}")
            user_sessions[chat_id] = {'step': 'admin_panel'}
            
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_new_price':
            try:
                new_price = float(text)
                session_data = user_sessions[chat_id]
                item_name = session_data['editing_item']
                category = session_data['item_category']
                grocery_categories[category][item_name]['price'] = new_price
                save_prices_to_csv()
                send_message(chat_id, 
                    f"✅ Price updated!\n\n"
                    f"📦 {item_name}\n"
                    f"💰 New Price: ${new_price}/{grocery_categories[category][item_name]['unit']}"
                )
                show_admin_panel(chat_id)
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid number (e.g., 12.99)")
            except Exception as e:
                logger.error(f"❌ Error updating price: {e}")
                send_message(chat_id, "❌ Error updating price. Please try again.")
                show_admin_panel(chat_id)
                
        # FIXED: Add New Item session handling with proper session management
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_new_item_name':
            item_name = text
            # Ensure session exists and update it properly
            if chat_id not in user_sessions:
                user_sessions[chat_id] = {}
            user_sessions[chat_id].update({
                'step': 'awaiting_new_item_price',
                'new_item_name': item_name
            })
            send_message(chat_id, f"📦 Item Name: {item_name}\n\nPlease enter the price (e.g., 12.99):")
            
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_new_item_price':
            try:
                item_price = float(text)
                session_data = user_sessions[chat_id]
                # Check if required session data exists
                if 'new_item_name' not in session_data or 'new_item_category' not in session_data:
                    logger.error(f"❌ Missing session data: {session_data}")
                    send_message(chat_id, "❌ Session expired. Please start over.")
                    show_admin_panel(chat_id)
                    return
                    
                item_name = session_data['new_item_name']
                category = session_data['new_item_category']
                # Update session properly
                user_sessions[chat_id].update({
                    'step': 'awaiting_new_item_unit',
                    'new_item_name': item_name,
                    'new_item_price': item_price,
                    'new_item_category': category
                })
                send_message(chat_id, 
                    f"📦 Item: {item_name}\n"
                    f"💰 Price: ${item_price}\n\n"
                    f"Please enter the unit (e.g., kg, liter, pack, dozen):"
                )
            except ValueError:
                send_message(chat_id, "❌ Please enter a valid price number")
            except Exception as e:
                logger.error(f"❌ Error setting price: {e}")
                logger.error(f"❌ Session data: {user_sessions.get(chat_id, {})}")
                send_message(chat_id, "❌ Error setting price. Please try again.")
                show_admin_panel(chat_id)
                
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_new_item_unit':
            try:
                unit = text
                session_data = user_sessions[chat_id]
                # Check if all required session data exists
                required_fields = ['new_item_name', 'new_item_price', 'new_item_category']
                if not all(field in session_data for field in required_fields):
                    logger.error(f"❌ Missing session data: {session_data}")
                    send_message(chat_id, "❌ Session expired. Please start over.")
                    show_admin_panel(chat_id)
                    return
                    
                item_name = session_data['new_item_name']
                item_price = session_data['new_item_price']
                category = session_data['new_item_category']
                
                # Add the new item to the category
                if category not in grocery_categories:
                    grocery_categories[category] = {}
                
                grocery_categories[category][item_name] = {
                    'price': item_price,
                    'unit': unit
                }
                
                # Save to CSV
                save_prices_to_csv()
                
                send_message(chat_id,
                    f"✅ New Item Added!\n\n"
                    f"📦 {item_name}\n"
                    f"💰 ${item_price}/{unit}\n"
                    f"📋 Category: {category}"
                )
                show_admin_panel(chat_id)
            except Exception as e:
                logger.error(f"❌ Error adding new item: {e}")
                logger.error(traceback.format_exc())
                logger.error(f"❌ Session data: {user_sessions.get(chat_id, {})}")
                send_message(chat_id, "❌ Error adding new item. Please try again.")
                show_admin_panel(chat_id)
                
        elif text == '📞 Contact Store':
            send_message(chat_id, "📞 FreshMart Contact Info:\n\n🏪 Store: FreshMart Grocery\n📞 Phone: 555-1234\n📍 Address: 123 Main Street\n⏰ Hours: 7 AM - 10 PM Daily")
            
        elif text == 'ℹ️ Store Info':
            store_info = f"""🏪 FreshMart Grocery

🌟 Your trusted local grocery store!

🚚 Free delivery on orders over $50
💰 Cash on delivery only
⏰ Fast 2-hour delivery
🥦 Fresh produce daily
📞 Call: 555-1234

📊 All orders logged to CSV files
📥 Admin can download data anytime"""
            send_message(chat_id, store_info)
            
        else:
            handle_start(chat_id)

    except Exception as e:
        logger.error(f"❌ Error handling message: {e}")
        logger.error(traceback.format_exc())
        send_message(chat_id, "❌ Sorry, an error occurred. Please try again.")
        handle_start(chat_id)

# ==================== MAIN FUNCTION ====================
def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ CRITICAL: TELEGRAM_TOKEN environment variable not set!")
        exit(1)

    # Start health check server in a separate thread
    try:
        health_thread = threading.Thread(target=start_health_check_server, daemon=True)
        health_thread.start()
        logger.info(f"🩺 Health check server started on port {PORT}")
    except Exception as e:
        logger.warning(f"⚠️ Health check server failed: {e}")

    logger.info("🚀 FreshMart Grocery Bot Started on Railway!")
    logger.info("📊 Features: Order Tracking, Admin Controls, Real-time Updates")
    logger.info("💰 Payment: Cash on Delivery Only")
    logger.info("💾 Data Storage: CSV Files")
    logger.info("📥 Admin Features: Price Management, Inventory Control, Data Download")
    logger.info("🔄 Error Recovery: Auto-handles Telegram API conflicts")
    logger.info("📱 Ready to take orders!")

    # Main loop with error recovery
    error_count = 0
    max_errors = 10
    
    while True:
        try:
            updates = get_updates()

            if updates and 'result' in updates:
                for update in updates['result']:
                    if 'message' in update and 'text' in update['message']:
                        chat_id = update['message']['chat']['id']
                        text = update['message']['text']
                        logger.info(f"📩 Message from {chat_id}: {text}")
                        handle_message(chat_id, text)

                    elif 'callback_query' in update:
                        callback = update['callback_query']
                        chat_id = callback['message']['chat']['id']
                        callback_data = callback['data']
                        logger.info(f"🔘 Callback from {chat_id}: {callback_data}")
                        handle_callback_query(chat_id, callback_data)
                
                error_count = 0  # Reset error count on successful update
            else:
                time.sleep(1)
                
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Main loop error #{error_count}: {e}")
            logger.error(traceback.format_exc())
            
            if error_count > max_errors:
                logger.error("🔄 Too many consecutive errors, waiting 60 seconds before continuing...")
                time.sleep(60)
                error_count = 0
                
            time.sleep(5)

if __name__ == '__main__':
    main()
