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

echo "=== [7/8] Günlük DB yedeği (systemd timer) ==="
apt-get install -y -qq sqlite3 || true
chmod +x "$BOT_DIR/backup_db.sh"
cat > /etc/systemd/system/btc-bot-backup.service << EOF
[Unit]
Description=BTC Bot DB backup
[Service]
Type=oneshot
ExecStart=/bin/bash $BOT_DIR/backup_db.sh
EOF
cat > /etc/systemd/system/btc-bot-backup.timer << EOF
[Unit]
Description=Daily BTC Bot DB backup
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now btc-bot-backup.timer

echo "=== [8/8] Watchdog (donmuş bot'u yeniden başlat) ==="
# Heartbeat /tmp/bot_alive'ı 5 dk'da bir günceller. 15 dk güncellenmezse
# bot donmuş demektir → servisi yeniden başlat.
cat > /usr/local/bin/btc-bot-watchdog.sh << 'EOF'
#!/bin/bash
F=/tmp/bot_alive
if [ -f "$F" ]; then
    AGE=$(( $(date +%s) - $(cat "$F" 2>/dev/null || echo 0) ))
    if [ "$AGE" -gt 900 ]; then
        echo "Heartbeat $AGE s eski — bot yeniden başlatılıyor"
        systemctl restart btc-bot
    fi
fi
EOF
chmod +x /usr/local/bin/btc-bot-watchdog.sh
cat > /etc/systemd/system/btc-bot-watchdog.service << EOF
[Unit]
Description=BTC Bot watchdog
[Service]
Type=oneshot
ExecStart=/usr/local/bin/btc-bot-watchdog.sh
EOF
cat > /etc/systemd/system/btc-bot-watchdog.timer << EOF
[Unit]
Description=BTC Bot watchdog every 5 min
[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now btc-bot-watchdog.timer

echo ""
echo "================================================================"
echo "  Kurulum tamamlandi!"
echo "  1. .env ayarla:  nano $BOT_DIR/.env"
echo "  2. Botu baslat:  systemctl start btc-bot"
echo "  3. Loglar:       journalctl -u btc-bot -f"
echo "  Yedekler:        $BOT_DIR/backups/  (gunluk, 14 gun saklanir)"
echo "  Watchdog:        donmus bot 15 dk'da otomatik yeniden baslar"
echo "================================================================"
