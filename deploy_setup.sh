#!/bin/bash
# ============================================================
#  NUD COFFEE BOT — Oracle Cloud VM Auto-Setup Script
#  Run this ONCE on your Oracle Cloud Ubuntu VM
# ============================================================

set -e  # Exit immediately on any error

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   NUD COFFEE BOT — VM SETUP START   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# --- 1. System Update ---
echo "📦 Step 1/5: Updating system packages..."
sudo apt update -y && sudo apt upgrade -y
sudo apt install python3-pip python3-venv -y
echo "✅ System updated."

# --- 2. Virtual Environment ---
echo ""
echo "🐍 Step 2/5: Creating Python virtual environment..."
cd ~/nud_coffee
python3 -m venv venv
source venv/bin/activate
echo "✅ Virtual environment ready."

# --- 3. Install Dependencies ---
echo ""
echo "📚 Step 3/5: Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ All dependencies installed."

# --- 4. Create systemd Service ---
echo ""
echo "⚙️  Step 4/5: Creating systemd service for auto-start..."
sudo tee /etc/systemd/system/nudcoffee.service > /dev/null <<EOF
[Unit]
Description=Nud Coffee Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/nud_coffee
ExecStart=/home/ubuntu/nud_coffee/venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable nudcoffee
echo "✅ Service created and enabled (will auto-start on reboot)."

# --- 5. Start the Bot ---
echo ""
echo "🚀 Step 5/5: Starting the bot now..."
sudo systemctl start nudcoffee
sleep 3
sudo systemctl status nudcoffee --no-pager

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ NUD COFFEE BOT IS LIVE — SETUP COMPLETE ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "📋 Useful commands:"
echo "   sudo systemctl status nudcoffee     → Check status"
echo "   sudo systemctl restart nudcoffee    → Restart bot"
echo "   sudo journalctl -u nudcoffee -f     → Live logs"
echo "   sudo systemctl stop nudcoffee       → Stop bot"
echo ""
