"""
seed_menu.py — Run this ONCE to manually insert default menu into the database.
Usage: python seed_menu.py
"""
import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "nud_coffee.db")

DEFAULT_MENU = [
    ("Hot Items",    "Normal Coffee",   60.0),
    ("Hot Items",    "Tea",             40.0),
    ("Hot Items",    "Cappuccino",      80.0),
    ("Hot Items",    "American Coffee", 100.0),
    ("Hot Items",    "Special Tea",     120.0),
    ("Cold Items",   "Water 1L",        30.0),
    ("Cold Items",   "Water 2L",        60.0),
    ("Cold Items",   "Water 1/2",       20.0),
    ("Bakery Items", "English Cake",    60.0),
    ("Bakery Items", "Banana Cake",     60.0),
]

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create tables if they don't exist yet
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT,
            item_name TEXT UNIQUE,
            price REAL,
            FOREIGN KEY(category_name) REFERENCES categories(name)
        )
    ''')

    # Insert categories
    categories = list({row[0] for row in DEFAULT_MENU})
    for cat in sorted(categories):
        cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        print(f"  ✅ Category: {cat}")

    # Insert items
    for cat, item, price in DEFAULT_MENU:
        cursor.execute(
            "INSERT OR IGNORE INTO menu_items (category_name, item_name, price) VALUES (?, ?, ?)",
            (cat, item, price)
        )
        print(f"  ✅ Item: {item} ({price:.0f} ETB) → {cat}")

    conn.commit()
    conn.close()
    print("\n🎉 Done! All default categories and items have been added to the database.")

if __name__ == "__main__":
    print(f"\n📦 Seeding database: {DB_PATH}\n")
    seed()
