"""Binance USDⓈ-M 1d mum + fundingRate, 2019-09 → bugün (kamuya açık; anahtar yok)."""
import io, json, os, sys, time, zipfile, hashlib
import pandas as pd, requests
S = "LINK AVAX DOT UNI ATOM FIL ETC AAVE ALGO XTZ SAND MANA AXS EGLD RUNE EOS THETA GRT CRV HBAR VET APT ARB OP INJ SUI".split()
V = "https://data.binance.vision/data/futures/um"
OUT = "veri"; os.makedirs(OUT, exist_ok=True)
now = pd.Timestamp.now(tz="UTC"); ses = requests.Session()
def z(c):
    with zipfile.ZipFile(io.BytesIO(c)) as f: raw = f.read(f.namelist()[0]).decode()
    hdr = not raw.split(",",1)[0].strip().lstrip("-").isdigit()
    return pd.read_csv(io.StringIO(raw), header=0 if hdr else None)
ozet = {}
for c in S:
    sym = f"{c}USDT"; kl, fr = [], []
    for ay in pd.period_range("2019-09", now.tz_localize(None).to_period("M") - 1, freq="M"):
        r = ses.get(f"{V}/monthly/klines/{sym}/1d/{sym}-1d-{ay}.zip", timeout=60)
        if r.status_code == 200:
            d = z(r.content).iloc[:, :6]; d.columns = ["open_time","open","high","low","close","volume"]; kl.append(d)
        r = ses.get(f"{V}/monthly/fundingRate/{sym}/{sym}-fundingRate-{ay}.zip", timeout=60)
        if r.status_code == 200:
            d = z(r.content); d = d.iloc[:, [0, d.shape[1]-1]]; d.columns = ["calc_time","last_funding_rate"]; fr.append(d)
    for g in pd.date_range(now.tz_localize(None).to_period("M").start_time, now.floor("D").tz_localize(None) - pd.Timedelta(days=1)):
        r = ses.get(f"{V}/daily/klines/{sym}/1d/{sym}-1d-{g.date()}.zip", timeout=60)
        if r.status_code == 200:
            d = z(r.content).iloc[:, :6]; d.columns = ["open_time","open","high","low","close","volume"]; kl.append(d)
    k = pd.concat(kl).astype({"open_time":"int64"}).drop_duplicates("open_time").sort_values("open_time")
    k.to_csv(f"{OUT}/{c}_1d.csv", index=False)
    f = pd.concat(fr).dropna().drop_duplicates("calc_time").sort_values("calc_time") if fr else pd.DataFrame()
    f.to_csv(f"{OUT}/{c}_funding.csv", index=False)
    ozet[c] = dict(gun=len(k), ilk=str(pd.to_datetime(k.open_time.min(), unit="ms")), son=str(pd.to_datetime(k.open_time.max(), unit="ms")), funding=len(f))
    print(c, ozet[c], flush=True)
json.dump(dict(olusturma=str(now), ozet=ozet), open(f"{OUT}/ozet.json","w"), indent=1)

r = ses.get("https://contract.mexc.com/api/v1/contract/detail", timeout=60)
try:
    det = {e["baseCoin"]: e for e in r.json()["data"] if e.get("quoteCoin") == "USDT" and e["symbol"] == e["baseCoin"] + "_USDT"}
    json.dump({c: det[c] for c in S if c in det}, open(f"{OUT}/mexc_contract_detail.json", "w"), indent=1)
    print("mexc", sorted(c for c in S if c in det))
except Exception as e:
    print("mexc metadata alinamadi", r.status_code, e)
