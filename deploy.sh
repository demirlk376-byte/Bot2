#!/bin/bash
# deploy.sh — Kodu VPS'e güncelle ve botu yeniden başlat
# Kullanım: ./deploy.sh <VPS_IP>
# Örnek:    ./deploy.sh 65.21.100.200
set -e

VPS_IP="${1:-}"
if [ -z "$VPS_IP" ]; then
    echo "Kullanim: ./deploy.sh <VPS_IP>"
    exit 1
fi

echo "→ Kod VPS'e gönderiliyor ($VPS_IP)..."
ssh "root@$VPS_IP" "cd /opt/bot2 && git pull && venv/bin/pip install -q -r requirements.txt"

echo "→ Bot yeniden başlatılıyor..."
ssh "root@$VPS_IP" "systemctl restart btc-bot && sleep 2 && systemctl status btc-bot --no-pager"

echo "✓ Tamam. Loglar için: ssh root@$VPS_IP 'journalctl -u btc-bot -f'"
