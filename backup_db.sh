#!/bin/bash
# backup_db.sh — trades.db'yi güvenli şekilde yedekle (günlük rotasyon, son 14 gün)
# systemd timer ile günde bir çalışır. SQLite .backup kullanır (canlı DB'de güvenli).
set -e

BOT_DIR="/opt/bot2"
DB="$BOT_DIR/trades.db"
BACKUP_DIR="$BOT_DIR/backups"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
[ -f "$DB" ] || { echo "DB yok: $DB"; exit 0; }

STAMP="$(date -u +%Y%m%d-%H%M)"
OUT="$BACKUP_DIR/trades-$STAMP.db"

# .backup canlı veritabanını kilitlemeden tutarlı kopya alır
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"
echo "Yedek alındı: $OUT.gz"

# Eski yedekleri temizle
find "$BACKUP_DIR" -name 'trades-*.db.gz' -mtime +$KEEP_DAYS -delete
