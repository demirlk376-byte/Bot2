#!/bin/bash
# install_sentinel.sh — botun DIŞINDAN çalışan nöbetçiyi kurar (ölü-adam anahtarı).
#
# NEDEN: heartbeat'i botun kendisi gönderiyor → bot tamamen ölürse hiç mesaj gelmez
# ve sessizlik "her şey yolunda" ile karışır. Bu iki timer o boşluğu kapatır:
#   btc-bot-sentinel.timer  → her 30 dk sağlık kontrolü, YALNIZ sorunda mesaj
#   btc-bot-report.timer    → haftalık özet ("sağım" kanıtı; gelmiyorsa nöbetçi de düşmüş)
#
# AYRICA: eski btc-bot-report.service BOZUKTU — live_report.py'yi olmayan
# '--days/--notify' bayraklarıyla çağırıyordu (script argparse kullanmıyor, hiç
# bildirim kodu da yok). Bu kurulum onu ÜZERİNE YAZARAK düzeltir.
#
# Borsaya/bota DOKUNMAZ, tamamı salt-okunur.
#
# Kullanım (VPS'te, root):  bash install_sentinel.sh
# Özelleştir: BOT_DIR=/opt/bot2 EVERY=30min DAY=Sun HOUR=18:00 bash install_sentinel.sh
set -e

BOT_DIR="${BOT_DIR:-/opt/bot2}"
SERVICE="${SERVICE:-btc-bot}"
EVERY="${EVERY:-30min}"
DAY="${DAY:-Sun}"
HOUR="${HOUR:-18:00}"
PY="$BOT_DIR/venv/bin/python"

[ -f "$BOT_DIR/sentinel.py" ] || { echo "HATA: $BOT_DIR/sentinel.py yok — önce git pull." >&2; exit 1; }
[ -x "$PY" ] || { echo "HATA: $PY yok." >&2; exit 1; }
[ -f "$BOT_DIR/.env" ] || { echo "HATA: $BOT_DIR/.env yok." >&2; exit 1; }

echo "→ btc-bot-sentinel.service (sağlık kontrolü)..."
cat > /etc/systemd/system/btc-bot-sentinel.service << EOF
[Unit]
Description=BTC Bot sentinel - external health watchdog
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$BOT_DIR
EnvironmentFile=$BOT_DIR/.env
Environment=BOT_DIR=$BOT_DIR
Environment=BOT_SERVICE=$SERVICE
ExecStart=$PY $BOT_DIR/sentinel.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/btc-bot-sentinel.timer << EOF
[Unit]
Description=Run BTC Bot sentinel every $EVERY

[Timer]
OnBootSec=5min
OnUnitActiveSec=$EVERY
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "→ btc-bot-report.service (haftalık özet — eski BOZUK birimin üzerine yazılıyor)..."
cat > /etc/systemd/system/btc-bot-report.service << EOF
[Unit]
Description=BTC Bot weekly summary push
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$BOT_DIR
EnvironmentFile=$BOT_DIR/.env
Environment=BOT_DIR=$BOT_DIR
Environment=BOT_SERVICE=$SERVICE
ExecStart=$PY $BOT_DIR/sentinel.py --report
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/btc-bot-report.timer << EOF
[Unit]
Description=Weekly BTC Bot summary ($DAY $HOUR UTC)

[Timer]
OnCalendar=$DAY *-*-* $HOUR:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now btc-bot-sentinel.timer
systemctl enable --now btc-bot-report.timer

echo
echo "→ bildirim yolu test ediliyor (telefonuna mesaj gelmeli)..."
set +e
BOT_DIR="$BOT_DIR" BOT_SERVICE="$SERVICE" \
  env $(grep -E '^(TELEGRAM_|NTFY_)' "$BOT_DIR/.env" | xargs) \
  "$PY" "$BOT_DIR/sentinel.py" --test
TEST_RC=$?
set -e

echo
systemctl list-timers 'btc-bot-*' --no-pager || true
echo
if [ $TEST_RC -eq 0 ]; then
  echo "✅ KURULDU ve bildirim ÇALIŞIYOR. Telefonundaki test mesajını gördüysen hazırsın."
else
  echo "⚠️ Timer'lar kuruldu AMA test mesajı gönderilemedi."
  echo "   .env içinde TELEGRAM_TOKEN + TELEGRAM_CHAT_ID (veya NTFY_TOPIC) dolu mu bak."
  echo "   Tekrar dene:  systemctl start btc-bot-sentinel.service && journalctl -u btc-bot-sentinel -n 20 --no-pager"
fi
echo
echo "Elle çalıştırmak istersen:"
echo "  $PY $BOT_DIR/sentinel.py            # sağlık kontrolü (temizse sessiz)"
echo "  $PY $BOT_DIR/sentinel.py --report   # özet gönder"
