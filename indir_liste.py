"""Binance USDⓈ-M: arşivde bulunan TÜM USDT perp sembolleri (delist edilenler dahil) için günlük mumlar
ve funding. Kaynak: data.binance.vision S3 listesi (anahtarsız). Çıktı:
  veri/semboller.json  — sembol → {ilk_ay, son_ay}
  veri/1d/<SYM>.csv    — open_time,open,high,low,close,volume,quote_volume
  veri/funding/<SYM>.csv — calc_time,last_funding_rate
"""
import io, os, re, json, time, zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
B = "https://data.binance.vision"
OUT = "veri"; os.makedirs(f"{OUT}/1d", exist_ok=True); os.makedirs(f"{OUT}/funding", exist_ok=True)
ses = requests.Session()
ses.mount("https://", requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=3))
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def listele(prefix, delim=True):
    out, marker = [], ""
    while True:
        p = {"prefix": prefix, "marker": marker}
        if delim:
            p["delimiter"] = "/"
        r = ses.get(S3, params=p, timeout=60); r.raise_for_status()
        x = ET.fromstring(r.text)
        if delim:
            out += [e.find(f"{NS}Prefix").text for e in x.findall(f"{NS}CommonPrefixes")]
        else:
            out += [e.find(f"{NS}Key").text for e in x.findall(f"{NS}Contents")]
        if x.find(f"{NS}IsTruncated").text != "true":
            return out
        marker = (out[-1] if out else "")


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


def csv_oku(ham, kol):
    d = pd.read_csv(io.StringIO(ham), header=None if ham[:1].isdigit() else 0)
    d = d.iloc[:, :len(kol)]; d.columns = kol[:d.shape[1]]
    return d


pref = listele("data/futures/um/monthly/klines/")
semboller = sorted({p.rstrip("/").split("/")[-1] for p in pref})
semboller = [s for s in semboller if s.endswith("USDT") and re.fullmatch(r"[A-Z0-9]+USDT", s)]
print("sembol sayısı:", len(semboller), flush=True)
ozet = {}


def isle(sym):
    try:
        anahtarlar = listele(f"data/futures/um/monthly/klines/{sym}/1d/", delim=False)
        zipler = sorted(k for k in anahtarlar if k.endswith(".zip"))
        if not zipler:
            return sym, None
        parca = [al(f"{B}/{k}") for k in zipler]
        parca = [p for p in parca if p]
        kol = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"]
        d = pd.concat([csv_oku(p, kol) for p in parca]).drop_duplicates("open_time").sort_values("open_time")
        t = pd.to_numeric(d.open_time); d["open_time"] = t.where(t < 10**14, t // 1000)
        d[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].to_csv(f"{OUT}/1d/{sym}.csv", index=False)
        fz = listele(f"data/futures/um/monthly/fundingRate/{sym}/", delim=False)
        fp = [al(f"{B}/{k}") for k in sorted(k for k in fz if k.endswith(".zip"))]
        fp = [p for p in fp if p]
        if fp:
            f = pd.concat([csv_oku(p, ["calc_time", "funding_interval_hours", "last_funding_rate"]) for p in fp])
            f = f[["calc_time", "last_funding_rate"]].drop_duplicates("calc_time").sort_values("calc_time")
            f.to_csv(f"{OUT}/funding/{sym}.csv", index=False)
        return sym, dict(ilk_ay=zipler[0][-11:-4], son_ay=zipler[-1][-11:-4], gun=len(d), funding=len(fp))
    except Exception as e:
        return sym, dict(hata=f"{type(e).__name__}: {e}")


with ThreadPoolExecutor(8) as ex:
    for i, (s, o) in enumerate(ex.map(isle, semboller)):
        ozet[s] = o
        if i % 50 == 0:
            print(i, s, o, flush=True)
json.dump(ozet, open(f"{OUT}/semboller.json", "w"), indent=1)
print("tamam:", sum(1 for v in ozet.values() if v and "hata" not in v), "/", len(ozet))
