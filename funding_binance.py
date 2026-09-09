"""
funding_binance.py — VPS'te koş: 12 coin için TAM funding geçmişini BINANCE'ten çeker.

NEDEN BINANCE: MEXC'in `fetch_funding_rate_history`'si `since` parametresini YOK SAYIYOR
ve her çağrıda en yeni 1000 kaydı döndürüyor. `fetch_funding.py` 2023-01-01'den istedi,
2025-10-11'den itibaren 1000 kayıt aldı ve "başarılı" dedi. Ankorun yalnız **%22.9'unu**
(1579 işlemin 361'ini) kapsıyor — o pencerede test istatistiksel olarak zayıf kalır.

⚠ AYNI TUZAK exchange.py:fetch_transfers_in'de de vardı ve orada da not edilmişti:
   "MEXC'in `since` filtresine GÜVENME." Bu betik ilerlemeyi kendi doğruluyor.

Binance `/fapi/v1/fundingRate` startTime'a UYAR ve sayfalanır (8 saatlik funding,
1000 kayıt ≈ 333 gün, 3.3 yıl için ~4 sayfa).

VENÜS FARKI: Binance funding ≠ MEXC funding, ama arbitraj ikisini birbirine bağlar.
Filtre testi için ölçtüğümüz şey POZİSYONLANMA YÖNÜ ve o venüsler arası ortaktır.
Fiyat verisi MEXC vadeli kalıyor; yalnız funding Binance'ten. Bu karışım bilinçlidir
ve raporda belirtilmelidir.

Kullanım (VPS'te):
  cd /opt/bot2 && python3 funding_binance.py && \
    git -c user.email=demirlk99@gmail.com -c user.name=demirlk376-byte \
        commit -am "binance funding history" && git push
"""
import os
import sys
import time
import urllib.request
import json

import pandas as pd

COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"]
BAS = "2023-01-01T00:00:00Z"
URL = "https://fapi.binance.com/fapi/v1/fundingRate"
OUT = "data"


def cek(sym, bas_ms):
    rows, since, guard = [], bas_ms, 0
    while guard < 60:
        guard += 1
        u = f"{URL}?symbol={sym}&startTime={since}&limit=1000"
        try:
            with urllib.request.urlopen(u, timeout=30) as r:
                batch = json.loads(r.read().decode())
        except Exception as e:
            # ⚠ SESSİZ YUTMA YOK: sebebi yaz ve o coini BAŞARISIZ say.
            return None, f"{type(e).__name__}: {str(e)[:90]}"
        if not batch:
            break
        rows += batch
        nxt = int(batch[-1]["fundingTime"]) + 1
        if nxt <= since:                       # ilerleme yok → sunucu since'i yok sayıyor
            return None, "sayfalama İLERLEMİYOR (sunucu startTime'ı yok sayıyor olabilir)"
        since = nxt
        if len(batch) < 1000:
            break
        time.sleep(0.25)
    return rows, None


def main():
    os.makedirs(OUT, exist_ok=True)
    bas_ms = int(pd.Timestamp(BAS).timestamp() * 1000)
    hedef = pd.Timestamp(BAS).date()
    basarili, hatali = 0, []
    print(f"\n  hedef başlangıç: {hedef}  ·  kaynak: Binance vadeli\n")
    for c in COINS:
        sym = f"{c}USDT"
        rows, hata = cek(sym, bas_ms)
        if hata:
            print(f"  {c:<5s} ✗ {hata}")
            hatali.append(c); continue
        if not rows:
            print(f"  {c:<5s} ✗ veri gelmedi")
            hatali.append(c); continue
        df = pd.DataFrame([{"ts": int(r["fundingTime"]), "rate": float(r["fundingRate"])}
                           for r in rows]).drop_duplicates("ts")
        df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.sort_values("dt").set_index("dt")[["rate"]]
        p = f"{OUT}/{c}_funding_bnc.csv"
        df.to_csv(p)
        ilk = df.index[0].date()
        kapsam = "✓" if ilk <= hedef + pd.Timedelta(days=40) else f"⚠ {ilk}'den başlıyor"
        print(f"  {c:<5s} {len(df):>5d} kayıt  {ilk} → {df.index[-1].date()}  {kapsam}")
        basarili += 1
    print(f"\n  {basarili}/{len(COINS)} coin alındı" +
          (f"  ·  BAŞARISIZ: {', '.join(hatali)}" if hatali else ""))
    if hatali:
        print(f"  ⚠ Eksik coin varken test YAPILMAZ — eksik coinin işlemleri filtresiz")
        print(f"    kalır ve kıyas bozulur. Hatayı çöz, yeniden koş.")
        sys.exit(2)
    print(f"\n  Şimdi:")
    print(f"    git -c user.email=demirlk99@gmail.com -c user.name=demirlk376-byte \\")
    print(f"        commit -am 'binance funding history' && git push")


if __name__ == "__main__":
    main()
