# database.py
import aiosqlite
import random
import string
from config import DB_PATH

def generate_order_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def init_extended_tables():
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        ''')
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_name TEXT,
                item_name TEXT UNIQUE,
                price REAL,
                FOREIGN KEY(category_name) REFERENCES categories(name)
            )
        ''')
        await cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales_registration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                salesman TEXT,
                closing_salesman TEXT,
                customer_name TEXT,
                date TEXT,
                timestamp TEXT,
                coffee_type TEXT,
                quantity INTEGER,
                price REAL,
                payment_method TEXT,
                transaction_id TEXT,
                status TEXT,
                group_msg_id TEXT
            )
        ''')
        await conn.commit()

async def add_category_to_db(category_name: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category_name,))
        await conn.commit()

async def add_item_to_db(category_name: str, item_name: str, price: float):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO menu_items (category_name, item_name, price) VALUES (?, ?, ?)",
            (category_name, item_name, price)
        )
        await conn.commit()

async def get_categories_from_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT name FROM categories ORDER BY name ASC")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]

async def get_items_by_category(category_name: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT item_name, price FROM menu_items WHERE category_name = ?", (category_name,))
        return await cursor.fetchall()

async def get_menu_from_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute("SELECT item_name, price FROM menu_items ORDER BY item_name ASC")
        rows = await cursor.fetchall()
        return [{'name': r[0], 'price': r[1]} for r in rows]

async def save_order_to_db(customer_name: str, waiter_name: str, cart: list, total_amount: float) -> tuple:
    order_id = generate_order_id()
    from datetime import datetime
    now = datetime.now()
    db_date = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%d/%m/%Y, %I:%M %p")
    
    async with aiosqlite.connect(DB_PATH) as conn:
        for entry in cart:
            await conn.execute(
                """INSERT INTO sales_registration 
                (order_id, salesman, closing_salesman, customer_name, date, timestamp, coffee_type, quantity, price, payment_method, transaction_id, status, group_msg_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, waiter_name, "Pending", customer_name, db_date, timestamp, entry['item'], entry['qty'], entry['price'], "Pending", "Pending", "OPEN", "N/A")
            )
        await conn.commit()
    return order_id, timestamp

async def update_group_msg_id(order_id: str, msg_id: int):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE sales_registration SET group_msg_id = ? WHERE order_id = ?", (str(msg_id), order_id))
        await conn.commit()

async def get_open_orders():
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute("""
            SELECT DISTINCT order_id, customer_name, SUM(quantity * price) 
            FROM sales_registration 
            WHERE status IN ('OPEN', 'PREPARING') 
            GROUP BY order_id
        """)
        return await cursor.fetchall()

async def get_order_details_for_billing(order_id: str) -> tuple:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT coffee_type, quantity, price, customer_name, group_msg_id FROM sales_registration WHERE order_id = ?", 
            (order_id,)
        )
        rows = await cursor.fetchall()
        if not rows:
            return [], "Unknown", 0.0, "N/A"
        
        customer_name = rows[0][3]
        group_msg_id = rows[0][4]
        items = [(r[0], r[1], r[2]) for r in rows]
        total_due = sum(r[1] * r[2] for r in rows)
        return items, customer_name, total_due, group_msg_id

async def close_order_payment(order_id: str, settling_staff: str, payment_method: str, transaction_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE sales_registration SET closing_salesman = ?, payment_method = ?, transaction_id = ?, status = 'PAID' WHERE order_id = ?",
            (settling_staff, payment_method, transaction_id, order_id)
        )
        await conn.commit()

async def mark_order_preparing(order_id: str):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "UPDATE sales_registration SET status = 'PREPARING' WHERE order_id = ?",
            (order_id,)
        )
        await conn.commit()

async def generate_daily_report_metrics() -> str:
    from datetime import datetime
    db_date = datetime.now().strftime("%Y-%m-%d")
    display_date = datetime.now().strftime("%A, %d/%m/%Y")
    
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()
        await cursor.execute("""
            SELECT coffee_type, SUM(quantity), SUM(quantity * price) 
            FROM sales_registration 
            WHERE date = ? AND status = 'PAID' 
            GROUP BY coffee_type
        """, (db_date,))
        item_rows = await cursor.fetchall()
        
        await cursor.execute("""
            SELECT m.category_name, SUM(s.quantity * s.price)
            FROM sales_registration s
            JOIN menu_items m ON s.coffee_type = m.item_name
            WHERE s.date = ? AND s.status = 'PAID'
            GROUP BY m.category_name
        """, (db_date,))
        cat_rows = await cursor.fetchall()
        
        await cursor.execute("""
            SELECT closing_salesman, SUM(quantity * price)
            FROM sales_registration
            WHERE date = ? AND status = 'PAID'
            GROUP BY closing_salesman
        """, (db_date,))
        staff_rows = await cursor.fetchall()
        
        await cursor.execute("""
            SELECT payment_method, SUM(quantity * price)
            FROM sales_registration
            WHERE date = ? AND status = 'PAID'
            GROUP BY payment_method
        """, (db_date,))
        pay_rows = await cursor.fetchall()
        
        await cursor.execute("""
            SELECT COUNT(DISTINCT order_id), COALESCE(SUM(quantity * price), 0)
            FROM sales_registration
            WHERE status IN ('OPEN', 'PREPARING')
        """)
        open_tabs_row = await cursor.fetchone()
        open_count = open_tabs_row[0] if open_tabs_row else 0
        open_est = open_tabs_row[1] if open_tabs_row else 0.0

    report = (
        "📋 NUD COFFEE DAILY REPORT\n"
        f"📅 Date: {display_date}\n"
        "──────────────────────────────\n\n"
        "☕ SALES BY ITEM:\n"
    )
    if item_rows:
        for row in item_rows:
            report += f" • *{row[0]}*: {row[1]} sold → {row[2]:,.2f} ETB\n"
    else:
        report += " • No items sold yet today.\n"
        
    report += "\n📁 SALES BY CATEGORY:\n"
    if cat_rows:
        for row in cat_rows:
            report += f" • *{row[0]}*: {row[1]:,.2f} ETB\n"
    else:
        report += " • No category sales recorded.\n"
        
    report += "\n👤 COLLECTIONS BY CASHIER:\n"
    if staff_rows:
        for row in staff_rows:
            staff_name = row[0] if row[0] != "Pending" else "System"
            report += f" • *{staff_name}*: {row[1]:,.2f} ETB\n"
    else:
        report += " • No staff collections.\n"
        
    report += "\n💳 REVENUE BY PAYMENT METHOD:\n"
    grand_total = 0.0
    if pay_rows:
        for row in pay_rows:
            icon = "💵" if row[0] == "Cash" else "📱"
            report += f" • {icon} *{row[0]}*: {row[1]:,.2f} ETB\n"
            grand_total += row[1]
    else:
        report += " • No payments collected.\n"
        
    report += "──────────────────────────────\n\n"
    report += f"⏳ ACTIVE UNPAID ORDERS: {open_count} tabs (Est: {open_est:,.2f} ETB)\n"
    report += f"📈 GRAND NET REVENUE: {grand_total:,.2f} ETB"
    
    return report