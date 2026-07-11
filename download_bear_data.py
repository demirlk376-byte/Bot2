"""
download_bear_data.py — 2023 + 2024 BTC 1m verisini indirir (ayı/geçiş dönemi).

Neden: portföy simülasyonunun +%40/ay medyanı 2025-05→2026-04 (tek rejim)
penceresinden geliyor. 2023 (ayı sonrası dip) + 2024 (geçiş) farklı rejim
çeşitliliği katar. DÜRÜST NOT: 2023-24 bazı sleeve'lerin geliştirilmesinde
kullanıldı (research_sim_100 bu dönemi "in-sample, İYİMSER" etiketler) —
yani bu saf out-of-sample DEĞİL, rejim-dayanıklılık kontrolü: 2023-24'te
bile negatifse model tek rejimin hediyesi demektir ve beklenti kırpılır.

VPS'te (Binance erişimi olan makinede):
    cd /opt/bot2
    venv/bin/python download_bear_data.py
    venv/bin/python research_sim_100.py     # dönem-ayrımlı raporu basar
"""
from __future__ import annotations

from pathlib import Path

from download_data import download

OUT = Path(__file__).parent
MONTHS = [f"2023-{m:02d}" for m in range(1, 13)] + \
         [f"2024-{m:02d}" for m in range(1, 13)]


def main() -> None:
    ok = 0
    for month in MONTHS:
        if download("BTCUSDT", month, OUT):
            ok += 1
    print(f"\n{ok}/{len(MONTHS)} ay indi.")
    if ok == len(MONTHS):
        print("Şimdi koş:  venv/bin/python research_sim_100.py")
    else:
        print("Eksik aylar var — scripti tekrar çalıştırmak kaldığı yerden devam eder.")


if __name__ == "__main__":
    main()
