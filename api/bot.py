# api/bot.py
import logging
import http
import traceback
import sys
from fastapi import FastAPI, Request, Response

try:
    from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
        ConversationHandler,
        ContextTypes,
        CallbackQueryHandler,
    )
    import pytz
    from api import config
    from api import database
    import libsql_client
    import uvicorn
    import fastapi
    import telegram
    
    IMPORT_ERROR_LOG = None
except Exception as e:
    IMPORT_ERROR_LOG = f"Initialization Crash: {str(e)}\n{traceback.format_exc()}"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
telegram_app = None

# --- CORE UI COMPONENTS ---
def get_main_keyboard():
    return ReplyKeyboardMarkup([['📝 Create New Order'], ['💳 Pay Open Order'], ['📊 View Sales Report']], resize_keyboard=True)

def get_waiter_inline_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Create New Order", callback_data="create_order_inline_fallback")],
        [InlineKeyboardButton("💳 Pay Open Order", callback_data="pay_order_inline_fallback")],
        [InlineKeyboardButton("📊 View Sales Report", callback_data="view_report_inline_fallback")]
    ])

# --- FLOW 1: CREATE ORDER INTERACTION HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("☕ Nud Coffee Tab Terminal Operational\n• Select an option below:", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🛑 Operation cancelled.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 Use menu buttons or type /cancel to break out of operations.")

async def register_sale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()  
    context.user_data['salesman_name'] = update.effective_user.first_name
    context.user_data['waiter_chat_id'] = update.effective_user.id
    context.user_data['cart'] = [] 
    context.user_data['is_append_mode'] = False
    
    msg_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query: await update.callback_query.answer()
        
    await msg_target.reply_text("👤 Type Customer Name or Table Number:", reply_markup=ReplyKeyboardRemove())
    return config.CUSTOMER_NAME

async def customer_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer_name'] = update.message.text.strip()
    return await show_categories_menu(update.message, context)

async def show_categories_menu(message_obj, context: ContextTypes.DEFAULT_TYPE, is_edit=False):
    menu = await database.get_menu_from_db()
    keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in menu.keys()]
    markup = InlineKeyboardMarkup(keyboard)
    c_name = context.user_data.get('customer_name', 'Walk-in')
    
    text = f"➕ **Append Mode**" if context.user_data.get('is_append_mode') else f"📦 **Ticket: {c_name}**"
    text += "\nSelect a product category:"
    
    if is_edit and hasattr(message_obj, 'edit_message_text'): await message_obj.edit_message_text(text=text, parse_mode="Markdown", reply_markup=markup)
    elif is_edit and hasattr(message_obj, 'edit_text'): await message_obj.edit_text(text=text, parse_mode="Markdown", reply_markup=markup)
    else: await message_obj.reply_text(text=text, parse_mode="Markdown", reply_markup=markup)
    return config.SELECT_ITEM

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    menu = await database.get_menu_from_db()

    if data.startswith("cat_"):
        cat = data.replace("cat_", ""); context.user_data['current_category'] = cat
        keyboard = []
        row = []
        for item in menu.get(cat, {}).keys():
            row.append(InlineKeyboardButton(item, callback_data=f"item_{item}"))
            if len(row) == 2: keyboard.append(row); row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="back_categories")])
        
        await query.message.edit_text(text=f"🛒 Category: {cat}\nSelect an item:", reply_markup=InlineKeyboardMarkup(keyboard))
        return config.SELECT_ITEM

    elif data == "back_categories":
        await show_categories_menu(query, context, is_edit=True)
        return config.SELECT_ITEM

    elif data.startswith("item_"):
        item = data.replace("item_", ""); context.user_data['selected_item'] = item
        price = 0.0
        for c, items in menu.items():
            if item in items: price = items[item]; break
        context.user_data['selected_price'] = price
        
        keyboard = [
            [InlineKeyboardButton("1", callback_data="qty_1"), InlineKeyboardButton("2", callback_data="qty_2")],
            [InlineKeyboardButton("3", callback_data="qty_3"), InlineKeyboardButton("4", callback_data="qty_4")],
            [InlineKeyboardButton("✏️ Custom Input", callback_data="opt_custom")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_to_items")]
        ]
        await query.message.edit_text(text=f"🔢 Item: {item} ({price:.2f} ETB)\nSelect Quantity:", reply_markup=InlineKeyboardMarkup(keyboard))
        return config.QUANTITY

async def quantity_inline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data == "back_to_items":
        return config.SELECT_ITEM
    elif data == "opt_custom":
        await query.message.edit_text(text="✏️ Type the exact quantity value as a text message:")
        return config.QUANTITY
    elif data.startswith("qty_"):
        qty = int(data.replace("qty_", "")); context.user_data['temp_qty'] = qty
        return await processing_cart_addition(query.message, qty, context, from_inline=True)

async def quantity_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text)
        if qty <= 0: return config.QUANTITY
        return await processing_cart_addition(update.message, qty, context, from_inline=False)
    except ValueError:
        return config.QUANTITY

async def handle_qty_confirm_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "opt_continue":
        return await render_basket_view(query.message, context, edit_existing=True)

async def processing_cart_addition(message_obj, quantity, context, from_inline=False):
    context.user_data['cart'].append({
        'item_name': context.user_data['selected_item'],
        'quantity': quantity,
        'price': context.user_data['selected_price']
    })
    return await render_basket_view(message_obj, context, edit_existing=from_inline)

async def render_basket_view(message_obj, context, edit_existing=False):
    cart = context.user_data.get('cart', [])
    txt = f"🛒 **Basket Records Summary**\n\n"
    total = 0.0
    for item in cart:
        sub = item['quantity'] * item['price']
        total += sub
        txt += f"• {item['item_name']} x {item['quantity']} = {sub:.2f} ETB\n"
    txt += f"\n💰 Total: **{total:.2f} ETB**"
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Item", callback_data="cart_add_more")],
        [InlineKeyboardButton("💾 Dispatch Order", callback_data="cart_go_review")]
    ])
    if edit_existing and hasattr(message_obj, 'edit_text'): await message_obj.edit_text(text=txt, parse_mode="Markdown", reply_markup=markup)
    else: await message_obj.reply_text(text=txt, parse_mode="Markdown", reply_markup=markup)
    return config.CART_OPTIONS

async def handle_cart_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "cart_add_more": return await show_categories_menu(query, context, is_edit=True)
    if query.data == "cart_go_review":
        order_id = database.generate_order_id() if not context.user_data.get('is_append_mode') else context.user_data['checkout_order_id']
        context.user_data['order_id'] = order_id
        
        txt = f"📋 Review Ticket ID: #{order_id}\n\nConfirm items selection?"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm & Send", callback_data="review_confirm")]])
        await query.message.edit_text(text=txt, reply_markup=markup)
        return config.REVIEW

async def handle_final_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    cart = context.user_data.get('cart', [])
    order_id = context.user_data['order_id']
    salesman = context.user_data['salesman_name']
    c_name = context.user_data.get('customer_name', 'Walk-in')
    
    local_now = config.get_local_now()
    db_date = local_now.strftime("%Y-%m-%d")
    ts = local_now.strftime("%d/%m/%Y, %I:%M %p")
    
    items_summary = ""
    for item in cart:
        items_summary += f"• {item['item_name']} (x{item['quantity']})\n"
        
    kds_text = f"🔔 **NEW TICKET #{order_id}**\nWaiter: {salesman}\nCustomer: {c_name}\n\n{items_summary}\n👨‍🍳 Status: ⏳ Awaiting Barista..."
    kds_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Accept Order", callback_data=f"kds_accept_{order_id}")]])
    
    msg_id = "N/A"
    try:
        sent = await context.bot.send_message(chat_id=config.GROUP_CHAT_ID, text=kds_text, reply_markup=kds_markup)
        msg_id = str(sent.message_id)
    except Exception as e: logger.error(f"KDS pipeline error: {e}")

    client = database.get_client()
    for item in cart:
        client.execute(
            "INSERT INTO sales_registration (order_id, salesman, closing_salesman, customer_name, date, timestamp, coffee_type, quantity, price, payment_method, transaction_id, status, group_msg_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, salesman, str(context.user_data['waiter_chat_id']), c_name, db_date, ts, item['item_name'], item['quantity'], item['price'], "Pending", "Pending", "HOLD", msg_id)
        )
        
    await query.message.reply_text(f"💾 Ticket #{order_id} sent to kitchen ledger.")
    context.user_data.clear()
    return ConversationHandler.END

# --- KDS ENGINE HANDLERS ---
async def handle_kds_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data; chef = query.from_user.first_name
    try: await query.answer("🟢 Accepted.")
    except Exception: pass

    if data.startswith("kds_accept_"):
        order_id = data.replace("kds_accept_", "")
        client = database.get_client()
        
        res = client.execute("SELECT closing_salesman FROM sales_registration WHERE order_id = ? LIMIT 1", (order_id,))
        waiter_id = int(res.rows[0][0]) if res.rows else None
        
        client.execute("UPDATE sales_registration SET status = 'OPEN' WHERE order_id = ? AND status = 'HOLD'", (order_id,))
        
        try:
            await query.message.edit_text(text=f"🟢 **Order #{order_id} ACCEPTED & LIVE (Barista: {chef})**\nProcessed smoothly.", reply_markup=None)
        except Exception: pass

        if waiter_id:
            try:
                await context.bot.send_message(chat_id=waiter_id, text=f"🔔 Ticket **#{order_id}** Accepted by Barista!", parse_mode="Markdown", reply_markup=get_waiter_inline_menu())
            except Exception: pass

async def handle_ticket_lookup_viewer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "close_archive_card":
        try: await query.message.delete()
        except Exception: pass

# --- FLOW 2: SETTLEMENT CHECKOUT LEDGER ---
async def pay_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['active_closer_name'] = update.effective_user.first_name
    msg_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query: await update.callback_query.answer()

    client = database.get_client()
    res = client.execute("SELECT DISTINCT order_id, customer_name, status FROM sales_registration WHERE status IN ('OPEN', 'HOLD')")
    
    if not res.rows:
        await msg_target.reply_text("ℹ️ No active open orders found.", reply_markup=get_main_keyboard())
        return ConversationHandler.END
        
    keyboard = []
    for row in res.rows:
        oid, name, stat = row[0], row[1], row[2]
        lbl = f"🔒 #{oid} ({name}) - Hold" if stat == "HOLD" else f"🧾 #{oid} ({name})"
        cb = f"locked_tab_{oid}" if stat == "HOLD" else f"payid_{oid}"
        keyboard.append([InlineKeyboardButton(lbl, callback_data=cb)])
        
    await msg_target.reply_text("🖥️ Select a ticket to settle:", reply_markup=InlineKeyboardMarkup(keyboard))
    return config.SELECT_OPEN_ORDER

async def handle_locked_tab_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("❌ Barista has not accepted this order yet!", show_alert=True)
    return config.SELECT_OPEN_ORDER

async def handle_open_order_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); order_id = query.data.replace("payid_", "")
    context.user_data['checkout_order_id'] = order_id
    
    client = database.get_client()
    res = client.execute("SELECT coffee_type, quantity, price, customer_name FROM sales_registration WHERE order_id = ?", (order_id,))
    
    total = 0.0; summary = ""; c_name = "Walk-in"
    for row in res.rows:
        name, qty, prc, cust = row[0], row[1], row[2], row[3]
        if cust: c_name = cust
        sub = qty * prc; total += sub
        summary += f"• {name} x {qty} = {sub:.2f} ETB\n"
        
    context.user_data['checkout_total_bill'] = total
    context.user_data['customer_name'] = c_name
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Settle Bill", callback_data="route_to_settlement")],
        [InlineKeyboardButton("➕ Add Items", callback_data="route_to_append_items")]
    ])
    await query.message.edit_text(text=f"🧾 Ticket #{order_id} ({c_name})\n\n{summary}\nTotal Due: {total:.2f} ETB", reply_markup=markup)
    return config.CHOOSE_PAY_OR_APPEND

async def handle_pay_or_append_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); choice = query.data
    if choice == "route_to_append_items":
        context.user_data['is_append_mode'] = True
        context.user_data['cart'] = []
        context.user_data['salesman_name'] = query.from_user.first_name
        context.user_data['waiter_chat_id'] = query.from_user.id
        await show_categories_menu(query, context, is_edit=True)
        return config.SELECT_ITEM
        
    elif choice == "route_to_settlement":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 Cash", callback_data="settle_Cash")],
            [InlineKeyboardButton("📱 Telebirr", callback_data="settle_Telebirr")]
        ])
        await query.message.edit_text(text="💳 Choose payment terminal layout channel:", reply_markup=markup)
        return config.PAYMENT_METHOD

async def handle_settlement_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); method = query.data.replace("settle_", "")
    context.user_data['checkout_method'] = method
    
    if method == "Telebirr":
        await query.message.edit_text("Type the Telebirr reference code transaction ID:")
        return config.TRANS_ID
    else:
        context.user_data['checkout_trans_id'] = "N/A"
        await finalize_payment_in_db(query.message, context)
        return ConversationHandler.END

async def checkout_transaction_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checkout_trans_id'] = update.message.text.strip()
    await finalize_payment_in_db(update.message, context)
    return ConversationHandler.END

async def finalize_payment_in_db(message_obj, context):
    order_id = context.user_data['checkout_order_id']
    method = context.user_data['checkout_method']
    trans_id = context.user_data['checkout_trans_id']
    closer = context.user_data['active_closer_name']
    
    client = database.get_client()
    client.execute("UPDATE sales_registration SET payment_method = ?, transaction_id = ?, status = 'PAID', closing_salesman = ? WHERE order_id = ?", (method, trans_id, closer, order_id))
    
    txt = f"✅ Ticket #{order_id} Closed and Settled via {method} successfully!"
    if hasattr(message_obj, 'reply_text'): await message_obj.reply_text(txt, reply_markup=get_main_keyboard())
    else: await context.bot.send_message(chat_id=message_obj.chat_id, text=txt, reply_markup=get_main_keyboard())

# --- SALES ANALYTICS GENERATOR ENGINE ---
async def sales_report_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_target = update.callback_query.message if update.callback_query else update.message
    if update.callback_query: await update.callback_query.answer()
        
    client = database.get_client()
    today_date = config.get_local_now().strftime("%Y-%m-%d")
    res = client.execute("SELECT SUM(quantity * price) FROM sales_registration WHERE date = ? AND status = 'PAID'", (today_date,))
    total = res.rows[0][0] if res.rows and res.rows[0][0] else 0.0
    
    await msg_target.reply_text(f"📊 **Daily Financial Activity Analytics**\nDate: {today_date}\nTotal Revenue: **{total:.2f} ETB**", parse_mode="Markdown")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE): 
    logger.error(msg="Exception tracker hook caught update payload failure:", exc_info=context.error)

# =====================================================================
# ⚡ THE RAW LIGHTWEIGHT BACKEND STATE ENGINE
# =====================================================================
def get_stateless_application_engine():
    """Generates the routing mappings without forcing remote HTTP polling requests."""
    # Build directly from base class to bypass token string network parsing limitations
    application = Application.builder().token(config.TOKEN).build()
    fallback_rules = [CommandHandler('cancel', cancel)]
    
    shared_ordering_ui_states = {
        config.SELECT_ITEM: [CallbackQueryHandler(handle_menu_buttons, pattern="^(cat_|item_|back_categories)")],
        config.QUANTITY: [
            CallbackQueryHandler(quantity_inline_handler, pattern="^(back_to_items|opt_custom|qty_)"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_text_handler)
        ],
        config.QTY_CONFIRM: [CallbackQueryHandler(handle_qty_confirm_options, pattern="^opt_")], 
        config.CART_OPTIONS: [CallbackQueryHandler(handle_cart_options, pattern="^cart_")],
        config.REVIEW: [CallbackQueryHandler(handle_final_review, pattern="^review_")],
    }
    
    order_states = {config.CUSTOMER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name_received)]}
    order_states.update(shared_ordering_ui_states)
    
    order_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^📝 Create New Order$'), register_sale_start),
            CommandHandler(config.COMMAND_ORDER, register_sale_start),
            CallbackQueryHandler(register_sale_start, pattern="^create_order_inline_fallback$")
        ],
        states=order_states,
        fallbacks=fallback_rules,
        allow_reentry=True
    )
    
    checkout_states = {
        config.SELECT_OPEN_ORDER: [
            CallbackQueryHandler(handle_open_order_selection, pattern="^payid_"),
            CallbackQueryHandler(handle_locked_tab_alert, pattern="^locked_tab_")
        ],
        config.CHOOSE_PAY_OR_APPEND: [CallbackQueryHandler(handle_pay_or_append_choice, pattern="^route_")],
        config.PAYMENT_METHOD: [CallbackQueryHandler(handle_settlement_method, pattern="^settle_")],
        config.TRANS_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_transaction_id_received)]
    }
    checkout_states.update(shared_ordering_ui_states)
    
    checkout_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^💳 Pay Open Order$'), pay_order_start),
            CommandHandler(config.COMMAND_PAYMENT, pay_order_start),
            CallbackQueryHandler(pay_order_start, pattern="^pay_order_inline_fallback$")
        ],
        states=checkout_states,
        fallbacks=fallback_rules,
        allow_reentry=True
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('cancel', cancel))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.Regex('^📊 View Sales Report$'), sales_report_trigger))
    application.add_handler(CommandHandler(config.COMMAND_VIEW_SALES, sales_report_trigger))
    application.add_handler(CallbackQueryHandler(sales_report_trigger, pattern="^view_report_inline_fallback$"))
    application.add_handler(CallbackQueryHandler(handle_kds_clicks, pattern="^kds_"))
    application.add_handler(CallbackQueryHandler(handle_ticket_lookup_viewer, pattern="^(vw_rec_|close_archive_card)"))
    application.add_handler(order_conv)
    application.add_handler(checkout_conv)
    application.add_error_handler(error_handler)
    
    database.init_db()
    return application

@app.post("/")
async def process_webhook(request: Request):
    if IMPORT_ERROR_LOG:
        return Response(content=f"Webhook Execution Blocked:\n{IMPORT_ERROR_LOG}", media_type="text/plain", status_code=500)
    
    try:
        # Load mappings stateless
        engine = get_stateless_application_engine()
        req_json = await request.json()
        
        # Hydrate base update directly
        update = Update.de_json(req_json, engine.bot)
        
        # Inject context execution pipeline bypass smoothly
        await engine.initialize()
        await engine.process_update(update)
        await engine.shutdown()
            
    except Exception as e:
        logger.error(f"Runtime error processing update packet: {str(e)}")
        return Response(content=f"Runtime error processing update packet:\n{str(e)}\n{traceback.format_exc()}", media_type="text/plain", status_code=500)
    
    return Response(status_code=http.HTTPStatus.OK)

@app.get("/")
async def health_check():
    if IMPORT_ERROR_LOG:
        return {"status": "error", "diagnostics": IMPORT_ERROR_LOG}
    return {"status": "online", "engine": "Nud Coffee Stateless Active Layout", "database_client": "Connected"}