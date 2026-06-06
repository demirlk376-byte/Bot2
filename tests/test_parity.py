"""
test_parity.py — ÜRETİM MOTORU == BACKTEST kanıtı.

Doğrulanmış edge (+28.2%) araştırma scriptlerinden geliyor. Eğer canlı motor
(strategies/risk/exchange sınıfları) bu mantıktan SAPARSA edge anlamsız olur.

Bu test, GERÇEK üretim sınıflarını —
    MeanReversionStrategy  (sinyal)
    RiskManager            (SL/TP + pozisyon boyutu)
    PaperExchange          (maker giriş + SL/TP fill)
— geçmiş BTC verisi üzerinde bar-bar çalıştırır ve bağımsız bir referans
backtest ile karşılaştırır. İkisi kuruşu kuruşuna eşleşmeli.

Ayrıca birim testler: SL/TP hesabı, pozisyon boyutu (cap dahil), SL-önce fill.

Çalıştır:  python tests/test_parity.py
"""
from __future__ import annotations

import asyncio
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import RiskConfig, StrategyConfig
from indicators import bollinger_bands, atr
from risk import RiskManager
from exchange import PaperExchange
from strategies.mean_reversion import MeanReversionStrategy

RISK   = 0.03
SL_M   = 3.0
RR     = 5.0 / 3.0      # TP = 5xATR
MH     = 48
LEV    = 10
INIT   = 10_000.0
FEE    = 0.0001         # PaperExchange exit fee modeli
N_BARS = 2200          # ilk ~3 ay (hız için)


def load_btc_1h(n=N_BARS):
    files = sorted(glob.glob(str(Path(__file__).parent.parent / "BTCUSDT-1m-*.csv")))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    df1h = full.drop(columns=["ts"]).resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()
    return df1h.iloc[:n]


# ── REFERANS backtest (PaperExchange fee modeliyle birebir) ───────────────────

def reference(df):
    c=df["close"].values; h=df["high"].values; lo=df["low"].values; vol=df["volume"].values
    up,_,lw = bollinger_bands(df["close"],20,2.0)
    atr_s = atr(df["high"],df["low"],df["close"],14)
    vma = df["volume"].rolling(20).mean().values
    bbp = ((df["close"]-lw)/(up-lw).replace(0,np.nan)).values
    n=len(c); bal=INIT; ot=None; trades=[]
    for i in range(60,n):
        a=atr_s.iloc[i]
        if np.isnan(a) or a<=0: continue
        if ot is not None:
            d=ot["dir"];e=ot["entry"];sl=ot["sl"];tp=ot["tp"];qty=ot["qty"];hd=i-ot["i"]
            ep=None;r=None
            if d==1:
                if lo[i]<=sl: ep,r=sl,"sl"
                elif h[i]>=tp: ep,r=tp,"tp"
            else:
                if h[i]>=sl: ep,r=sl,"sl"
                elif lo[i]<=tp: ep,r=tp,"tp"
            if ep is None and hd>=MH: ep,r=c[i],"mh"
            if ep is not None:
                fees=(e+ep)*qty*FEE        # maker giriş 0 + çıkış; PaperExchange ile aynı
                pnl=d*(ep-e)*qty-fees
                bal+=pnl
                trades.append({"pnl":pnl,"reason":r}); ot=None
            continue
        bp=bbp[i]
        if np.isnan(bp) or not(bp<0 or bp>1): continue
        dr=1 if bp<0 else -1
        if np.isnan(vma[i]) or vol[i]<vma[i]: continue
        e=c[i]; sld=SL_M*a
        sl=e-dr*sld; tp=e+dr*RR*sld
        sl_pct=abs(e-sl)/e
        # RiskManager.calculate_position_size ile birebir: min, sonra round(3)
        qty=min((bal*RISK)/(e*sl_pct), bal*0.5/e)
        qty=round(qty,3)
        if qty<0.001: continue
        ot={"i":i,"dir":dr,"entry":e,"sl":sl,"tp":tp,"qty":qty}
    return bal, trades


# ── ÜRETİM motoru (gerçek sınıflarla) ─────────────────────────────────────────

async def production(df):
    scfg = StrategyConfig()   # default: BB(20,2), vol filter açık, RSI tie-break
    rcfg = RiskConfig(max_risk_per_trade=RISK, atr_sl_multiplier=SL_M,
                      rr_ratio=RR, max_positions=1, daily_max_loss=0.05,
                      max_hold_candles=MH)
    strat = MeanReversionStrategy(scfg)
    risk  = RiskManager(rcfg)
    ex    = PaperExchange(initial_balance=INIT, leverage=LEV)

    n=len(df); entry_i=None
    closed=[]      # callback tek kaynak: her kapanış (net_pnl, reason)
    async def on_close(pos, exit_price, net_pnl, fees, reason):
        closed.append({"pnl":net_pnl,"reason":reason})
    ex.register_close_callback(on_close)

    atr_full = atr(df["high"],df["low"],df["close"],14)

    async def yield_tasks():
        # _close_paper_position callback'i create_task ile deferred çalışır;
        # task'ların koşması için event loop'a yield et.
        for _ in range(3):
            await asyncio.sleep(0)

    for i in range(60,n):
        bar=df.iloc[i]
        await ex.update_price(float(bar["close"]))

        # Pozisyon AÇIKSA: çıkış işle ve bu barda yeni giriş ARAMA
        # (referans backtest ile birebir kontrol akışı — kapanan barda re-entry yok)
        if ex.get_open_positions():
            prev=len(closed)
            await ex.check_sl_tp(float(bar["high"]), float(bar["low"]))   # SL önce
            await yield_tasks()
            if len(closed)>prev:
                entry_i=None
            elif entry_i is not None and (i-entry_i)>=MH:                 # max-hold
                for p in ex.get_open_positions():
                    await ex.close_position(p.symbol, p.side, p.quantity, "mh")
                await yield_tasks()
                entry_i=None
            continue

        # Pozisyon YOK: sinyal ara
        sub=df.iloc[:i+1]
        sig=strat.analyze(sub)
        if sig.direction!=0:
            a=atr_full.iloc[i]
            if np.isnan(a) or a<=0: continue
            bal=await ex.get_balance()
            setup=risk.build_trade_setup(
                direction=sig.direction, entry_price=float(bar["close"]),
                atr=float(a), balance=bal, leverage=LEV, symbol="BTC/USDT:USDT")
            if setup is None: continue
            side="buy" if sig.direction==1 else "sell"
            params={"stopLossPrice":setup.sl_price,"takeProfitPrice":setup.tp_price}
            await ex.place_limit_order("BTC/USDT:USDT", side, setup.quantity,
                                       setup.entry_price, params)
            entry_i=i

    # Referans, sonda açık kalan pozisyonu saymaz ve bakiyesine katmaz.
    # PaperExchange açık pozisyonun margin'ini düşmüş durumda → realize bakiye için
    # margin'i geri ekle (unrealized PnL EKLEME — referansla aynı davranış).
    bal=await ex.get_balance() + sum(p.margin_used for p in ex.get_open_positions())
    return bal, closed


def approx(a,b,tol): return abs(a-b)<=tol


def main():
    print("="*70)
    print("PARITY TEST — üretim motoru vs referans backtest")
    print("="*70)

    df=load_btc_1h()
    print(f"Veri: {len(df)} adet 1h bar ({df.index[0]:%Y-%m-%d}→{df.index[-1]:%Y-%m-%d})")

    ref_bal, ref_tr = reference(df)
    prod_bal, prod_tr = asyncio.run(production(df))

    print(f"\nReferans:  {len(ref_tr):>3} trade,  son bakiye ${ref_bal:,.2f}")
    print(f"Üretim:    {len(prod_tr):>3} trade,  son bakiye ${prod_bal:,.2f}")
    print(f"Fark:      {abs(len(ref_tr)-len(prod_tr))} trade, ${abs(ref_bal-prod_bal):,.2f}")

    # Trade sayısı birebir, bakiye $1 tolerans (float yuvarlama)
    assert len(ref_tr)==len(prod_tr), \
        f"Trade sayısı uyuşmuyor: ref {len(ref_tr)} vs prod {len(prod_tr)}"
    assert approx(ref_bal, prod_bal, 1.0), \
        f"Bakiye uyuşmuyor: ${ref_bal:.2f} vs ${prod_bal:.2f}"
    print("\n✓ PARITY: üretim motoru referans backtest ile eşleşiyor")

    # ── Birim testler ─────────────────────────────────────────────────────────
    print("\n" + "-"*70)
    print("Birim testler:")
    rcfg=RiskConfig(max_risk_per_trade=0.03, atr_sl_multiplier=3.0, rr_ratio=5/3,
                    max_positions=1, daily_max_loss=0.05, max_hold_candles=48)
    rm=RiskManager(rcfg)

    # SL/TP: long, entry 100000, atr 1000 → SL 97000, TP 105000
    sl,tp=rm.calculate_sl_tp(1, 100000.0, 1000.0)
    assert approx(sl,97000,0.01) and approx(tp,105000,0.5), f"SL/TP yanlış: {sl},{tp}"
    print(f"  ✓ SL/TP hesabı: SL={sl:.0f} TP={tp:.0f} (3×/5×ATR)")

    # Pozisyon boyutu cap testi: yüksek ATR'de cap bağlamalı
    # entry 100000, sl_pct=0.03 → risk-qty = bal*0.03/(100000*0.03)=bal/100000=0.1
    # cap = bal*0.5/entry = 5000/100000=0.05 → cap bağlar
    q=rm.calculate_position_size(10000.0, 100000.0, 97000.0)
    assert approx(q,0.05,1e-6), f"Cap testi başarısız: {q}"
    print(f"  ✓ Pozisyon boyutu cap: qty={q} (bakiye %50 cap bağladı)")

    # SL-önce fill: aynı mumda hem SL hem TP değerse SL kazanır
    async def fill_test():
        ex=PaperExchange(10000.0,10)
        await ex.update_price(100000.0)
        await ex.place_limit_order("BTC/USDT:USDT","buy",0.05,100000.0,
                                   {"stopLossPrice":97000.0,"takeProfitPrice":105000.0})
        box=[]
        async def _cb(*a): box.append(a)
        ex.register_close_callback(_cb)
        # mum hem 96000 (SL) hem 106000 (TP) görüyor → SL önce
        await ex.check_sl_tp(candle_high=106000.0, candle_low=96000.0)
        await asyncio.sleep(0.01)
        return box
    box=asyncio.run(fill_test())
    assert box and box[0][4]=="sl_hit", f"SL-önce kuralı bozuk: {box}"
    print(f"  ✓ SL-önce fill: aynı mumda SL+TP → SL kazandı (konservatif)")

    print("\n" + "="*70)
    print("✓ TÜM TESTLER GEÇTİ — motor backtest ile tutarlı, mekanik doğru")
    print("="*70)


if __name__ == "__main__":
    main()
