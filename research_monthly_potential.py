"""
research_monthly_potential.py — Aylık gerçek getiri potansiyeli

3 coin (BTC + ETH + SOL) × 4 strateji (BB + ORB + Asia BO + FVG*) portföyü.
Üç yıl (2023-2025) aylık aylık P&L kırılımı. FVG sadece BTC'de (cross-coin
henüz test edilmedi); diğerleri 3 coinde de ✅ doğrulandı.

PARAMETRELER: canlı botla AYNI (sıfır re-tune):
  BB   : risk %8,  SL=3×ATR TP=5×ATR, weekend-only, ADX<28
  ORB  : risk %5,  SL=range  TP=2×range, 6h max-hold
  Asia : risk %3,  SL=1×ATR  TP=2×ATR,  6h max-hold
  FVG  : risk %2,  BTC only  (ETH/SOL cross-coin testi eksik)

Çalıştır:  python3 research_monthly_potential.py
"""
from __future__ import annotations

import io
import zipfile
from collections import defaultdict

import numpy as np
import pandas as pd
import requests

# ── Config ───────────────────────────────────────────────────────────
COINS       = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
YEARS       = [2023, 2024, 2025]
BAL         = 10_000.0   # normalize — tüm % getiriler buna göre
FEE         = 0.0001     # entry (maker) + exit (market)

RISK = {
    "bb":   0.08,
    "orb":  0.05,
    "asia": 0.03,
    "fvg":  0.02,   # sadece BTC
}


# ── Indicators ───────────────────────────────────────────────────────
def _atr(h, l, c, p=14):
    h, l, c = np.asarray(h, float), np.asarray(l, float), np.asarray(c, float)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h-l, np.maximum(np.abs(h-pc), np.abs(l-pc)))
    a = np.zeros(len(tr)); a[p-1] = tr[:p].mean()
    for i in range(p, len(tr)): a[i] = (a[i-1]*(p-1)+tr[i])/p
    return a

def _adx(h, l, c, p=14):
    h, l, c = np.asarray(h, float), np.asarray(l, float), np.asarray(c, float)
    n = len(h)
    pdm = np.where(h[1:]-h[:-1] > l[:-1]-l[1:], np.maximum(h[1:]-h[:-1], 0), 0.0)
    ndm = np.where(l[:-1]-l[1:] > h[1:]-h[:-1], np.maximum(l[:-1]-l[1:], 0), 0.0)
    atr14 = _atr(h, l, c, p)
    def sm(x):
        r = np.zeros(n)
        r[p] = x[:p].sum()
        for i in range(p+1, n): r[i] = r[i-1] - r[i-1]/p + x[i-1]
        return r
    sp = sm(pdm); sn = sm(ndm)
    pdi = np.zeros(n); ndi = np.zeros(n); dx = np.zeros(n)
    for i in range(p, n):
        if atr14[i] > 0:
            pdi[i] = 100*sp[i]/atr14[i]; ndi[i] = 100*sn[i]/atr14[i]
        s = pdi[i]+ndi[i]; dx[i] = 100*abs(pdi[i]-ndi[i])/s if s>0 else 0.0
    adx_ = np.zeros(n)
    if 2*p-1 < n: adx_[2*p-1] = dx[p:2*p].mean()
    for i in range(2*p, n): adx_[i] = (adx_[i-1]*(p-1)+dx[i])/p
    return adx_

def _bb(c, p=20, s=2.0):
    c = pd.Series(c); mid = c.rolling(p).mean().values
    sig = c.rolling(p).std(ddof=0).values
    return mid+s*sig, mid-s*sig

def _volma(v, p=20):
    return pd.Series(v).rolling(p).mean().values

def _ema200(c):
    return pd.Series(c).ewm(span=200, adjust=False).mean().values


# ── Data ─────────────────────────────────────────────────────────────
def load(symbol, years):
    base = "https://data.binance.vision/data/spot/monthly/klines"
    frames = []
    for y in years:
        for m in range(1, 13):
            url = f"{base}/{symbol}/1h/{symbol}-1h-{y}-{m:02d}.zip"
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200: continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    with z.open(z.namelist()[0]) as f:
                        df = pd.read_csv(f, header=None,
                            names=["ts","open","high","low","close","volume",
                                   "ct","qv","n","tbbv","tbqv","ig"])
                df = df[pd.to_numeric(df["ts"], errors="coerce").notna()].copy()
                df["ts"] = pd.to_numeric(df["ts"])
                unit = "us" if df["ts"].iloc[0] > 1e15 else "ms"
                df["ts"] = pd.to_datetime(df["ts"], unit=unit, utc=True)
                df = df.set_index("ts")[["open","high","low","close","volume"]].astype(float)
                frames.append(df)
            except Exception as e:
                print(f"  warn {symbol} {y}-{m:02d}: {e}")
    if not frames: raise RuntimeError(f"No data: {symbol}")
    return pd.concat(frames).sort_index()


# ── Strategy backtests (same as research_strategies_crosscoin.py) ────
def run_bb(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    v=df["volume"].values; idx=df.index; n=len(c)
    atr14=_atr(h,l,c,14); adx14=_adx(h,l,c,14)
    up,lo=_bb(c,20,2.0); vma=_volma(v,20)
    trades=[]; pos=None
    for i in range(50,n):
        if pos and (i-pos["bar"])>=48:
            p_=(pos["dir"]*(c[i]-pos["ep"])/pos["ep"])*pos["risk"]/pos["sld"]*pos["ep"]
            trades.append({"ts":idx[i],"pnl":p_-pos["ntl"]*FEE})
            pos=None
        if pos:
            if pos["dir"]==1:
                if l[i]<=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if h[i]>=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*5/3-pos["ntl"]*FEE}); pos=None; continue
            else:
                if h[i]>=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if l[i]<=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*5/3-pos["ntl"]*FEE}); pos=None; continue
        if pos: continue
        if idx[i].weekday() not in (5,6): continue
        atr_v=atr14[i]; adx_v=adx14[i]
        if atr_v<=0 or adx_v>=28 or vma[i]<=0 or np.isnan(up[i]): continue
        if v[i]<=vma[i]: continue
        risk=BAL*RISK["bb"]; d=0; ep=c[i]
        if c[i]<lo[i]: d=1; sl=ep-3*atr_v; tp=ep+5*atr_v
        elif c[i]>up[i]: d=-1; sl=ep+3*atr_v; tp=ep-5*atr_v
        if d==0: continue
        sld=abs(ep-sl); ntl=(risk/sld)*ep
        pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
    return trades

def run_orb(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    idx=df.index; n=len(c)
    trades=[]; pos=None
    oh=ol=od=None; done=False
    for i in range(1,n):
        ts=idx[i]; bar_date=ts.date()
        if od!=bar_date: oh=ol=od=None; done=False
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
        if ts.hour==14: oh=h[i]; ol=l[i]; od=bar_date
        if oh and ts.hour>14 and not done and not pos:
            rng=oh-ol
            if rng<=0: continue
            risk=BAL*RISK["orb"]; ep=None; d=0
            if c[i]>oh: d=1; ep=oh; sl=ol; tp=ep+2*rng
            elif c[i]<ol: d=-1; ep=ol; sl=oh; tp=ep-2*rng
            if d==0: continue
            sld=rng; ntl=(risk/sld)*ep
            pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
            done=True
    return trades

def run_asia(df):
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    idx=df.index; n=len(c)
    atr14=_atr(h,l,c,14)
    trades=[]; pos=None
    ah=-np.inf; al=np.inf; ad=None; done=False
    for i in range(1,n):
        ts=idx[i]; bar_date=ts.date()
        if ad!=bar_date: ah=-np.inf; al=np.inf; ad=bar_date; done=False
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
            risk=BAL*RISK["asia"]; d=0; ep=None
            if c[i]>ah: d=1; ep=ah; sl=ep-atr_v; tp=ep+2*atr_v
            elif c[i]<al: d=-1; ep=al; sl=ep+atr_v; tp=ep-2*atr_v
            if d==0: continue
            sld=atr_v; ntl=(risk/sld)*ep
            pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
            done=True
    return trades

def run_fvg(df):
    """Fair Value Gap — BTC only. EMA200 trend filter, gap>=0.5×ATR, RR 2.5."""
    h=df["high"].values; l=df["low"].values; c=df["close"].values
    o=df["open"].values; idx=df.index; n=len(c)
    atr14=_atr(h,l,c,14); e200=_ema200(c)
    trades=[]; pos=None
    for i in range(210,n):
        atr_v=atr14[i]
        if atr_v<=0 or np.isnan(e200[i]): continue
        if pos and (i-pos["bar"])>=48:
            p_=(pos["dir"]*(c[i]-pos["ep"])/pos["ep"])*pos["risk"]/pos["sld"]*pos["ep"]
            trades.append({"ts":idx[i],"pnl":p_-pos["ntl"]*FEE}); pos=None
        if pos:
            if pos["dir"]==1:
                if l[i]<=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if h[i]>=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*2.5-pos["ntl"]*FEE}); pos=None; continue
            else:
                if h[i]>=pos["sl"]: trades.append({"ts":idx[i],"pnl":-pos["risk"]-pos["ntl"]*FEE}); pos=None; continue
                if l[i]<=pos["tp"]: trades.append({"ts":idx[i],"pnl":pos["risk"]*2.5-pos["ntl"]*FEE}); pos=None; continue
        if pos: continue
        # Bullish FVG: candle[i-2] high < candle[i] low → gap bullish
        # Only trade with EMA200 trend
        if i<2: continue
        bull_gap = l[i] - h[i-2]
        bear_gap = l[i-2] - h[i]
        risk=BAL*RISK["fvg"]; d=0; ep=None; sl=None; tp=None
        if bull_gap >= 0.5*atr_v and c[i] > e200[i]:  # bullish FVG, uptrend
            mid = (l[i]+h[i-2])/2
            ep=mid; sl=ep-atr_v; tp=ep+2.5*atr_v; d=1
        elif bear_gap >= 0.5*atr_v and c[i] < e200[i]:  # bearish FVG, downtrend
            mid = (h[i]+l[i-2])/2
            ep=mid; sl=ep+atr_v; tp=ep-2.5*atr_v; d=-1
        if d==0: continue
        sld=abs(ep-sl); ntl=(risk/sld)*ep
        pos={"dir":d,"ep":ep,"sl":sl,"tp":tp,"risk":risk,"sld":sld,"ntl":ntl,"bar":i}
    return trades


# ── Monthly aggregator ────────────────────────────────────────────────
def monthly_pnl(trades: list) -> dict:
    m = defaultdict(float)
    for t in trades:
        key = t["ts"].strftime("%Y-%m")
        m[key] += t["pnl"]
    return dict(m)


# ── Main ──────────────────────────────────────────────────────────────
def main():
    print("=" * 68)
    print("AYLIK GETİRİ POTANSİYELİ — 3 Coin × 4 Strateji, 2023-2025")
    print("Baz bakiye $10,000 | FVG sadece BTC")
    print("=" * 68)

    all_monthly: dict[str, float] = defaultdict(float)
    coin_data = {}

    for sym in COINS:
        print(f"\n  {sym} verisi indiriliyor...")
        df = load(sym, YEARS)
        coin_data[sym] = df
        print(f"  {len(df):,} bar  ({df.index[0].date()} → {df.index[-1].date()})")

    print("\n  Strateji backtestleri çalıştırılıyor...\n")

    strategy_monthly: dict[str, dict] = {}

    for sym in COINS:
        df = coin_data[sym]
        short = sym.replace("USDT", "")

        bb_tr   = run_bb(df)
        orb_tr  = run_orb(df)
        asia_tr = run_asia(df)

        for name, tr in [("BB", bb_tr), ("ORB", orb_tr), ("Asia", asia_tr)]:
            key = f"{short}-{name}"
            mp = monthly_pnl(tr)
            strategy_monthly[key] = mp
            for month, pnl in mp.items():
                all_monthly[month] += pnl
            tot = sum(mp.values())
            n_tr = len(tr)
            print(f"  {key:12s}: {n_tr:4d} trade  toplam ${tot:+.0f}")

        if sym == "BTCUSDT":
            fvg_tr = run_fvg(df)
            mp = monthly_pnl(fvg_tr)
            strategy_monthly["BTC-FVG"] = mp
            for month, pnl in mp.items():
                all_monthly[month] += pnl
            tot = sum(mp.values())
            print(f"  {'BTC-FVG':12s}: {len(fvg_tr):4d} trade  toplam ${tot:+.0f}")

    # ── Monthly breakdown ────────────────────────────────────────────
    months = sorted(all_monthly.keys())
    pnls_pct = [all_monthly[m] / BAL * 100 for m in months]

    print(f"\n{'─'*68}")
    print(f"  {'AY':<10} {'PORTFÖY $':>10} {'% GETİRİ':>10}  YIL")
    print(f"{'─'*68}")

    year_pnls: dict[str, list] = defaultdict(list)
    for m, pct in zip(months, pnls_pct):
        yr = m[:4]
        dol = all_monthly[m]
        bar_len = int(abs(pct) / 2)
        bar = ("+" if pct >= 0 else "-") * min(bar_len, 25)
        print(f"  {m:<10} {dol:>+10.0f}  {pct:>+8.1f}%  {yr}  {bar}")
        year_pnls[yr].append(pct)

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'═'*68}")
    print(f"  ÖZET")
    print(f"{'─'*68}")

    all_pct = pnls_pct
    pos_months = sum(1 for p in all_pct if p > 0)
    total_months = len(all_pct)

    print(f"  Toplam ay          : {total_months}")
    print(f"  Pozitif ay         : {pos_months}/{total_months}  (%{pos_months/total_months*100:.0f})")
    print(f"  Ortalama ay getiri : %{np.mean(all_pct):+.1f}")
    print(f"  Medyan  ay getiri  : %{np.median(all_pct):+.1f}")
    print(f"  Std sapma          : %{np.std(all_pct):.1f}")
    print(f"  En iyi ay          : %{max(all_pct):+.1f}")
    print(f"  En kötü ay         : %{min(all_pct):+.1f}")
    print(f"  Negatif ay sayısı  : {total_months - pos_months}")

    print(f"\n{'─'*68}")
    print(f"  YILLIK ORTALAMA")
    for yr, pcts in sorted(year_pnls.items()):
        print(f"  {yr}: ort %{np.mean(pcts):+.1f}/ay  |  toplam %{sum(pcts):+.0f}/yıl  |  pozitif {sum(1 for p in pcts if p>0)}/12 ay")

    print(f"\n{'─'*68}")
    print(f"  $48 + $150/ay BÜYÜME PROJEKSİYONU")
    avg = np.mean(all_pct) / 100
    bal = 48.0
    print(f"  {'Ay':>4}  {'Bakiye':>10}")
    for mo in range(1, 25):
        bal = bal * (1 + avg) + 150
        if mo in (1, 3, 6, 12, 18, 24):
            print(f"  {mo:>4}  ${bal:>10,.0f}")

    print(f"\n  ⚠️  Backtest rakamları. Gerçek sonuç daha düşük olabilir.")
    print(f"  ⚠️  İlk 2-3 ay live veri birikmeden projeksiyon güncellenmeli.")
    print(f"{'═'*68}")


if __name__ == "__main__":
    main()
