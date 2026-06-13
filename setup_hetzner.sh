#!/bin/bash
# setup_hetzner.sh — Bot2'yi Hetzner VPS'e kur (bir kez çalıştır)
# Kullanım: ssh root@<IP> 'bash -s' < setup_hetzner.sh
set -e

REPO_URL="https://github.com/demirlk376-byte/Bot2.git"
REPO_BRANCH="claude/btc-intraday-trading-engine-U2C8A"
BOT_DIR="/opt/bot2"
BOT_USER="botuser"

echo "=== [1/6] Sistem güncellemesi ==="
apt-get update -qq && apt-get install -y -qq git python3 python3-pip python3-venv

echo "=== [2/6] Kullanıcı oluşturuluyor ==="
id "$BOT_USER" &>/dev/null || useradd -m -s /bin/bash "$BOT_USER"

echo "=== [3/6] Repo klonlanıyor ==="
if [ -d "$BOT_DIR" ]; then
    cd "$BOT_DIR" && git fetch origin && git checkout "$REPO_BRANCH" && git pull origin "$REPO_BRANCH"
else
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$BOT_DIR"
fi
chown -R "$BOT_USER:$BOT_USER" "$BOT_DIR"

echo "=== [4/6] Python venv + bağımlılıklar ==="
sudo -u "$BOT_USER" bash -c "
    cd $BOT_DIR
    python3 -m venv venv
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
"

echo "=== [5/6] .env dosyası ==="
if [ ! -f "$BOT_DIR/.env" ]; then
    cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
    echo ""
    echo ">>> .env dosyası oluşturuldu. Düzenlemek için:"
    echo "    nano $BOT_DIR/.env"
    echo "    (En azından TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID gir)"
fi

echo "=== [6/6] systemd servisi kuruluyor ==="
cat > /etc/systemd/system/btc-bot.service << EOF
[Unit]
Description=BTC Trading Bot
After=network.target
Wants=network.target

[Service]
User=$BOT_USER
WorkingDirectory=$BOT_DIR
EnvironmentFile=$BOT_DIR/.env
ExecStart=$BOT_DIR/venv/bin/python main.py
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable btc-bot
echo ""
echo "================================================================"
echo "  Kurulum tamamlandi!"
echo "  1. .env ayarla:  nano $BOT_DIR/.env"
echo "  2. Botu baslat:  systemctl start btc-bot"
echo "  3. Loglar:       journalctl -u btc-bot -f"
echo "================================================================"
