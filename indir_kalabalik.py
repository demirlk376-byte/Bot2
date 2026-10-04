"""Binance USDⓈ-M kamu arşivi (data.binance.vision): metrics + bookDepth → sıkıştırılmış özet CSV'ler.
metrics (5m): sum_open_interest, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
              count_long_short_ratio, sum_taker_long_short_vol_ratio
  → 36 coin için 1h (saat içindeki SON kayıt) ve 12 bot coini için 15m.
bookDepth (yaklaşık 30 sn anlık derinlik, yüzde bantları) → 12 bot coini için 5m dengesizlik:
  imb1 = (alış − satış)/(alış + satış) ±%1 bandında birikimli notional; imb2 aynı ±%2; tavan 5m'deki SON anlık.
Dönem: metrics 2022-01-01 → 2026-01-08, bookDepth 2023-01-01 → 2026-01-08 (araştırmaların FİNAL'i hariç).
Anahtarsız, yalnız kamu arşivi."""
import io, os, sys, json, zipfile, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, numpy as np, requests

V = "https://data.binance.vision/data/futures/um/daily"
OUT = "veri"; os.makedirs(OUT, exist_ok=True)
BOT12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
DIGER = "LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV HBAR VET APT ARB OP INJ SUI".split()
BIT = pd.Timestamp("2026-01-08")
ses = requests.Session()
ses.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3))
ozet = {"metrics": {}, "bookDepth": {}, "ornek": {}}


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


def gunler(bas):
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(bas, BIT - pd.Timedelta(days=1))]


def metrics(coin):
    sym = f"{coin}USDT"
    urls = [f"{V}/metrics/{sym}/{sym}-metrics-{g}.zip" for g in gunler("2022-01-01")]
    with ThreadPoolExecutor(16) as ex:
        parcalar = [p for p in ex.map(al, urls) if p]
    if not parcalar:
        ozet["metrics"][coin] = "YOK"; return
    if coin == "ETH":
        ozet["ornek"]["metrics"] = parcalar[0][:400]
    df = pd.concat([pd.read_csv(io.StringIO(p)) for p in parcalar], ignore_index=True)
    df["t"] = pd.to_datetime(df["create_time"], utc=True).astype("int64") // 10**6
    kol = ["sum_open_interest", "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
           "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
    df = df[["t"] + [k for k in kol if k in df.columns]].drop_duplicates("t").sort_values("t")
    for ad, ms in (("1h", 3_600_000), ("15m", 900_000)):
        if ad == "15m" and coin not in BOT12:
            continue
        g = df.assign(b=(df.t // ms) * ms + ms).groupby("b").last().drop(columns="t").reset_index().rename(columns={"b": "t_kapanis"})
        g.round(6).to_csv(f"{OUT}/{coin}_metrics_{ad}.csv.gz", index=False, compression="gzip")
    ozet["metrics"][coin] = dict(satir=len(df), ilk=str(pd.to_datetime(df.t.min(), unit="ms")),
                                 son=str(pd.to_datetime(df.t.max(), unit="ms")))
    print("metrics", coin, ozet["metrics"][coin], flush=True)


def bookdepth(coin):
    sym = f"{coin}USDT"
    urls = [f"{V}/bookDepth/{sym}/{sym}-bookDepth-{g}.zip" for g in gunler("2023-01-01")]
    satirlar = []

    def isle(u):
        p = al(u)
        if not p:
            return None
        d = pd.read_csv(io.StringIO(p))
        if "percentage" not in d.columns:
            return ("BICIM", list(d.columns))
        d["t"] = pd.to_datetime(d["timestamp"], utc=True).astype("int64") // 10**6
        d["b"] = (d.t // 300_000) * 300_000 + 300_000
        son_t = d.groupby("b").t.max().rename("st")
        d = d.join(son_t, on="b")
        d = d[d.t == d.st]
        piv = d.pivot_table(index="b", columns="percentage", values="notional", aggfunc="last")
        out = pd.DataFrame(index=piv.index)
        for bant in (1, 2):
            a = piv.get(-bant); s = piv.get(bant)
            if a is None or s is None:
                continue
            out[f"imb{bant}"] = ((a - s) / (a + s)).round(4)
        return out
    with ThreadPoolExecutor(12) as ex:
        for r in ex.map(isle, urls):
            if r is None:
                continue
            if isinstance(r, tuple):
                ozet["bookDepth"][coin] = f"BEKLENMEYEN BICIM {r[1]}"; return
            satirlar.append(r)
    if not satirlar:
        ozet["bookDepth"][coin] = "YOK"; return
    df = pd.concat(satirlar).sort_index()
    df.index.name = "t_kapanis"
    df.reset_index().to_csv(f"{OUT}/{coin}_bookdepth_5m.csv.gz", index=False, compression="gzip")
    ozet["bookDepth"][coin] = dict(satir=len(df), ilk=str(pd.to_datetime(df.index.min(), unit="ms")),
                                   son=str(pd.to_datetime(df.index.max(), unit="ms")))
    print("bookDepth", coin, ozet["bookDepth"][coin], flush=True)


# biçim örneği (ilk mevcut bookDepth günü)
for g in ("2023-01-02", "2024-01-02", "2025-01-02"):
    p = al(f"{V}/bookDepth/ETHUSDT/ETHUSDT-bookDepth-{g}.zip")
    if p:
        ozet["ornek"]["bookDepth"] = p[:600]; break
for c in BOT12 + DIGER:
    metrics(c)
for c in BOT12:
    bookdepth(c)
json.dump(ozet, open(f"{OUT}/ozet.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: v for k, v in ozet.items() if k != "ornek"}, ensure_ascii=False)[:3000])
