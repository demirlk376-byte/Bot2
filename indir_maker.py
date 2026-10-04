"""Binance USDⓈ-M aggTrades kamu arşivinden, donchian sinyallerinin çevresindeki işlemler.
Her sinyal i için [t−60 sn, t+300 sn] aralığındaki tüm aggTrade'ler → veri/islemler.csv.gz
(sutunlar: i, dt_ms = işlem zamanı − t, fiyat, adet, ibm). Anahtarsız, yalnız kamu arşivi."""
import csv, gzip, io, json, os, tempfile, time, zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import requests

V = "https://data.binance.vision/data/futures/um/daily/aggTrades"
OUT = "veri"; os.makedirs(OUT, exist_ok=True)
ONCE, SONRA = 60_000, 300_000
GUN = 86_400_000
sinyaller = [dict(i=i, coin=r["coin"], t=int(r["t_ms"]), L=float(r["L"]), yon=r["yon"])
             for i, r in enumerate(csv.DictReader(open("sinyaller.csv")))]
# (coin, gün) → o günün dosyasından gereken pencereler
is_listesi = defaultdict(list)
for s in sinyaller:
    a, b = s["t"] - ONCE, s["t"] + SONRA
    for g in range(a // GUN, b // GUN + 1):
        is_listesi[(s["coin"], g)].append((s["i"], s["t"], a, b))
ozet = {"dosya_yok": [], "hata": [], "sayim": {}}
ses = requests.Session()
ses.mount("https://", requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=3))


def gun_str(g):
    return time.strftime("%Y-%m-%d", time.gmtime(g * GUN / 1000))


def isle(anahtar):
    coin, g = anahtar
    sym = f"{coin}USDT"
    url = f"{V}/{sym}/{sym}-aggTrades-{gun_str(g)}.zip"
    pencere = is_listesi[anahtar]
    son = max(b for _, _, _, b in pencere)
    satirlar = []
    for d in range(4):
        try:
            with tempfile.TemporaryFile() as tf:
                with ses.get(url, stream=True, timeout=120) as r:
                    if r.status_code == 404:
                        ozet["dosya_yok"].append(url); return []
                    r.raise_for_status()
                    for parca in r.iter_content(1 << 20):
                        tf.write(parca)
                tf.seek(0)
                with zipfile.ZipFile(tf) as z, z.open(z.namelist()[0]) as f:
                    for ham in io.TextIOWrapper(f, encoding="ascii", errors="ignore"):
                        p = ham.split(",")
                        if not p[0][:1].isdigit():
                            continue                       # başlık satırı
                        ts = int(p[5])
                        if ts > 10**14:
                            ts //= 1000                     # mikro saniye ise ms'e çevir
                        if ts > son:
                            break
                        for i, t, a, b in pencere:
                            if a <= ts <= b:
                                satirlar.append((i, ts - t, p[1], p[2], 1 if p[6].strip().lower() == "true" else 0))
            return satirlar
        except Exception as e:
            err = f"{url}: {type(e).__name__}: {e}"
            time.sleep(3 * (d + 1))
    ozet["hata"].append(err)
    return []


anahtarlar = sorted(is_listesi)
print("dosya sayısı:", len(anahtarlar), flush=True)
hepsi = []
with ThreadPoolExecutor(6) as ex:
    for k, sat in enumerate(ex.map(isle, anahtarlar)):
        hepsi += sat
        if k % 25 == 0:
            print(k, anahtarlar[k], len(sat), flush=True)
hepsi.sort()
with gzip.open(f"{OUT}/islemler.csv.gz", "wt", newline="") as f:
    w = csv.writer(f); w.writerow(["i", "dt_ms", "fiyat", "adet", "ibm"]); w.writerows(hepsi)
say = defaultdict(int)
for r in hepsi:
    say[r[0]] += 1
ozet["sayim"] = {"sinyal": len(sinyaller), "verili_sinyal": len(say), "islem": len(hepsi),
                 "medyan_islem_sinyal_basi": sorted(say.values())[len(say) // 2] if say else 0}
json.dump(ozet, open(f"{OUT}/ozet.json", "w"), indent=1)
print(json.dumps(ozet["sayim"]), "dosya_yok", len(ozet["dosya_yok"]), "hata", len(ozet["hata"]), flush=True)
