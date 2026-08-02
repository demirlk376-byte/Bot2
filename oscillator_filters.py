"""
oscillator_filters.py — GOREV B: KLASIK OSILATORLER (RSI / StochRSI / MACD / Aroon / SuperTrend)
donchian ve squeeze girisinde FILTRE olarak.

NEDEN: kullanici MEXC grafiginde RSI(14), StochRSI, MACD(12,26,9) goruyor. Ledger'daki 13
ozellik listesinde bunlar YOK -> mesru bosluk. BB koluna DOKUNULMAZ (zaten RSI kullaniyor).

METODOLOJI (deployed_backtest.py ile birebir):
  * Aday uretimi gen()/gen_bb() ile BAYT-DENK. Kanit: filtresiz replay == deployed_backtest
    (n=1579, $+1421) assert ile dogrulanir.
  * occ = j, coin basina tek pozisyon. Filtre SINYAL ANINDA uygulanir; elenen sinyal occ'u
    ILERLETMEZ (post-hoc eleme YANLIS olurdu, seat pool'u da bozardi).
  * Gostergeler PENCERE-YEREL: donchian icin son 260 bar (4h), squeeze icin son 120 bar (1h)
    — canli get_candles/analyze ile ayni. Tam-seri hesap YOK -> lookahead YOK.
  * Koltuk secimi MAXPOS=7 ORTAK havuz (donchian+squeeze+BB), giris zamanina gore.
  * eff = min(RISKF, CAP*sl_pct).
  * Zaman damgasi: idx[i].value (NANO-saniye) — deployed_backtest.seat_select AYNEN import
    edilir, birim karismaz.

KOSU:  python3 oscillator_filters.py            (tam tur)
       python3 oscillator_filters.py --verify    (yalniz taban dogrulama)
"""
from __future__ import annotations
import os, sys, pickle, time
import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, rsi as rsi_fn, macd as macd_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
import deployed_backtest as DB
from deployed_backtest import seat_select, BAL0, FEE, RISKF, CAP, MAXPOS, DONCH, SQZ, CFG

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/osc_cands.pkl"
TRAIN_YEARS = (2023, 2024)
TEST_YEARS = (2025, 2026)
BASE_YEAR_PNL = {2023: 321.0, 2024: 457.0, 2025: 447.0, 2026: 195.0}


# ----------------------------------------------------------------------------- gostergeler
def _stochrsi(close_v, rsi_len=14, stoch_len=14, k=3, d=3):
    """StochRSI(14,14,3,3) -> (%K, %D) son deger. Pencere-yerel."""
    r = rsi_fn(pd.Series(close_v), rsi_len)
    lo = r.rolling(stoch_len).min()
    hi = r.rolling(stoch_len).max()
    rng = (hi - lo)
    raw = ((r - lo) / rng.replace(0, np.nan) * 100.0).fillna(50.0)
    kk = raw.rolling(k).mean()
    dd = kk.rolling(d).mean()
    return float(kk.iloc[-1]), float(dd.iloc[-1])


def _aroon(high_v, low_v, period=25):
    """Aroon(25) -> (up, down) son deger. Son period+1 bar."""
    if len(high_v) < period + 1:
        return np.nan, np.nan
    wh = high_v[-(period + 1):]
    wl = low_v[-(period + 1):]
    up = 100.0 * int(np.argmax(wh)) / period
    dn = 100.0 * int(np.argmin(wl)) / period
    return up, dn


def _supertrend_dir(high_v, low_v, close_v, period=10, mult=3.0):
    """SuperTrend(10,3) yonu (+1/-1). numpy dongusu, pencere-yerel."""
    n = len(close_v)
    if n < period + 2:
        return 0
    a = atr_fn(pd.Series(high_v), pd.Series(low_v), pd.Series(close_v), period).values
    hl2 = (high_v + low_v) / 2.0
    ub = hl2 + mult * a
    lb = hl2 - mult * a
    fu = ub.copy(); fl = lb.copy()
    dirn = np.ones(n, dtype=np.int8)
    for i in range(1, n):
        if not (ub[i] > 0):          # NaN ATR bolgesi
            fu[i] = ub[i]; fl[i] = lb[i]; dirn[i] = dirn[i - 1]; continue
        fu[i] = min(ub[i], fu[i - 1]) if (close_v[i - 1] <= fu[i - 1]) else ub[i]
        fl[i] = max(lb[i], fl[i - 1]) if (close_v[i - 1] >= fl[i - 1]) else lb[i]
        if close_v[i] > fu[i - 1]:
            dirn[i] = 1
        elif close_v[i] < fl[i - 1]:
            dirn[i] = -1
        else:
            dirn[i] = dirn[i - 1]
    return int(dirn[-1])


def _macd_feats(close_v):
    ml, sl, hist = macd_fn(pd.Series(close_v), 12, 26, 9)
    diff = (ml - sl).values
    m = ml.values
    # son bogа / ayi kesisimi kac bar once
    bull_ago = 999; bear_ago = 999
    last = len(diff) - 1
    for i in range(last, 0, -1):
        if not (np.isfinite(diff[i]) and np.isfinite(diff[i - 1])):
            break
        if diff[i - 1] <= 0 < diff[i] and bull_ago == 999:
            bull_ago = last - i
        if diff[i - 1] >= 0 > diff[i] and bear_ago == 999:
            bear_ago = last - i
        if bull_ago != 999 and bear_ago != 999:
            break
    return float(m[-1]), float(diff[-1]), bull_ago, bear_ago


def features(sub):
    """sub = canli analyze'a verilen PENCERE (donchian 260x4h / squeeze 120x1h)."""
    c = sub["close"].values.astype(float)
    h = sub["high"].values.astype(float)
    lo = sub["low"].values.astype(float)
    f = {}
    f["rsi"] = float(rsi_fn(pd.Series(c), 14).iloc[-1])
    f["srk"], f["srd"] = _stochrsi(c)
    f["macd"], f["mhist"], f["mbull"], f["mbear"] = _macd_feats(c)
    f["aup"], f["adn"] = _aroon(h, lo)
    f["st"] = _supertrend_dir(h, lo, c)
    return f


# ----------------------------------------------------------------------------- aday uretimi
def build_candidates(sleeve, m):
    """deployed_backtest.gen() ile BIREBIR ayni tarama; occ UYGULANMAZ (filtreye gore
    replay'de uygulanacak). Her aday icin islem sonucu (j,R,slpct) + gosterge ozellikleri."""
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
    hi = d["high"].values; low = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sub = d.iloc[max(0, i - win):i + 1]
        sg = s.analyze(sub, float(a)); d_ = sg.direction
        if d_ == 0: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if low[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if low[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        rec = {"i": i, "j": j, "dir": d_, "ns": idx[i].value, "exit": idx[j],
               "R": R, "slp": sld / e}
        rec.update(features(sub))
        out.append(rec)
    return out


def load_all(rebuild=False):
    if os.path.exists(CACHE) and not rebuild:
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    data = {"donchian": {}, "squeeze": {}, "bb": None}
    for c in DONCH:
        t0 = time.time()
        data["donchian"][c] = build_candidates("donchian", fast_bt.load(c, source="local"))
        print(f"  donchian {c}: {len(data['donchian'][c])} aday ({time.time()-t0:.0f}s)", flush=True)
    for c in SQZ:
        t0 = time.time()
        data["squeeze"][c] = build_candidates("squeeze", fast_bt.load(c, source="local"))
        print(f"  squeeze  {c}: {len(data['squeeze'][c])} aday ({time.time()-t0:.0f}s)", flush=True)
    bb = []
    for c in DB.BB_COINS:
        bb += DB.gen_bb(fast_bt.load(c, source="local"))
    data["bb"] = bb
    print(f"  bb: {len(bb)} islem (filtresiz, DOKUNULMUYOR)", flush=True)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump(data, fh)
    return data


# ----------------------------------------------------------------------------- replay + metrik
def replay(cands, keep):
    """occ zinciri: elenen sinyal occ'u ILERLETMEZ."""
    out = []; occ = -1
    for k, c in enumerate(cands):
        if c["i"] <= occ: continue
        if not keep[k]: continue
        out.append((c["ns"], c["exit"], c["R"], c["slp"]))
        occ = c["j"]
    return out


def run(data, keeps):
    """keeps: {(sleeve,coin): bool-array} — yoksa hepsi True."""
    trades = []
    for sl in ("donchian", "squeeze"):
        for c, cd in data[sl].items():
            k = keeps.get((sl, c))
            if k is None:
                k = np.ones(len(cd), dtype=bool)
            trades += replay(cd, k)
    trades += data["bb"]
    return seat_select(trades)


def metrics(taken):
    r = np.array([R for _, R, _ in taken])
    slp = np.array([sp for _, _, sp in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    eff = np.minimum(RISKF, CAP * slp)
    pnl = r * eff * BAL0
    yr = np.array([x.year for x in ex])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    m = {"n": len(r), "pf": gp / max(gl, 1e-9), "wr": (r > 0).mean() * 100,
         "usd": pnl.sum(), "risk": eff.mean() * 100, "pnl": pnl, "yr": yr, "r": r}
    for y in (2023, 2024, 2025, 2026):
        msk = yr == y
        m[f"y{y}"] = pnl[msk].sum()
        m[f"n{y}"] = int(msk.sum())
    m["train"] = pnl[(yr <= 2024)].sum()
    m["test"] = pnl[(yr >= 2025)].sum()
    rt = r[yr <= 2024]; rs = r[yr >= 2025]
    m["train_pf"] = rt[rt > 0].sum() / max(-rt[rt < 0].sum(), 1e-9)
    m["test_pf"] = rs[rs > 0].sum() / max(-rs[rs < 0].sum(), 1e-9)
    m["train_wr"] = (rt > 0).mean() * 100
    m["test_wr"] = (rs > 0).mean() * 100
    m["train_n"] = len(rt); m["test_n"] = len(rs)
    return m


# ----------------------------------------------------------------------------- hipotezler
def make_hypotheses():
    """(ad, sleeve, fn(rec)->keep) listesi. fn SADECE sinyal anindaki ozellikleri gorur."""
    H = []

    def add(name, sleeve, fn, fam, param):
        H.append({"name": name, "sleeve": sleeve, "fn": fn, "fam": fam, "param": param})

    for sleeve in ("donchian", "squeeze"):
        p = sleeve[:4]
        # --- 1) RSI(14): momentum-onayi vs asiri-alim fade (simetrik esik)
        for t in (40, 50, 60, 70):
            add(f"[{p}] RSI mom  L>{t} S<{100-t}", sleeve,
                (lambda t: lambda r: (r["rsi"] > t) if r["dir"] == 1 else (r["rsi"] < 100 - t))(t),
                f"{p}:rsi_mom", t)
            add(f"[{p}] RSI fade L<{t} S>{100-t}", sleeve,
                (lambda t: lambda r: (r["rsi"] < t) if r["dir"] == 1 else (r["rsi"] > 100 - t))(t),
                f"{p}:rsi_fade", t)
        # --- 3) MACD(12,26,9)
        add(f"[{p}] MACD hist uyum", sleeve,
            lambda r: (r["mhist"] > 0) if r["dir"] == 1 else (r["mhist"] < 0), f"{p}:mhist", 0)
        add(f"[{p}] MACD hist TERS", sleeve,
            lambda r: (r["mhist"] < 0) if r["dir"] == 1 else (r["mhist"] > 0), f"{p}:mhist_inv", 0)
        add(f"[{p}] MACD>0 uyum", sleeve,
            lambda r: (r["macd"] > 0) if r["dir"] == 1 else (r["macd"] < 0), f"{p}:mline", 0)
        add(f"[{p}] MACD>0 TERS", sleeve,
            lambda r: (r["macd"] < 0) if r["dir"] == 1 else (r["macd"] > 0), f"{p}:mline_inv", 0)
        for N in (3, 5, 10):
            add(f"[{p}] MACD kesisim<={N}bar", sleeve,
                (lambda N: lambda r: (r["mbull"] <= N) if r["dir"] == 1 else (r["mbear"] <= N))(N),
                f"{p}:mcross", N)
            add(f"[{p}] MACD kesisim>{N}bar", sleeve,
                (lambda N: lambda r: (r["mbull"] > N) if r["dir"] == 1 else (r["mbear"] > N))(N),
                f"{p}:mcross_inv", N)

    # --- 2) StochRSI, 4) Aroon, 5) SuperTrend: yalniz donchian (gorev tanimi)
    p = "donc"
    for t in (20, 50, 80):
        H.append({"name": f"[{p}] StochK mom  L>{t} S<{100-t}", "sleeve": "donchian",
                  "fn": (lambda t: lambda r: (r["srk"] > t) if r["dir"] == 1 else (r["srk"] < 100 - t))(t),
                  "fam": f"{p}:srk_mom", "param": t})
        H.append({"name": f"[{p}] StochK fade L<{t} S>{100-t}", "sleeve": "donchian",
                  "fn": (lambda t: lambda r: (r["srk"] < t) if r["dir"] == 1 else (r["srk"] > 100 - t))(t),
                  "fam": f"{p}:srk_fade", "param": t})
    H.append({"name": f"[{p}] StochRSI K>D uyum", "sleeve": "donchian",
              "fn": lambda r: (r["srk"] > r["srd"]) if r["dir"] == 1 else (r["srk"] < r["srd"]),
              "fam": f"{p}:srx", "param": 0})
    H.append({"name": f"[{p}] StochRSI K>D TERS", "sleeve": "donchian",
              "fn": lambda r: (r["srk"] < r["srd"]) if r["dir"] == 1 else (r["srk"] > r["srd"]),
              "fam": f"{p}:srx_inv", "param": 0})
    for t in (50, 70):
        H.append({"name": f"[{p}] Aroon uyum >{t}", "sleeve": "donchian",
                  "fn": (lambda t: lambda r: (r["aup"] >= t) if r["dir"] == 1 else (r["adn"] >= t))(t),
                  "fam": f"{p}:aroon", "param": t})
        H.append({"name": f"[{p}] Aroon TERS <{t}", "sleeve": "donchian",
                  "fn": (lambda t: lambda r: (r["aup"] < t) if r["dir"] == 1 else (r["adn"] < t))(t),
                  "fam": f"{p}:aroon_inv", "param": t})
    H.append({"name": f"[{p}] SuperTrend uyum", "sleeve": "donchian",
              "fn": lambda r: (r["st"] == 1) if r["dir"] == 1 else (r["st"] == -1),
              "fam": f"{p}:st", "param": 0})
    H.append({"name": f"[{p}] SuperTrend TERS", "sleeve": "donchian",
              "fn": lambda r: (r["st"] == -1) if r["dir"] == 1 else (r["st"] == 1),
              "fam": f"{p}:st_inv", "param": 0})
    return H


def keeps_for(data, hyp):
    ks = {}
    sl = hyp["sleeve"]; fn = hyp["fn"]
    for c, cd in data[sl].items():
        ks[(sl, c)] = np.array([bool(fn(r)) for r in cd], dtype=bool)
    return ks


# ----------------------------------------------------------------------------- permutasyon
def permutation_p(data, hyp, observed_delta, base_usd, nperm=1000, seed=7, field="usd"):
    """Filtre etiketlerini sleeve havuzunda RASTGELE karistir (ayni sayida eleme),
    delta dagilimini cikar, p = P(rastgele delta >= gerceklesen)."""
    sl = hyp["sleeve"]
    coins = list(data[sl].keys())
    sizes = [len(data[sl][c]) for c in coins]
    ks = keeps_for(data, hyp)
    flat = np.concatenate([ks[(sl, c)] for c in coins])
    nkeep = int(flat.sum()); ntot = len(flat)
    rng = np.random.default_rng(seed)
    deltas = np.empty(nperm)
    base_lab = np.zeros(ntot, dtype=bool); base_lab[:nkeep] = True
    for b in range(nperm):
        lab = rng.permutation(base_lab)
        kk = {}; o = 0
        for c, s in zip(coins, sizes):
            kk[(sl, c)] = lab[o:o + s]; o += s
        m = metrics(run(data, kk))
        deltas[b] = m[field] - base_usd
    p = float((deltas >= observed_delta).mean())
    return p, deltas


# ----------------------------------------------------------------------------- ana
def main():
    verify_only = "--verify" in sys.argv
    rebuild = "--rebuild" in sys.argv
    data = load_all(rebuild=rebuild)

    # ---- TABAN DOGRULAMA (filtresiz replay == deployed_backtest)
    base = metrics(run(data, {}))
    print("\n" + "=" * 78)
    print("TABAN DOGRULAMA (filtresiz replay vs deployed_backtest.py local)")
    print(f"  n={base['n']}  PF {base['pf']:.2f}  WR {base['wr']:.0f}%  ${base['usd']:+.0f}  "
          f"ort risk {base['risk']:.2f}%")
    print(f"  2023 ${base['y2023']:+.0f} | 2024 ${base['y2024']:+.0f} | "
          f"2025 ${base['y2025']:+.0f} | 2026 ${base['y2026']:+.0f}")
    ok = (base["n"] == 1579 and abs(base["usd"] - 1421) < 1.5 and
          abs(base["pf"] - 1.45) < 0.005 and abs(base["risk"] - 2.13) < 0.01 and
          all(abs(base[f"y{y}"] - v) < 1.5 for y, v in BASE_YEAR_PNL.items()))
    print(f"  -> TABAN {'DOGRULANDI' if ok else 'TUTMADI — DUR'}")
    if not ok:
        sys.exit(1)
    if verify_only:
        return
    print(f"  TRAIN(2023-24) ${base['train']:+.0f} PF {base['train_pf']:.2f} "
          f"WR {base['train_wr']:.1f}% n{base['train_n']}")
    print(f"  TEST (2025-26) ${base['test']:+.0f} PF {base['test_pf']:.2f} "
          f"WR {base['test_wr']:.1f}% n{base['test_n']}")

    H = make_hypotheses()
    print(f"\n{'='*78}\nHIPOTEZ SAYISI: {len(H)}  (indikator x esik x yon)")
    print("SECIM YALNIZ TRAIN(2023-01..2024-12). TEST kolonu SADECE raporlama icin,")
    print("secimde KULLANILMIYOR.\n")

    rows = []
    hdr = (f"{'filtre':<34}{'elenen%':>8}{'TRAIN$':>9}{'dTR':>7}{'trPF':>6}{'trWR':>6}"
           f"{'trN':>6}  |{'TEST$':>8}{'dTE':>7}{'teWR':>6}{'risk%':>7}")
    print(hdr); print("-" * len(hdr))
    for h in H:
        ks = keeps_for(data, h)
        allk = np.concatenate([v for v in ks.values()])
        drop = 100.0 * (1 - allk.mean())
        m = metrics(run(data, ks))
        m["name"] = h["name"]; m["hyp"] = h; m["drop"] = drop
        rows.append(m)
        print(f"{h['name']:<34}{drop:>7.0f}%{m['train']:>9.0f}{m['train']-base['train']:>7.0f}"
              f"{m['train_pf']:>6.2f}{m['train_wr']:>6.1f}{m['train_n']:>6d}  |"
              f"{m['test']:>8.0f}{m['test']-base['test']:>7.0f}{m['test_wr']:>6.1f}"
              f"{m['risk']:>7.2f}", flush=True)

    # ---- TRAIN'de secim
    print(f"\n{'='*78}\nTRAIN SECIMI (kriter: TRAIN toplam$ > taban VE her iki TRAIN yili > taban)")
    cands = [m for m in rows
             if m["train"] > base["train"]
             and m["y2023"] > BASE_YEAR_PNL[2023] and m["y2024"] > BASE_YEAR_PNL[2024]]
    cands.sort(key=lambda m: -m["train"])
    if not cands:
        print("  TRAIN'de tabani gecen filtre YOK. Aday yok, tur burada biter.")
    for m in cands:
        print(f"  {m['name']:<34} TRAIN ${m['train']:+.0f} (taban ${base['train']:+.0f}) "
              f"2023 ${m['y2023']:+.0f} 2024 ${m['y2024']:+.0f}")

    # ---- KABUL BARI: TEST + her yil + permutasyon + plato
    print(f"\n{'='*78}\nKABUL BARI KONTROLU (TEST + her yil + permutasyon + plato)")
    survivors = []
    for m in cands:
        name = m["name"]
        yr_ok = all(m[f"y{y}"] > BASE_YEAR_PNL[y] for y in (2023, 2024, 2025, 2026))
        test_ok = m["test"] > base["test"]
        print(f"\n  --- {name}")
        print(f"      yil-yil: " + " ".join(
            f"{y}:${m[f'y{y}']:+.0f}({'+' if m[f'y{y}']>BASE_YEAR_PNL[y] else '-'})"
            for y in (2023, 2024, 2025, 2026)))
        print(f"      TEST ${m['test']:+.0f} vs taban ${base['test']:+.0f} -> "
              f"{'GECTI' if test_ok else 'KALDI'}")
        print(f"      WR {base['wr']:.1f}% -> {m['wr']:.1f}%  (degismiyorsa filtre "
              f"kazanan/kaybeden AYIRMIYOR)")
        print(f"      ort risk {base['risk']:.2f}% -> {m['risk']:.2f}%  (kaldirac kontrolu)")
        if not (yr_ok and test_ok):
            print("      -> RET (TEST/yil bari)")
            continue
        t0 = time.time()
        p_tr, _ = permutation_p(data, m["hyp"], m["train"] - base["train"], base["train"],
                                nperm=1000, field="train")
        p_all, _ = permutation_p(data, m["hyp"], m["usd"] - base["usd"], base["usd"],
                                 nperm=1000, field="usd")
        print(f"      permutasyon (1000 tur): p_TRAIN={p_tr:.3f}  p_TUM={p_all:.3f} "
              f"({time.time()-t0:.0f}s)")
        if p_tr >= 0.05:
            print("      -> RET (p>=0.05, sans)")
            continue
        survivors.append((m, p_tr, p_all))

    # ---- PLATO (komsu esikler) — hayatta kalanlar icin
    if survivors:
        print(f"\n{'='*78}\nPLATO KONTROLU (ayni ailenin komsu esikleri)")
        for m, p_tr, p_all in survivors:
            fam = m["hyp"]["fam"]
            sib = [x for x in rows if x["hyp"]["fam"] == fam]
            print(f"  {m['name']} ailesi ({fam}):")
            for x in sorted(sib, key=lambda z: z["hyp"]["param"]):
                print(f"    esik {x['hyp']['param']:>3}: TRAIN ${x['train']:+.0f} "
                      f"TEST ${x['test']:+.0f} TOPLAM ${x['usd']:+.0f}")
            # kazancin kac isleme dayandigi
            mm = m
            base_sorted = np.sort(mm["pnl"])
            print(f"    kazanc yogunlugu: en iyi 30 islem ${base_sorted[-30:].sum():+.0f} / "
                  f"toplam ${mm['usd']:+.0f}")
    else:
        print(f"\n{'='*78}\nHayatta kalan aday YOK — plato kontrolu gereksiz.")

    print(f"\n{'='*78}\nOZET: {len(H)} hipotez test edildi, TRAIN'i gecen {len(cands)}, "
          f"tum bariyeri gecen {len(survivors)}.")

    # en iyi/en kotu birkac satir (raporlama)
    rows.sort(key=lambda m: -m["usd"])
    print("\nTOPLAM$'a gore en iyi 5 (RAPOR AMACLI, secim TRAIN'den yapildi):")
    for m in rows[:5]:
        print(f"  {m['name']:<34} TOPLAM ${m['usd']:+.0f} (taban ${base['usd']:+.0f}) "
              f"TRAIN ${m['train']:+.0f} TEST ${m['test']:+.0f} n{m['n']} WR{m['wr']:.1f}%")


if __name__ == "__main__":
    main()
