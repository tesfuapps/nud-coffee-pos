import asyncio
import logging
import random
import string
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
            ['📊 View Sales Report', '⚙️ Admin Management']
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
        
        msg = await context.bot.send_message(
            chat_id=config.GROUP_CHAT_ID, 
            text=alert_msg, 
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        await database.update_group_msg_id(order_id, msg.message_id)
        
        # Confirmation to operator
        await update.message.reply_text(
            f"✅ Order `{order_id}` saved successfully and pushed to group queue!",
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
        ['↩️ Back to Dashboard']
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
            "🏷️ Enter the name of the new category (e.g. *Hot Items*, *Cold Items*):" ,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return config.ADM_ADD_CAT_ONLY
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
    
    # Ensure category exists in db
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
    if not price_text.isdigit():
        await update.message.reply_text("❌ Numbers only. Please enter a proper price number:")
        return config.ADM_ADD_ITEM_PRICE
        
    category = context.user_data['new_item_category']
    name = context.user_data['new_item_name']
    price = float(price_text)
    
    # Insert new entry item into database table
    await database.add_item_to_db(category, name, price)
    
    await update.message.reply_text(
        f"✅ Added **{name}** ({price:,.2f} ETB) to the **{category}** category!", 
        parse_mode="Markdown"
    )
    return await start(update, context)

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

async def post_init(application: Application) -> None:
    await database.init_extended_tables()

def main():
    # Build complete telegram application state mapping
    application = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('(?i)^📝 Create New Order$'), register_sale_start),
            MessageHandler(filters.Regex('(?i)^💳 Pay Open Order$'), pay_order_start),
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
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('(?i)^/cancel$'), cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_accept_order, pattern="^accept_"))
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('cancel', cancel))

    # Run the bot using long polling (no webhook)
    try:
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Polling stopped due to error: {e}")
        # Exit gracefully
        import sys
        sys.exit(1)

if __name__ == '__main__':
    main()