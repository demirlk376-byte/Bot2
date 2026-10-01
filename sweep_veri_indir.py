"""
sweep_veri_indir.py — LIQUIDITY_SWEEP_V1 ham veri indirici (yalnız kamuya açık veri, anahtar yok).

İndirilenler (her sembol için ayrı dosya, numpy savez_compressed):
  mexc_5m/<COIN>.npz      MEXC USDT-M sürekli vadeli 5m mum (contract API, Min5)
  binance_5m/<COIN>.npz   Binance USDⓈ-M sürekli vadeli 5m mum (data.binance.vision)
  binance_funding/<COIN>.csv   Binance funding geçmişi (gerçek settlement zamanları)
  mexc_funding/<COIN>.csv      MEXC funding geçmişi (API'nin verdiği kadar)
  mexc_contract_detail.json    MEXC güncel sözleşme metadatası (contractSize, priceUnit, volUnit, minVol)
  indirme_ozeti.json           kapsam, boşluk, sha256
npz alanları: open_time_ms (int64, mum AÇILIŞ), open, high, low, close, volume (float64).
Son, oluşmakta olan mum atılır. Boşluk doldurulmaz.
"""
import hashlib, io, json, os, sys, time, zipfile
import numpy as np
import pandas as pd
import requests

SEMBOLLER = ["SOL", "ETH", "ADA", "NEAR", "BCH", "XRP", "DOGE", "TRX", "XLM", "LTC", "ICP", "BNB"]
BAS = pd.Timestamp("2023-01-01", tz="UTC")
SIMDI = pd.Timestamp.now(tz="UTC")
OUT = sys.argv[1] if len(sys.argv) > 1 else "veri"
S = requests.Session()
S.headers.update({"User-Agent": "bot2-sweep-veri/1.0"})
ozet = {"olusturma": str(SIMDI), "baslangic": str(BAS), "semboller": SEMBOLLER, "dosyalar": {}}


def get(url, params=None, tries=5, ok404=False):
    for k in range(tries):
        try:
            r = S.get(url, params=params, timeout=60)
            if ok404 and r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:
            if k == tries - 1:
                print("HATA", url, params, e, flush=True)
                return None
            time.sleep(2 ** k)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def kaydet_npz(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, open_time_ms=d["open_time_ms"].to_numpy("int64"),
                        **{c: d[c].to_numpy("float64") for c in ("open", "high", "low", "close", "volume")})
    t = pd.to_datetime(d["open_time_ms"], unit="ms", utc=True)
    dt = t.diff().dropna()
    ozet["dosyalar"][path] = dict(sha256=sha(path), satir=len(d), ilk=str(t.min()), son=str(t.max()),
                                 bosluk_sayisi=int((dt > pd.Timedelta(minutes=5)).sum()),
                                 eksik_bar=int(((dt / pd.Timedelta(minutes=5)) - 1).clip(lower=0).sum()),
                                 tekrar=int((dt == pd.Timedelta(0)).sum()))


def temizle(d):
    d = d.astype({"open_time_ms": "int64"}).sort_values("open_time_ms")
    cak = d.duplicated("open_time_ms", keep=False) & ~d.duplicated(keep=False)
    if cak.any():
        print("  ÇATIŞAN satır:", int(cak.sum()), flush=True)
    d = d.drop_duplicates()
    d = d[~d.duplicated("open_time_ms", keep=False)]          # çatışanları kullanma
    d = d[d["open_time_ms"] + 300_000 <= int(SIMDI.timestamp() * 1000)]   # oluşan mumu at
    return d.reset_index(drop=True)


# ── MEXC sözleşme metadatası ──────────────────────────────────────────────────
r = get("https://contract.mexc.com/api/v1/contract/detail")
det = {}
if r is not None:
    for x in r.json().get("data", []):
        b = x.get("symbol", "").replace("_USDT", "")
        if b in SEMBOLLER and x.get("symbol", "").endswith("_USDT"):
            det[b] = x
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "mexc_contract_detail.json"), "w") as f:
    json.dump(det, f, indent=1)
print("MEXC detail:", sorted(det), flush=True)

# ── MEXC 5m ───────────────────────────────────────────────────────────────────
for c in SEMBOLLER:
    cur, son, parca, bos = int(BAS.timestamp()), int(SIMDI.timestamp()), [], 0
    while cur < son:
        bit = min(cur + 1990 * 300, son)
        r = get(f"https://contract.mexc.com/api/v1/contract/kline/{c}_USDT",
                {"interval": "Min5", "start": cur, "end": bit})
        k = (r.json().get("data") or {}) if r is not None else {}
        t = k.get("time") or []
        if t:
            parca.append(pd.DataFrame({"open_time_ms": np.asarray(t, dtype="int64") * 1000, "open": k["open"],
                                       "high": k["high"], "low": k["low"], "close": k["close"], "volume": k["vol"]}))
            cur = max(int(t[-1]) + 300, cur + 300)
        else:
            bos += 1
            cur = bit
        time.sleep(0.12)
    if parca:
        d = temizle(pd.concat(parca, ignore_index=True))
        kaydet_npz(os.path.join(OUT, "mexc_5m", f"{c}.npz"), d)
        print(f"MEXC {c}: {len(d)} bar {ozet['dosyalar'][os.path.join(OUT, 'mexc_5m', c + '.npz')]['ilk']}", flush=True)
    else:
        print(f"MEXC {c}: veri yok", flush=True)

# ── Binance 5m + funding ──────────────────────────────────────────────────────
V = "https://data.binance.vision/data/futures/um"


def zip_df(content, kolon):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        ham = z.read(z.namelist()[0]).decode()
    ilk = ham.split("\n", 1)[0].split(",")[0].strip()
    d = pd.read_csv(io.StringIO(ham), header=None if ilk.lstrip("-").isdigit() else 0)
    return d


for c in SEMBOLLER:
    sym = f"{c}USDT"
    kl, fr = [], []
    ay, bu_ay = BAS.tz_localize(None).to_period("M"), SIMDI.tz_localize(None).to_period("M")
    while ay < bu_ay:
        r = get(f"{V}/monthly/klines/{sym}/5m/{sym}-5m-{ay}.zip", ok404=True)
        if r is not None:
            d = zip_df(r.content, None).iloc[:, :6]
            d.columns = ["open_time_ms", "open", "high", "low", "close", "volume"]
            kl.append(d)
        else:
            for g in pd.date_range(ay.start_time, ay.end_time.floor("D"), freq="D"):
                r2 = get(f"{V}/daily/klines/{sym}/5m/{sym}-5m-{g.date()}.zip", ok404=True)
                if r2 is not None:
                    d = zip_df(r2.content, None).iloc[:, :6]
                    d.columns = ["open_time_ms", "open", "high", "low", "close", "volume"]
                    kl.append(d)
        r = get(f"{V}/monthly/fundingRate/{sym}/{sym}-fundingRate-{ay}.zip", ok404=True)
        if r is not None:
            fr.append(zip_df(r.content, None))
        ay += 1
    for g in pd.date_range(bu_ay.start_time, (SIMDI.floor("D") - pd.Timedelta(days=1)).tz_localize(None), freq="D"):
        r2 = get(f"{V}/daily/klines/{sym}/5m/{sym}-5m-{g.date()}.zip", ok404=True)
        if r2 is not None:
            d = zip_df(r2.content, None).iloc[:, :6]
            d.columns = ["open_time_ms", "open", "high", "low", "close", "volume"]
            kl.append(d)
    if kl:
        d = pd.concat(kl, ignore_index=True)
        d["open_time_ms"] = d["open_time_ms"].astype("int64")
        d.loc[d["open_time_ms"] > 10**14, "open_time_ms"] //= 1000      # µs → ms (şemaya göre)
        d = temizle(d.astype({c_: float for c_ in ("open", "high", "low", "close", "volume")}))
        kaydet_npz(os.path.join(OUT, "binance_5m", f"{c}.npz"), d)
        print(f"BINANCE {c}: {len(d)} bar", flush=True)
    if fr:
        f = pd.concat(fr, ignore_index=True)
        f.columns = [str(x) for x in f.columns]
        os.makedirs(os.path.join(OUT, "binance_funding"), exist_ok=True)
        p = os.path.join(OUT, "binance_funding", f"{c}.csv")
        f.to_csv(p, index=False)
        ozet["dosyalar"][p] = dict(sha256=sha(p), satir=len(f), kolonlar=list(f.columns))

# ── MEXC funding geçmişi ──────────────────────────────────────────────────────
for c in SEMBOLLER:
    rows, page = [], 1
    while page < 200:
        r = get("https://contract.mexc.com/api/v1/contract/funding_rate/history",
                {"symbol": f"{c}_USDT", "page_num": page, "page_size": 1000})
        if r is None:
            break
        dd = (r.json().get("data") or {})
        lst = dd.get("resultList") or []
        rows += lst
        if page >= int(dd.get("totalPage") or 1) or not lst:
            break
        page += 1
        time.sleep(0.2)
    if rows:
        os.makedirs(os.path.join(OUT, "mexc_funding"), exist_ok=True)
        p = os.path.join(OUT, "mexc_funding", f"{c}.csv")
        pd.DataFrame(rows).to_csv(p, index=False)
        ozet["dosyalar"][p] = dict(sha256=sha(p), satir=len(rows))

with open(os.path.join(OUT, "indirme_ozeti.json"), "w") as f:
    json.dump(ozet, f, indent=1)
print(json.dumps({k: (v.get("satir"), v.get("ilk"), v.get("eksik_bar")) for k, v in ozet["dosyalar"].items()}, indent=0))
