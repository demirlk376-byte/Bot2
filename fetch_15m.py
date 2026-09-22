"""
fetch_15m.py — VPS'te çalıştır: 12 canlı coin için 15 DAKİKALIK mum geçmişini
çeker, data/'ya kaydeder. (fetch_funding.py ile aynı iş akışı: konteyner
MEXC'e erişemiyor, VPS erişiyor; CSV'ler commit'lenip çevrimdışı kullanılıyor.)

NEDEN GEREKLİ — İKİZ'in bilinen iki sınırını kapatır:

1. AYNI MUMDA HEM STOP HEM HEDEF. Şu an 1h çözünürlükte hangisinin önce
   geldiğini bilemiyoruz ve üretim kodu STOP'u kazandırıyor (temkinli).
   15m ile vakaların çoğu çözülür -> backtest gerçeğe yaklaşır.
   ⚠ Bu düzeltme sonuçları YUKARI da AŞAĞI da taşıyabilir; şu anki hal
   temkinli olduğu için muhtemelen yukarı.

2. MFE/MAE (test protokolü §9). "Kaybeden işlemlerin kaçı önce +1R gördü?"
   sorusu 1h barlarla kaba, 15m ile anlamlı cevaplanır. Stop/BE/TP tasarımı
   bu analize dayanır.

NE YAPMAZ: 45 saniyelik maker dolum kararını çözmez. 15 dakika onun için de
fazla kaba. O sayı canlı loglardan ölçülür (şu an %27).

Kullanım (VPS'te):
  cd /opt/bot2 && python3 fetch_15m.py
  git add data/*_15m.csv && git commit -m "15m data" && git push
"""
import os
import time

import pandas as pd
import ccxt

COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB",
         "XRP", "DOGE", "TRX", "XLM", "LTC"]
OUT = "data"
TF = "15m"
BASLA = "2023-04-01T00:00:00Z"
# ⚠ 1000'lik sayfalarla ~3.4 yıl = ~118 sayfa/coin. Rate limit'e uyuluyor,
# toplam 10-20 dakika sürer. Kesilirse: var olan dosyalar ATLANIR, tekrar
# çalıştırmak kaldığı yerden devam ettirir.
SAYFA = 1000
GUARD = 400

os.makedirs(OUT, exist_ok=True)
ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True,
                "timeout": 30000})

for c in COINS:
    sym = f"{c}/USDT:USDT"
    path = f"{OUT}/{c}_{TF}.csv"
    if os.path.exists(path):
        print(f"{c}: zaten var, atlanıyor")
        continue
    rows, since, guard = [], ex.parse8601(BASLA), 0
    while guard < GUARD:
        guard += 1
        try:
            batch = ex.fetch_ohlcv(sym, TF, since=since, limit=SAYFA)
        except Exception as e:
            print(f"{c}: hata {type(e).__name__} {str(e)[:80]}")
            break
        if not batch:
            break
        rows += batch
        nxt = batch[-1][0] + 1
        if nxt <= since:                  # ilerleme yok -> sonsuz döngü koruması
            break
        since = nxt
        if batch[-1][0] > ex.milliseconds() - 15 * 60 * 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    if not rows:
        print(f"{c}: veri yok")
        continue
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("dt")[["open", "high", "low", "close", "volume"]]
    df.to_csv(path)
    # ⚠ BOŞLUK KONTROLU: eksik mum varsa SÖYLE. Sessiz boşluk, mum-içi
    # cozumlemeyi bozar ve kimse fark etmez.
    beklenen = int((df.index[-1] - df.index[0]).total_seconds() // 900) + 1
    eksik = beklenen - len(df)
    uyari = f"  ⚠ {eksik} mum EKSİK (%{eksik/beklenen*100:.1f})" if eksik > 0 else ""
    print(f"{c}: {len(df)} mum, {df.index[0].date()} → {df.index[-1].date()}{uyari}")

print("\nBitti. Şimdi:")
print("  git add data/*_15m.csv && git commit -m '15m data' && git push")
