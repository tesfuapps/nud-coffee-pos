import asyncio
import logging
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import config
import database

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Health Check Server to satisfy Render port scan ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress logging health checks to keep logs clean
        pass

def run_health_check_server():
    import os
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Starting health check server on port {port}...")
    try:
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health check server error: {e}")

# --- Helper to check Admin status ---
def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS

# --- Main Entry Point ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_id = user.id
    name = (user.first_name or user.username or "USER").upper()
    
    if is_admin(user_id):
        reply_keyboard = [
            ['📝 Create New Order', '💳 Pay Open Order'],
            ['📋 View Orders', '📈 Sales Result'],
            ['⚙️ Admin Management']
        ]
        await update.message.reply_text(
            f"👋 WELCOME BACK, ADMIN {name}!\nSelect an option from the panel below:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
    else:
        reply_keyboard = [['📝 Create New Order']]
        await update.message.reply_text(
            f"👋 WELCOME TO NUD COFFEE {name}!\nPress the button below to start your order:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
    return ConversationHandler.END

# --- Order Placement Flow ---
async def register_sale_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Clear any leftover context data
    context.user_data.clear()
    await update.message.reply_text(
        "👤 Please enter the Customer's Name or Table Number:\n(Or type /cancel to stop)",
        reply_markup=ReplyKeyboardRemove()
    )
    return config.CUSTOMER_NAME

async def customer_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['customer_name'] = update.message.text.strip()
    
    # Fetch categories from database
    categories = await database.get_categories_from_db()
    if not categories:
        await update.message.reply_text("❌ No categories found. Admin must add menu categories first!")
        return ConversationHandler.END
        
    # Build keyboard from category list
    reply_keyboard = [[cat] for cat in categories]
    reply_keyboard.append(['/cancel'])
    
    await update.message.reply_text(
        "📂 Select an item *category*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.SELECT_CATEGORY

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category_name = update.message.text.strip()
    
    # Verify category exists
    categories = await database.get_categories_from_db()
    if category_name not in categories:
        await update.message.reply_text("❌ Invalid category. Please choose from the list.")
        return config.SELECT_CATEGORY
    
    context.user_data['selected_category'] = category_name
    
    # Fetch items for this category
    items = await database.get_items_by_category(category_name)
    if not items:
        await update.message.reply_text(
            f"❌ No items found under *{category_name}*. Admin must add items to this category first!",
            parse_mode="Markdown"
        )
        return config.SELECT_CATEGORY
    
    reply_keyboard = [[item[0]] for item in items]  # item[0] = item_name
    reply_keyboard.append(['/cancel'])
    
    await update.message.reply_text(
        f"☕ Select an item from *{category_name}*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.SELECT_ITEM

async def item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_name = update.message.text.strip()
    category = context.user_data.get('selected_category')
    
    # Look up the item within the selected category
    items_in_cat = await database.get_items_by_category(category) if category else []
    selected_item = next((i for i in items_in_cat if i[0] == item_name), None)
    
    if not selected_item:
        await update.message.reply_text("❌ Invalid selection. Please choose an item from the keyboard menu.")
        return config.SELECT_ITEM
        
    context.user_data['selected_item'] = {'name': selected_item[0], 'price': selected_item[1]}
    
    await update.message.reply_text(
        f"🔢 Enter the quantity for {item_name}:",
        reply_markup=ReplyKeyboardRemove()
    )
    return config.QUANTITY

async def quantity_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    qty_text = update.message.text.strip()
    if not qty_text.isdigit() or int(qty_text) <= 0:
        await update.message.reply_text("❌ Please enter a valid number greater than 0:")
        return config.QUANTITY
        
    context.user_data['quantity'] = int(qty_text)
    item = context.user_data['selected_item']
    total = item['price'] * int(qty_text)
    
    # Save current item summary text
    summary = f"• {item['name']} x{qty_text} ({total:,} ETB)"
    context.user_data['cart_summary'] = summary
    context.user_data['total_amount'] = total

    reply_keyboard = [['🛒 Confirm Order', '/cancel']]
    await update.message.reply_text(
        f"📋 **Order Summary Check**\n\n"
        f"👤 Customer: {context.user_data['customer_name']}\n"
        f"{summary}\n\n"
        f"💰 Total Cost: **{total:,} ETB**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.CART_OPTIONS

async def process_cart_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    
    if choice == '🛒 Confirm Order':
        cust_name = context.user_data['customer_name']
        item = context.user_data['selected_item']
        qty = context.user_data['quantity']
        total = context.user_data['total_amount']
        waiter_name = update.effective_user.first_name or "Waiter"
        
        cart = [{'item': item['name'], 'qty': qty, 'price': item['price']}]
        order_id, timestamp = await database.save_order_to_db(cust_name, waiter_name, cart, total)
        
        # Beautified Alert notification
        alert_msg = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔔 **NEW ORDER PLACED**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Order ID:** `{order_id}`\n"
            f"👤 **Customer/Table:** `{cust_name}`\n"
            f"──────────────────────\n"
            f"📦 **Items:**\n"
            f" • `{item['name']}` x `{qty}`\n"
            f"💰 **Total Amount:** `{total:,} ETB`\n"
            f"──────────────────────\n"
            f"⚡ **Status:** 🔴 **UNPAID / OPEN**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        keyboard = [[InlineKeyboardButton("☕ Accept Order", callback_data=f"accept_{order_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        group_msg_sent = False
        push_error = ""
        try:
            msg = await context.bot.send_message(
                chat_id=config.GROUP_CHAT_ID, 
                text=alert_msg, 
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            group_msg_sent = True
            try:
                await database.update_group_msg_id(order_id, msg.message_id)
            except Exception as e:
                logger.error(f"Order saved & pushed to group, but failed to store group_msg_id: {e}")
        except Exception as e:
            push_error = str(e)
            logger.error(f"Failed to send order alert to group chat: {e}")
        
        # Confirmation to operator
        if group_msg_sent:
            await update.message.reply_text(
                f"✅ Order `{order_id}` saved successfully and pushed to group queue!",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Order `{order_id}` saved locally, but failed to push to the Telegram group chat.\n"
                f"Error: `{push_error}`\n"
                f"Please ensure the bot is added to the group and the group ID is correct.",
                parse_mode="Markdown"
            )
        return await start(update, context)
        
    return config.CART_OPTIONS

# --- Order Closing / Payment Flow ---
async def pay_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Access Denied.")
        return ConversationHandler.END
        
    rows = await database.get_open_orders()
    
    if not rows:
        await update.message.reply_text("🎉 No open/unpaid orders found in the system right now.")
        return ConversationHandler.END
        
    reply_keyboard = [[f"{row[0]} - {row[1]} ({row[2]:,} ETB)"] for row in rows]
    reply_keyboard.append(['/cancel'])
    
    await update.message.reply_text(
        "💳 Select an open order to register payment:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.SELECT_OPEN_ORDER

async def open_order_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selection = update.message.text.strip()
    order_id = selection.split(" - ")[0]
    
    context.user_data['pay_order_id'] = order_id
    
    reply_keyboard = [['💵 Cash', '📱 Mobile Banking', '/cancel']]
    await update.message.reply_text(
        f"Select the payment method for order `{order_id}`:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.PAYMENT_METHOD

async def payment_method_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    method = update.message.text.strip()
    context.user_data['pay_method'] = method
    
    if method == '📱 Mobile Banking':
        await update.message.reply_text(
            "🔢 Enter the Reference / Transaction ID number:",
            reply_markup=ReplyKeyboardRemove()
        )
        return config.TRANS_ID
        
    return await finalize_payment(update, context, "N/A - Cash")

async def trans_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tx_id = update.message.text.strip()
    return await finalize_payment(update, context, tx_id)

async def finalize_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: str) -> int:
    order_id = context.user_data['pay_order_id']
    method = context.user_data['pay_method']
    settling_staff = update.effective_user.first_name or "Admin"
    
    await database.close_order_payment(order_id, settling_staff, method, tx_id)
    
    items, customer_name, total_due, group_msg_id = await database.get_order_details_for_billing(order_id)
    
    if items:
        item_details = "\n".join([f" • `{item[0]}` x `{item[1]}` ({item[2]:,} ETB)" for item in items])
        close_msg = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ **ORDER CLOSED & PAID**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Order ID:** `{order_id}`\n"
            f"👤 **Customer/Table:** `{customer_name}`\n"
            f"──────────────────────\n"
            f"📦 **Details:**\n"
            f"{item_details}\n"
            f"💰 **Total Paid:** `{total_due:,} ETB`\n"
            f"──────────────────────\n"
            f"💳 **Method:** `{method}`\n"
            f"🧾 **Ref ID:** `{tx_id}`\n"
            f"⚡ **Status:** 🟢 **SETTLED & CLOSED**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        reply_to_msg_id = None
        if group_msg_id and group_msg_id.isdigit():
            reply_to_msg_id = int(group_msg_id)
            
        try:
            try:
                await context.bot.send_message(
                    chat_id=config.GROUP_CHAT_ID, 
                    text=close_msg, 
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to_msg_id
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=config.GROUP_CHAT_ID, 
                    text=close_msg, 
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to send payment close notification to group chat: {e}")

    await update.message.reply_text(f"🏁 Order `{order_id}` completely settled and marked as PAID.")
    return await start(update, context)

async def handle_accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data or not data.startswith("accept_"):
        return
        
    order_id = data.split("_")[1]
    barista = (query.from_user.first_name or query.from_user.username or "Barista").upper()
    
    # Update status in database
    await database.mark_order_preparing(order_id)
    
    # Get order details to update the group message
    items, customer_name, total_due, group_msg_id = await database.get_order_details_for_billing(order_id)
    
    if items:
        item_details = "\n".join([f" • `{item[0]}` x `{item[1]}`" for item in items])
        updated_msg = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"☕ **ORDER IN PREPARATION**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Order ID:** `{order_id}`\n"
            f"👤 **Customer/Table:** `{customer_name}`\n"
            f"──────────────────────\n"
            f"📦 **Items:**\n"
            f"{item_details}\n"
            f"💰 **Total Amount:** `{total_due:,} ETB`\n"
            f"──────────────────────\n"
            f"⚡ **Status:** 🟡 **PREPARING**\n"
            f"👨‍🍳 **Barista:** `{barista}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        try:
            await query.edit_message_text(text=updated_msg, parse_mode="Markdown")
        except Exception:
            pass

        try:
            if group_msg_id and group_msg_id != "N/A":
                await context.bot.send_message(
                    chat_id=config.GROUP_CHAT_ID,
                    text=updated_msg,
                    parse_mode="Markdown",
                    reply_to_message_id=int(group_msg_id),
                )
            else:
                await context.bot.send_message(
                    chat_id=config.GROUP_CHAT_ID,
                    text=updated_msg,
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error(f"Failed to send PREPARING status reply to group chat: {e}")

# --- View Orders (Today) ---
async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    orders = await database.get_all_orders_today()

    if not orders:
        await update.message.reply_text("📭 No orders placed today yet.")
        return ConversationHandler.END

    status_icons = {
        'OPEN':      '🔴',
        'PREPARING': '🟡',
        'PAID':      '🟢',
    }

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📋 *TODAY'S ORDERS*",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for row in orders:
        order_id, customer, total, status, ts = row
        icon = status_icons.get(status, '⚪')
        lines.append(
            f"{icon} `{order_id}` — *{customer}*\n"
            f"   💰 {total:,.0f} ETB  |  {status}  |  🕐 {ts}"
        )
        lines.append("──────────────────────")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    return ConversationHandler.END

# --- Sales Reports ---
async def view_sales_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    report = await database.generate_daily_report_metrics()
    await update.message.reply_text(report, parse_mode="Markdown")
    return ConversationHandler.END


# --- Admin Management Panel ---
async def admin_panel_start_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    reply_keyboard = [
        ['➕ Add New Menu Item', '🗂️ Add New Category'],
        ['✏️ Edit Item Price',   '🗑️ Delete Menu Item'],
        ['❌ Delete Category',   '↩️ Back to Dashboard'],
    ]
    await update.message.reply_text(
        "⚙️ **Admin Database Management Control**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.ADM_MAIN

async def process_admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()

    if choice == '➕ Add New Menu Item':
        categories = await database.get_categories_from_db()
        reply_keyboard = [[cat] for cat in categories]
        reply_keyboard.append(['/cancel'])
        await update.message.reply_text(
            "🏷️ Select a category for the new item, or type a new category name:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
        return config.ADM_ADD_CAT

    elif choice == '🗂️ Add New Category':
        await update.message.reply_text(
            "🏷️ Enter the name of the new category (e.g. *Hot Items*, *Cold Items*):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return config.ADM_ADD_CAT_ONLY

    elif choice == '✏️ Edit Item Price':
        categories = await database.get_categories_from_db()
        reply_keyboard = [[cat] for cat in categories]
        reply_keyboard.append(['/cancel'])
        await update.message.reply_text(
            "📂 Select the *category* of the item you want to edit:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
        context.user_data['admin_action'] = 'edit_price'
        return config.ADM_EDIT_PRICE_CAT

    elif choice == '🗑️ Delete Menu Item':
        categories = await database.get_categories_from_db()
        reply_keyboard = [[cat] for cat in categories]
        reply_keyboard.append(['/cancel'])
        await update.message.reply_text(
            "📂 Select the *category* of the item you want to delete:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
        context.user_data['admin_action'] = 'delete_item'
        return config.ADM_DEL_ITEM_CAT

    elif choice == '❌ Delete Category':
        categories = await database.get_categories_from_db()
        reply_keyboard = [[cat] for cat in categories]
        reply_keyboard.append(['/cancel'])
        await update.message.reply_text(
            "⚠️ Select a *category* to delete (ALL its items will also be removed!):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        )
        return config.ADM_DEL_CAT_SEL

    return await start(update, context)

async def admin_add_cat_only_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cat_name = update.message.text.strip()
    await database.add_category_to_db(cat_name)
    await update.message.reply_text(
        f"✅ Category **{cat_name}** added successfully!",
        parse_mode="Markdown"
    )
    return await admin_panel_start_text(update, context)

async def admin_category_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip()
    context.user_data['new_item_category'] = category
    await database.add_category_to_db(category)
    await update.message.reply_text(
        "✏️ Enter the name of the new item:",
        reply_markup=ReplyKeyboardRemove()
    )
    return config.ADM_ADD_ITEM_NAME

async def admin_item_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_item_name'] = update.message.text.strip()
    await update.message.reply_text("💰 Enter the unit price in ETB (numbers only):")
    return config.ADM_ADD_ITEM_PRICE

async def admin_item_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    if not price_text.replace('.', '', 1).isdigit():
        await update.message.reply_text("❌ Numbers only. Please enter a proper price number:")
        return config.ADM_ADD_ITEM_PRICE

    category = context.user_data['new_item_category']
    name = context.user_data['new_item_name']
    price = float(price_text)
    await database.add_item_to_db(category, name, price)
    await update.message.reply_text(
        f"✅ Added **{name}** ({price:,.0f} ETB) to the **{category}** category!",
        parse_mode="Markdown"
    )
    return await admin_panel_start_text(update, context)

# --- Edit Price Flow ---
async def admin_edit_price_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip()
    items = await database.get_items_by_category(category)
    if not items:
        await update.message.reply_text(f"❌ No items found in *{category}*.", parse_mode="Markdown")
        return config.ADM_EDIT_PRICE_CAT

    context.user_data['edit_price_category'] = category
    reply_keyboard = [[f"{i[0]} ({i[1]:,.0f} ETB)"] for i in items]
    reply_keyboard.append(['/cancel'])
    await update.message.reply_text(
        f"✏️ Select the item to edit from *{category}*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.ADM_EDIT_PRICE_ITEM

async def admin_edit_price_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Strip the price part "(XX ETB)" from the selection
    selection = update.message.text.strip()
    item_name = selection.split(" (")[0]
    context.user_data['edit_price_item'] = item_name
    await update.message.reply_text(
        f"💰 Enter the new price for *{item_name}* (ETB, numbers only):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return config.ADM_EDIT_PRICE_VAL

async def admin_edit_price_val(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    price_text = update.message.text.strip()
    if not price_text.replace('.', '', 1).isdigit():
        await update.message.reply_text("❌ Numbers only. Enter a valid price:")
        return config.ADM_EDIT_PRICE_VAL

    item_name = context.user_data['edit_price_item']
    new_price = float(price_text)
    await database.update_item_price_in_db(item_name, new_price)
    await update.message.reply_text(
        f"✅ *{item_name}* price updated to *{new_price:,.0f} ETB* successfully!",
        parse_mode="Markdown"
    )
    return await admin_panel_start_text(update, context)

# --- Delete Item Flow ---
async def admin_del_item_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip()
    items = await database.get_items_by_category(category)
    if not items:
        await update.message.reply_text(f"❌ No items found in *{category}*.", parse_mode="Markdown")
        return config.ADM_DEL_ITEM_CAT

    context.user_data['del_item_category'] = category
    reply_keyboard = [[i[0]] for i in items]
    reply_keyboard.append(['/cancel'])
    await update.message.reply_text(
        f"🗑️ Select the item to *delete* from *{category}*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.ADM_DEL_ITEM_SEL

async def admin_del_item_sel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    item_name = update.message.text.strip()
    context.user_data['del_item_name'] = item_name
    reply_keyboard = [[f"✅ Yes, Delete {item_name}", '❌ Cancel']]
    await update.message.reply_text(
        f"⚠️ Are you sure you want to delete *{item_name}*? This cannot be undone.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.ADM_DEL_ITEM_CONF

async def admin_del_item_conf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    item_name = context.user_data.get('del_item_name', '')
    if choice.startswith('✅ Yes'):
        await database.delete_item_from_db(item_name)
        await update.message.reply_text(
            f"🗑️ *{item_name}* has been permanently deleted.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("↩️ Deletion cancelled.")
    return await admin_panel_start_text(update, context)

# --- Delete Category Flow ---
async def admin_del_cat_sel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip()
    context.user_data['del_cat_name'] = category
    reply_keyboard = [[f"✅ Yes, Delete {category}", '❌ Cancel']]
    await update.message.reply_text(
        f"⚠️ Delete *{category}* and ALL its items? This cannot be undone!",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    return config.ADM_DEL_CAT_CONF

async def admin_del_cat_conf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip()
    cat_name = context.user_data.get('del_cat_name', '')
    if choice.startswith('✅ Yes'):
        await database.delete_category_from_db(cat_name)
        await update.message.reply_text(
            f"🗑️ Category *{cat_name}* and all its items have been permanently deleted.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("↩️ Deletion cancelled.")
    return await admin_panel_start_text(update, context)


# --- Global Interruption Handler ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔄 Current action aborted. Resetting dashboard context values to clean...",
        reply_markup=ReplyKeyboardRemove()
    )
    return await start(update, context)

# --- Init Router Shortcut Handler ---
async def shortcut_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    await update.message.reply_text(
        f"Chat ID: `{chat.id}`\nType: `{chat.type}`",
        parse_mode="Markdown",
    )


async def post_init(application: Application) -> None:
    await database.init_extended_tables()
    await database.seed_default_menu()

    # Log configuration variables for Render deployment diagnostics
    masked_token = f"...{config.BOT_TOKEN[-8:]}" if config.BOT_TOKEN else "None"
    logger.info(f"Starting post_init check with BOT_TOKEN={masked_token} and GROUP_CHAT_ID={config.GROUP_CHAT_ID}")

    try:
        chat = await application.bot.get_chat(config.GROUP_CHAT_ID)
        logger.info(f"Connected to group chat: {chat.title} (id={config.GROUP_CHAT_ID})")
        await application.bot.send_message(
            config.GROUP_CHAT_ID,
            "🟢 NUD Coffee bot is online (group push test).",
        )
    except Exception as e:
        logger.error(
            f"Cannot access GROUP_CHAT_ID={config.GROUP_CHAT_ID}: {e}. "
            f"The bot must be a member of the group and the chat ID must be correct."
        )

def main():
    # Build complete telegram application state mapping
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('(?i)^📝 Create New Order$'), register_sale_start),
            MessageHandler(filters.Regex('(?i)^💳 Pay Open Order$'), pay_order_start),
            MessageHandler(filters.Regex('(?i)^📋 View Orders$'), view_orders),
            MessageHandler(filters.Regex('(?i)^📈 Sales Result$'), view_sales_report),
            MessageHandler(filters.Regex('(?i)^📊 View Sales Report$'), view_sales_report),
            MessageHandler(filters.Regex('(?i)^⚙️ Admin Management$'), admin_panel_start_text),
            CommandHandler('admin', admin_panel_start_text),
            CommandHandler('start', start),
        ],
        states={
            config.CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name_received)],
            config.SELECT_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, category_selected)],
            config.SELECT_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_selected)],
            config.QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_received)],
            config.CART_OPTIONS: [MessageHandler(filters.Regex('^🛒 Confirm Order$'), process_cart_options)],
            config.SELECT_OPEN_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, open_order_selected)],
            config.PAYMENT_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_method_received)],
            config.TRANS_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, trans_id_received)],
            config.ADM_MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_main)],
            config.ADM_ADD_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_category_received)],
            config.ADM_ADD_ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_item_name_received)],
            config.ADM_ADD_ITEM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_item_price_received)],
            config.ADM_ADD_CAT_ONLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_cat_only_received)],
            # Edit price flow
            config.ADM_EDIT_PRICE_CAT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_cat)],
            config.ADM_EDIT_PRICE_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_item)],
            config.ADM_EDIT_PRICE_VAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_price_val)],
            # Delete item flow
            config.ADM_DEL_ITEM_CAT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_item_cat)],
            config.ADM_DEL_ITEM_SEL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_item_sel)],
            config.ADM_DEL_ITEM_CONF: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_item_conf)],
            # Delete category flow
            config.ADM_DEL_CAT_SEL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_cat_sel)],
            config.ADM_DEL_CAT_CONF: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_del_cat_conf)],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('(?i)^/cancel$'), cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_accept_order, pattern="^accept_"))
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('cancel', cancel))
    application.add_handler(CommandHandler('chatid', chatid_command))

    # Start health check server in a background thread to satisfy Render port check
    health_thread = threading.Thread(target=run_health_check_server, daemon=True)
    health_thread.start()

    # Run the bot using long polling with conflict-safe retry
    import time
    from telegram.error import Conflict

    MAX_RETRIES = 5
    retry_delay = 15  # seconds

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Starting polling (attempt {attempt}/{MAX_RETRIES})...")
            application.run_polling(drop_pending_updates=True)
            break  # Clean exit — no need to retry
        except Conflict as e:
            logger.warning(
                f"Conflict error: another instance is still running. "
                f"Retrying in {retry_delay}s... (attempt {attempt}/{MAX_RETRIES})\n{e}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Ensure only one bot instance is running.")
                import sys
                sys.exit(1)
        except Exception as e:
            logger.error(f"Polling stopped due to error: {e}")
            import sys
            sys.exit(1)

if __name__ == '__main__':
    main()