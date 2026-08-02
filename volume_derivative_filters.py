"""
volume_derivative_filters.py — GOREV C: HACIM TUREVLERI (ham hacim reddedildi, TUREVLERI degil)

NEDEN: ham hacim filtresi (>1.0/1.25/1.5/2.0x 20-bar ort) test edildi ve REDDEDILDI — WR hic
degismedi (%43->%43->%44->%43): hacim SEVIYESI kazanani kaybedenden AYIRMIYOR, sadece sistemi
kuculttu. Burada test edilenler hacmin YONU / BIRIKIMI / GORECELIGI = farkli bilgi:
  1. OBV egimi (N=10,20)                         — kirilim yonunde birikim var mi?
  2. VWAP(24) mesafesi, yon-isaretli              — donchian'da HIC denenmedi
  3. Hacim-agirlikli kirilim gucu                 — SEVIYEDEKI likiditeye gore normalize
  4. Kesitsel relatif hacim (11 coin)             — piyasa mi hareketli, BU coin mi?
  5. A/D (Chaikin) egimi (N=10,20)

METODOLOJI (deployed_backtest.py ile birebir):
  * Aday uretimi gen() ile BAYT-DENK. Kanit: filtresiz replay == deployed_backtest
    (n=1579, PF 1.45, $+1421, ort risk %2.13, 2023/24/25/26 = 321/457/447/195) assert edilir.
  * occ = j, coin basina tek pozisyon. Filtre SINYAL ANINDA uygulanir; elenen sinyal occ'u
    ILERLETMEZ (post-hoc eleme YANLIS olurdu, koltuk havuzunu da bozardi).
  * LOOKAHEAD YOK. Tum hacim turevleri NEDENSEL (causal) ve PENCERE-YEREL'e denk:
      - OBV/AD FARKI (X[i]-X[i-N]) kumulatif tabani goturur -> pencere baslangicindan bagimsiz
      - VWAP24 / rvol21 / bstr41 en fazla 41 bar geriye bakar; canli pencere donchian 260 (4h),
        squeeze 120 (1h) -> tam-seri nedensel hesap pencere-yerel hesapla ozdes.
    Bu iddia --verify ile 200 rastgele aday uzerinde SAYISAL olarak dogrulanir.
  * Kesitsel relatif hacim SADECE ES-ZAMANLI (ayni 4h bari) veriyi kullanir -> lookahead yok.
  * Koltuk secimi MAXPOS=7 ORTAK havuz (donchian+squeeze+BB), giris zamanina gore.
  * eff = min(RISKF, CAP*sl_pct).
  * Zaman damgasi: idx[i].value (NANO-saniye). deployed_backtest.seat_select AYNEN import
    edilir -> pandas 3 birim tuzagi (values.astype(int64) = MIKRO-saniye) yasanmaz.
  * SECIM YALNIZ TRAIN (2023-01..2024-12). TEST (2025-01..) secimde ACILMAZ.

KOSU:  python3 volume_derivative_filters.py            (tam tur)
       python3 volume_derivative_filters.py --verify    (taban + lookahead dogrulama)

============================== SONUC (2026-08-02) — HEPSI RET =============================
TABAN DOGRULANDI birebir: n=1579 PF 1.45 WR %44 $+1421 ort risk %2.13,
  2023 +321 / 2024 +457 / 2025 +447 / 2026 +195. Pencere-yerel dogrulama: sapma 1.1e-11.
68 hipotez (5 aile x esik x yon x kol). TRAIN'i gecen: 1. Tum bari gecen: 0.

  * WR HIC KIMILDAMADI — ham hacimdeki bulgunun AYNISI. 68 hipotezin WR araligi
    %41.5..%44.9 (taban %43.5); |dWR|>2 puan olan 0/68. Hacmin YONU/BIRIKIMI de
    kazanani kaybedenden AYIRMIYOR. Ham hacim ile turevleri arasinda fark YOK.
  * Tek TRAIN adayi [sqz] OBV10 egim uyum>0: TRAIN +$39 (perm p=0.034) AMA
    TEST -$5, 2026 -$7 -> RET. Ustelik PLATO YOK: komsu esikler (>0.15, N=20)
    TRAIN'de de TEST'te de NEGATIF. 68 testte p=0.034 zaten beklenen sanstir
    (Bonferroni 0.034x68 = 2.3).
  * VWAP24 donchian'da DEJENERE: yon-isaretli mesafenin MINIMUMU +%0.89, %100'u
    >%1 -> 40-bar kanal kirilimi zaten VWAP'in cok uzerinde kapaniyor. Bilgi = 0.
    (mean_rev'de calismasi bundan; donchian'da MEKANIK olarak bos.)
  * "Kirilim gucu" (seviye-likiditesine gore normalize) REDDEDILEN ham hacimden
    ZAYIF: desil analizinde ham vol/kanal-ort rho=+0.075 (p=0.008) vs kirilim gucu
    rho=+0.038 (p=0.180). Yani seviye-likiditesi normalizasyonu bilgi EKLEMIYOR,
    gurultu EKLIYOR. Hipotezin dayanagi (3 numara) coktu.
  * A/D20 klasik TRAIN/TEST isaret donmesi: Q5-Q1 dR TRAIN +0.263 (p=0.023),
    TEST -0.077 (p=0.724). Secim TRAIN'den yapilsa TEST'te tersine donerdi.
  * Kesitsel rvol: TRAIN Q5 en iyi, TEST'te Q4 tepe / Q5 orta -> monoton degil.
  * Kaldirac tuzagi YOK: aday ort risk %2.14 vs taban %2.13.
  * TEK ilginc kalinti: [sqz] VWAP24 yakin <%1 -> WR %44.9 (grid'in en iyisi,
    +1.4 puan) ve HEM TRAIN HEM TEST'te trPF 1.56 / teWR %44.6. AMA parayi
    KAYBEDIYOR (TRAIN -$31, TEST -$33): sinyalin %63'unu kesiyor. Ileride
    "eleme" degil "boyutlandirma" olarak bakilabilir; filtre olarak OLU.
==========================================================================================
"""
from __future__ import annotations
import os, sys, pickle, time
import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
import deployed_backtest as DB
from deployed_backtest import seat_select, BAL0, FEE, RISKF, CAP, MAXPOS, DONCH, SQZ, CFG

SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
CACHE = os.path.join(SCRATCH, "vol_deriv_cands.pkl")
BASE_YEAR_PNL = {2023: 321.0, 2024: 457.0, 2025: 447.0, 2026: 195.0}
XSEC_COINS = DONCH + SQZ          # gorevdeki "11 coin"
CHANNEL = 40                      # DonchianStrategy kanal uzunlugu (birebir)


# ============================================================ HACIM TUREVLERI (nedensel)
def _obv(c, v):
    """OBV = kumulatif(sign(close farki) * hacim). Ilk bar 0 katki."""
    sgn = np.sign(np.diff(c, prepend=c[0]))
    return np.cumsum(sgn * v)


def _ad(h, l, c, v):
    """Chaikin Accumulation/Distribution = kumulatif(CLV * hacim)."""
    rng = h - l
    clv = np.where(rng > 0, ((c - l) - (h - c)) / np.where(rng > 0, rng, 1.0), 0.0)
    return np.cumsum(clv * v)


def _norm_slope(cum, v, N):
    """(cum[i]-cum[i-N]) / (N * son-N-bar ort hacim) -> boyutsuz, [-1,1] araliginda.
    Kumulatif taban FARKTA gotugu icin pencere-yerel hesapla ozdes."""
    n = len(cum)
    out = np.full(n, np.nan)
    vm = pd.Series(v).rolling(N).mean().values      # son N bar (guncel dahil), nedensel
    d = np.full(n, np.nan)
    d[N:] = cum[N:] - cum[:-N]
    ok = np.isfinite(vm) & (vm > 0) & np.isfinite(d)
    out[ok] = d[ok] / (N * vm[ok])
    return out


def volume_features(d):
    """d: sleeve'in kendi timeframe'ine resample edilmis OHLCV. Hepsi NEDENSEL."""
    h = d["high"].values.astype(float); l = d["low"].values.astype(float)
    c = d["close"].values.astype(float); v = d["volume"].values.astype(float)
    f = {}
    obv = _obv(c, v); ad = _ad(h, l, c, v)
    for N in (10, 20):
        f[f"obv{N}"] = _norm_slope(obv, v, N)
        f[f"ad{N}"] = _norm_slope(ad, v, N)
    # VWAP(24) mesafesi, % — nedensel rolling
    tp = (h + l + c) / 3.0
    num = pd.Series(tp * v).rolling(24).sum().values
    den = pd.Series(v).rolling(24).sum().values
    vw = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    f["vwapd"] = (c - vw) / vw * 100.0
    # kendi rvol'u (kesitsel karsilastirma icin): hacim / ONCEKI 20 barin ort hacmi
    f["rvol"] = v / pd.Series(v).rolling(20).mean().shift(1).values
    # referans (hipotez DEGIL, sadece raporlama): kanal boyu ort hacme gore
    f["vchan"] = v / pd.Series(v).rolling(CHANNEL).mean().shift(1).values
    return f


def breakout_strength(h, l, v, atr_i, i, dirn, chan=CHANNEL, tol_atr=0.25):
    """(kirilim bari hacmi) / (SEVIYEYE YAKIN islem goren barlarin ort hacmi).
    Long: seviye = onceki `chan` barin en yuksegi; 'yakin' = high >= seviye - 0.25*ATR.
    Ham hacimden farki: paydada TUM kanal degil, DIRENCTE islem goren likidite var."""
    if i - chan < 0:
        return np.nan
    wh = h[i - chan:i]; wl = l[i - chan:i]; wv = v[i - chan:i]
    if dirn == 1:
        lvl = wh.max(); msk = wh >= lvl - tol_atr * atr_i
    else:
        lvl = wl.min(); msk = wl <= lvl + tol_atr * atr_i
    zv = wv[msk]
    if zv.size == 0 or zv.mean() <= 0:
        return np.nan
    return float(v[i] / zv.mean())


# ============================================================ kesitsel relatif hacim
def build_xsec(mdict, tf="4h"):
    """xrel = coin'in rvol'u / 11 coinin AYNI BARDAKI ortalama rvol'u.
    ES-ZAMANLI -> lookahead yok. rvol = hacim / ONCEKI 20 barin ort hacmi (birim-bagimsiz,
    coinler arasi karsilastirilabilir; ham hacim coinler arasi karsilastirilamaz)."""
    cols = {}
    for c in XSEC_COINS:
        d = fast_bt.resample(mdict[c], tf)
        v = d["volume"]
        cols[c] = v / v.rolling(20).mean().shift(1)
    R = pd.DataFrame(cols).sort_index()
    mkt = R.mean(axis=1, skipna=True)
    return R.div(mkt, axis=0)          # DataFrame: index=4h ts, kolon=coin


# ============================================================ aday uretimi (gen ile birebir)
def build_candidates(sleeve, m, coin, xsec=None):
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
    vol = d["volume"].values.astype(float)
    idx = d.index; n = len(cl)
    F = volume_features(d)
    xs = None
    if xsec is not None and coin in xsec.columns:
        xs = xsec[coin].reindex(idx).values
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
        for k in ("obv10", "obv20", "ad10", "ad20", "vwapd", "rvol", "vchan"):
            rec[k] = float(F[k][i])
        rec["bstr"] = breakout_strength(hi, low, vol, float(a), i, d_)
        rec["xrel"] = float(xs[i]) if (xs is not None and np.isfinite(xs[i])) else np.nan
        out.append(rec)
    return out


def load_all(rebuild=False):
    if os.path.exists(CACHE) and not rebuild:
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    mdict = {c: fast_bt.load(c, source="local") for c in XSEC_COINS}
    t0 = time.time()
    xsec = build_xsec(mdict, "4h")
    print(f"  kesitsel rvol tablosu: {xsec.shape} ({time.time()-t0:.0f}s)", flush=True)
    data = {"donchian": {}, "squeeze": {}, "bb": None}
    for c in DONCH:
        t0 = time.time()
        data["donchian"][c] = build_candidates("donchian", mdict[c], c, xsec)
        print(f"  donchian {c}: {len(data['donchian'][c])} aday ({time.time()-t0:.0f}s)", flush=True)
    for c in SQZ:
        t0 = time.time()
        data["squeeze"][c] = build_candidates("squeeze", mdict[c], c, None)
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


# ============================================================ LOOKAHEAD DOGRULAMA
def verify_window_local(nsample=200, seed=3):
    """Tam-seri NEDENSEL hesap == PENCERE-YEREL (canli get_candles) hesap iddiasini
    SAYISAL dogrula. Donchian 260x4h, squeeze 120x1h pencerelerinde."""
    rng = np.random.default_rng(seed)
    worst = 0.0; checked = 0
    for sleeve, coins in (("donchian", DONCH[:3]), ("squeeze", SQZ[:2])):
        tf, win, *_ = CFG[sleeve]
        for c in coins:
            d = fast_bt.resample(fast_bt.load(c, source="local"), tf)
            F = volume_features(d)
            n = len(d)
            for i in rng.integers(300, n - 2, size=nsample // 5):
                i = int(i)
                sub = d.iloc[max(0, i - win):i + 1]
                Fl = volume_features(sub)
                for k in ("obv10", "obv20", "ad10", "ad20", "vwapd", "rvol"):
                    a = F[k][i]; b = Fl[k][-1]
                    if np.isfinite(a) and np.isfinite(b):
                        worst = max(worst, abs(a - b) / max(abs(a), 1e-9))
                    elif np.isfinite(a) != np.isfinite(b):
                        worst = 9.99
                    checked += 1
    return worst, checked


# ============================================================ replay + metrik
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
        m[f"y{y}"] = pnl[msk].sum(); m[f"n{y}"] = int(msk.sum())
    m["train"] = pnl[yr <= 2024].sum(); m["test"] = pnl[yr >= 2025].sum()
    rt = r[yr <= 2024]; rs = r[yr >= 2025]
    m["train_pf"] = rt[rt > 0].sum() / max(-rt[rt < 0].sum(), 1e-9)
    m["test_pf"] = rs[rs > 0].sum() / max(-rs[rs < 0].sum(), 1e-9)
    m["train_wr"] = (rt > 0).mean() * 100; m["test_wr"] = (rs > 0).mean() * 100
    m["train_n"] = len(rt); m["test_n"] = len(rs)
    return m


# ============================================================ hipotezler
def _cmp(key, op, t):
    """NaN -> GECER (kapatilamayan gosterge sinyali dusurmez; NaN orani raporlanir)."""
    if op == ">":
        return lambda r: (not np.isfinite(r[key])) or (r[key] > t)
    return lambda r: (not np.isfinite(r[key])) or (r[key] < t)


def _signed(key, op, t):
    """yon-isaretli: v = dir * gosterge."""
    if op == ">":
        return lambda r: (not np.isfinite(r[key])) or (r["dir"] * r[key] > t)
    return lambda r: (not np.isfinite(r[key])) or (r["dir"] * r[key] < t)


def make_hypotheses():
    H = []

    def add(name, sleeve, fn, fam, param):
        H.append({"name": name, "sleeve": sleeve, "fn": fn, "fam": fam, "param": param})

    for sleeve in ("donchian", "squeeze"):        # 1 ve 2 HER IKI kolda
        p = "donc" if sleeve == "donchian" else "sqz"
        # --- 1) OBV EGIMI (yon-isaretli)
        for N in (10, 20):
            for t in (0.0, 0.15):
                add(f"[{p}] OBV{N} egim uyum >{t}", sleeve, _signed(f"obv{N}", ">", t),
                    f"{p}:obv{N}_up", t)
                add(f"[{p}] OBV{N} egim TERS <{-t}", sleeve, _signed(f"obv{N}", "<", -t),
                    f"{p}:obv{N}_dn", t)
        # --- 2) VWAP(24) MESAFESI (yon-isaretli, %)
        for t in (0.0, 0.5, 1.0):
            add(f"[{p}] VWAP24 uyum >{t}%", sleeve, _signed("vwapd", ">", t), f"{p}:vwap_up", t)
            add(f"[{p}] VWAP24 TERS <{-t}%", sleeve, _signed("vwapd", "<", -t), f"{p}:vwap_dn", t)

    # --- 3,4,5 YALNIZ donchian (gorev tanimi)
    p = "donc"
    for t in (0.8, 1.0, 1.25, 1.5):
        add(f"[{p}] kirilim gucu >{t}", "donchian", _cmp("bstr", ">", t), f"{p}:bstr_hi", t)
        add(f"[{p}] kirilim gucu <{t}", "donchian", _cmp("bstr", "<", t), f"{p}:bstr_lo", t)
    for t in (0.8, 1.0, 1.25, 1.5):
        add(f"[{p}] kesitsel rvol >{t}", "donchian", _cmp("xrel", ">", t), f"{p}:xrel_hi", t)
        add(f"[{p}] kesitsel rvol <{t}", "donchian", _cmp("xrel", "<", t), f"{p}:xrel_lo", t)
    for N in (10, 20):
        for t in (0.0, 0.15):
            add(f"[{p}] A/D{N} egim uyum >{t}", "donchian", _signed(f"ad{N}", ">", t),
                f"{p}:ad{N}_up", t)
            add(f"[{p}] A/D{N} egim TERS <{-t}", "donchian", _signed(f"ad{N}", "<", -t),
                f"{p}:ad{N}_dn", t)

    # ---------------- 2. GECIS: DAGILIM-FARKINDA ESIKLER (ilk izgara YANLIS MERKEZLIYDI)
    # Denetimde cikti: yon-isaretli VWAP mesafesi TEK-YONLU. donchian'da min +%0.89
    # (100%'i >%1) -> {0, 0.5, 1.0} esikleri DEJENERE, hicbir sinyali elemiyor.
    # squeeze'de de %98.9'u >0 -> "TERS <0" esigi kolu tamamen olduruyor.
    # Anlamli araligi test etmek icin GOZLENEN dagilimin ceyreklerinden esik eklenir.
    # !!! DURUSTLUK NOTU: bu esikler, TEST ceyreklerini de gosteren bir teshis
    # tablosundan SONRA secildi -> bu aile KIRLI (contaminated). Gecerse bile
    # bagimsiz dogrulama ister. Hipotez sayimina DAHIL edilir.
    for t in (3.0, 5.0, 7.0, 10.0):
        add(f"[donc] VWAP24 uzak >{t}%", "donchian", _signed("vwapd", ">", t), "donc:vwapq_hi", t)
        add(f"[donc] VWAP24 yakin <{t}%", "donchian", _signed("vwapd", "<", t), "donc:vwapq_lo", t)
    for t in (0.5, 1.0, 2.0):
        add(f"[sqz] VWAP24 yakin <{t}%", "squeeze", _signed("vwapd", "<", t), "sqz:vwapq_lo", t)
    add("[sqz] VWAP24 uzak >2.0%", "squeeze", _signed("vwapd", ">", 2.0), "sqz:vwapq_hi", 2.0)
    for t in (2.0, 2.5):
        add(f"[donc] kirilim gucu >{t}", "donchian", _cmp("bstr", ">", t), "donc:bstr_hi", t)
        add(f"[donc] kesitsel rvol >{t}", "donchian", _cmp("xrel", ">", t), "donc:xrel_hi", t)
    return H


def keeps_for(data, hyp):
    ks = {}
    sl = hyp["sleeve"]; fn = hyp["fn"]
    for c, cd in data[sl].items():
        ks[(sl, c)] = np.array([bool(fn(r)) for r in cd], dtype=bool)
    return ks


# ============================================================ permutasyon
def permutation_p(data, hyp, observed_delta, base_usd, nperm=1000, seed=11, field="usd"):
    """Filtre etiketlerini sleeve havuzunda RASTGELE karistir (AYNI sayida eleme, ama
    RASTGELE secilmis), delta dagilimini cikar; p = P(rastgele delta >= gerceklesen)."""
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
        deltas[b] = metrics(run(data, kk))[field] - base_usd
    return float((deltas >= observed_delta).mean()), deltas


# ============================================================ ana
def main():
    verify_only = "--verify" in sys.argv
    rebuild = "--rebuild" in sys.argv
    data = load_all(rebuild=rebuild)

    # ---- TABAN DOGRULAMA
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

    # ---- LOOKAHEAD / PENCERE-YEREL DOGRULAMA
    if verify_only:
        w, ch = verify_window_local()
        print(f"\nPENCERE-YEREL DOGRULAMA: {ch} karsilastirma, en buyuk goreli sapma {w:.2e}")
        print(f"  -> {'TAM-SERI == PENCERE-YEREL (lookahead yok)' if w < 1e-9 else 'SAPMA VAR — DUR'}")
        return

    print(f"  TRAIN(2023-24) ${base['train']:+.0f} PF {base['train_pf']:.2f} "
          f"WR {base['train_wr']:.1f}% n{base['train_n']}")
    print(f"  TEST (2025-26) ${base['test']:+.0f} PF {base['test_pf']:.2f} "
          f"WR {base['test_wr']:.1f}% n{base['test_n']}")

    # ---- gosterge dagilimlari (NaN orani / kapsam)
    print(f"\n{'='*78}\nGOSTERGE KAPSAMI (NaN -> filtre GECER olarak islenir)")
    for sl in ("donchian", "squeeze"):
        allc = [r for cd in data[sl].values() for r in cd]
        for k in ("obv10", "obv20", "ad10", "ad20", "vwapd", "bstr", "xrel", "vchan"):
            v = np.array([r.get(k, np.nan) for r in allc], dtype=float)
            fin = np.isfinite(v)
            if fin.sum() == 0: continue
            print(f"  {sl:9s} {k:7s} n={len(v):5d} NaN {100*(1-fin.mean()):4.1f}%  "
                  f"med {np.median(v[fin]):+7.3f}  p10 {np.percentile(v[fin],10):+7.3f}  "
                  f"p90 {np.percentile(v[fin],90):+7.3f}")

    H = make_hypotheses()
    print(f"\n{'='*78}\nHIPOTEZ SAYISI: {len(H)}  (indikator x esik x yon)")
    print("SECIM YALNIZ TRAIN(2023-01..2024-12). TEST kolonu SADECE raporlama.\n")

    rows = []
    hdr = (f"{'filtre':<30}{'elenen%':>8}{'TRAIN$':>9}{'dTR':>7}{'trPF':>6}{'trWR':>6}"
           f"{'trN':>6}  |{'TEST$':>8}{'dTE':>7}{'teWR':>6}{'WR':>6}{'risk%':>7}")
    print(hdr); print("-" * len(hdr))
    for h in H:
        ks = keeps_for(data, h)
        allk = np.concatenate([v for v in ks.values()])
        drop = 100.0 * (1 - allk.mean())
        m = metrics(run(data, ks))
        m["name"] = h["name"]; m["hyp"] = h; m["drop"] = drop
        rows.append(m)
        print(f"{h['name']:<30}{drop:>7.0f}%{m['train']:>9.0f}{m['train']-base['train']:>7.0f}"
              f"{m['train_pf']:>6.2f}{m['train_wr']:>6.1f}{m['train_n']:>6d}  |"
              f"{m['test']:>8.0f}{m['test']-base['test']:>7.0f}{m['test_wr']:>6.1f}"
              f"{m['wr']:>6.1f}{m['risk']:>7.2f}", flush=True)

    # ---- WR OZETI (ham hacimde DEGISMEMISTI — turevleri degistiriyor mu?)
    print(f"\n{'='*78}\nWR DEGISIMI OZETI (taban WR {base['wr']:.1f}%)")
    wrs = np.array([m["wr"] for m in rows])
    print(f"  {len(rows)} hipotez WR araligi: {wrs.min():.1f}% .. {wrs.max():.1f}%  "
          f"(ort {wrs.mean():.1f}%, taban {base['wr']:.1f}%)")
    print(f"  |dWR| > 2 puan olan hipotez sayisi: {(np.abs(wrs-base['wr'])>2).sum()}/{len(rows)}")
    ext = sorted(rows, key=lambda m: -abs(m["wr"] - base["wr"]))[:6]
    for m in ext:
        print(f"    {m['name']:<30} WR {m['wr']:.1f}% (d{m['wr']-base['wr']:+.1f}) "
              f"elenen {m['drop']:.0f}% TOPLAM ${m['usd']:+.0f}")

    # ---- TRAIN'de secim
    print(f"\n{'='*78}\nTRAIN SECIMI (kriter: TRAIN toplam$ > taban VE her iki TRAIN yili > taban)")
    cands = [m for m in rows if m["train"] > base["train"]
             and m["y2023"] > BASE_YEAR_PNL[2023] and m["y2024"] > BASE_YEAR_PNL[2024]]
    cands.sort(key=lambda m: -m["train"])
    if not cands:
        print("  TRAIN'de tabani gecen filtre YOK.")
    for m in cands:
        print(f"  {m['name']:<30} TRAIN ${m['train']:+.0f} (taban ${base['train']:+.0f}) "
              f"2023 ${m['y2023']:+.0f} 2024 ${m['y2024']:+.0f}")

    # ---- KABUL BARI
    print(f"\n{'='*78}\nKABUL BARI (TEST + her yil + permutasyon p<0.05 + plato)")
    survivors = []
    for m in cands:
        yr_ok = all(m[f"y{y}"] > BASE_YEAR_PNL[y] for y in (2023, 2024, 2025, 2026))
        test_ok = m["test"] > base["test"]
        print(f"\n  --- {m['name']}")
        print("      yil-yil: " + " ".join(
            f"{y}:${m[f'y{y}']:+.0f}({'+' if m[f'y{y}']>BASE_YEAR_PNL[y] else '-'})"
            for y in (2023, 2024, 2025, 2026)))
        print(f"      TEST ${m['test']:+.0f} vs taban ${base['test']:+.0f} -> "
              f"{'GECTI' if test_ok else 'KALDI'}")
        print(f"      WR {base['wr']:.1f}% -> {m['wr']:.1f}% | ort risk {base['risk']:.2f}% -> "
              f"{m['risk']:.2f}% (kaldirac kontrolu)")
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

    # ---- PLATO
    if survivors:
        print(f"\n{'='*78}\nPLATO KONTROLU (ayni ailenin komsu esikleri)")
        for m, p_tr, p_all in survivors:
            fam = m["hyp"]["fam"]
            sib = [x for x in rows if x["hyp"]["fam"] == fam]
            print(f"  {m['name']} ailesi ({fam}):")
            for x in sorted(sib, key=lambda z: z["hyp"]["param"]):
                print(f"    esik {x['hyp']['param']:>5}: TRAIN ${x['train']:+.0f} "
                      f"TEST ${x['test']:+.0f} TOPLAM ${x['usd']:+.0f}")
            srt = np.sort(m["pnl"])
            print(f"    kazanc yogunlugu: en iyi 30 islem ${srt[-30:].sum():+.0f} / "
                  f"toplam ${m['usd']:+.0f}")
    else:
        print(f"\n{'='*78}\nHayatta kalan aday YOK — plato kontrolu gereksiz.")

    print(f"\n{'='*78}\nOZET: {len(H)} hipotez, TRAIN'i gecen {len(cands)}, "
          f"tum bariyeri gecen {len(survivors)}.")
    rows.sort(key=lambda m: -m["usd"])
    print("\nTOPLAM$'a gore en iyi 5 (RAPOR AMACLI — secim TRAIN'den yapildi):")
    for m in rows[:5]:
        print(f"  {m['name']:<30} TOPLAM ${m['usd']:+.0f} (taban ${base['usd']:+.0f}) "
              f"TRAIN ${m['train']:+.0f} TEST ${m['test']:+.0f} n{m['n']} WR{m['wr']:.1f}%")
    print("\nTOPLAM$'a gore en KOTU 5:")
    for m in rows[-5:]:
        print(f"  {m['name']:<30} TOPLAM ${m['usd']:+.0f} (taban ${base['usd']:+.0f}) "
              f"TRAIN ${m['train']:+.0f} TEST ${m['test']:+.0f} n{m['n']} WR{m['wr']:.1f}%")


if __name__ == "__main__":
    main()
