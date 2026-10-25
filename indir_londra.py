"""Londra kırılımı dış-örneklem testi verisi — Binance kamu arşivi (data.binance.vision), anahtarsız.
Çıktı (veri/):
  BTC_spot_1h.csv      spot BTCUSDT saatlik (taker alış hacmi dahil), 2020-01 →
  BTC_fut_5m.csv.gz    USDⓈ-M vadeli BTCUSDT 5 dakikalık, 2020-01 →
"""
import io, os, json, time, zipfile
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests

B = "https://data.binance.vision/data"
OUT = "veri"; os.makedirs(OUT, exist_ok=True)
BUGUN = pd.Timestamp.utcnow().tz_localize(None).normalize()
ses = requests.Session()
ses.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3))
ozet = {}
KL = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count",
      "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def al(url):
    for d in range(3):
        try:
            r = ses.get(url, timeout=60)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as f:
                    return f.read(f.namelist()[0]).decode()
            if r.status_code == 404:
                return None
        except Exception:
            time.sleep(2 * (d + 1))
    return None


def csv_oku(ham):
    ilk = ham.split("\n", 1)[0]
    basliksiz = ilk[:1].isdigit()
    d = pd.read_csv(io.StringIO(ham), header=None if basliksiz else 0)
    if basliksiz:
        d.columns = KL[:d.shape[1]]
    return d


def ms(seri):
    seri = pd.to_numeric(seri)
    return seri.where(seri < 10**14, seri // 1000).astype("int64")   # mikro saniye → ms


def aylar(bas):
    return [p.strftime("%Y-%m") for p in pd.period_range(bas, BUGUN - pd.offsets.MonthBegin(1), freq="M")]


def gunler(ay):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(ay + "-01", BUGUN - pd.Timedelta(days=1))]


def klines(pazar, sym, tf, bas, dosya):
    kok = f"{B}/{pazar}/monthly/klines/{sym}/{tf}"
    urls = [f"{kok}/{sym}-{tf}-{a}.zip" for a in aylar(bas)]
    onceki_ay = (BUGUN - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    urls += [f"{B}/{pazar}/daily/klines/{sym}/{tf}/{sym}-{tf}-{g}.zip" for g in gunler(onceki_ay)]
    with ThreadPoolExecutor(16) as ex:
        parca = [p for p in ex.map(al, urls) if p]
    d = pd.concat([csv_oku(p) for p in parca], ignore_index=True)
    d["open_time"] = ms(d["open_time"])
    d = d[KL[:6] + ["quote_volume", "taker_buy_volume", "taker_buy_quote_volume"]]
    d = d.drop_duplicates("open_time").sort_values("open_time")
    d.to_csv(f"{OUT}/{dosya}", index=False)
    t = pd.to_datetime(d.open_time, unit="ms")
    adim = pd.Timedelta(tf.replace("m", "min"))
    ozet[dosya] = dict(satir=len(d), ilk=str(t.min()), son=str(t.max()), bosluk=int((t.diff() > adim).sum()))
    print(dosya, ozet[dosya], flush=True)


klines("spot", "BTCUSDT", "1h", "2020-01", "BTC_spot_1h.csv")
klines("futures/um", "BTCUSDT", "5m", "2020-01", "BTC_fut_5m.csv.gz")
json.dump(ozet, open(f"{OUT}/ozet.json", "w"), indent=1)
