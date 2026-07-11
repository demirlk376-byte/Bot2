#!/bin/bash
# setup_paper_forward.sh — TAM SİSTEM paper forward testi kurar (VPS).
#
# Neden: paper_scanner sadece BB sleeve'ini izliyor. Botun kendisini ikinci
# bir instance olarak PAPER modda çalıştırmak, canlıyla AYNI kodu + AYNI 7
# sleeve'i + AYNI config'i sanal $10k ile ileri veride test eder. 4-6 hafta
# sonra "model (+%40/ay medyan) canlı veride ne veriyor?" sorusunun tam-sistem
# cevabı bu instance'ın DB'sinden okunur.
#
# Güvenlik: PAPER_MODE=true → hiçbir gerçek emir gönderilmez (PaperExchange).
# Bildirimler kapalı (canlı botun Telegram'ıyla karışmasın), web dashboard
# kapalı (port çakışması olmasın), ayrı klasör → ayrı trades.db.
#
# Kullanım (root):  cd /opt/bot2 && bash setup_paper_forward.sh
# Durum:            systemctl status btc-bot-paper
# Rapor:            cd /opt/bot2-paper && /opt/bot2/venv/bin/python live_report.py
set -euo pipefail

LIVE_DIR=/opt/bot2
PAPER_DIR=/opt/bot2-paper
VENV_PY=$LIVE_DIR/venv/bin/python

[ -d "$LIVE_DIR" ] || { echo "HATA: $LIVE_DIR yok"; exit 1; }
[ -x "$VENV_PY" ]  || { echo "HATA: $VENV_PY yok"; exit 1; }

# 0) Git "dubious ownership" koruması: root, farklı kullanıcıya ait repoyu
#    klonlarken/okurken git reddediyor — iki dizini de güvenli ilan et.
git config --global --add safe.directory "$LIVE_DIR"
git config --global --add safe.directory "$LIVE_DIR/.git"
git config --global --add safe.directory "$PAPER_DIR"

# 1) Kod kopyası (yerel clone — canlı repo neyse o, aynı branch)
#    Önceki başarısız denemeden yarım dizin kaldıysa (içinde .git yok) temizle.
if [ -d "$PAPER_DIR" ] && [ ! -d "$PAPER_DIR/.git" ]; then
    rm -rf "$PAPER_DIR"
fi
if [ ! -d "$PAPER_DIR" ]; then
    git clone "$LIVE_DIR" "$PAPER_DIR"
    git -C "$PAPER_DIR" checkout "$(git -C $LIVE_DIR rev-parse --abbrev-ref HEAD)"
else
    git -C "$PAPER_DIR" pull origin "$(git -C $LIVE_DIR rev-parse --abbrev-ref HEAD)" || true
fi
# Güncellemeleri canlı repodan çekebilsin
git -C "$PAPER_DIR" remote set-url origin "$LIVE_DIR"

# 2) .env: canlının kopyası + paper override'ları (dotenv'de SON satır kazanır)
cp "$LIVE_DIR/.env" "$PAPER_DIR/.env"
cat >> "$PAPER_DIR/.env" <<'EOF'

# ── paper-forward override'ları (setup_paper_forward.sh) ────────────
PAPER_MODE=true
PAPER_INITIAL_BALANCE=10000
TELEGRAM_ENABLED=false
NTFY_ENABLED=false
WEB_DASHBOARD_ENABLED=false
DB_PATH=./trades.db
EOF

# 3) systemd servisi
cat > /etc/systemd/system/btc-bot-paper.service <<EOF
[Unit]
Description=BTC Trading Bot — FULL-SYSTEM PAPER forward test
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PAPER_DIR
ExecStart=$VENV_PY main.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now btc-bot-paper

echo
echo "════════════════════════════════════════════════════════════"
echo "  ✓ Tam-sistem paper forward testi çalışıyor ($PAPER_DIR)"
echo "  Durum : systemctl status btc-bot-paper --no-pager -n 5"
echo "  Log   : journalctl -u btc-bot-paper -n 30 --no-pager"
echo "  Rapor : cd $PAPER_DIR && $VENV_PY live_report.py"
echo "  4-6 hafta sonra bu rapor 'model vs gerçek' cevabını verir."
echo "════════════════════════════════════════════════════════════"
