#!/usr/bin/env bash
# LIQUIDITY_SWEEP_V1 — tek komutla tam koşu. Canlı checkout'a DOKUNMAZ: izole bir kopyada çalışır.
#   bash research/liquidity_sweep_v1/run_sweep_v1.sh [ÇALIŞMA_DİZİNİ]
# Varsayılan çalışma dizini: /tmp/sweep_v1 (VPS'te canlı /opt/bot2 yerine).
# Gereken ham veri: GitHub 'veri/sweep5m' dalı → veri/ (Binance USDⓈ-M 5m 12 coin 2023-01→,
#   fundingRate, MEXC contract/detail). Hiçbir veritabanı silinmez/taşınmaz; ağdan emir yok.
set -euo pipefail
WD="${1:-/tmp/sweep_v1}"
REPO_URL="$(git -C "$(dirname "$0")/../.." remote get-url origin)"
if [ ! -d "$WD/.git" ]; then
  git clone --quiet --branch research/liquidity-sweep-v1 "$REPO_URL" "$WD"
fi
cd "$WD"
git fetch --quiet origin research/liquidity-sweep-v1 veri/sweep5m
git checkout --quiet research/liquidity-sweep-v1 && git pull --quiet --ff-only
mkdir -p research_data/liquidity_sweep_v1
git archive origin/veri/sweep5m veri | tar -x -C research_data/liquidity_sweep_v1/
PY="${PYTHON:-python3}"
nice -n 19 "$PY" -m research.liquidity_sweep_v1.cli doctor
nice -n 19 "$PY" -m research.liquidity_sweep_v1.cli verify
nice -n 19 "$PY" -m research.liquidity_sweep_v1.cli run-all --jobs 1
ls -1d research_outputs/liquidity_sweep_v1/*/ | tail -1
