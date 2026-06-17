"""
research_xau_validation.py — XAU (altın) MEXC perp validasyonu

Binance'te XAU yok, o yüzden MEXC'in KENDİ perp geçmişini ccxt ile çeker
(canlı botun veri kaynağıyla aynı). ORB + Asia BO + BB'yi BTC paramlarıyla
test eder. Ayrıca hafta-sonu davranışını ölçer — altın hafta sonu ölüyse
BB (hafta-sonu only) çalışmaz.

NOT: MEXC fetchOHLCV geçmişi sınırlı olabilir (birkaç ay). Kısa pencere =
zayıf istatistik; sonucu o gözle oku. n (trade sayısı) düşükse güvenme.

Çalıştır (VPS'te, ccxt kurulu):  python3 research_xau_validation.py
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

SYMBOL = "XAU/USDT:USDT"   # gerekirse "PAXG/USDT:USDT" dene
BAL    = 10_000.0
FEE    = 0.0001


# ── Indicators ───────────────────────────────────────────────────────
def _atr(h, l, c, p=14):
    h, l, c = np.asarray(h, float), np.asarray(l, float), np.asarray(c, float)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h-l, np.maximum(np.abs(h-pc), np.abs(l-pc)))
    a = np.zeros(len(tr)); a[p-1] = tr[:p].mean() if len(tr) >= p else 0
    for i in range(p, len(tr)): a[i] = (a[i-1]*(p-1)+tr[i])/p
    return a

def _adx(h, l, c, p=14):
    h, l, c = np.asarray(h, float), np.asarray(l, float), np.asarray(c, float)
    n = len(h)
    if n < 2*p: return np.zeros(n)
    pdm = np.where(h[1:]-h[:-1] > l[:-1]-l[1:], np.maximum(h[1:]-h[:-1], 0), 0.0)
    ndm = np.where(l[:-1]-l[1:] > h[1:]-h[:-1], np.maximum(l[:-1]-l[1:], 0), 0.0)
    atr14 = _atr(h, l, c, p)
    def sm(x):
        r = np.zeros(n); r[p] = x[:p].sum()
        for i in range(p+1, n): r[i] = r[i-1] - r[i-1]/p + x[i-1]
        return r
    sp = sm(pdm); sn = sm(ndm)
    pdi = np.zeros(n); ndi = np.zeros(n); dx = np.zeros(n)
    for i in range(p, n):
        if atr14[i] > 0:
            pdi[i] = 100*sp[i]/atr14[i]; ndi[i] = 100*sn[i]/atr14[i]
        s = pdi[i]+ndi[i]; dx[i] = 100*abs(pdi[i]-ndi[i])/s if s>0 else 0.0
    adx_ = np.zeros(n); adx_[2*p-1] = dx[p:2*p].mean()
    for i in range(2*p, n): adx_[i] = (adx_[i-1]*(p-1)+dx[i])/p
    return adx_

def _bb(c, p=20, s=2.0):
    c = pd.Series(c); mid = c.rolling(p).mean().values
    sig = c.rolling(p).std(ddof=0).values
    return mid+s*sig, mid-s*sig

def _volma(v, p=20):
    return pd.Series(v).rolling(p).mean().values


# ── MEXC data via ccxt (paginated history) ───────────────────────────
def load_mexc(symbol: str) -> pd.DataFrame:
    import ccxt
    ex = ccxt.mexc({
        "options": {"defaultType": "swap", "defaultSubType": "linear"},
        "enableRateLimit": True,
    })
    ex.load_markets()
    if symbol not in ex.markets:
        # sembol farklı yazılmış olabilir — adayları göster
        cands = [m for m in ex.markets if "XAU" in m or "PAXG" in m or "GOLD" in m.upper()]
        raise RuntimeError(
            f"{symbol} MEXC swap'ta yok. Altın adayları: {cands or 'HİÇBİRİ'}"
        )

    all_rows = []
    since = ex.parse8601("2023-01-01T00:00:00Z")
    now = ex.milliseconds()
    while since < now:
        batch = ex.fetch_ohlcv(symbol, timeframe="1h", since=since, limit=1000)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + 3_600_000
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)

    if not all_rows:
        raise RuntimeError(f"{symbol} için OHLC dönmedi")
    df = pd.DataFrame(all_rows, columns=["ts","open","high","low","close","volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts")
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts")[["open","high","low","close","volume"]].astype(float)


# ── Backtests (BTC params, identical to crosscoin) ───────────────────
def run_bb(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    v=df["volume"].values; idx=df.index; n=len(c)
    if n < 60: return []
    atr14=_atr(h,l,c,14); adx14=_adx(h,l,c,14)
    up,lo=_bb(c,20,2.0); vma=_volma(v,20)
    trades=[]; pos=None
    for i in range(50,n):
        if pos and (i-pos["bar"])>=48:
            p_=(pos["dir"]*(c[i]-pos["ep"])/pos["ep"])*pos["risk"]/pos["sld"]*pos["ep"]
            trades.append({"ts":idx[i],"pnl":p_-pos["ntl"]*FEE}); pos=None
        if pos:
            if pos["dir"]==1:
                if l[i]<=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if h[i]>=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*5/3-pos["ntl"]*FEE}); pos=None; continue
            else:
                if h[i]>=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if l[i]<=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*5/3-pos["ntl"]*FEE}); pos=None; continue
        if pos: continue
        if idx[i].weekday() not in (5,6): continue   # hafta-sonu only
        atr_v=atr14[i]; adx_v=adx14[i]
        if atr_v<=0 or adx_v>=28 or vma[i]<=0 or np.isnan(up[i]): continue
        if v[i]<=vma[i]: continue
        risk=BAL*0.08; d=0; ep=c[i]
        if c[i]<lo[i]: d=1; sl=ep-3*atr_v; tp=ep+5*atr_v
        elif c[i]>up[i]: d=-1; sl=ep+3*atr_v; tp=ep-5*atr_v
        if d==0: continue
        sld=abs(ep-sl); ntl=(risk/sld)*ep
        pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
    return trades

def run_orb(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    idx=df.index; n=len(c); trades=[]; pos=None
    oh=ol=od=None; done=False
    for i in range(1,n):
        ts=idx[i]; bd=ts.date()
        if od!=bd: oh=ol=od=None; done=False
        if pos:
            if (i-pos["bar"])>=6:
                p_=(pos["dir"]*(c[i]-pos["ep"])/pos["ep"])*pos["risk"]/pos["sld"]*pos["ep"]
                trades.append({"ts":ts,"pnl":p_-pos["ntl"]*FEE}); pos=None
            elif pos["dir"]==1:
                if l[i]<=pos["sl"]: trades.append({"ts":ts,"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None
                elif h[i]>=pos["tp"]: trades.append({"ts":ts,"pnl":pos["risk"]*2-pos["ntl"]*FEE}); pos=None
            else:
                if h[i]>=pos["sl"]: trades.append({"ts":ts,"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None
                elif l[i]<=pos["tp"]: trades.append({"ts":ts,"pnl":pos["risk"]*2-pos["ntl"]*FEE}); pos=None
        if ts.hour==14: oh=h[i]; ol=l[i]; od=bd
        if oh and ts.hour>14 and not done and not pos:
            rng=oh-ol
            if rng<=0: continue
            risk=BAL*0.05; d=0; ep=None
            if c[i]>oh: d=1; ep=oh; sl=ol; tp=ep+2*rng
            elif c[i]<ol: d=-1; ep=ol; sl=oh; tp=ep-2*rng
            if d==0: continue
            sld=rng; ntl=(risk/sld)*ep
            pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
            done=True
    return trades

def run_asia(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    idx=df.index; n=len(c); atr14=_atr(h,l,c,14)
    trades=[]; pos=None; ah=-np.inf; al=np.inf; ad=None; done=False
    for i in range(1,n):
        ts=idx[i]; bd=ts.date()
        if ad!=bd: ah=-np.inf; al=np.inf; ad=bd; done=False
        if pos:
            if (i-pos["bar"])>=6:
                p_=(pos["dir"]*(c[i]-pos["ep"])/pos["ep"])*pos["risk"]/pos["sld"]*pos["ep"]
                trades.append({"ts":ts,"pnl":p_-pos["ntl"]*FEE}); pos=None
            elif pos["dir"]==1:
                if l[i]<=pos["sl"]: trades.append({"ts":ts,"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None
                elif h[i]>=pos["tp"]: trades.append({"ts":ts,"pnl":pos["risk"]*2-pos["ntl"]*FEE}); pos=None
            else:
                if h[i]>=pos["sl"]: trades.append({"ts":ts,"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None
                elif l[i]<=pos["tp"]: trades.append({"ts":ts,"pnl":pos["risk"]*2-pos["ntl"]*FEE}); pos=None
        if ts.hour<8: ah=max(ah,h[i]); al=min(al,l[i])
        if ts.hour>=8 and ah>al and not done and not pos:
            atr_v=atr14[i]
            if atr_v<=0: continue
            risk=BAL*0.03; d=0; ep=None
            if c[i]>ah: d=1; ep=ah; sl=ep-atr_v; tp=ep+2*atr_v
            elif c[i]<al: d=-1; ep=al; sl=ep+atr_v; tp=ep-2*atr_v
            if d==0: continue
            sld=atr_v; ntl=(risk/sld)*ep
            pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
            done=True
    return trades


def stats(tr):
    if not tr: return (0, 0.0, 0.0, 0.0)
    t = pd.DataFrame(tr)
    w = t[t["pnl"]>0]; l = t[t["pnl"]<=0]
    gw = w["pnl"].sum(); gl = abs(l["pnl"].sum()) or 0.001
    return (len(t), round(gw/gl,2), round(len(w)/len(t)*100,1), round(t["pnl"].sum(),0))


def main():
    print("="*60)
    print("XAU (ALTIN) VALIDASYONU — MEXC perp, BTC paramları")
    print("="*60)
    try:
        df = load_mexc(SYMBOL)
    except Exception as e:
        print(f"\n  ❌ {e}")
        return 1

    days = (df.index[-1] - df.index[0]).days
    print(f"\n  {len(df):,} bar  ({df.index[0].date()} → {df.index[-1].date()}, ~{days} gün)")

    # ── Hafta-sonu canlılık teşhisi (BB için kritik) ──
    we = df[df.index.weekday >= 5]; wd = df[df.index.weekday < 5]
    we_range = ((we["high"]-we["low"])/we["close"]).mean()*100 if len(we) else 0
    wd_range = ((wd["high"]-wd["low"])/wd["close"]).mean()*100 if len(wd) else 0
    we_vol = we["volume"].mean() if len(we) else 0
    wd_vol = wd["volume"].mean() if len(wd) else 0
    print(f"\n  Hafta-sonu teşhisi (BB hafta-sonu only çalışır):")
    print(f"    Hafta-içi  : ort mum aralığı %{wd_range:.2f}  ort hacim {wd_vol:,.0f}")
    print(f"    Hafta-sonu : ort mum aralığı %{we_range:.2f}  ort hacim {we_vol:,.0f}")
    if wd_vol > 0:
        ratio = we_vol/wd_vol*100
        print(f"    → Hafta-sonu hacim, hafta-içinin %{ratio:.0f}'i", end="")
        print("  ⚠️ ÖLÜ — BB işe yaramaz" if ratio < 30 else "  (canlı sayılır)")

    # ── Strateji sonuçları ──
    print(f"\n  {'Strateji':<10} {'n':>5} {'PF':>6} {'WR':>7} {'$PnL':>9}   karar")
    print(f"  {'-'*52}")
    for name, fn in [("BB", run_bb), ("ORB", run_orb), ("Asia BO", run_asia)]:
        n, pf, wr, pnl = stats(fn(df))
        if n < 30:
            verdict = "⚠️ az veri"
        elif pf >= 1.15:
            verdict = "✅ ekle"
        elif pf >= 1.0:
            verdict = "⚠️ marjinal"
        else:
            verdict = "❌ ekleme"
        print(f"  {name:<10} {n:>5} {pf:>6.2f} {wr:>6.1f}% {pnl:>+9.0f}   {verdict}")

    print(f"\n  ⚠️  Tek dönem (train/test split yok — geçmiş kısa). n<30 ise güvenme.")
    print(f"  ⚠️  Crypto'daki 3 yıl × train/test güvencesi YOK. İhtiyatlı ol.")
    print("="*60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
