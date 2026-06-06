"""
download_data.py

Binance public data mirror'dan 1m OHLCV indirir.
Hedef coinler: BTC, ETH, SOL, BNB, XRP (genişletilebilir)

Kullanım:
  python download_data.py                   # tüm coinler, tüm aylar
  python download_data.py SOL BNB           # sadece belirtilen coinler
  python download_data.py --months 6        # son N ay

Çıktı: ./data/<SYMBOL>-1m-<YYYY-MM>.csv
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE_SPOT    = "https://data.binance.vision/data/spot/monthly/klines"
BASE_FUTURES = "https://data.binance.vision/data/futures/um/monthly/klines"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# Ay listesi — strateji backtest dönemi
MONTHS = [
    "2025-05","2025-06","2025-07","2025-08",
    "2025-09","2025-10","2025-11","2025-12",
    "2026-01","2026-02","2026-03","2026-04",
]


def download(symbol: str, month: str, out_dir: Path, use_futures=False) -> bool:
    base = BASE_FUTURES if use_futures else BASE_SPOT
    fname = f"{symbol}-1m-{month}.zip"
    url   = f"{base}/{symbol}/1m/{fname}"
    out_csv = out_dir / f"{symbol}-1m-{month}.csv"

    if out_csv.exists():
        print(f"  {out_csv.name} zaten var, atlanıyor")
        return True

    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    csvname = z.namelist()[0]
                    data = z.read(csvname)
                # Binance CSV header yok — ekle
                header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
                out_csv.write_bytes(header.encode() + data)
                print(f"  {out_csv.name}  {len(data)//1024}KB")
                return True
            elif r.status_code == 404:
                print(f"  {fname} bulunamadı (404) — ay henüz yayınlanmamış olabilir")
                return False
            else:
                print(f"  {fname} HTTP {r.status_code}, deneme {attempt+1}/3")
        except Exception as e:
            print(f"  {fname} hata: {e}, deneme {attempt+1}/3")
        time.sleep(2 ** attempt)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*", default=SYMBOLS,
                        help="İndirilecek coinler (varsayılan: hepsi)")
    parser.add_argument("--months", type=int, default=0,
                        help="Son N ay (varsayılan: tüm liste)")
    parser.add_argument("--futures", action="store_true",
                        help="Futures veri kullan (varsayılan: spot)")
    parser.add_argument("--out", default=".", help="Çıkış klasörü")
    args = parser.parse_args()

    months = MONTHS[-args.months:] if args.months > 0 else MONTHS
    symbols = [s.upper() if not s.endswith("USDT") else s.upper()
               for s in args.symbols]
    symbols = [s if s.endswith("USDT") else s+"USDT" for s in symbols]

    out_dir = Path(args.out)

    print(f"İndirilecek: {symbols}")
    print(f"Aylar: {months[0]} → {months[-1]}  ({len(months)} ay)")
    print(f"Tip: {'futures' if args.futures else 'spot'}")
    print(f"Hedef: {out_dir.resolve()}")
    print()

    ok = fail = 0
    for sym in symbols:
        sym_dir = out_dir / sym.lower().replace("usdt","_data")
        if sym == "BTCUSDT":
            sym_dir = out_dir   # BTC direkt ana klasöre (mevcut yapı)
        sym_dir.mkdir(exist_ok=True)
        print(f"\n[{sym}] → {sym_dir}/")
        for m in months:
            if download(sym, m, sym_dir, use_futures=args.futures):
                ok += 1
            else:
                fail += 1

    print(f"\n{'='*40}")
    print(f"Tamamlandı: {ok} OK, {fail} başarısız")
    if fail > 0:
        print("İpucu: Futures verisi için --futures flag'i dene")


if __name__ == "__main__":
    main()
