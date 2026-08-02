"""
trendquality_filters.py — GÖREV A: YOL-VERİMLİLİĞİ (path-efficiency) tabanlı
trend-kalitesi göstergeleri DONCHIAN kolunda giriş filtresi olarak.

Test edilen (hepsi burada sıfırdan, pencere-yerel, lookahead YOK):
  1. Kaufman Efficiency Ratio (ER)  N∈{10,20,40}  eşik∈{0.2,0.3,0.4,0.5}
  2. Choppiness Index (CI)          N∈{14,28}     eşik∈{38.2,50,61.8}
  3. Vertical Horizontal Filter     N∈{14,28}     eşik∈{0.2,0.3,0.35,0.4}
  4. Hurst üssü (basit R/S)         N∈{50,100}    eşik∈{0.45,0.5,0.55,0.6}
Her biri hem ">" hem "<" yönünde → toplam 68 hipotez.

METODOLOJİ (görev şartnamesi):
  · occ = j, coin başına tek pozisyon (deployed_backtest.gen ile birebir)
  · FİLTRE SİNYAL ANINDA uygulanır; elenen sinyal occ'u İLERLETMEZ
  · koltuk seçimi giriş zamanına göre MAXPOS=7 ortak havuz (DB.seat_select aynen)
  · eff = min(RISKF, CAP*sl_pct)
  · squeeze + BB kolları TABANDA SABİT (tek değişken kuralı)
  · SEÇİM YALNIZ TRAIN'den (çıkış yılı 2023-2024). TEST (2025+) seçimde açılmaz.
  · aday → permütasyon testi (1000 tur) + komşu eşik platosu + kaldıraç kontrolü

pandas 3 NOTU: idx[i].value NANOsaniye verir (dtype datetime64[us] olsa bile).
DB.seat_select aynen kullanılıyor → birim karışması yok; ayrıca assert ile teyit.

Kullanım:  python trendquality_filters.py
"""
from __future__ import annotations
import os, sys, pickle, time
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn
from strategies.donchian import DonchianStrategy

BAL0, FEE, RISKF, CAP, MAXPOS = DB.BAL0, DB.FEE, DB.RISKF, DB.CAP, DB.MAXPOS
CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/tq_cache.pkl"
RNG_SEED = 20260802
N_PERM = 2000

TRAIN_YEARS = (2023, 2024)
TEST_YEARS = (2025, 2026)


# ────────────────────────────────────────────────────────────────────────────
# 1) TREND-KALİTESİ GÖSTERGELERİ — hepsi SON N+1 BARIN SAF FONKSİYONU
#    (yol-bağımlı ewm YOK → tam-seri rolling == pencere-yerel; aşağıda kanıtlanıyor)
# ────────────────────────────────────────────────────────────────────────────
def calc_er(close: pd.Series, N: int) -> pd.Series:
    """Kaufman Efficiency Ratio = |c[t]-c[t-N]| / Σ|c[i]-c[i-1]| (son N bar)."""
    num = (close - close.shift(N)).abs()
    den = close.diff().abs().rolling(N).sum()
    return num / den.where(den > 0)


def _true_range(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def calc_chop(h, l, c, N: int) -> pd.Series:
    """Choppiness = 100*log10(ΣTR(N) / (maxHigh(N)-minLow(N))) / log10(N)."""
    s = _true_range(h, l, c).rolling(N).sum()
    rng = h.rolling(N).max() - l.rolling(N).min()
    return 100.0 * np.log10(s / rng.where(rng > 0)) / np.log10(N)


def calc_vhf(close: pd.Series, N: int) -> pd.Series:
    """VHF = (maxClose(N)-minClose(N)) / Σ|c[i]-c[i-1]| (son N bar)."""
    den = close.diff().abs().rolling(N).sum()
    return (close.rolling(N).max() - close.rolling(N).min()) / den.where(den > 0)


def _rs_hurst(w: np.ndarray) -> float:
    """Basit R/S: log-getirilerin ortalama-düzeltilmiş kümülatif sapma aralığı / std."""
    m = w.mean()
    dev = np.cumsum(w - m)
    R = dev.max() - dev.min()
    S = w.std(ddof=1)
    if not np.isfinite(R) or not np.isfinite(S) or S <= 0 or R <= 0:
        return np.nan
    return float(np.log(R / S) / np.log(len(w)))


def calc_hurst(close: pd.Series, N: int) -> pd.Series:
    lr = np.log(close).diff()
    return lr.rolling(N).apply(_rs_hurst, raw=True)


def indicator_panel(d: pd.DataFrame) -> dict:
    """Tüm gösterge serilerini tek seferde (tam-seri form) üret."""
    h, l, c = d["high"], d["low"], d["close"]
    P = {}
    for N in (10, 20, 40):
        P[f"ER{N}"] = calc_er(c, N).values
    for N in (14, 28):
        P[f"CHOP{N}"] = calc_chop(h, l, c, N).values
        P[f"VHF{N}"] = calc_vhf(c, N).values
    for N in (50, 100):
        P[f"HURST{N}"] = calc_hurst(c, N).values
    return P


def _panel_window_local(sub: pd.DataFrame) -> dict:
    """Aynı göstergeler, YALNIZ verilen pencereden (canlı get_candles ile aynı görüş)."""
    h, l, c = sub["high"], sub["low"], sub["close"]
    P = {}
    for N in (10, 20, 40):
        P[f"ER{N}"] = float(calc_er(c, N).iloc[-1])
    for N in (14, 28):
        P[f"CHOP{N}"] = float(calc_chop(h, l, c, N).iloc[-1])
        P[f"VHF{N}"] = float(calc_vhf(c, N).iloc[-1])
    for N in (50, 100):
        P[f"HURST{N}"] = float(calc_hurst(c, N).iloc[-1])
    return P


# ────────────────────────────────────────────────────────────────────────────
# 2) DONCHIAN HAM ADAY SİNYALLERİ (occ UYGULANMADAN)
#    DB.gen ile birebir: analyze occ kontrolünden ÖNCE çağrılıyor, MTF kapısı
#    occ'u ilerletmiyor → occ'suz üretip sonradan replay etmek MATEMATİKSEL DENK.
# ────────────────────────────────────────────────────────────────────────────
def donch_candidates(m: pd.DataFrame):
    tf, win, sl_a, rr, mh = DB.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    P = indicator_panel(d)
    keys = sorted(P.keys())
    cands = []          # (i, j, entry_ns, exit_ts, R, slp)
    ivals = []          # gösterge değerleri (aday sırasıyla)
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp_ = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        cands.append((i, j, idx[i].value, idx[j], R, sld / e))
        ivals.append([P[k][i] for k in keys])
    return cands, np.array(ivals, float), keys, d


def replay(cands, mask):
    """occ replay: elenen sinyal occ'u İLERLETMEZ."""
    occ = -1; out = []
    for k in range(len(cands)):
        i, j, ens, ex, R, slp = cands[k]
        if i <= occ: continue
        if not mask[k]: continue
        out.append((ens, ex, R, slp)); occ = j
    return out


# ────────────────────────────────────────────────────────────────────────────
# 3) METRİKLER
# ────────────────────────────────────────────────────────────────────────────
def metrics(taken):
    if not taken:
        return None
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    exits = pd.DatetimeIndex([t[0] for t in taken])
    eff = np.minimum(RISKF, CAP * slp)
    pnl = r * eff * BAL0
    yr = exits.year.values
    out = {"n": len(r), "pnl": pnl.sum(), "wr": (r > 0).mean() * 100,
           "avg_risk": eff.mean() * 100, "r": r, "pnl_arr": pnl, "yr": yr}
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    out["pf"] = gp / gl if gl > 0 else np.inf
    for y in (2023, 2024, 2025, 2026):
        msk = yr == y
        out[f"y{y}"] = pnl[msk].sum()
        out[f"n{y}"] = int(msk.sum())
    out["train"] = pnl[np.isin(yr, TRAIN_YEARS)].sum()
    out["test"] = pnl[np.isin(yr, TEST_YEARS)].sum()
    return out


def run_config(DC, fixed, mask_fn):
    """mask_fn(coin, ivals) -> bool mask. None => filtresiz.
    DİKKAT: seat_select'in sort'u STABİL → aynı entry_ns'li işlemlerde sıralama
    koltuk seçimini değiştirir. DB.main'in ekleme sırası (DONCH → SQZ → BB) BİREBİR
    korunmalı; sq/bb'yi öne almak tabanı $1421 yerine $1418 gösteriyordu."""
    trades = []
    for coin in DB.DONCH:
        cands, ivals, _k = DC[coin]
        mask = np.ones(len(cands), bool) if mask_fn is None else mask_fn(coin, ivals)
        trades += replay(cands, mask)
    trades += fixed
    return metrics(DB.seat_select(trades))


# ────────────────────────────────────────────────────────────────────────────
# 4) ANA AKIŞ
# ────────────────────────────────────────────────────────────────────────────
def build():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    DC = {}; keys = None; dsample = None
    for c in DB.DONCH:
        m = fast_bt.load(c, source="local")
        cd, iv, keys, d = donch_candidates(m)
        DC[c] = (cd, iv, keys)
        if dsample is None: dsample = (c, d)
        print(f"  donchian {c}: {len(cd)} ham aday sinyal", flush=True)
    fixed = []
    for c in DB.SQZ:
        fixed += [(t[0], t[1], t[2], t[3]) for t in DB.gen("squeeze", fast_bt.load(c, source="local"))]
        print(f"  squeeze {c}: ok", flush=True)
    for c in DB.BB_COINS:
        fixed += [(t[0], t[1], t[2], t[3]) for t in DB.gen_bb(fast_bt.load(c, source="local"))]
        print(f"  bb {c}: ok", flush=True)
    obj = (DC, fixed, keys, dsample)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(obj, f)
    return obj


def verify_window_local(d, keys, n_check=25):
    """tam-seri rolling == pencere-yerel (canlı 260-bar penceresi) KANITI."""
    P = indicator_panel(d)
    rs = np.random.RandomState(7)
    idxs = rs.choice(np.arange(300, len(d) - 2), n_check, replace=False)
    worst = 0.0
    for i in idxs:
        sub = d.iloc[max(0, i - 259):i + 1]
        pw = _panel_window_local(sub)
        for k in keys:
            a, b = P[k][i], pw[k]
            if np.isnan(a) and np.isnan(b): continue
            worst = max(worst, abs(a - b) / max(abs(a), 1e-12))
    return worst


def main():
    t0 = time.time()
    print("=== TREND-KALİTESİ FİLTRELERİ (Görev A) ===\n")
    DC, fixed, keys, dsample = build()

    # --- birim (pandas 3) teyidi -------------------------------------------
    any_c = DC[DB.DONCH[0]][0][0]
    assert isinstance(any_c[2], (int, np.integer)) and any_c[2] > 1_600_000_000_000_000_000, \
        "entry_ns NANOsaniye değil — pandas 3 birim tuzağı!"
    assert pd.Timestamp(any_c[3]).value > 1_600_000_000_000_000_000, "exit_ts.value NANOsaniye değil!"
    print(f"birim teyidi OK: entry_ns ve exit_ts.value ikisi de nanosaniye "
          f"({any_c[2]} / {pd.Timestamp(any_c[3]).value})")

    # --- lookahead / pencere-yerellik teyidi -------------------------------
    w = verify_window_local(dsample[1], keys)
    print(f"pencere-yerellik teyidi ({dsample[0]}): tam-seri vs 260-bar pencere "
          f"max göreli fark = {w:.2e}  → {'AYNI (lookahead yok)' if w < 1e-9 else 'FARKLI!'}")
    assert w < 1e-9

    # --- TABAN DOĞRULAMA ---------------------------------------------------
    base = run_config(DC, fixed, None)
    print(f"\n--- TABAN (filtresiz, canlı config) ---")
    print(f"  n={base['n']} PF {base['pf']:.2f} WR {base['wr']:.0f}% ${base['pnl']:+.0f} "
          f"| ort risk {base['avg_risk']:.2f}%")
    print(f"  2023 ${base['y2023']:+.0f} | 2024 ${base['y2024']:+.0f} | "
          f"2025 ${base['y2025']:+.0f} | 2026 ${base['y2026']:+.0f}")
    print(f"  TRAIN(23-24) ${base['train']:+.0f}   TEST(25-26) ${base['test']:+.0f}")
    ok = (base["n"] == 1579 and abs(base["pnl"] - 1421) < 2 and abs(base["pf"] - 1.45) < 0.01
          and abs(base["y2023"] - 321) < 2 and abs(base["y2024"] - 457) < 2
          and abs(base["y2025"] - 447) < 2 and abs(base["y2026"] - 195) < 2
          and abs(base["avg_risk"] - 2.13) < 0.02)
    print(f"  TABAN DOĞRULAMA: {'✓ GEÇTİ' if ok else '✗ TUTMADI — DUR'}")
    if not ok:
        sys.exit("TABAN TUTMADI")

    # --- gösterge dağılımları ----------------------------------------------
    allv = np.vstack([DC[c][1] for c in DB.DONCH])
    print("\n--- sinyal anındaki gösterge dağılımları (tüm donchian adayları) ---")
    for gi, k in enumerate(keys):
        v = allv[:, gi]; v = v[np.isfinite(v)]
        print(f"  {k:9s} n={len(v):5d}  p10 {np.percentile(v,10):6.3f} "
              f"med {np.percentile(v,50):6.3f} p90 {np.percentile(v,90):6.3f}")

    # --- HİPOTEZ IZGARASI ---------------------------------------------------
    GRID = []
    for N in (10, 20, 40):
        for th in (0.2, 0.3, 0.4, 0.5):
            GRID += [(f"ER{N}", th, ">"), (f"ER{N}", th, "<")]
    for N in (14, 28):
        for th in (38.2, 50.0, 61.8):
            GRID += [(f"CHOP{N}", th, ">"), (f"CHOP{N}", th, "<")]
        for th in (0.2, 0.3, 0.35, 0.4):
            GRID += [(f"VHF{N}", th, ">"), (f"VHF{N}", th, "<")]
    for N in (50, 100):
        for th in (0.45, 0.5, 0.55, 0.6):
            GRID += [(f"HURST{N}", th, ">"), (f"HURST{N}", th, "<")]
    kpos = {k: i for i, k in enumerate(keys)}
    print(f"\n=== {len(GRID)} HİPOTEZ (gösterge x eşik x yön) — TRAIN'de taranıyor ===")

    def mk(key, th, op):
        gi = kpos[key]
        def f(coin, ivals):
            v = ivals[:, gi]
            # NaN (gösterge hazır değil) → sinyali ELEME (taban davranışı korunur)
            if op == ">": return ~np.isfinite(v) | (v > th)
            return ~np.isfinite(v) | (v < th)
        return f

    rows = []
    for (key, th, op) in GRID:
        r = run_config(DC, fixed, mk(key, th, op))
        if r is None: continue
        kept = np.mean(np.concatenate(
            [(lambda v: (v > th) | ~np.isfinite(v))(DC[c][1][:, kpos[key]]) if op == ">"
             else (lambda v: (v < th) | ~np.isfinite(v))(DC[c][1][:, kpos[key]]) for c in DB.DONCH]))
        rows.append(dict(key=key, th=th, op=op, keep=kept * 100, **{
            kk: r[kk] for kk in ("n", "pf", "wr", "pnl", "avg_risk", "train", "test",
                                 "y2023", "y2024", "y2025", "y2026")}))
    R = pd.DataFrame(rows).sort_values("train", ascending=False)

    print(f"\n--- TRAIN sıralaması (TEST GİZLİ tutuldu; sadece seçim için) ---")
    print(f"  taban TRAIN ${base['train']:+.0f}")
    hdr = f"  {'filtre':22s} {'tut%':>5s} {'n':>5s} {'TRAIN$':>8s} {'ΔTRAIN':>8s} {'risk%':>6s}"
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for _, x in R.iterrows():
        print(f"  {x['key']+' '+x['op']+str(x['th']):22s} {x['keep']:5.0f} {x['n']:5.0f} "
              f"{x['train']:+8.0f} {x['train']-base['train']:+8.0f} {x['avg_risk']:6.2f}")

    # --- TRAIN eleği: taban TRAIN'i geçenler --------------------------------
    surv = R[R["train"] > base["train"]]
    print(f"\n=== TRAIN elemesi: {len(surv)}/{len(R)} hipotez taban TRAIN'i geçti ===")

    if len(surv) == 0:
        print("  ADAY YOK — hiçbiri TRAIN'de tabanı geçmedi. Görev burada biter.")
        print(f"\nsüre {time.time()-t0:.0f}s")
        return R, base, None

    # --- ŞİMDİ TEST AÇILIYOR (seçimden SONRA) -------------------------------
    print(f"\n=== TEST AÇILIYOR (seçim bitti) — taban TEST ${base['test']:+.0f} ===")
    hdr2 = (f"  {'filtre':22s} {'TRAIN$':>8s} {'TEST$':>8s} {'2023':>7s} {'2024':>7s} "
            f"{'2025':>7s} {'2026':>7s} {'4/4?':>5s} {'risk%':>6s}")
    print(hdr2); print("  " + "-" * (len(hdr2) - 2))
    finals = []
    for _, x in surv.iterrows():
        allyr = all(x[f"y{y}"] > base[f"y{y}"] for y in (2023, 2024, 2025, 2026))
        tst = x["test"] > base["test"]
        print(f"  {x['key']+' '+x['op']+str(x['th']):22s} {x['train']:+8.0f} {x['test']:+8.0f} "
              f"{x['y2023']:+7.0f} {x['y2024']:+7.0f} {x['y2025']:+7.0f} {x['y2026']:+7.0f} "
              f"{('EVET' if allyr else 'hayir'):>5s} {x['avg_risk']:6.2f}")
        if tst and allyr:
            finals.append(x)

    print(f"\n=== TEST + HER-YIL kapısı: {len(finals)} aday kaldı ===")
    if not finals:
        print("  ADAY YOK — TRAIN'de iyi görünenler TEST'te ve/veya yıl-yıl çöktü.")

    # --- NEGATİF SONUCU BELGELEMEK İÇİN: en yakın kaçanlarda da tam denetim ---
    probe = [x for _, x in surv.iterrows() if x["test"] > base["test"]]
    if not probe:
        probe = [surv.iloc[0]]
    print(f"\n{'='*78}\n=== TAM DENETİM (kabul barını geçmeseler de en yakın {len(probe)} "
          f"hipotez için permütasyon + plato + yoğunlaşma) ===")
    for x in probe:
        print(f"\n--- {x['key']} {x['op']} {x['th']}  "
              f"(TRAIN Δ{x['train']-base['train']:+.0f}, TEST Δ{x['test']-base['test']:+.0f}) ---")
        permutation_test(DC, fixed, base, x, kpos)
        plateau(R, base, x)
        concentration(DC, fixed, base, x, kpos)

    addendum(DC, fixed, base, keys)
    print(f"\nsüre {time.time()-t0:.0f}s")
    return R, base, finals


def addendum(DC, fixed, base, keys):
    """POST-HOC (ızgara başarısız olduktan SONRA bakıldı — seçim için KULLANILAMAZ).
    Eşik ızgarası 'toplam $' bariyerinde çöktü. Ayrı ve DAHA ZAYIF bir soru: göstergeler
    işlem-başına R ile hiç ilişkili mi? Bu, para kazandırmaktan FARKLI bir iddiadır."""
    kpos = {k: i for i, k in enumerate(keys)}
    iv = np.vstack([DC[c][1] for c in DB.DONCH])
    R = np.concatenate([[t[4] for t in DC[c][0]] for c in DB.DONCH])
    yr = np.concatenate([[pd.Timestamp(t[3]).year for t in DC[c][0]] for c in DB.DONCH])
    tr = np.isin(yr, TRAIN_YEARS)

    def sp(a, b):
        ra = pd.Series(a).rank().values; rb = pd.Series(b).rank().values
        return float(np.corrcoef(ra, rb)[0, 1])

    print(f"\n{'='*78}\n=== EK (POST-HOC, seçimde kullanılmadı): sinyal-düzeyi Spearman(gösterge, R) ===")
    print(f"  ham donchian aday sinyali: {len(R)} (occ/koltuk YOK) | ort {R.mean():+.3f}R  "
          f"TRAIN {R[tr].mean():+.3f}R  TEST {R[~tr].mean():+.3f}R")
    rs = np.random.RandomState(1)
    for k in keys:
        v = iv[:, kpos[k]]; m = np.isfinite(v)
        parts = []
        for nm, msk in (("ALL", m), ("TRAIN", m & tr), ("TEST", m & ~tr)):
            x_, y_ = v[msk], R[msk]; rho = sp(x_, y_)
            perm = np.array([sp(x_, rs.permutation(y_)) for _ in range(2000)])
            p = (np.sum(np.abs(perm) >= abs(rho)) + 1) / 2001
            parts.append(f"{nm} rho{rho:+.3f} p={p:.3f}")
        print(f"  {k:9s} " + " | ".join(parts))

    print("\n  göstergeler ARASI Spearman (tutarlılık denetimi):")
    for a, b in (("HURST50", "ER40"), ("HURST50", "ER20"), ("HURST50", "VHF28"),
                 ("HURST50", "CHOP28"), ("HURST50", "HURST100"), ("ER40", "VHF28")):
        x_, y_ = iv[:, kpos[a]], iv[:, kpos[b]]; m = np.isfinite(x_) & np.isfinite(y_)
        print(f"    {a:9s} vs {b:9s} rho={sp(x_[m], y_[m]):+.3f}")

    print(f"\n  --- HURST parasallaşıyor mu? (avgR/PF artıyor ama n ÇÖKÜYOR) ---")
    print(f"  taban: n{base['n']} avgR {base['r'].mean():+.3f} PF {base['pf']:.2f} "
          f"TRAIN ${base['train']:+.0f} TEST ${base['test']:+.0f} risk {base['avg_risk']:.2f}%")
    print(f"  {'filtre':16s} {'tut%':>5s} {'n':>5s} {'avgR':>6s} {'PF':>5s} {'TRAIN$':>8s} "
          f"{'TEST$':>7s} {'2023':>6s} {'2024':>6s} {'2025':>6s} {'2026':>6s} {'risk%':>6s}")
    for key in ("HURST50", "HURST100"):
        for th in (0.40, 0.45, 0.50, 0.52, 0.55, 0.60):
            gi = kpos[key]
            def mf(c, ivv, _g=gi, _t=th):
                v = ivv[:, _g]; return (v > _t) | ~np.isfinite(v)
            r = run_config(DC, fixed, mf)
            keep = np.mean(np.concatenate(
                [(DC[c][1][:, gi] > th) | ~np.isfinite(DC[c][1][:, gi]) for c in DB.DONCH]))
            print(f"  {key+' >'+str(th):16s} {keep*100:5.0f} {r['n']:5d} {r['r'].mean():+6.3f} "
                  f"{r['pf']:5.2f} {r['train']:+8.0f} {r['test']:+7.0f} {r['y2023']:+6.0f} "
                  f"{r['y2024']:+6.0f} {r['y2025']:+6.0f} {r['y2026']:+6.0f} {r['avg_risk']:6.2f}")
    print("  SONUÇ: HURST işlem-başına kaliteyi yükseltiyor (avgR .237→.303, PF 1.45→1.59)")
    print("         ama işlem sayısını 1579→995'e düşürdüğü için TOPLAM $ HER eşikte ve HER")
    print("         yılda tabanın ALTINDA. Kabul barı (toplam $) karşılanmıyor. Ayrıca ort risk")
    print("         2.13→2.06 düşüyor: PF artışının bir kısmı kaldıraç düşüşünün yan etkisi.")


def concentration(DC, fixed, base, x, kpos):
    """(e) Kazanç kaç işleme dayanıyor? Filtreli ve tabansız işlem kümelerinin farkı."""
    gi = kpos[x["key"]]; th = x["th"]; op = x["op"]
    def mf(coin, ivals, _gi=gi):
        v = ivals[:, _gi]
        return (((v > th) if op == ">" else (v < th)) | ~np.isfinite(v))
    tk_f = DB.seat_select(sum([replay(DC[c][0], mf(c, DC[c][1])) for c in DB.DONCH], []) + fixed)
    tk_b = DB.seat_select(sum([replay(DC[c][0], np.ones(len(DC[c][0]), bool)) for c in DB.DONCH], []) + fixed)
    kf = {(pd.Timestamp(t[0]).value, float(t[1])) for t in tk_f}
    kb = {(pd.Timestamp(t[0]).value, float(t[1])) for t in tk_b}
    only_f = [t for t in tk_f if (pd.Timestamp(t[0]).value, float(t[1])) not in kb]
    only_b = [t for t in tk_b if (pd.Timestamp(t[0]).value, float(t[1])) not in kf]
    pf_ = sum(t[1] * min(RISKF, CAP * t[2]) * BAL0 for t in only_f)
    pb_ = sum(t[1] * min(RISKF, CAP * t[2]) * BAL0 for t in only_b)
    delta = x["pnl"] - base["pnl"]
    contrib = sorted([t[1] * min(RISKF, CAP * t[2]) * BAL0 for t in only_f] +
                     [-t[1] * min(RISKF, CAP * t[2]) * BAL0 for t in only_b], reverse=True)
    c = np.array(contrib)
    need = 0; s = 0.0
    for v in c:
        s += v; need += 1
        if s >= 0.5 * max(delta, 1e-9): break
    print(f"  yoğunlaşma: taban ile FARKLI işlem sayısı = {len(only_f)} eklenen / "
          f"{len(only_b)} çıkarılan (toplam Δ${delta:+.0f})")
    print(f"    Δ'nın %50'si {need} işlemden geliyor "
          f"{'⚠ <30 İŞLEM — ÖRNEKLEM GÜRÜLTÜSÜ' if need < 30 else ''}")


def permutation_test(DC, fixed, base, x, kpos):
    """Filtre etiketlerini coin-içi rastgele karıştır (aynı sayıda sinyal elensin,
    ama RASTGELE seçilsin). Gerçekleşen delta'nın p-değeri."""
    gi = kpos[x["key"]]; th = x["th"]; op = x["op"]
    masks = {}
    for c in DB.DONCH:
        v = DC[c][1][:, gi]
        masks[c] = ((v > th) if op == ">" else (v < th)) | ~np.isfinite(v)
    rs = np.random.RandomState(RNG_SEED)
    real = {p: x[p] - base[p] for p in ("pnl", "train", "test")}
    cnt = {p: 0 for p in real}; dist = {p: [] for p in real}
    for _ in range(N_PERM):
        def mf(coin, ivals, _m=masks, _rs=rs):
            mm = _m[coin].copy(); _rs.shuffle(mm); return mm
        r = run_config(DC, fixed, mf)
        for p in real:
            dlt = r[p] - base[p]
            dist[p].append(dlt)
            if dlt >= real[p]: cnt[p] += 1
    for p in ("train", "test", "pnl"):
        dd = np.array(dist[p]); pv = (cnt[p] + 1) / (N_PERM + 1)
        print(f"  permütasyon {p:5s}: gerçek Δ${real[p]:+.0f} | rastgele ort Δ${dd.mean():+.0f} "
              f"sd ${dd.std():.0f} | p={pv:.4f} {'✓' if pv < 0.05 else '✗ RET'}")


def plateau(R, base, x):
    sub = R[(R["key"] == x["key"]) & (R["op"] == x["op"])].sort_values("th")
    print(f"  plato ({x['key']} {x['op']}, komşu eşikler):")
    for _, y in sub.iterrows():
        mark = "  <== aday" if y["th"] == x["th"] else ""
        print(f"    th={y['th']:<6} TRAIN {y['train']:+7.0f} (Δ{y['train']-base['train']:+6.0f}) "
              f"TEST {y['test']:+7.0f} (Δ{y['test']-base['test']:+6.0f}){mark}")


if __name__ == "__main__":
    main()
