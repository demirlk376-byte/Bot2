#!/usr/bin/env bash
# ============================================================================
#  FILTRE.sh — KAZANAN AYARI (hacim2.5 + %3.5 risk) TEK KOMUTLA ac/kapat.
#
#  Ayar:
#    DONCHIAN_VOL_MULT=2.5    kirilim hacmi onceki 20 barin ortalamasinin 2.5 kati
#    RISK_SCALE=1.75          islem basina risk %2.8 -> %3.5
#
#  ⚠ RISK DE DEGISIYOR, sadece filtre degil. Sebebi: hacim2.5 dususu %62'den
#  %39'a indiriyor ve bu KULLANILMAMIS RISK ALANI demek. Riski %3.5'e cikarmak
#  IKI YARIDA DA iyilestirdi (dTR +1.02 / dTE +2.43). Ayni sey rakip ayarda
#  (teyit1+h1.5) TRAIN'i BOZDU (dTR -0.59) -- yani bu, hacim2.5'e ozgu.
#
#  IKIZ olcumu (OLCULEN maliyetle: giris 15.85bp, cikis 0.24bp, funding):
#    islem      1752 -> 1013   (gunde 1.46 -> ~0.85)
#    aylik      %5.53 -> %8.51
#    TEST maxDD %61.8 -> %42.8
#    TEST MAR   1.47 -> 3.89
#  Kendi maliyet grubunun tabanina gore IKI YARIDA DA gecti.
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
ANAHTARLAR=("DONCHIAN_VOL_MULT" "RISK_SCALE")
ACIK_DEGER=("2.5" "1.75")

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
print(f"    DONCHIAN_VOL_MULT  = {s.donchian_vol_mult}")
print(f"    islem basina risk  = %{r.max_risk_per_trade*100:.2f}")
acik = s.donchian_vol_mult >= 2.5
print(f"    AYAR: {'ACIK (hacim2.5 + %3.5 risk)' if acik else 'KAPALI'}")
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
      grep -E "^[[:space:]]*(DONCHIAN_VOL_MULT|RISK_SCALE)=" "$ENV_DOSYA" \
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
    renk "  Ayar acildi. Beklenen degisim (3 ay sonra sinanacak):"
    renk "    - donchian islem hizi ~%42 DUSER (gunde 1.46 -> ~0.85)"
    renk "    - risk %2.8 -> %3.5, yani pozisyonlar ~%25 BUYUR"
    renk "  Izle:  journalctl -u $SERVIS -f | grep -iE 'donchian|hacim zayif'"
    ;;
  kapat)
    renk "=== FILTRE KAPATILIYOR ==="
    y="$(env_yaz kapat | tail -1)"
    durum_yaz
    yeniden_baslat "$y"
    renk "  Ayar kapatildi (bugunku davranisa donuldu)."
    ;;
  *)
    hata "bilinmeyen komut: $1"
    renk "  kullanim: bash FILTRE.sh [durum|ac|kapat]"
    exit 2
    ;;
esac
