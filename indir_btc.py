"""BTC boy araştırması verisi — Binance kamu arşivi (data.binance.vision), anahtarsız.
Çıktı (veri/):
  BTC_spot_1d.csv      spot BTCUSDT günlük, 2017-08 →
  {BTC,ETH,BTCDOM}_fut_1h.csv  USDⓈ-M vadeli saatlik (BTCDOM listelendiği aydan)
  BTC_funding.csv      vadeli funding oranları
  BTC_metrics_1h.csv   OI, top-trader/retail L/S, taker al/sat oranı (saatin son kaydı), 2021-12 →
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


def csv_oku(ham, kolonlar):
    ilk = ham.split("\n", 1)[0]
    basliksiz = ilk[:1].isdigit()
    d = pd.read_csv(io.StringIO(ham), header=None if basliksiz else 0)
    if basliksiz:
        d.columns = kolonlar[:d.shape[1]]
    return d


def ms(seri):
    seri = pd.to_numeric(seri)
    return seri.where(seri < 10**14, seri // 1000).astype("int64")   # mikro saniye → ms


def aylar(bas):
    return [p.strftime("%Y-%m") for p in pd.period_range(bas, BUGUN - pd.offsets.MonthBegin(1), freq="M")]


def gunler(ay):
    """Aylık dosyası henüz olmayan (içinde bulunulan) ay için günlük dosyalar."""
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(ay + "-01", BUGUN - pd.Timedelta(days=1))]


def klines(pazar, sym, tf, bas, dosya):
    kok = f"{B}/{pazar}/monthly/klines/{sym}/{tf}"
    urls = [f"{kok}/{sym}-{tf}-{a}.zip" for a in aylar(bas)]
    # aylık dosyası henüz yayımlanmamış olabilecek son iki ay için günlük dosyalar da (tekrarlar atılır)
    onceki_ay = (BUGUN - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    urls += [f"{B}/{pazar}/daily/klines/{sym}/{tf}/{sym}-{tf}-{g}.zip" for g in gunler(onceki_ay)]
    with ThreadPoolExecutor(16) as ex:
        parca = [p for p in ex.map(al, urls) if p]
    d = pd.concat([csv_oku(p, KL) for p in parca], ignore_index=True)
    d["open_time"] = ms(d["open_time"])
    d = d[KL[:6] + ["quote_volume", "taker_buy_volume"]].drop_duplicates("open_time").sort_values("open_time")
    d.to_csv(f"{OUT}/{dosya}", index=False)
    ozet[dosya] = dict(satir=len(d), ilk=str(pd.to_datetime(d.open_time.min(), unit="ms")),
                       son=str(pd.to_datetime(d.open_time.max(), unit="ms")))
    print(dosya, ozet[dosya], flush=True)


def funding():
    kok = f"{B}/futures/um/monthly/fundingRate/BTCUSDT"
    with ThreadPoolExecutor(16) as ex:
        parca = [p for p in ex.map(al, [f"{kok}/BTCUSDT-fundingRate-{a}.zip" for a in aylar("2019-09")]) if p]
    d = pd.concat([csv_oku(p, ["calc_time", "funding_interval_hours", "last_funding_rate"]) for p in parca])
    d["calc_time"] = ms(d["calc_time"])
    d = d[["calc_time", "last_funding_rate"]].drop_duplicates("calc_time").sort_values("calc_time")
    d.to_csv(f"{OUT}/BTC_funding.csv", index=False)
    ozet["BTC_funding.csv"] = dict(satir=len(d), ilk=str(pd.to_datetime(d.calc_time.min(), unit="ms")))
    print("funding", ozet["BTC_funding.csv"], flush=True)


def metrics():
    gun = [d.strftime("%Y-%m-%d") for d in pd.date_range("2021-12-01", BUGUN - pd.Timedelta(days=1))]
    urls = [f"{B}/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{g}.zip" for g in gun]
    with ThreadPoolExecutor(16) as ex:
        parca = [p for p in ex.map(al, urls) if p]
    d = pd.concat([pd.read_csv(io.StringIO(p)) for p in parca], ignore_index=True)
    ts = pd.to_datetime(d["create_time"], utc=True)
    d["t"] = ((ts - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).astype("int64")
    kol = [k for k in ["sum_open_interest_value", "sum_open_interest", "count_toptrader_long_short_ratio",
                       "sum_toptrader_long_short_ratio", "count_long_short_ratio",
                       "sum_taker_long_short_vol_ratio"] if k in d.columns]
    d = d[["t"] + kol].drop_duplicates("t").sort_values("t")
    H = 3_600_000
    g = d.assign(t_kapanis=(d.t // H) * H + H).groupby("t_kapanis").last().drop(columns="t").reset_index()
    g.to_csv(f"{OUT}/BTC_metrics_1h.csv", index=False)
    ozet["BTC_metrics_1h.csv"] = dict(satir=len(g), ilk=str(pd.to_datetime(g.t_kapanis.min(), unit="ms")))
    print("metrics", ozet["BTC_metrics_1h.csv"], flush=True)


klines("spot", "BTCUSDT", "1d", "2017-08", "BTC_spot_1d.csv")
klines("futures/um", "BTCUSDT", "1h", "2019-09", "BTC_fut_1h.csv")
klines("futures/um", "ETHUSDT", "1h", "2019-11", "ETH_fut_1h.csv")
klines("futures/um", "BTCDOMUSDT", "1h", "2021-06", "BTCDOM_fut_1h.csv")
funding()
metrics()
json.dump(ozet, open(f"{OUT}/ozet.json", "w"), indent=1)
