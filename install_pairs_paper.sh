#!/usr/bin/env bash
# install_pairs_paper.sh — pairs KÂĞIT koşucusunu günlük timer olarak kurar.
#
# SIFIR RİSK: pairs_paper.py emir göndermez, API anahtarı istemez, bot'un hiçbir
# dosyasına dokunmaz. Yalnızca MEXC'in PUBLIC uçlarından günlük kapanış çeker,
# z-skoru hesaplar ve "ne yapardım" kaydını pairs_paper.csv'ye yazar.
#
# AMAÇ: kullanıcı bir ay uzaktayken pairs için İLERİYE DÖNÜK (örneklem-dışı) veri
# biriktirmek. Dönüşte "backtest +$532 dedi, gerçekte ne oldu" karşılaştırılabilecek.
set -euo pipefail
BOT_DIR="${BOT_DIR:-/opt/bot2}"

cat > /etc/systemd/system/btc-bot-pairs-paper.service <<UNIT
[Unit]
Description=Pairs kagit kosucusu (emir GONDERMEZ)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$BOT_DIR
Environment=BOT_DIR=$BOT_DIR
ExecStart=/usr/bin/python3 $BOT_DIR/pairs_paper.py
UNIT

cat > /etc/systemd/system/btc-bot-pairs-paper.timer <<UNIT
[Unit]
Description=Pairs kagit kosucusu - gunde bir (gun kapanisindan sonra)

[Timer]
OnCalendar=*-*-* 00:20:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now btc-bot-pairs-paper.timer
echo "kuruldu. ilk tur simdi calistiriliyor:"
systemctl start btc-bot-pairs-paper.service
sleep 3
journalctl -u btc-bot-pairs-paper.service -n 30 --no-pager
echo
echo "Ozet icin:  cd $BOT_DIR && python3 pairs_paper.py --ozet"
