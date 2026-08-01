"""
trail_exit_test.py — GÖREV C: SABİT TP'Yİ KALDIR, KAZANANI SERBEST BIRAK.

SORU (daha önce reddedilenlerden FARKLI): rr=2.5 sabit TP her kazananı 2.5R'de KESİYOR.
Trend takibinin klasik gerçeği "kâr az sayıda ÇOK BÜYÜK kazanandan gelir" ise, sabit TP
tam da her şeyi ödeyen işlemleri buduyor olabilir.
  Reddedilenler: erken çıkış (KAYBEDENİ kesmek) · kısmi TP (kazancı bölmek) ·
  BE/trailing (yalnız orb/ifvg'de, KAYBI önlemek için) · sr_breakout BE+trail.
  BURADAKİ: TP'yi tamamen kaldırıp KAZANANI KOŞTURMAK.

BÖLÜM 0 — TAVAN ÖLÇÜMÜ: TP'ye değen işlemler TP'den SONRA ne kadar devam etti?
  (TP barından sonra, kalan max-hold penceresi içinde ek maksimum lehte hareket, R cinsinden.)
  Bu bir ÜST SINIR: sıfır sürtünme, mükemmel öngörü. Küçükse kol ölüdür.

BÖLÜM 1-2 — VARYANTLAR (maxhold KORUNUR, sleeve başına AYRI):
  (a) TP YOK + chandelier trail: stop = (girişten beri en yüksek) − k*ATR
  (b) TP YOK + donchian trail:   stop = son N barın en düşüğü
  (c) HİBRİT: yarısı rr'de kapanır, KALAN BACAK SINIRSIZ koşar (trail'li)
  Hepsi ratchet'li (stop asla aleyhe hareket etmez), stop bar KAPANIŞINDA güncellenir ve
  BİR SONRAKİ bardan itibaren geçerlidir (LOOKAHEAD YOK). Aynı barda önce STOP kontrol edilir.

METODOLOJİ (zorunlu):
  occ = j (append sonrası) · koltuk seçimi giriş zamanına göre MAXPOS=7 tek havuz ·
  eff = min(RISKF, CAP*sl_pct), pnl = R*eff*BAL0 · SEÇİM YALNIZ TRAIN (2023-01→2024-12),
  ölçüm TEST (2025-01→) · yıl-yıl zorunlu · plato aranır, tepe değil.
  TRAILING DAHA UZUN TUTAR → FUNDING ARTAR: ölçülmüş −0.0058R/işlem (donchian, 8.4 bacak)
  bacak başına oranlanarak her varyanta ayrı uygulanır ve raporlanır.

Kullanım:  py trail_exit_test.py local
"""
import sys, os, heapq, pickle, itertools
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; MAXPOS = 7; CAP = 1.25
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
BB_COINS = ["LTC"]
BB_TF = "1h"; BB_SL_ATR = 3.0; BB_RR = 1.667; BB_MH = 48; BB_ADX_MAX = 28.0

# funding: ölçülmüş toplam / ölçülmüş bacak = bacak başına R maliyeti (1 bacak = 8 saat)
FUND_PER_LEG = {"donchian": -0.0058 / 8.4, "squeeze": -0.0084 / 2.6, "bb": -0.0084 / 2.6}
BAR_HOURS = {"donchian": 4.0, "squeeze": 1.0, "bb": 1.0}

SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
CACHE = os.path.join(SCRATCH, "trail_signals.pkl")
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


# ─────────────────────────── SİNYAL ÖN-HESABI (bir kez) ───────────────────────────
# gen()/gen_bb() içindeki PAHALI kısım s.analyze(); ve sinyalin KENDİSİ occ'tan bağımsız
# (occ yalnız `continue` yapar, hiçbir kapı occ'u değiştirmez). Bu yüzden yön/ATR bir kez
# hesaplanır, occ döngüsü her varyantta ucuzca yeniden koşar → deployed_backtest ile denk.

def precompute(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    cl = d["close"].values; n = len(cl)
    sig = []
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        d_ = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
        if d_ == 0: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        sig.append((i, d_, sl_a * float(a)))
    return dict(hi=d["high"].values, lo=d["low"].values, cl=cl, atr=atr_ser,
                idx=d.index, n=n, sig=sig, mh=mh, rr=rr, sleeve=sleeve)


def precompute_bb(m):
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, BB_TF)
    cl = d["close"].values; idx = d.index; n = len(cl)
    atr_full = atr_fn(d["high"], d["low"], d["close"], 14).values   # trail için (giriş SL'i pencere-yerel)
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    sig = []
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1: continue
        if idx[i].weekday() < 5: continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= BB_ADX_MAX: continue
        d_ = s.analyze(sub).direction
        if d_ == 0: continue
        sig.append((i, d_, BB_SL_ATR * float(av)))
    return dict(hi=d["high"].values, lo=d["low"].values, cl=cl, atr=atr_full,
                idx=idx, n=n, sig=sig, mh=BB_MH, rr=BB_RR, sleeve="bb")


def build_cache(source):
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f: return pickle.load(f)
    P = {}
    for c in DONCH: P[("donchian", c)] = precompute("donchian", fast_bt.load(c, source=source))
    for c in SQZ:   P[("squeeze", c)] = precompute("squeeze", fast_bt.load(c, source=source))
    for c in BB_COINS: P[("bb", c)] = precompute_bb(fast_bt.load(c, source=source))
    with open(CACHE, "wb") as f: pickle.dump(P, f)
    return P


# ─────────────────────────── ÇIKIŞ MOTORU ───────────────────────────
# mode: "fixed" (taban) | "chand" | "dontr" | "hchand" | "hdontr"
# Muhafazakâr sıra: aynı barda önce STOP, sonra TP. Trail stop bar KAPANIŞINDA güncellenir,
# bir SONRAKİ bardan itibaren geçerli (bar j'de kullanılan stop, j-1 kapanışında belliydi).

def run_sleeve(P, mode, prm):
    """Tek bir (sleeve,coin) paketi için tüm işlemleri üretir. occ = j."""
    hi, lo, cl, atrv, idx, n, mh, rr = (P["hi"], P["lo"], P["cl"], P["atr"],
                                        P["idx"], P["n"], P["mh"], P["rr"])
    out = []; occ = -1
    for (i, d_, sld) in P["sig"]:
        if i <= occ: continue
        e = cl[i]; stop = e - d_ * sld; tp = e + d_ * rr * sld
        # mode "notp": TP YOK, stop SABİT (ilk SL), maxhold'da kapan → SAF "kazananı koştur"
        # kontrolü: kaybedenlere HİÇ dokunmaz, o yüzden örtük-erken-çıkış bulaşması yoktur.
        use_tp = (mode in ("fixed", "hchand", "hdontr"))
        hybrid = mode in ("hchand", "hdontr")
        trail = mode in ("chand", "hchand", "dontr", "hdontr")
        tkind = "chand" if mode in ("chand", "hchand") else "dontr"
        ext = e            # girişten beri en uç lehte fiyat (chandelier)
        half_done = False; R1 = 0.0
        ep = None; j = i
        jmax = min(i + 1 + mh, n)
        for j in range(i + 1, jmax):
            # 1) mevcut stop (önceki bar kapanışında belliydi) — önce kontrol
            if d_ == 1:
                if lo[j] <= stop: ep = stop; break
            else:
                if hi[j] >= stop: ep = stop; break
            # 2) TP (varsa)
            if use_tp and not half_done:
                if (d_ == 1 and hi[j] >= tp) or (d_ == -1 and lo[j] <= tp):
                    if not hybrid: ep = tp; break
                    half_done = True; R1 = rr           # yarısı kapandı, KALAN SERBEST KOŞAR
            # 3) bar kapanışında trail güncelle (ratchet)
            if trail:
                if tkind == "chand":
                    a = atrv[j]
                    if np.isfinite(a) and a > 0:
                        if d_ == 1:
                            ext = max(ext, hi[j]); stop = max(stop, ext - prm * a)
                        else:
                            ext = min(ext, lo[j]); stop = min(stop, ext + prm * a)
                else:
                    k0 = max(0, j - int(prm) + 1)
                    if d_ == 1: stop = max(stop, lo[k0:j + 1].min())
                    else:       stop = min(stop, hi[k0:j + 1].max())
                # stop girişin ötesine geçse bile fiyatın YANLIŞ tarafına asla koymayız
                if d_ == 1: stop = min(stop, cl[j])
                else:       stop = max(stop, cl[j])
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        Rraw = d_ * (ep - e) / sld
        R = (0.5 * R1 + 0.5 * Rraw if half_done else Rraw) - 2 * FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, j - i, P["sleeve"]))
        occ = j
    return out


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, bars, slv in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, bars, slv))
    return sorted(taken, key=lambda t: t[0])


def portfolio(P, spec):
    """spec: {sleeve: (mode, prm)} — belirtilmeyen sleeve TABAN (fixed)."""
    tr = []
    for (slv, c), pk in P.items():
        mode, prm = spec.get(slv, ("fixed", None))
        tr += run_sleeve(pk, mode, prm)
    return seat_select(tr)


def stats(taken, funding=True):
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    bars = np.array([t[3] for t in taken], float); slv = np.array([t[4] for t in taken])
    yrs = np.array([pd.Timestamp(t[0]).year for t in taken])
    fund = np.zeros(len(r))
    if funding:
        for s in ("donchian", "squeeze", "bb"):
            m = slv == s
            fund[m] = bars[m] * BAR_HOURS[s] / 8.0 * FUND_PER_LEG[s]
    rn = r + fund
    eff = np.minimum(RISKF, CAP * slp)
    pnl = rn * eff * BAL0
    out = {"n": len(r), "R": rn, "pnl": pnl, "yrs": yrs, "eff": eff, "bars": bars, "slv": slv,
           "tot": pnl.sum(), "wr": (rn > 0).mean() * 100,
           "pf": rn[rn > 0].sum() / max(-rn[rn < 0].sum(), 1e-9),
           "avgR": rn.mean(), "avg_risk": eff.mean() * 100, "fund": fund.sum(),
           "fund_usd": (fund * eff * BAL0).sum(),
           "avg_bars_hours": (bars * np.array([BAR_HOURS[s] for s in slv])).mean()}
    out["by_year"] = {int(y): pnl[yrs == y].sum() for y in sorted(set(yrs))}
    out["train"] = pnl[yrs < 2025].sum(); out["test"] = pnl[yrs >= 2025].sum()
    out["ntrain"] = int((yrs < 2025).sum()); out["ntest"] = int((yrs >= 2025).sum())
    return out


def line(tag, st):
    yy = " ".join(f"{y}:{v:+.0f}" for y, v in st["by_year"].items())
    return (f"  {tag:34s} n{st['n']:5d} PF{st['pf']:.3f} WR{st['wr']:4.1f}% "
            f"${st['tot']:+7.0f} | TR ${st['train']:+6.0f} TE ${st['test']:+6.0f} | {yy}"
            f" | risk{st['avg_risk']:.2f}% {st['avg_bars_hours']:.0f}h")


# ─────────────────────────── BÖLÜM 0: TP SONRASI TAVAN ───────────────────────────
def tp_headroom(P):
    print("\n" + "=" * 100)
    print("BÖLÜM 0 — TAVAN: TP'ye DEĞEN işlem, TP'den SONRA kalan max-hold içinde ne kadar devam etti?")
    print("  (mükemmel öngörü + sıfır sürtünme ÜST SINIRI. sabit TP zaten alındı; bu EK lehte hareket.)")
    print("=" * 100)
    agg = {}
    for (slv, c), pk in P.items():
        hi, lo, cl, idx, n, mh, rr = pk["hi"], pk["lo"], pk["cl"], pk["idx"], pk["n"], pk["mh"], pk["rr"]
        occ = -1
        for (i, d_, sld) in pk["sig"]:
            if i <= occ: continue
            e = cl[i]; slp = e - d_ * sld; tp = e + d_ * rr * sld
            ep = None; j = i; reason = "mh"
            for j in range(i + 1, min(i + 1 + mh, n)):
                if d_ == 1:
                    if lo[j] <= slp: ep = slp; reason = "sl"; break
                    if hi[j] >= tp: ep = tp; reason = "tp"; break
                else:
                    if hi[j] >= slp: ep = slp; reason = "sl"; break
                    if lo[j] <= tp: ep = tp; reason = "tp"; break
            if ep is None: j = min(i + mh, n - 1); ep = cl[j]
            a = agg.setdefault(slv, {"tp": 0, "all": 0, "head": [], "endR": [], "give": []})
            a["all"] += 1
            if reason == "tp":
                a["tp"] += 1
                # TP barından SONRA kalan pencere (giriş barından mh bar sınırı korunur)
                k1 = min(i + 1 + mh, n)
                if j + 1 < k1:
                    seg_hi = hi[j + 1:k1]; seg_lo = lo[j + 1:k1]
                    mfe_after = (seg_hi.max() - e) / sld if d_ == 1 else (e - seg_lo.min()) / sld
                    endp = cl[k1 - 1]
                    endR = d_ * (endp - e) / sld
                else:
                    mfe_after = rr; endR = rr
                a["head"].append(max(0.0, mfe_after - rr))     # TP'nin ÜSTÜNE ek R
                a["endR"].append(endR)                          # pencere sonuna kadar tutsaydık
            occ = j
    for slv, a in agg.items():
        h = np.array(a["head"]); er = np.array(a["endR"]); rr = CFG.get(slv, (0,) * 5)[3] if slv in CFG else BB_RR
        print(f"\n  [{slv}] TP olan {a['tp']}/{a['all']} işlem ({a['tp']/a['all']*100:.0f}%)")
        print(f"    TP ÜSTÜ ek MFE (R): ort {h.mean():+.2f}  medyan {np.median(h):+.2f}  "
              f"p75 {np.percentile(h,75):+.2f}  p90 {np.percentile(h,90):+.2f}  max {h.max():+.2f}")
        print(f"    >1R ek: %{(h>1).mean()*100:.0f} | >2R ek: %{(h>2).mean()*100:.0f} | "
              f"~hiç (<0.25R): %{(h<0.25).mean()*100:.0f}")
        print(f"    pencere SONUNA kadar tutsaydık ort {er.mean():+.2f}R (TP {rr:+.2f}R) "
              f"→ fark {er.mean()-rr:+.2f}R/TP-işlemi")
        print(f"    TÜM işlemlere yayılmış tavan: {h.mean()*a['tp']/a['all']:+.3f}R/işlem "
              f"(mükemmel öngörü); gerçekçi kırıntı bunun ÇOK altı")
    return agg


# ─────────────────────────── ANA ───────────────────────────
def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    P = build_cache(source)
    print(f"\nsinyal paketleri hazır: {len(P)} (coin,sleeve); ham sinyal "
          f"{sum(len(p['sig']) for p in P.values())} (occ öncesi)")

    base = stats(portfolio(P, {}), funding=False)
    print("\n" + "=" * 100)
    print("TABAN DOĞRULAMA (deployed_backtest.py ile birebir olmalı: n1579 PF1.45 WR44% $+1421)")
    print("=" * 100)
    print(line("TABAN (fixed TP, funding YOK)", base))
    basef = stats(portfolio(P, {}), funding=True)
    print(line("TABAN (funding düşülmüş)", basef))

    tp_headroom(P)

    # ── VARYANT IZGARASI ──
    KS = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]      # chandelier k
    NS = [5, 10, 15, 20, 30]                  # donchian trail N
    variants = ([("chand", k) for k in KS] + [("dontr", n) for n in NS] +
                [("hchand", k) for k in KS] + [("hdontr", n) for n in NS])
    ncomb = len(variants) * 3
    print("\n" + "=" * 100)
    print(f"BÖLÜM 1 — SLEEVE BAŞINA VARYANT TARAMASI: {len(variants)} varyant × 3 sleeve = {ncomb} kombinasyon")
    print("  (diğer sleeve'ler TABANDA kalır; koltuk havuzu ORTAK → marjinal etki ölçülür)")
    print("  SEÇİM YALNIZ TRAIN (2023-24) SÜTUNUNDAN. TEST sütunu seçimde KULLANILMAZ.")
    print("=" * 100)
    res = {}
    for slv in ("donchian", "squeeze", "bb"):
        print(f"\n  ### {slv} ### (taban TRAIN ${base['train']:+.0f} TEST ${base['test']:+.0f})")
        for (mode, prm) in variants:
            st = stats(portfolio(P, {slv: (mode, prm)}), funding=False)
            res[(slv, mode, prm)] = st
            print(line(f"{mode} {prm}", st))
    with open(os.path.join(os.path.dirname(CACHE), "trail_res.pkl"), "wb") as f:
        pickle.dump({k: {kk: vv for kk, vv in v.items() if kk not in ("R", "pnl", "yrs", "eff", "bars", "slv")}
                     for k, v in res.items()}, f)

    # ── TRAIN'DEN SEÇİM ──
    print("\n" + "=" * 100)
    print("BÖLÜM 2 — TRAIN'DEN SEÇİM → TEST'TE ÖLÇÜM (funding düşülmüş, yıl-yıl)")
    print("=" * 100)
    picks = {}
    for slv in ("donchian", "squeeze", "bb"):
        cand = [(k, v) for k, v in res.items() if k[0] == slv]
        best = max(cand, key=lambda kv: kv[1]["train"])
        picks[slv] = best[0]
        # plato: aynı ailedeki komşular
        fam = [(k[2], v["train"]) for k, v in cand if k[1] == best[0][1]]
        fam.sort()
        print(f"\n  {slv}: TRAIN en iyi = {best[0][1]} {best[0][2]} "
              f"(TRAIN ${best[1]['train']:+.0f} vs taban ${base['train']:+.0f})")
        print(f"    aile TRAIN profili: " + " ".join(f"{p}:{v:+.0f}" for p, v in fam))
    print()

    for slv, key in picks.items():
        _, mode, prm = key
        st = stats(portfolio(P, {slv: (mode, prm)}), funding=True)
        print(line(f"SEÇİM {slv} {mode} {prm}", st))
    print(line("TABAN (funding düşülmüş)", basef))

    # hepsi birlikte
    spec_all = {slv: (k[1], k[2]) for slv, k in picks.items()}
    st = stats(portfolio(P, spec_all), funding=True)
    print(line("SEÇİM hepsi birlikte", st))

    # ── KABUL BARI ──
    print("\n" + "=" * 100)
    print("KABUL BARI: TEST'te tabanı geçsin VE HER YIL (2023,2024,2025,2026) tabanı geçsin")
    print("=" * 100)
    for tag, spec in [(f"{s} {picks[s][1]} {picks[s][2]}", {s: (picks[s][1], picks[s][2])})
                      for s in picks] + [("hepsi birlikte", spec_all)]:
        st = stats(portfolio(P, spec), funding=True)
        ok_test = st["test"] > basef["test"]
        yrs_ok = all(st["by_year"].get(y, 0) > basef["by_year"].get(y, 0) for y in (2023, 2024, 2025, 2026))
        print(f"  {tag:32s} TEST {'GEÇ' if ok_test else 'KALDI'} "
              f"(${st['test']:+.0f} vs ${basef['test']:+.0f}) | "
              f"her-yıl {'GEÇ' if yrs_ok else 'KALDI'} | "
              f"SONUÇ: {'ADAY' if (ok_test and yrs_ok) else 'RED'}")
        print(f"    yıl-yıl: " + " ".join(f"{y}:{v:+.0f}(taban{basef['by_year'].get(y,0):+.0f})"
                                          for y, v in st["by_year"].items()))
        print(f"    ort risk {st['avg_risk']:.2f}% (taban {basef['avg_risk']:.2f}%) | "
              f"ort tutuş {st['avg_bars_hours']:.0f}h (taban {basef['avg_bars_hours']:.0f}h) | "
              f"WR {st['wr']:.1f}% (taban {basef['wr']:.1f}%) | "
              f"ort kazanan {st['R'][st['R']>0].mean():+.2f}R (taban {basef['R'][basef['R']>0].mean():+.2f}R) | "
              f"funding ${st['fund_usd']:+.1f} (taban ${basef['fund_usd']:+.1f})")


if __name__ == "__main__":
    main()
