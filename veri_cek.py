"""
veri_cek.py — İNTRADAY VERİ ÇEKİCİ (5dk/15dk), yeni strateji araştırması için.

NEDEN: yeni brief 1H rejim + 15M setup + 5M teyit üzerine kurulu. Ama repoda
canlı coinler için YALNIZ 1 SAATLİK veri var (data/*_fut_1h.csv). 15M/5M hiç yok.
1dk yalnız BTC (Binance, 12 ay) ve ETH (Binance, 5 ay BOŞLUKLU) için var — ikisi de
canlı venue değil, biri canlı evrende bile değil. Yani brief bu veriyle
ÇALIŞTIRILAMAZ. Önce veri.

NEDEN 5dk, 1dk DEĞİL:
  • 5dk'dan 15dk ve 1saat TÜRETİLEBİLİR (resample). Strateji mantığının tamamı
    o üç katmanda yaşıyor.
  • 1dk brief'te YALNIZ entry timing için. Bugün ölçüldü (gecikme_olc.py): bar
    kapanışı sonrası 1dk sürüklenme +0.12bp, %95 aralık sıfırı içeriyor →
    ölçülen değeri ~SIFIR. Veri maliyetini 5 katına çıkarır.
  • Bir strateji baseline'ı geçerse 1dk O ZAMAN çekilir (config'de anahtar hazır).

MALİYET: 3 yıl 5dk ≈ 315k bar/coin. 500'lük sayfalarla ~630 istek/coin.
12 coin ≈ 7.500 istek ≈ 20-30 dk. Diske ~250MB.

⚠ GİT'E COMMİTLENMEZ. data/ altındaki 5dk dosyaları .gitignore'a eklendi; araştırma
  VPS'te koşacak (MEXC oraya açık). Repoyu 250MB şişirmenin anlamı yok.

⚠ SON BAR ATILIR (iloc[:-1]) — oluşmakta olan mum. Bu, look-ahead'in en sinsi
  kaynağıdır ve fast_bt.load da aynısını yapıyor.

Kullanım (VPS'te):
    python3 veri_cek.py            # canlı 12 coin, 5dk, 3 yıl
    python3 veri_cek.py 5m 730 SOL ETH
    python3 veri_cek.py --durum    # neyin çekildiğini göster, indirme yapma
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

CACHE = "data"
# Canlı evren (deployed_backtest) + BTC (referans/vekil, canlı değil ama en likit)
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB",
         "XRP", "DOGE", "TRX", "XLM", "LTC", "BTC"]
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def yol(coin: str, tf: str) -> str:
    return os.path.join(CACHE, f"{coin}_fut_{tf}.csv")


def durum(tf: str) -> None:
    print(f"\n{'coin':<6s} {'bar':>9s}  {'ilk':<17s} {'son':<17s} {'gün':>6s}  boşluk?")
    for c in COINS:
        p = yol(c, tf)
        if not os.path.exists(p):
            print(f"{c:<6s} {'—':>9s}  {'YOK':<17s}")
            continue
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        gun = (d.index[-1] - d.index[0]).total_seconds() / 86400
        bekl = int(gun * 86400 * 1000 / TF_MS[tf])
        eksik = 1 - len(d) / max(bekl, 1)
        print(f"{c:<6s} {len(d):>9d}  {str(d.index[0])[:16]:<17s} "
              f"{str(d.index[-1])[:16]:<17s} {gun:>6.0f}  "
              f"%{eksik*100:>4.1f}{'  ⚠ BÜYÜK BOŞLUK' if eksik > 0.05 else ''}")


def cek(coin: str, tf: str, gun: int) -> pd.DataFrame | None:
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    sym = f"{coin}/USDT:USDT"
    since = int((time.time() - gun * 86400) * 1000)
    step = TF_MS[tf]
    rows: list = []
    bos = 0
    while True:
        try:
            b = ex.fetch_ohlcv(sym, tf, since=since, limit=500)
        except Exception as e:
            print(f"    ⚠ {coin}: {type(e).__name__} — 3sn bekle, tekrar dene")
            time.sleep(3)
            bos += 1
            if bos > 5:
                print(f"    ✗ {coin}: 5 ardışık hata, bırakıldı")
                break
            continue
        bos = 0
        if not b:
            break
        rows += b
        # İlerleme GARANTİSİ: borsa aynı sayfayı tekrar verirse sonsuz döngü olur.
        yeni_since = b[-1][0] + step
        if yeni_since <= since:
            break
        since = yeni_since
        if len(b) < 500:
            break
        if since > time.time() * 1000:
            break
    if not rows:
        return None
    m = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    m = m.drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop(columns=["ts"]).astype(float)
    # SON BAR ATILIR — oluşmakta olan mum. Look-ahead'in en sinsi kaynağı.
    return m.iloc[:-1]


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tf = args[0] if args and args[0] in TF_MS else "5m"
    gun = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1095
    coins = args[2:] if len(args) > 2 else COINS
    if "--durum" in sys.argv:
        durum(tf)
        return
    os.makedirs(CACHE, exist_ok=True)
    print(f"=== {tf} veri çekiliyor · {gun} gün · {len(coins)} coin ===")
    print(f"  kaynak: MEXC VADELİ (canlı-birebir borsa/enstrüman)")
    print(f"  ⚠ son bar atılıyor (oluşmakta olan mum → look-ahead kaynağı)")
    t0 = time.time()
    for i, c in enumerate(coins, 1):
        p = yol(c, tf)
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True)
            print(f"[{i}/{len(coins)}] {c:<5s} zaten var ({len(d)} bar) — atlandı "
                  f"(yeniden çekmek için dosyayı sil)")
            continue
        print(f"[{i}/{len(coins)}] {c:<5s} çekiliyor...", end="", flush=True)
        m = cek(c, tf, gun)
        if m is None or len(m) < 100:
            print(f" ✗ veri gelmedi")
            continue
        m.to_csv(p)
        kaps = (m.index[-1] - m.index[0]).total_seconds() / 86400
        print(f" ✓ {len(m)} bar · {kaps:.0f} gün · {m.index[0].date()} → {m.index[-1].date()}")
    print(f"\n  toplam {time.time()-t0:.0f} sn")
    durum(tf)
    print(f"\n  ⚠ Bu dosyalar GIT'E GİRMEZ (.gitignore). Araştırma VPS'te koşacak.")


if __name__ == "__main__":
    main()
