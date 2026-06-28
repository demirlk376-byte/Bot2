#!/bin/bash
# install_weekly_report.sh — haftalık canlı performans raporunu telefona (ntfy/
# Telegram) gönderen bir systemd timer kurar. Botun .env'indeki bildirim
# ayarlarını kullanır; borsaya/bota DOKUNMAZ (salt-okunur rapor).
#
# Kullanım (VPS'te, root):  bash install_weekly_report.sh
# Özelleştir:               BOT_DIR=/opt/bot2 DAY=Sun HOUR=18:00 bash install_weekly_report.sh
set -e

BOT_DIR="${BOT_DIR:-/opt/bot2}"
DAY="${DAY:-Sun}"          # OnCalendar günü (Mon..Sun)
HOUR="${HOUR:-18:00}"      # UTC saat
WINDOW_DAYS="${WINDOW_DAYS:-7}"

if [ ! -f "$BOT_DIR/live_report.py" ]; then
    echo "HATA: $BOT_DIR/live_report.py yok — önce 'git pull' yap." >&2
    exit 1
fi

echo "→ btc-bot-report.service yazılıyor ($BOT_DIR, son ${WINDOW_DAYS}g)..."
cat > /etc/systemd/system/btc-bot-report.service << EOF
[Unit]
Description=BTC Bot weekly performance report (push to ntfy/Telegram)
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$BOT_DIR
EnvironmentFile=$BOT_DIR/.env
ExecStart=$BOT_DIR/venv/bin/python live_report.py --days $WINDOW_DAYS --notify
StandardOutput=journal
StandardError=journal
EOF

echo "→ btc-bot-report.timer yazılıyor ($DAY $HOUR UTC)..."
cat > /etc/systemd/system/btc-bot-report.timer << EOF
[Unit]
Description=Weekly BTC Bot performance report

[Timer]
OnCalendar=$DAY *-*-* $HOUR:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now btc-bot-report.timer

echo "✓ Kuruldu. Sıradaki çalışma:"
systemctl list-timers btc-bot-report.timer --no-pager || true
echo ""
echo "Hemen test için:  systemctl start btc-bot-report.service && journalctl -u btc-bot-report -n 20 --no-pager"
