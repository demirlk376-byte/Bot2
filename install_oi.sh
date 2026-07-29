#!/bin/bash
# install_oi.sh — Open Interest kaydediciyi 15 dakikalık timer'a bağlar.
#
# NEDEN: sahte kırılım için denenen HER özellik OHLCV'den geliyordu (fiyat NE YAPTI) ve hepsi
# başarısız oldu — giriş anında (AUC 0.502) ve girişten sonra (erken çıkış 13/13 kaybettirdi).
# OI farklı bir SORU sorar: pozisyon KİMDE? Kırılım+artan OI = yeni para = gerçek;
# kırılım+düşen OI = pozisyon kapanışı = stop avı = sahte. Bu ayrım OHLCV'de GÖRÜNMEZ.
#
# Geçmiş OI satın alınamaz, sadece BİRİKTİRİLİR. Bu yüzden bugün başlıyoruz.
# 15 dk çözünürlük: donchian 4h barlarda çalışıyor → bir kırılım barının içinde 16 örnek.
#
# Bota, borsaya, emirlere DOKUNMAZ. Sadece halka açık ticker endpoint'ini okur.
#
# Kullanım (VPS'te, root):  bash install_oi.sh
set -e

BOT_DIR="${BOT_DIR:-/opt/bot2}"
EVERY="${EVERY:-15min}"
PY="$BOT_DIR/venv/bin/python"

[ -f "$BOT_DIR/oi_collect.py" ] || { echo "HATA: $BOT_DIR/oi_collect.py yok — git pull yap." >&2; exit 1; }
[ -x "$PY" ] || { echo "HATA: $PY yok." >&2; exit 1; }

echo "→ btc-bot-oi.service yazılıyor..."
cat > /etc/systemd/system/btc-bot-oi.service << EOF
[Unit]
Description=BTC Bot open-interest collector (forward log for false-breakout research)
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$BOT_DIR
Environment=OI_CSV=$BOT_DIR/data/oi_log.csv
ExecStart=$PY $BOT_DIR/oi_collect.py
StandardOutput=journal
StandardError=journal
EOF

cat > /etc/systemd/system/btc-bot-oi.timer << EOF
[Unit]
Description=Collect open interest every $EVERY

[Timer]
OnBootSec=2min
OnUnitActiveSec=$EVERY
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now btc-bot-oi.timer

echo
echo "→ ilk kayıt alınıyor..."
systemctl start btc-bot-oi.service
sleep 3
echo
if [ -f "$BOT_DIR/data/oi_log.csv" ]; then
    echo "✅ KURULDU. İlk satırlar:"
    head -4 "$BOT_DIR/data/oi_log.csv"
    echo "   ..."
    echo "   satır sayısı: $(wc -l < "$BOT_DIR/data/oi_log.csv")"
else
    echo "⚠️ CSV oluşmadı — journalctl -u btc-bot-oi -n 20 --no-pager ile bak."
fi
echo
systemctl list-timers 'btc-bot-*' --no-pager || true
echo
echo "Büyüme: 12 coin × 4/saat × 24 × 365 ≈ 420k satır/yıl ≈ 25 MB. Disk sorunu değil."
echo "6-12 ay sonra: kırılım anındaki OI DEĞİŞİMİ kazananı kaybedenden ayırıyor mu test edilir."
