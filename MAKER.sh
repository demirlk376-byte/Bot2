#!/usr/bin/env bash
# ============================================================================
#  MAKER.sh — Donchian MAKER GIRISINI TEK KOMUTLA ac/kapat.
#
#    DONCHIAN_MAKER_ENTRY=true
#
#  NE YAPAR: donchian girisi PIYASA emri yerine MAKER limit emri koyar.
#  Dolmazsa 45 sn sonra PIYASA yedegine duser (execution.py:636) -- yani
#  HICBIR ISLEM KACMAZ, sadece odenen fiyat degisir. Kazanc: taker ucreti +
#  15.85bp giris kaymasi yerine maker (%0 ucret, kaymasiz).
#
#  IKIZ olcumu (OLCULEN maliyetle, TEST yarisi):
#    islem sayisi  1752 -> 1752  (DEGISMIYOR, hicbir islem kacmiyor)
#    yillik %90.7 -> %139.8   aylik %5.5 -> %7.6   maxDD %61.8 -> %59.2
#    Dort karsilastirmanin (filtreli/filtresiz x TRAIN/TEST) DORDUNDE de kazandi
#    ve %50 dolum kotumser senaryosunda bile kazanmaya devam etti.
#
#  Kullanim (VPS'te, /opt/bot2 icinde):
#    bash MAKER.sh durum     -> su an acik mi, hangi degerlerle
#    bash MAKER.sh ac        -> filtreyi ac, botu yeniden baslat, dogrula
#    bash MAKER.sh kapat     -> filtreyi kapat, botu yeniden baslat, dogrula
#
#  Her degisiklikten ONCE .env yedeklenir. Bot yeniden baslamazsa komut
#  DURUR ve geri donus satirini yazar -- sessizce bozuk birakmaz.
# ============================================================================
set -uo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DOSYA="$KOK/.env"
SERVIS="btc-bot"
ANAHTARLAR=("DONCHIAN_MAKER_ENTRY")
ACIK_DEGER=("true")

renk() { printf '%s\n' "$*"; }
hata() { printf '  !! %s\n' "$*" >&2; }

py() {
  # venv varsa onu kullan; yoksa sistem python'u
  for p in "$KOK/venv/bin/python" "$KOK/.venv/bin/python" python3 python; do
    if command -v "$p" >/dev/null 2>&1 || [ -x "$p" ]; then echo "$p"; return; fi
  done
  echo python3
}

durum_yaz() {
  renk ""
  renk "  --- AYARIN KODDA OKUNAN HALI ---"
  ( cd "$KOK" && "$(py)" - <<'PYEOF' 2>&1 || echo "  (config okunamadi)"
from config import load_config
c = load_config()
s, r = c.strategy, c.risk
e = c.exchange
print(f"    DONCHIAN_MAKER_ENTRY = {e.donchian_maker_entry}")
print(f"    MAKER_ENTRY (genel)  = {e.maker_entry}")
print(f"    MAKER GIRISI: {'ACIK' if e.donchian_maker_entry else 'KAPALI'}")
PYEOF
  )
}

env_yaz() {
  # $1=ac|kapat  — anahtarlari temizle, acilacaksa yeniden ekle
  local yedek="$ENV_DOSYA.yedek-$(date +%Y%m%d-%H%M%S)"
  cp "$ENV_DOSYA" "$yedek" || { hata ".env yedeklenemedi, DURDUM"; exit 1; }
  renk "  yedek: $yedek"

  local desen
  desen="$(IFS='|'; echo "${ANAHTARLAR[*]}")"
  grep -v -E "^[[:space:]]*($desen)=" "$ENV_DOSYA" > "$ENV_DOSYA.tmp" \
    || { hata ".env yazilamadi, DURDUM"; rm -f "$ENV_DOSYA.tmp"; exit 1; }
  mv "$ENV_DOSYA.tmp" "$ENV_DOSYA"

  if [ "$1" = "ac" ]; then
    local i
    for i in "${!ANAHTARLAR[@]}"; do
      printf '%s=%s\n' "${ANAHTARLAR[$i]}" "${ACIK_DEGER[$i]}" >> "$ENV_DOSYA"
    done
  fi
  echo "$yedek"
}

yeniden_baslat() {
  local yedek="$1"
  renk "  bot yeniden baslatiliyor..."
  systemctl restart "$SERVIS" || { hata "restart basarisiz"; }
  sleep 20
  if systemctl is-active --quiet "$SERVIS"; then
    renk "  servis: ACTIVE ✓"
    return 0
  fi
  hata "SERVIS AYAKTA DEGIL. Son loglar:"
  journalctl -u "$SERVIS" -n 25 --no-pager >&2
  hata "GERI DONUS:  cp '$yedek' '$ENV_DOSYA' && systemctl restart $SERVIS"
  exit 1
}

# ⚠ .env yoksa ac/kapat ANLAMSIZ -- sessizce yeni dosya olusturup botu
# varsayilanlarla baslatmak canliyi habersiz degistirirdi.
if [ "${1:-durum}" != "durum" ] && [ ! -f "$ENV_DOSYA" ]; then
  hata ".env bulunamadi: $ENV_DOSYA"
  hata "Bu betigi botun kurulu oldugu dizinde calistir (ornegin /opt/bot2)."
  exit 1
fi

case "${1:-durum}" in
  durum)
    renk "=== MAKER GIRISI DURUMU ==="
    renk "  .env satirlari:"
    if [ -f "$ENV_DOSYA" ]; then
      grep -E "^[[:space:]]*(DONCHIAN_MAKER_ENTRY)=" "$ENV_DOSYA" \
        2>/dev/null || renk "    (satir yok -> filtre KAPALI)"
    else
      renk "    (.env dosyasi yok)"
    fi
    durum_yaz
    renk ""
    renk "  servis: $(systemctl is-active $SERVIS 2>/dev/null || echo bilinmiyor)"
    ;;
  ac)
    renk "=== MAKER GIRISI ACILIYOR ==="
    y="$(env_yaz ac | tail -1)"
    durum_yaz
    yeniden_baslat "$y"
    renk ""
    renk "  Maker girisi acildi. Ilk donchian girisinde logda '(maker)' gorunmeli:"
    renk "    journalctl -u $SERVIS -f | grep -iE 'donchian|LIMIT|maker'"
    renk "  ⚠ 2-4 hafta sonra KAC girisin maker doldugunu, kacinin 45sn sonra"
    renk "    PIYASA yedegine dustugunu say. IKIZ %66 dolum varsaydi."
    ;;
  kapat)
    renk "=== MAKER GIRISI KAPATILIYOR ==="
    y="$(env_yaz kapat | tail -1)"
    durum_yaz
    yeniden_baslat "$y"
    renk "  Maker girisi kapatildi (piyasa emrine donuldu)."
    ;;
  *)
    hata "bilinmeyen komut: $1"
    renk "  kullanim: bash MAKER.sh [durum|ac|kapat]"
    exit 2
    ;;
esac
