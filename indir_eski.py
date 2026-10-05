"""12 bot coini, Binance USDⓈ-M 1h, 2019-12 → 2023-05 (ikizin eski dönem testi için).
Çıktı: veri/<COIN>_fut_1h.csv (ts,open,high,low,close,volume — ikiz/fast_bt biçimi)."""
import io, os, json, time, zipfile
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests

B = "https://data.binance.vision/data/futures/um/monthly/klines"
OUT = "veri"; os.makedirs(OUT, exist_ok=True)
COINS = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
AYLAR = [p.strftime("%Y-%m") for p in pd.period_range("2019-12", "2023-05", freq="M")]
ses = requests.Session()
ses.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3))
ozet = {}


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


for c in COINS:
    sym = f"{c}USDT"
    with ThreadPoolExecutor(16) as ex:
        parca = [p for p in ex.map(al, [f"{B}/{sym}/1h/{sym}-1h-{a}.zip" for a in AYLAR]) if p]
    if not parca:
        ozet[c] = "YOK"; continue
    dfs = []
    for p in parca:
        basliksiz = p[:1].isdigit()
        d = pd.read_csv(io.StringIO(p), header=None if basliksiz else 0).iloc[:, :6]
        d.columns = ["open_time", "open", "high", "low", "close", "volume"]
        dfs.append(d)
    d = pd.concat(dfs).drop_duplicates("open_time").sort_values("open_time")
    t = pd.to_numeric(d.open_time)
    t = t.where(t < 10**14, t // 1000)
    d["ts"] = (pd.Timestamp("1970-01-01", tz="UTC") + pd.to_timedelta(t, unit="ms")).astype(str)
    d[["ts", "open", "high", "low", "close", "volume"]].to_csv(f"{OUT}/{c}_fut_1h.csv", index=False)
    ozet[c] = dict(satir=len(d), ilk=d.ts.iloc[0], son=d.ts.iloc[-1])
    print(c, ozet[c], flush=True)
json.dump(ozet, open(f"{OUT}/ozet.json", "w"), indent=1)
