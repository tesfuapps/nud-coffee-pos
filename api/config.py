# api/config.py
import os
from datetime import datetime
import pytz

# Core Bot Settings (Loaded from secure cloud environment variables on Vercel)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "873612435:AAGZAc4BqoWj0jdnZjjxNagpGkHDsUks2nc")
GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_ID", "-1004460430054")

# Turso Cloud Database Connections
TURSO_URL = "libsql://nud-coffee-db-tesfutilahun66.aws-us-east-1.turso.io"
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "") # We will paste this token safely inside Vercel later

# Access Permissions
ADMIN_IDS = [612345678]  # Swap with your actual Telegram User ID for admin panel access

# Conversation State Keys
CUSTOMER_NAME, SELECT_ITEM, QUANTITY, QTY_CONFIRM, CART_OPTIONS, REVIEW = range(6)
SELECT_OPEN_ORDER, CHOOSE_PAY_OR_APPEND, PAYMENT_METHOD, TRANS_ID = range(6, 10)
ADMIN_MAIN, ADMIN_SELECT_ITEM, ADMIN_INPUT_PRICE = range(10, 13)

# System Command Shortcuts
COMMAND_ORDER = "order"
COMMAND_PAYMENT = "pay"
COMMAND_VIEW_SALES = "report"

def get_local_now():
    """Ensures business timestamp metrics sync cleanly with local time standards."""
    return datetime.now(pytz.timezone("Africa/Addis_Ababa"))