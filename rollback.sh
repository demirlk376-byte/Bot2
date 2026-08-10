#!/usr/bin/env bash
# rollback.sh — SAĞLAM SÜRÜME GERİ DÖN. Mutabakat değişikliği bozarsa tek komut.
#
# NEDEN VAR: pairs için mutabakat mantığına (get_position / position_reconciliation_loop /
# _resync_symbol_stops_locked) dokunuyoruz. Bu mantık hata yaparsa AÇIK pozisyonları
# "kapandı" sayıp deftere UYDURMA PnL yazar — sessiz bozulma. Kullanıcı bir ay uzakta
# olacağı için geri dönüş yolu ÖNCEDEN kurulmalı ve ÇALIŞTIĞI KANITLANMALI.
#
# SAĞLAM SÜRÜM: c757a3a5eab3930ea35e394762ed2f12df37a498
#   "research: EMA200 kapısı denetlendi — kapı hak ediyor"
#   DOĞRULANMIŞ: 9/9 test · canlıda 70 kapanan işlem / PnL +$24.73 / bakiye $215.45
#   temiz dönem 21 işlem +$32.66 PF 1.91 · R:R donchian 2.29/2.50 mean_rev 1.68/1.667
#
# ⚠️ KAPSAM: bu betik YALNIZCA KODU geri alır.
#    .env (config)  → git'te DEĞİL, dokunulmaz, olduğu gibi kalır
#    trades.db      → dokunulmaz (işlem geçmişi KORUNUR)
#    açık pozisyonlar → borsada durur; SL/TP emirleri çalışmaya devam eder
#
# KULLANIM:
#   bash rollback.sh --snapshot   # mevcut hali yedekle (değişiklikten ÖNCE çalıştır)
#   bash rollback.sh --kontrol    # geri dönüş yapmadan yalnızca DOĞRULA (kuru çalışma)
#   bash rollback.sh              # SAĞLAM sürüme dön, test et, yeniden başlat
set -uo pipefail

SAGLAM="c757a3a5eab3930ea35e394762ed2f12df37a498"
BOT_DIR="${BOT_DIR:-/opt/bot2}"
SERVICE="${BOT_SERVICE:-btc-bot}"
YEDEK_KOK="${YEDEK_KOK:-/opt/bot2-yedek}"
DAL="claude/btc-intraday-trading-engine-U2C8A"

cd "$BOT_DIR" || { echo "✗ $BOT_DIR yok"; exit 1; }

testleri_kos() {
  local gecen=0 kalan=0
  for f in tests/test_*.py; do
    [ -e "$f" ] || continue
    if python3 "$f" >/dev/null 2>&1; then gecen=$((gecen+1)); else kalan=$((kalan+1)); echo "   FAIL $f"; fi
  done
  echo "   test: $gecen geçti · $kalan kaldı"
  [ "$kalan" -eq 0 ]
}

# ── SNAPSHOT ────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--snapshot" ]; then
  ts=$(date -u +%Y%m%d-%H%M%S)
  hedef="$YEDEK_KOK/$ts"
  mkdir -p "$hedef"
  # .git HARİÇ tüm çalışma ağacı + mevcut SHA kaydı
  tar --exclude=.git --exclude=__pycache__ --exclude='*.pyc' \
      -czf "$hedef/calisma-agaci.tar.gz" . 2>/dev/null
  git rev-parse HEAD > "$hedef/HEAD.sha"
  git status --short > "$hedef/git-status.txt" 2>&1
  cp -a .env "$hedef/.env.kopya" 2>/dev/null && echo "   .env de kopyalandı"
  echo "✓ yedek: $hedef"
  echo "   HEAD: $(cat "$hedef/HEAD.sha")"
  echo "   boyut: $(du -sh "$hedef" | cut -f1)"
  echo
  echo "   Bu yedekten ELLE dönmek için:"
  echo "     systemctl stop $SERVICE"
  echo "     tar -xzf $hedef/calisma-agaci.tar.gz -C $BOT_DIR"
  echo "     systemctl start $SERVICE"
  exit 0
fi

# ── KONTROL (kuru çalışma) ──────────────────────────────────────────────────
if [ "${1:-}" = "--kontrol" ]; then
  echo "═══ GERİ DÖNÜŞ KONTROLÜ (hiçbir şey değiştirilmiyor) ═══"
  echo "  şu anki HEAD : $(git rev-parse HEAD)"
  echo "  sağlam sürüm : $SAGLAM"
  if git cat-file -e "$SAGLAM^{commit}" 2>/dev/null; then
    echo "  ✓ sağlam commit yerel depoda MEVCUT — geri dönüş mümkün"
  else
    echo "  ⚠ sağlam commit yerelde yok, uzaktan çekilecek:"
    git fetch origin "$DAL" 2>&1 | tail -1
    git cat-file -e "$SAGLAM^{commit}" 2>/dev/null \
      && echo "  ✓ çekildi, geri dönüş mümkün" \
      || { echo "  ✗ ULAŞILAMIYOR — geri dönüş YAPILAMAZ, önce bunu çöz"; exit 1; }
  fi
  echo "  servis: $(systemctl is-active "$SERVICE" 2>/dev/null || echo bilinmiyor)"
  echo "  yedekler: $(ls -1 "$YEDEK_KOK" 2>/dev/null | wc -l) adet"
  echo "  mevcut sürümün testleri:"
  testleri_kos && echo "  ✓ şu anki sürüm sağlıklı" || echo "  ⚠ ŞU ANKİ SÜRÜM TEST GEÇMİYOR"
  exit 0
fi

# ── GERİ DÖNÜŞ ──────────────────────────────────────────────────────────────
echo "═══ GERİ DÖNÜŞ: sağlam sürüme dönülüyor ═══"
echo "  şu anki : $(git rev-parse --short HEAD)"
echo "  hedef   : ${SAGLAM:0:7}"

# 1) her ihtimale karşı mevcut hali yedekle
echo "→ [1/5] mevcut hal yedekleniyor…"
bash "$0" --snapshot | sed 's/^/   /'

# 2) botu durdur (pozisyonlar borsada kalır, SL/TP çalışmaya devam eder)
echo "→ [2/5] bot durduruluyor (pozisyonlar borsada KALIR)…"
systemctl stop "$SERVICE" 2>/dev/null || echo "   (servis zaten duruk)"

# 3) sağlam sürüme dön
echo "→ [3/5] kod geri alınıyor…"
git cat-file -e "$SAGLAM^{commit}" 2>/dev/null || git fetch origin "$DAL" 2>&1 | tail -1
if ! git reset --hard "$SAGLAM" 2>&1 | tail -1; then
  echo "   ✗ reset BAŞARISIZ — bot DURUK bırakıldı. Yedekten elle dönün."
  exit 1
fi

# 4) doğrula
echo "→ [4/5] testler…"
if ! testleri_kos; then
  echo
  echo "  ✗✗✗ SAĞLAM SÜRÜM DE TEST GEÇMİYOR — bot BAŞLATILMIYOR."
  echo "      Bu, kod dışı bir sorun demek (paket eksik? disk? python sürümü?)."
  echo "      Bot DURUK. Açık pozisyonlar borsada, SL/TP'leri çalışıyor."
  exit 1
fi

# 5) başlat
echo "→ [5/5] bot başlatılıyor…"
systemctl start "$SERVICE"
sleep 10
durum=$(systemctl is-active "$SERVICE" 2>/dev/null)
echo "   servis: $durum"
if [ "$durum" = "active" ]; then
  echo
  echo "✓ GERİ DÖNÜŞ TAMAM — sağlam sürüm çalışıyor."
  echo "  Telegram'dan /status ile bakiyeyi teyit edin."
else
  echo
  echo "✗ servis başlamadı. Günlük:"
  journalctl -u "$SERVICE" -n 30 --no-pager
fi
