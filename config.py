# config.py
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
import telegram


# Load environment variables
load_dotenv()

# --- SYSTEM SETTINGS & AUTHENTICATION ---
ADMIN_ID = int(os.getenv("ADMIN_ID", 6280916362))

# Multiple admin IDs support (comma-separated list from .env)
admin_ids_str = os.getenv("ADMIN_IDS", "")

ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]
if ADMIN_ID not in ADMIN_IDS:
    ADMIN_IDS.append(ADMIN_ID)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8736124035:AAEPDGX9GhUXsqDUD1UKrNzYlwCZK32phps")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", -1004460430054))

# --- DATABASE CONFIGURATION ---
DB_PATH = os.getenv("DB_PATH", "nud_coffee.db")

# =====================================================================
# 🧭 CONVERSATION STATE MACHINE CONSTANTS
# =====================================================================
CUSTOMER_NAME = 1
SELECT_ITEM = 2
QUANTITY = 3
QTY_CONFIRM = 4
CART_OPTIONS = 5
REVIEW = 6
SELECT_CATEGORY = 8

SELECT_OPEN_ORDER = 7
PAYMENT_METHOD = 9
TRANS_ID = 10

ADM_MAIN = 20
ADM_ADD_CAT = 21
ADM_ADD_ITEM_NAME = 22
ADM_ADD_ITEM_PRICE = 23
ADM_ADD_CAT_ONLY = 24