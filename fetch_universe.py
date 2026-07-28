"""
fetch_universe.py — VPS'te çalıştır: GENİŞLİK için yeni aday coin'lerin 1h OHLCV'sini çeker.

NEDEN (breadth_test.py teşhisi): darboğaz KOLTUK değil SİNYAL. 7 koltuk zamanın yalnız
%2.7'sinde dolu, ortalama 2.56 pozisyon açık, %14.8 tamamen boş. Yani coin eklemek mevcut
coinlerin işlemini KOVMAZ — doğrudan yeni işlem ekler. Elimizdeki 22-coin evreni ise tarandı
(coin_expand → ICP+BNB çıktı, gerisi elendi). Yeni coin = yeni veri gerekiyor.

LİKİDİTE TABANI — KEYFİ DEĞİL: edge'imiz ince (+0.239R/işlem). İnce spread'li büyük coinlerde
çalışıyor; MEXC'in kuyruk paritelerinde spread+slippage bu edge'i tamamen yiyebilir. Bu yüzden
taban "zaten DOĞRULANMIŞ en düşük likidite" olarak seçiliyor: mevcut 12 coinin en düşük 24s
hacmi. Altına inmiyoruz — kanıtlanmamış bir likidite rejimine girmek testin görmediği bir
maliyet ekler.

Ayrıca: 2023-01'den ÖNCE listelenmemiş pariteler elenir (her-yıl testi için 3+ yıl geçmiş şart).

Kullanım (VPS'te):
  cd /opt/bot2 && python3 fetch_universe.py
  git add data/ && git commit -m "universe data" && git push
Sonra PC/container'da:  git pull && python3 breadth_expand.py local
"""
import os, sys, time
import pandas as pd
import ccxt

OUT = "data"
DEPLOYED = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"]
HAVE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]  # zaten indirdiklerimiz
START = "2023-01-01T00:00:00Z"
MAX_NEW = int(os.environ.get("MAX_NEW", "60"))     # kaç yeni coin indirilsin
TF = "1h"

os.makedirs(OUT, exist_ok=True)
ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True, "timeout": 30000})

print("=== [1/3] MEXC vadeli evreni + 24s hacimler ===")
mk = ex.load_markets()
swaps = {s: v for s, v in mk.items()
         if v.get("swap") and v.get("settle") == "USDT" and v.get("active")}
print(f"  aktif USDT perp: {len(swaps)}")

tk = ex.fetch_tickers(list(swaps.keys()))
def qvol(sym):
    t = tk.get(sym) or {}
    q = t.get("quoteVolume")
    if q: return float(q)
    b, p = t.get("baseVolume"), t.get("last")
    return float(b) * float(p) if b and p else 0.0

# Likidite tabanı = mevcut 12 coinin EN DÜŞÜĞÜ (doğrulanmış rejim)
dep_vols = {c: qvol(f"{c}/USDT:USDT") for c in DEPLOYED}
for c, v in sorted(dep_vols.items(), key=lambda kv: kv[1]):
    print(f"    {c:<6s} 24s hacim ${v:>15,.0f}")
FLOOR = min(v for v in dep_vols.values() if v > 0)
print(f"  → LİKİDİTE TABANI (mevcut en düşük): ${FLOOR:,.0f}")

skip = set(DEPLOYED) | set(HAVE)
cands = []
for s in swaps:
    base = s.split("/")[0]
    if base in skip: continue
    v = qvol(s)
    if v >= FLOOR: cands.append((v, base, s))
cands.sort(reverse=True)
cands = cands[:MAX_NEW]
print(f"\n=== [2/3] tabanı geçen {len(cands)} yeni aday (hacme göre) ===")
print("  " + ", ".join(b for _, b, _ in cands))

print(f"\n=== [3/3] 1h OHLCV indiriliyor ({START}'den) ===")
since0 = ex.parse8601(START)
ok, short, fail = [], [], []
for n, (v, base, sym) in enumerate(cands, 1):
    path = f"{OUT}/{base}_fut_1h.csv"
    if os.path.exists(path):
        print(f"  [{n}/{len(cands)}] {base}: zaten var, atlanıyor"); ok.append(base); continue
    rows, since, guard = [], since0, 0
    try:
        while guard < 600:
            guard += 1
            batch = ex.fetch_ohlcv(sym, TF, since=since, limit=1000)
            if not batch: break
            rows += batch
            nxt = batch[-1][0] + 3_600_000
            if nxt <= since: break
            since = nxt
            if len(batch) < 1000: break
            time.sleep(0.12)
    except Exception as e:
        print(f"  [{n}/{len(cands)}] {base}: HATA {type(e).__name__}: {e}"); fail.append(base); continue
    if not rows:
        fail.append(base); print(f"  [{n}/{len(cands)}] {base}: veri yok"); continue
    d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    d = d.drop_duplicates("ts").sort_values("ts")
    d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    d = d.set_index("ts")
    first = d.index[0]
    # Her-yıl testi için 2023 başından beri geçmiş şart; sonradan listelenenler elenir.
    if first > pd.Timestamp("2023-04-01", tz="UTC"):
        short.append((base, first.date()))
        print(f"  [{n}/{len(cands)}] {base}: geçmiş KISA (ilk bar {first.date()}) — atlandı")
        continue
    d.to_csv(path)
    ok.append(base)
    print(f"  [{n}/{len(cands)}] {base}: {len(d)} bar ({first.date()} → {d.index[-1].date()}) ✓")

print(f"\n=== ÖZET ===")
print(f"  indirildi/mevcut : {len(ok)}  {', '.join(ok)}")
if short: print(f"  geçmiş kısa      : {len(short)}  " + ", ".join(f"{b}({d})" for b, d in short))
if fail:  print(f"  başarısız        : {len(fail)}  {', '.join(fail)}")
print(f"\n  Sıradaki: git add data/ && git commit -m 'universe data' && git push")
print(f"  Sonra çevrimdışı: python3 breadth_expand.py local")
