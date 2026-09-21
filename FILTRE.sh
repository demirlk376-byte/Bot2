#!/usr/bin/env bash
# ============================================================================
#  FILTRE.sh — Donchian sahte-kirilim filtresini TEK KOMUTLA ac/kapat.
#
#  Filtre iki kapidan olusur:
#    DONCHIAN_CONFIRM_BARS=1  kirilimdan sonraki bar seviyenin USTUNDE kapanmali
#    DONCHIAN_VOL_MULT=1.5    kirilim hacmi onceki 20 barin ortalamasinin 1.5 kati
#
#  IKIZ olcumu (1752 islem, TRAIN 2023-04..2024-12 / TEST 2025-01..2026-07):
#    donchian islem 1173 -> 764, ort R +0.150 -> +0.197
#    TEST MAR 3.31 -> 5.63, TEST maxDD %56.8 -> %55.6
#
#  Kullanim (VPS'te, /opt/bot2 icinde):
#    bash FILTRE.sh durum     -> su an acik mi, hangi degerlerle
#    bash FILTRE.sh ac        -> filtreyi ac, botu yeniden baslat, dogrula
#    bash FILTRE.sh kapat     -> filtreyi kapat, botu yeniden baslat, dogrula
#
#  Her degisiklikten ONCE .env yedeklenir. Bot yeniden baslamazsa komut
#  DURUR ve geri donus satirini yazar -- sessizce bozuk birakmaz.
# ============================================================================
set -uo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DOSYA="$KOK/.env"
SERVIS="btc-bot"
ANAHTARLAR=("DONCHIAN_CONFIRM_BARS" "DONCHIAN_VOL_MULT")
ACIK_DEGER=("1" "1.5")

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
print(f"    DONCHIAN_CONFIRM_BARS = {s.donchian_confirm_bars}")
print(f"    DONCHIAN_VOL_MULT     = {s.donchian_vol_mult}")
print(f"    islem basina risk     = %{r.max_risk_per_trade*100:.2f}")
acik = s.donchian_confirm_bars > 0 and s.donchian_vol_mult > 0
print(f"    FILTRE: {'ACIK' if acik else 'KAPALI'}")
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
    renk "=== FILTRE DURUMU ==="
    renk "  .env satirlari:"
    if [ -f "$ENV_DOSYA" ]; then
      grep -E "^[[:space:]]*(DONCHIAN_CONFIRM_BARS|DONCHIAN_VOL_MULT)=" "$ENV_DOSYA" \
        2>/dev/null || renk "    (satir yok -> filtre KAPALI)"
    else
      renk "    (.env dosyasi yok)"
    fi
    durum_yaz
    renk ""
    renk "  servis: $(systemctl is-active $SERVIS 2>/dev/null || echo bilinmiyor)"
    ;;
  ac)
    renk "=== FILTRE ACILIYOR ==="
    y="$(env_yaz ac | tail -1)"
    durum_yaz
    yeniden_baslat "$y"
    renk ""
    renk "  Filtre acildi. Ilk Donchian sinyalinde logda [teyit1b] etiketi gorunmeli:"
    renk "    journalctl -u $SERVIS -f | grep -i donchian"
    ;;
  kapat)
    renk "=== FILTRE KAPATILIYOR ==="
    y="$(env_yaz kapat | tail -1)"
    durum_yaz
    yeniden_baslat "$y"
    renk "  Filtre kapatildi (bugunku davranisa donuldu)."
    ;;
  *)
    hata "bilinmeyen komut: $1"
    renk "  kullanim: bash FILTRE.sh [durum|ac|kapat]"
    exit 2
    ;;
esac
