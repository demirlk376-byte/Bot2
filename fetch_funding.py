"""
fetch_funding.py — VPS'te çalıştır: 12 coin için funding rate GEÇMİŞİNİ çeker, data/'ya kaydeder.

Container MEXC'e erişemiyor; bu script VPS'te koşup CSV üretir, commit'lenir, sonra funding_filter
testi çevrimdışı çalışır (OHLCV cache'i ile aynı iş akışı).

Kullanım (VPS'te):  cd /opt/bot2 && python3 fetch_funding.py && git add data/ && git commit -m "funding data" && git push
"""
import os, time
import pandas as pd
import ccxt

COINS = ["SOL","ETH","ADA","NEAR","BCH","ICP","BNB","XRP","DOGE","TRX","XLM","LTC"]
OUT = "data"
os.makedirs(OUT, exist_ok=True)
ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True, "timeout": 30000})

for c in COINS:
    sym = f"{c}/USDT:USDT"
    path = f"{OUT}/{c}_funding.csv"
    if os.path.exists(path):
        print(f"{c}: zaten var, atlanıyor"); continue
    rows, since, guard = [], ex.parse8601("2023-01-01T00:00:00Z"), 0
    while guard < 400:
        guard += 1
        try:
            batch = ex.fetch_funding_rate_history(sym, since=since, limit=1000)
        except Exception as e:
            print(f"{c}: hata {type(e).__name__} {str(e)[:80]}"); break
        if not batch: break
        rows += batch
        nxt = batch[-1]["timestamp"] + 1
        if nxt <= since: break            # ilerleme yok → sonsuz döngü koruması
        since = nxt
        if batch[-1]["timestamp"] > ex.milliseconds() - 8*3600*1000: break
        time.sleep(ex.rateLimit / 1000)
    if not rows:
        print(f"{c}: veri yok"); continue
    df = pd.DataFrame([{"ts": r["timestamp"], "rate": r["fundingRate"]} for r in rows]).drop_duplicates("ts")
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("dt").set_index("dt")[["rate"]]
    df.to_csv(path)
    print(f"{c}: {len(df)} kayıt, {df.index[0].date()} → {df.index[-1].date()} → {path}")
print("\nBitti. Şimdi: git add data/*_funding.csv && git commit -m 'funding history' && git push")
