# api/database.py
import libsql_client
import random
import string
from api import config

def get_client():
    return libsql_client.create_client_sync(
        url=config.TURSO_URL,
        auth_token=config.TURSO_TOKEN
    )

def init_db():
    """Creates operational ledger schemas inside Turso if they don't exist."""
    client = get_client()
    
    # Sales ledger schema
    client.execute("""
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
    """)
    
    # Products table schema
    client.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            item_name TEXT,
            price REAL
        )
    """)
    
    # Seed default products if menu setup is empty
    res = client.execute("SELECT COUNT(*) FROM products")
    if res.rows[0][0] == 0:
        default_items = [
            ("Espresso Bar", "Macchiato", 45.0),
            ("Espresso Bar", "Americano", 50.0),
            ("Espresso Bar", "Cafe Latte", 65.0),
            ("Sweet Treats", "Croissant", 55.0),
            ("Sweet Treats", "Brownie", 70.0)
        ]
        for cat, name, prc in default_items:
            client.execute("INSERT INTO products (category, item_name, price) VALUES (?, ?, ?)", (cat, name, prc))

def generate_order_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def get_menu_from_db():
    client = get_client()
    res = client.execute("SELECT category, item_name, price FROM products")
    menu = {}
    for row in res.rows:
        cat, name, prc = row[0], row[1], row[2]
        if cat not in menu:
            menu[cat] = {}
        menu[cat][name] = prc
    return menu

async def get_category_for_item(item_name):
    client = get_client()
    res = client.execute("SELECT category FROM products WHERE item_name = ? LIMIT 1", (item_name,))
    if res.rows:
        return res.rows[0][0]
    return "Other"