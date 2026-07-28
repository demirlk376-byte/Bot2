"""
fetch_universe.py — VPS'te çalıştır: GENİŞLİK için yeni aday coin'lerin 1h OHLCV'sini çeker.

NEDEN (breadth_test.py teşhisi): darboğaz KOLTUK değil SİNYAL. 7 koltuk zamanın yalnız
%2.7'sinde dolu, ortalama 2.56 pozisyon açık, %14.8 tamamen boş. Yani coin eklemek mevcut
coinlerin işlemini KOVMAZ — doğrudan yeni işlem ekler. Elimizdeki 22-coin evreni ise tarandı
(coin_expand → ICP+BNB çıktı, gerisi elendi). Yeni coin = yeni veri gerekiyor.

NEDEN ccxt DEĞİL: ccxt'nin load_markets()'i MEXC'in SPOT listesini de indiriyor (binlerce
parite) ve 30sn'de timeout veriyor. Bize yalnız vadeli lazım → doğrudan contract API:
  /api/v1/contract/detail  → tüm vadeli kontratlar
  /api/v1/contract/ticker  → 24s hacim
  /api/v1/contract/kline/  → OHLCV (interval=Min60, start/end SANİYE)
Küçük, hızlı, spot yükü yok.

LİKİDİTE TABANI — KEYFİ DEĞİL: edge'imiz ince (+0.239R/işlem). İnce spread'li büyük coinlerde
çalışıyor; MEXC'in kuyruk paritelerinde spread+slippage bu edge'i tamamen yiyebilir. Taban
"zaten DOĞRULANMIŞ en düşük likidite" = mevcut 12 coinin en düşük 24s hacmi. Altına inmiyoruz.

Ayrıca: 2023-04'ten sonra listelenen pariteler elenir (her-yıl testi için geçmiş şart).

DAYANIKLILIK: her adım tek tek doğrulanır; bir alan adı beklenenden farklıysa script ham
anahtarları basıp durur (sessizce yanlış veri üretmez).

Kullanım (VPS'te):  cd /opt/bot2 && nice -n 19 ./venv/bin/python fetch_universe.py
"""
import os, sys, time
import pandas as pd
import requests

BASE = "https://contract.mexc.com/api/v1/contract"
OUT = "data"
DEPLOYED = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"]
HAVE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]
START = pd.Timestamp("2023-01-01", tz="UTC")
MIN_FIRST_BAR = pd.Timestamp("2023-04-01", tz="UTC")
MAX_NEW = int(os.environ.get("MAX_NEW", "60"))
CHUNK = 1900          # kline limiti ~2000; güvenli pay
TIMEOUT = 45

os.makedirs(OUT, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "bot2-universe/1.0"})


def get(path, params=None, tries=4):
    last = None
    for k in range(tries):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            j = r.json()
            if not j.get("success", True):
                raise RuntimeError(f"API success=false: {str(j)[:200]}")
            return j.get("data")
        except Exception as e:
            last = e
            if k < tries - 1:
                time.sleep(2 ** k)
    raise RuntimeError(f"{path} başarısız ({tries} deneme): {last}")


print("=== [1/3] MEXC vadeli kontrat listesi ===")
det = get("detail")
if not isinstance(det, list) or not det:
    sys.exit(f"BEKLENMEYEN detail yanıtı: {str(det)[:300]}")
print(f"  örnek kayıt anahtarları: {sorted(det[0].keys())}")
perps = {}
for d in det:
    sym = d.get("symbol") or ""
    if not sym.endswith("_USDT"): continue
    if d.get("state") not in (0, "0", None): continue      # 0 = aktif
    perps[sym] = sym.split("_")[0]
print(f"  aktif USDT perp: {len(perps)}")

print("\n=== [2/3] 24s hacimler + likidite tabanı ===")
tick = get("ticker")
if isinstance(tick, dict): tick = [tick]
if not isinstance(tick, list) or not tick:
    sys.exit(f"BEKLENMEYEN ticker yanıtı: {str(tick)[:300]}")
print(f"  örnek ticker anahtarları: {sorted(tick[0].keys())}")


def qvol(row):
    """24s ciro (quote). MEXC 'amount24' verir; yoksa volume24×lastPrice."""
    for k in ("amount24", "amount", "turnover24", "quoteVolume"):
        v = row.get(k)
        if v not in (None, "", 0, "0"):
            try: return float(v)
            except (TypeError, ValueError): pass
    try:
        return float(row.get("volume24") or 0) * float(row.get("lastPrice") or 0)
    except (TypeError, ValueError):
        return 0.0


vols = {r.get("symbol"): qvol(r) for r in tick if r.get("symbol")}
dep_vols = {c: vols.get(f"{c}_USDT", 0.0) for c in DEPLOYED}
for c, v in sorted(dep_vols.items(), key=lambda kv: kv[1]):
    print(f"    {c:<6s} 24s ciro ${v:>16,.0f}")
live = [v for v in dep_vols.values() if v > 0]
if not live:
    sys.exit("Mevcut coinlerin hacmi okunamadı — alan adı değişmiş olabilir (yukarıdaki "
             "ticker anahtarlarını bana gönder).")
FLOOR = min(live)
print(f"  → LİKİDİTE TABANI (mevcut en düşük): ${FLOOR:,.0f}")

skip = set(DEPLOYED) | set(HAVE)
cands = sorted(
    ((vols.get(s, 0.0), b, s) for s, b in perps.items()
     if b not in skip and vols.get(s, 0.0) >= FLOOR),
    reverse=True)[:MAX_NEW]
print(f"\n  tabanı geçen {len(cands)} yeni aday:")
print("  " + ", ".join(b for _, b, _ in cands))
if not cands:
    sys.exit("\nAday yok — likidite tabanının üstünde yeni parite bulunamadı.")

print(f"\n=== [3/3] 1h OHLCV indiriliyor ({START.date()}'den) ===")
ok, short, fail = [], [], []
for n, (v, base, sym) in enumerate(cands, 1):
    path = f"{OUT}/{base}_fut_1h.csv"
    if os.path.exists(path):
        print(f"  [{n}/{len(cands)}] {base}: zaten var, atlanıyor"); ok.append(base); continue
    frames, cur, guard = [], int(START.timestamp()), 0
    now = int(time.time())
    try:
        while cur < now and guard < 60:
            guard += 1
            end = min(cur + CHUNK * 3600, now)
            k = get(f"kline/{sym}", {"interval": "Min60", "start": cur, "end": end})
            if not isinstance(k, dict) or "time" not in k:
                raise RuntimeError(f"beklenmeyen kline şekli: {str(k)[:200]}")
            t = k.get("time") or []
            if not t: break
            frames.append(pd.DataFrame({
                "ts": t, "open": k["open"], "high": k["high"],
                "low": k["low"], "close": k["close"], "volume": k["vol"]}))
            nxt = int(t[-1]) + 3600
            if nxt <= cur: break
            cur = nxt
            time.sleep(0.15)
    except Exception as e:
        print(f"  [{n}/{len(cands)}] {base}: HATA {e}"); fail.append(base); continue
    if not frames:
        fail.append(base); print(f"  [{n}/{len(cands)}] {base}: veri yok"); continue
    d = pd.concat(frames, ignore_index=True).astype({"ts": "int64"})
    d = d.drop_duplicates("ts").sort_values("ts")
    d["ts"] = pd.to_datetime(d["ts"], unit="s", utc=True)
    d = d.set_index("ts").astype(float)
    first = d.index[0]
    if first > MIN_FIRST_BAR:
        short.append((base, first.date()))
        print(f"  [{n}/{len(cands)}] {base}: geçmiş KISA (ilk bar {first.date()}) — atlandı")
        continue
    d.to_csv(path)
    ok.append(base)
    print(f"  [{n}/{len(cands)}] {base}: {len(d)} bar ({first.date()} → {d.index[-1].date()}) ✓")

print("\n=== ÖZET ===")
print(f"  indirildi/mevcut : {len(ok)}  {', '.join(ok)}")
if short: print(f"  geçmiş kısa      : {len(short)}  " + ", ".join(f"{b}({d})" for b, d in short))
if fail:  print(f"  başarısız        : {len(fail)}  {', '.join(fail)}")
print(f"\n  Sıradaki:  nice -n 19 ./venv/bin/python breadth_expand.py local")
