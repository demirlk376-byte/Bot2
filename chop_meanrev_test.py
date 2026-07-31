"""
chop_meanrev_test.py — GOREV A: CHOP aylarinda KACINMAK yerine KAZANMAK mumkun mu?

Bilinen: mukemmel kahin tum 16 kotu ayi atlasa kazanc sadece +$231/3.2yil.
Bu, KACINMA kolunun TAVANI. Soru: MEAN-REVERSION kolu bundan buyuk mu?

Yontem (metodolojiye birebir uyar):
  * Veri: fast_bt.load(coin, source="local") + fast_bt.resample
  * Breakout taban = deployed_backtest.gen (donchian 7 + squeeze 4), occ=j, MAXPOS=7 koltuk
  * Mean-rev sleeve = URETIM sinifi (strategies.mean_reversion.MeanReversionStrategy)
    canlinin BB koluyla BIREBIR: 1h, get_candles(120) pencere, pencere-yerel ATR/ADX,
    bb_allowed = ADX < 28 (trending blok), SL 3xATR, RR 1.667, max-hold 48.
    -> faithful_bt.prod_bb ile ayni; sadece hizlandirildi (asagida ESDEGERLIK ispati).
  * occ = j ZORUNLU (coin basina tek pozisyon)
  * Koltuk secimi giris zamanina gore, MAXPOS=7
  * Boyut: eff = min(RISKF, CAP*sl_pct); pnl = R*eff*BAL0
  * Filtre (ay-kapisi) SINYAL ANINDA uygulanir, elenen sinyal occ'u ILERLETMEZ.
  * LOOKAHEAD YOK: tum gostergeler i barinin KAPANISINDA bilinen pencereden.
    (Tek istisna ay-kapisi = MUKEMMEL KAHIN, bilerek lookahead — TAVAN olcumu.)

HIZLANDIRMA ESDEGERLIGI (exact, yaklasim degil):
  BB sinyali close'un BB(20,2) disinda kapanmasini SART kosar. bollinger_bands
  rolling(20) kullanir -> 120-barlik pencerenin son barindaki deger, tam-seri
  rolling(20)'nin ayni indeksteki degeriyle BAYT-DENKTIR (pencere >= 20).
  Ayni sekilde hacim filtresi vol.rolling(20).mean(). Dolayisiyla "aday bar"
  kumesi tam-seriden ONCEDEN cikarilabilir; pahali pencere-yerel ATR/ADX/analyze
  SADECE aday barlarda calisir. Sonuc birebir ayni (script --verify ile kanitlar).

Kullanim:
  python chop_meanrev_test.py            # tam analiz
  python chop_meanrev_test.py --verify   # SOL uzerinde faithful_bt.prod_bb esdegerlik testi
"""
from __future__ import annotations

import heapq
import os
import pickle
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, adx as adx_fn, bollinger_bands

BAL0 = DB.BAL0        # 190.0
FEE = DB.FEE          # 0.0001
RISKF = DB.RISKF      # 0.0225
CAP = DB.CAP          # 1.25
MAXPOS = DB.MAXPOS    # 7

DONCH = DB.DONCH      # SOL ETH ADA NEAR BCH ICP BNB
SQZ = DB.SQZ          # XRP DOGE TRX XLM
COINS = DONCH + SQZ   # 11 coin

# Canlı BB kolu (config.py / .env.example): SL 3.0xATR, RR_RATIO 1.667, MAX_HOLD 48, 1h
BB_SL_ATR = 3.0
BB_RR = 1.667
BB_MH = 48
BB_ADX_MAX = 28.0     # bb_allowed: ADX >= 28 "trending" blok (canlı live_gates ile aynı)

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/cmr_cache.pkl"


# ─────────────────────────────────────────────────────────────────────────────
# MEAN-REVERSION SLEEVE (üretim sınıfı, canlı-birebir)
# ─────────────────────────────────────────────────────────────────────────────
def _mr_strategy():
    from config import load_config
    from strategies.mean_reversion import MeanReversionStrategy
    return MeanReversionStrategy(load_config().strategy)


def gen_bb(m, weekend_only=False, month_gate=None, strat=None):
    """Canlı BB/mean-rev kolunun trade listesi.

    month_gate: None ya da izin verilen pd.Period('M') kümesi. SİNYAL ANINDA
      uygulanır; elenen sinyal occ'u İLERLETMEZ (metodoloji md.7).
    Dönüş: (entry_ns, entry_ts, exit_ts, R, sl_pct) listesi.
    """
    s = strat if strat is not None else _mr_strategy()
    d = fast_bt.resample(m, "1h")
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)

    # --- ucuz ön-eleme (tam-seri; pencere-yerel ile BAYT-DENK, docstring'e bak) ---
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))   # vol_filter_enabled=True
    cand = np.where(outside & volok)[0]

    out = []; occ = -1
    for i in cand:
        i = int(i)
        if i < 260 or i >= n - 1: continue
        if i <= occ: continue                       # coin başına TEK pozisyon
        ts = idx[i]
        if weekend_only and ts.weekday() < 5: continue
        if month_gate is not None and ts.tz_localize(None).to_period("M") not in month_gate:
            continue                                # elenen sinyal occ'u İLERLETMEZ
        sub = d.iloc[max(0, i - 119):i + 1]         # canlı get_candles(120)
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= BB_ADX_MAX: continue
        sg = s.analyze(sub)
        d_ = sg.direction
        if d_ == 0: continue
        a = float(av); sld = BB_SL_ATR * a
        e = cl[i]; slp = e - d_ * sld; tp = e + d_ * BB_RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + BB_MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + BB_MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[i], idx[j], R, sld / e))
        occ = j                                     # ZORUNLU
    return out


def gen_breakout(sleeve, m):
    """deployed_backtest.gen + entry timestamp (aynı mantık, tuple genişletildi)."""
    raw = DB.gen(sleeve, m)
    return [(ns, pd.Timestamp(ns, tz="UTC"), ex, R, slp) for (ns, ex, R, slp) in raw]


# ─────────────────────────────────────────────────────────────────────────────
# koltuk + ölçüm
# ─────────────────────────────────────────────────────────────────────────────
def seat_select(trades, maxpos=MAXPOS):
    """deployed_backtest.seat_select ile aynı; entry_ts de taşınır."""
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, entry_ts, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((entry_ts, exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[1])


def to_frame(taken):
    if not taken:
        return pd.DataFrame(columns=["entry", "exit", "R", "slp", "pnl", "me", "mx", "yx"])
    df = pd.DataFrame(taken, columns=["entry", "exit", "R", "slp"])
    eff = np.minimum(RISKF, CAP * df["slp"].values)
    df["pnl"] = df["R"].values * eff * BAL0
    df["me"] = [t.tz_localize(None).to_period("M") for t in df["entry"]]   # giriş ayı
    df["mx"] = [t.tz_localize(None).to_period("M") for t in df["exit"]]    # çıkış ayı
    df["yx"] = [t.year for t in df["exit"]]
    return df


def stats(df, label):
    if len(df) == 0:
        print(f"  {label:28s} işlem yok"); return
    r = df["R"].values
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 99.0
    print(f"  {label:28s} n={len(r):>4d} WR{(r>0).mean()*100:>3.0f}% PF{pf:5.2f} "
          f"tot{r.sum():+7.1f}R  ${df['pnl'].sum():+8.2f}")


def yearly(df, key="yx"):
    return df.groupby(key)["pnl"].sum() if len(df) else pd.Series(dtype=float)


def monthly(df, key="mx"):
    return df.groupby(key)["pnl"].sum() if len(df) else pd.Series(dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
_MEM = {}


def _data(c):
    if c not in _MEM: _MEM[c] = fast_bt.load(c, source="local")
    return _MEM[c]


def build(force=False):
    """Faz-1: breakout + meanrev(tum gunler) + meanrev(hafta sonu). Diske onbellek."""
    if os.path.exists(CACHE) and not force:
        with open(CACHE, "rb") as f: return pickle.load(f)
    bo, mr, mrw = [], [], []
    strat = _mr_strategy()
    for c in COINS:
        m = _data(c)
        sleeve = "donchian" if c in DONCH else "squeeze"
        b = gen_breakout(sleeve, m); bo += b
        v = gen_bb(m, strat=strat); mr += v
        w = gen_bb(m, weekend_only=True, strat=strat); mrw += w
        print(f"  {c:5s} breakout={len(b):>4d}  meanrev={len(v):>4d}  meanrev-wknd={len(w):>4d}",
              flush=True)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f: pickle.dump((bo, mr, mrw), f)
    return bo, mr, mrw


def verify():
    """ESDEGERLIK: hizlandirilmis gen_bb == faithful_bt.prod_bb (uretim yolu)."""
    import faithful_bt
    m = fast_bt.load("SOL", source="local")
    fast = gen_bb(m)
    slow = faithful_bt.prod_bb(m, weekend_only=False)
    rf = np.array([t[3] for t in fast]); rs = np.array([t["r"] for t in slow])
    print(f"\nESDEGERLIK TESTI (SOL, BB tum gunler)")
    print(f"  hizli  n={len(rf)}  totR={rf.sum():+.3f}")
    print(f"  uretim n={len(rs)}  totR={rs.sum():+.3f}")
    ok = len(rf) == len(rs) and np.allclose(rf, rs, atol=1e-12)
    print(f"  BIREBIR MI: {'EVET' if ok else 'HAYIR'}")
    return ok


def main():
    if "--verify" in sys.argv:
        verify(); return
    print("=" * 78)
    print("GOREV A — CHOP AYLARINDA MEAN-REVERSION ILE KAZANMA TAVANI")
    print("=" * 78)
    print("\n[1] Trade uretimi (11 coin, breakout=deploy config, meanrev=uretim BB sinifi)")
    bo_raw, mr_raw, mrw_raw = build("--rebuild" in sys.argv)

    bo = to_frame(seat_select(bo_raw))
    mr = to_frame(seat_select(mr_raw))
    print("\n[2] Sleeve'ler AYRI (her biri kendi 7 koltugu)")
    stats(bo, "BREAKOUT (deploy)")
    stats(mr, "MEAN-REV (BB, tum gunler)")

    # ── kötü/iyi ay ayrimi: breakout aylik PnL (cikis ayi = deployed_backtest ile ayni)
    bm = monthly(bo, "mx")
    bad = set(bm[bm < 0].index); good = set(bm[bm >= 0].index)
    print(f"\n[3] Ay siniflandirmasi (breakout cikis-ayi PnL): "
          f"{len(bm)} ay, KOTU={len(bad)}, IYI={len(good)}")
    print(f"    breakout kotu aylar toplami : ${bm[bm<0].sum():+8.2f}")
    print(f"    breakout iyi  aylar toplami : ${bm[bm>=0].sum():+8.2f}")
    print(f"    breakout TOPLAM             : ${bm.sum():+8.2f}")

    # ── mean-rev'in kötü/iyi aylardaki performansi (HEM giris HEM cikis ayina gore)
    print("\n[4] MEAN-REV'in kotu vs iyi aylardaki PnL'i")
    for key, nm in (("me", "GIRIS ayina gore"), ("mx", "CIKIS ayina gore")):
        sub_b = mr[mr[key].isin(bad)]; sub_g = mr[mr[key].isin(good)]
        print(f"  -- {nm} --")
        stats(sub_b, "  meanrev @ KOTU aylar")
        stats(sub_g, "  meanrev @ IYI  aylar")

    # ── aylik korelasyon
    print("\n[5] Aylik PnL korelasyonu (breakout vs meanrev)")
    mm = monthly(mr, "mx")
    allm = sorted(set(bm.index) | set(mm.index))
    a = bm.reindex(allm).fillna(0.0); b = mm.reindex(allm).fillna(0.0)
    pear = np.corrcoef(a.values, b.values)[0, 1]
    spear = pd.Series(a.values).corr(pd.Series(b.values), method="spearman")
    print(f"  Pearson  r = {pear:+.3f}   Spearman = {spear:+.3f}   (n={len(allm)} ay)")
    hit = ((a.values < 0) & (b.values > 0)).sum()
    print(f"  breakout<0 iken meanrev>0 olan ay: {hit}/{(a.values<0).sum()}")

    # ── TAVAN: mukemmel rejim bilgisiyle mean-rev SADECE kotu aylarda
    print("\n[6] TAVAN — mean-rev SADECE kotu aylarda (MUKEMMEL KAHIN, giris-ayi kapisi)")
    print("    (kapi sinyal aninda; elenen sinyal occ'u ilerletmez -> yeniden uretim)")
    gcache = CACHE.replace(".pkl", "_gated.pkl")
    if os.path.exists(gcache) and "--rebuild" not in sys.argv:
        with open(gcache, "rb") as f: mr_gated_raw = pickle.load(f)
    else:
        mr_gated_raw = []
        strat = _mr_strategy()
        for c in COINS:
            mr_gated_raw += gen_bb(_data(c), month_gate=bad, strat=strat)
        with open(gcache, "wb") as f: pickle.dump(mr_gated_raw, f)
    mrg = to_frame(seat_select(mr_gated_raw))
    stats(mrg, "MEAN-REV @ sadece kotu ay")
    # MUTLAK tavan: mean-rev'in kendi POZITIF aylarinin toplami (herhangi bir ay-zamanlama
    # semasinin ustune cikamayacagi sinir; %100 kahin, uygulanamaz)
    mm_all = monthly(mr, "mx")
    print(f"    -> KACINMA kolunun tavani (bilinen)      : +$231")
    print(f"    -> MEAN-REV kotu-ay kapisi (kahin)       : ${mrg['pnl'].sum():+.2f}")
    print(f"    -> MEAN-REV MUTLAK tavan (tum + aylar)   : ${mm_all[mm_all>0].sum():+.2f} "
          f"({(mm_all>0).sum()}/{len(mm_all)} ay) <- hicbir sema bunu gecemez")

    # ── BIRLESIK PORTFOY (ayni 7 koltuk icin yarisirlar) — GERCEK kabul testi
    print("\n[7] BIRLESIK PORTFOY (breakout + meanrev AYNI 7 koltuk) — kabul testi")
    base = to_frame(seat_select(bo_raw))
    yb = yearly(base)
    for lbl, extra in (("meanrev TUM gunler", mr_raw),
                       ("meanrev SADECE kotu ay (kahin)", mr_gated_raw)):
        comb = to_frame(seat_select(bo_raw + extra))
        yc = yearly(comb)
        yrs = sorted(set(yb.index) | set(yc.index))
        d_tot = comb["pnl"].sum() - base["pnl"].sum()
        line = "  ".join(
            f"{y}:{yc.get(y,0)-yb.get(y,0):+7.2f}" for y in yrs)
        allpos = all((yc.get(y, 0) - yb.get(y, 0)) > 0 for y in yrs)
        print(f"  + {lbl}")
        print(f"      taban ${base['pnl'].sum():+8.2f} -> ${comb['pnl'].sum():+8.2f} "
              f"(delta ${d_tot:+.2f}, n {len(base)}->{len(comb)})")
        print(f"      yil-yil delta: {line}")
        print(f"      KABUL BARI (toplam+ VE her yil+): {'GECTI' if (d_tot>0 and allpos) else 'KALDI'}")

    # ── hafta-sonu varyanti (canli deploy bunu kullaniyor)
    print("\n[8] Canli deploy varyanti: BB SADECE hafta sonu (BB_WEEKDAY_ENABLED=false)")
    mrw = to_frame(seat_select(mrw_raw))
    stats(mrw, "MEAN-REV hafta-sonu")
    wb = mrw[mrw["mx"].isin(bad)]; wg = mrw[mrw["mx"].isin(good)]
    stats(wb, "  haftasonu @ KOTU aylar")
    stats(wg, "  haftasonu @ IYI  aylar")
    combw = to_frame(seat_select(bo_raw + mrw_raw))
    ycw = yearly(combw)
    yrs = sorted(set(yb.index) | set(ycw.index))
    dw = combw["pnl"].sum() - base["pnl"].sum()
    print(f"  BIRLESIK: ${base['pnl'].sum():+.2f} -> ${combw['pnl'].sum():+.2f} (delta ${dw:+.2f})")
    print("      yil-yil delta: " + "  ".join(f"{y}:{ycw.get(y,0)-yb.get(y,0):+7.2f}" for y in yrs))
    allpos = all((ycw.get(y, 0) - yb.get(y, 0)) > 0 for y in yrs)
    print(f"      KABUL BARI: {'GECTI' if (dw>0 and allpos) else 'KALDI'}")

    # ── aday sarti
    print("\n[9] ADAY SARTI: meanrev kotu aylarda POZITIF ve korelasyon < +0.3")
    kb = mr[mr["mx"].isin(bad)]["pnl"].sum()
    print(f"    meanrev kotu-ay PnL = ${kb:+.2f}  ({'POZITIF' if kb>0 else 'NEGATIF'})")
    print(f"    korelasyon r = {pear:+.3f}  ({'<0.3 OK' if pear<0.3 else '>=0.3 RED'})")
    print(f"    ADAY: {'EVET' if (kb>0 and pear<0.3) else 'HAYIR'}")

    # ── aylik tablo (denetim icin)
    print("\n[10] Aylik tablo (breakout | meanrev-tum | meanrev-haftasonu), $")
    mw = monthly(mrw, "mx").reindex(allm).fillna(0.0)
    print(f"    {'ay':8s} {'breakout':>10s} {'mrev':>9s} {'mrev-wknd':>10s}")
    for mth in allm:
        flag = "KOTU" if mth in bad else ""
        print(f"    {str(mth):8s} {a.get(mth,0):+10.2f} {b.get(mth,0):+9.2f} "
              f"{mw.get(mth,0):+10.2f}  {flag}")


def wknd_deepdive():
    """[11] HAFTA-SONU BB derin inceleme.

    Ana kosuda tek POZITIF isaret buydu: hafta-sonu BB kotu aylarda +$326 (PF1.26),
    iyi aylarda -$50 (PF0.97). Kotu-ay tavani KACINMA'nin +$231'ini ASIYOR.
    Ama once kirilganlik testi: yil-yil, coin-coin, kac ayda kazaniyor, korelasyon.
    """
    bo_raw, mr_raw, mrw_raw = build()
    bo = to_frame(seat_select(bo_raw))
    mrw = to_frame(seat_select(mrw_raw))
    bm = monthly(bo, "mx"); bad = set(bm[bm < 0].index)
    mw = monthly(mrw, "mx")

    print("=" * 78)
    print("[11] HAFTA-SONU BB DERIN INCELEME")
    print("=" * 78)

    allm = sorted(set(bm.index) | set(mw.index))
    a = bm.reindex(allm).fillna(0.0); w = mw.reindex(allm).fillna(0.0)
    print(f"\n  korelasyon (aylik): Pearson {np.corrcoef(a.values,w.values)[0,1]:+.3f}  "
          f"Spearman {pd.Series(a.values).corr(pd.Series(w.values),method='spearman'):+.3f}")
    hit = ((a.values < 0) & (w.values > 0)).sum()
    print(f"  breakout<0 iken hafta-sonu BB>0: {hit}/{(a.values<0).sum()} ay")

    print("\n  TEK BASINA yil-yil (kendi 7 koltugu):")
    yw = yearly(mrw)
    for y in sorted(yw.index): print(f"    {y}: ${yw[y]:+8.2f}")
    print(f"    -> her yil pozitif mi: {'EVET' if (yw > 0).all() else 'HAYIR'}")

    print("\n  KOTU-AY PnL'inin yil-yil dagilimi (tavan ne kadar saglam?):")
    kb = mrw[mrw["mx"].isin(bad)]
    for y in sorted(kb["yx"].unique()):
        s = kb[kb["yx"] == y]
        print(f"    {y}: ${s['pnl'].sum():+8.2f}  (n{len(s)})")

    print("\n  KOTU-AY PnL'inin ay-ay dagilimi (birkac aya mi yigilmis?):")
    kbm = kb.groupby("mx")["pnl"].sum().sort_values(ascending=False)
    print(f"    en iyi 3 ay: {', '.join(f'{m} ${v:+.0f}' for m,v in kbm.head(3).items())}"
          f"  = toplamin %{kbm.head(3).sum()/kbm.sum()*100:.0f}'i")
    print(f"    pozitif kotu-ay: {(kbm>0).sum()}/{len(kbm)}")

    # KAHIN: hafta-sonu BB SADECE kotu aylarda (sinyal aninda kapi, occ ilerlemez)
    print("\n  KAHIN (hafta-sonu BB yalniz kotu aylarda) + BIRLESIK PORTFOY:")
    wcache = CACHE.replace(".pkl", "_wgated.pkl")
    if os.path.exists(wcache):
        with open(wcache, "rb") as f: wg_raw = pickle.load(f)
    else:
        wg_raw = []; strat = _mr_strategy()
        for c in COINS:
            wg_raw += gen_bb(_data(c), weekend_only=True, month_gate=bad, strat=strat)
        with open(wcache, "wb") as f: pickle.dump(wg_raw, f)
    wg = to_frame(seat_select(wg_raw))
    stats(wg, "  hafta-sonu BB @ kotu ay")
    yb = yearly(bo)
    for lbl, extra in (("hafta-sonu BB HER ZAMAN", mrw_raw),
                       ("hafta-sonu BB SADECE kotu ay (kahin)", wg_raw)):
        comb = to_frame(seat_select(bo_raw + extra)); yc = yearly(comb)
        yrs = sorted(set(yb.index) | set(yc.index))
        d = comb["pnl"].sum() - bo["pnl"].sum()
        allpos = all((yc.get(y, 0) - yb.get(y, 0)) > 0 for y in yrs)
        print(f"    + {lbl}: ${bo['pnl'].sum():+.2f} -> ${comb['pnl'].sum():+.2f} (delta ${d:+.2f})")
        print(f"        " + "  ".join(f"{y}:{yc.get(y,0)-yb.get(y,0):+7.2f}" for y in yrs)
              + f"   KABUL: {'GECTI' if (d>0 and allpos) else 'KALDI'}")

    print("\n  COIN-COIN hafta-sonu BB (tek basina, koltuksuz ham R -> $):")
    per = {}
    for c in COINS:
        v = gen_bb(_data(c), weekend_only=True)
        f = to_frame([(e, x, R, s) for (_ns, e, x, R, s) in v])
        yy = yearly(f)
        per[c] = (f["pnl"].sum(), len(f), (yy > 0).all() if len(yy) else False, yy)
    for c, (p, n, ok, yy) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        ys = " ".join(f"{y}:{yy.get(y,0):+6.0f}" for y in sorted(yy.index))
        print(f"    {c:5s} ${p:+8.2f} n{n:>4d} her-yil+:{'E' if ok else 'H'}   {ys}")
    npos = sum(1 for c in per if per[c][2])
    print(f"    -> her-yil-pozitif coin: {npos}/{len(COINS)}")


if __name__ == "__main__":
    if "--wknd" in sys.argv: wknd_deepdive()
    else: main()
