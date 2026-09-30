#!/usr/bin/env bash
# FAILED_PULLBACK_V1 — tüm ikiz koşuları + analiz. Repo kökünden:
#   bash arastirma/failed_pullback_v1/kos_hepsi.sh [CIKTI_DIZINI] [PARALEL]
# Her koşu ~23 dk (4 çekirdekte 3 paralel ≈ 1.5 sa). Emir yok, ağ yok, data/ salt okunur.
set -euo pipefail
KOK="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$KOK/fpb_kosular}"
PAR="${2:-3}"
mkdir -p "$OUT"
python3 "$KOK/arastirma/failed_pullback_v1/fpb_risk_haritasi.py" > "$OUT/risk_haritasi.log"

# AD MOD SLIP_KAT FIX_FUNDING ADAY_CIKIS_SLIP_BP
cat > "$OUT/kosular.txt" <<'EOF'
A A 1 0 -
A75 A75 1 0 -
B B 1 0 -
S S 1 0 -
B_2x B 2 0 -
A_2x A 2 0 -
A75_2x A75 2 0 -
S_2x S 2 0 -
S_cikis S 1 0 15.85
A_f A 1 1 -
A75_f A75 1 1 -
B_f B 1 1 -
EOF

kos() {
  AD=$1; MOD=$2; KAT=$3; FF=$4; AC=$5
  mkdir -p "$OUT/$AD"
  cd "$OUT/$AD"
  if [ "$AC" = "-" ]; then unset ADAY_CIKIS_SLIP_BP; else export ADAY_CIKIS_SLIP_BP=$AC; fi
  AD=$AD MOD=$MOD SLIP_KAT=$KAT FIX_FUNDING=$FF REPLAY_DB="$OUT/$AD/$AD.db" \
    python3 "$KOK/arastirma/failed_pullback_v1/fpb_kos.py" > "$OUT/$AD/kos.log" 2>&1
  for f in "$OUT/$AD/${AD}_"*; do cp "$f" "$OUT/"; done
  echo "bitti $AD"
}
export -f kos
export OUT KOK
xargs -P "$PAR" -L 1 bash -c 'kos "$@"' _ < "$OUT/kosular.txt"
python3 "$KOK/arastirma/failed_pullback_v1/fpb_analiz.py" "$OUT"
