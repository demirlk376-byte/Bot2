"""
trigger_swap_test.py — Donchian TETİKLEYİCİSİNİ başka mekanizmalarla DEĞİŞTİR (ekleme değil).

KULLANICI SORUSU: "üstüne filtre eklemek yerine, çalışan göstergenin YERİNE başkalarını dene."
BU GERÇEKTEN YENİ BİR SORU. Bugüne kadar:
  • donchian'ın ÜSTÜNE filtre eklendi        → ~230 hipotez, hepsi RET
  • donchian'ın PARAMETRELERİ tarandı        → 427 kombinasyon, RET (kanal UZUNLUĞU değişti,
                                                kanal KAVRAMI hiç değişmedi)
  • tetikleyicinin KENDİSİ hiç değiştirilmedi ← BU TEST
Üstelik donchian seçimi eski: occ hatası ve MTF lookahead düzeltilmeden önce yapılmıştı.

TASARIM — TEK DEĞİŞKEN KURALI: sadece GİRİŞ TETİKLEYİCİSİ değişir. Diğer her şey SABİT:
  aynı 7 coin · 4h · EMA200 trend kapısı · günlük-EMA20 MTF · SL 2×ATR · rr 2.5 · maxhold 30
  occ per-coin · ortak 7 koltuk (squeeze+bb tabanda) · eff = min(RISKF, CAP×sl_pct)
Böylece fark yalnızca "kırılımı nasıl tanımlıyoruz"dan gelir.

DOĞRULAMA: 'donchian_ref' tetikleyicisi elle yazıldı; DB.gen'in ürettiği taban ile BİREBİR
aynı sonucu vermeli. Vermiyorsa motor bozuktur ve tüm karşılaştırma geçersizdir.

METODOLOJİ: TRAIN(2023-24)'te seç → TEST(2025-26) BİR KEZ → HER YIL → permütasyon (aynı sayıda
RASTGELE giriş) → Šidák(mekanizma sayısı). Büyüklük eşiği %2.

Kullanım:  py trigger_swap_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, ema as ema_fn

RNG = np.random.default_rng(99)
TRAIN_END_NS = pd.Timestamp("2025-01-01", tz="UTC").value
SL_A, RR, MH = 2.0, 2.5, 30


# ── TETİKLEYİCİLER: her biri (long_sinyal, short_sinyal) boolean dizisi döndürür ──
# HEPSİ .shift(1) mantığıyla: eşik ÖNCEKİ barlardan, mevcut bar HARİÇ. Lookahead YOK.
def t_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def t_close_channel(d, n=40):
    """Kanal HIGH/LOW yerine KAPANIŞ'tan — fitil gürültüsünü dışlar."""
    hi = d["close"].rolling(n).max().shift(1).values
    lo = d["close"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def t_keltner(d, n=20, k=2.0):
    e = ema_fn(d["close"], n).shift(1).values
    a = atr_fn(d["high"], d["low"], d["close"], 14).shift(1).values
    c = d["close"].values
    return c > e + k * a, c < e - k * a


def t_bollinger(d, n=20, k=2.0):
    m = d["close"].rolling(n).mean().shift(1).values
    s = d["close"].rolling(n).std().shift(1).values
    c = d["close"].values
    return c > m + k * s, c < m - k * s


def t_supertrend(d, n=10, k=3.0):
    """Supertrend yön DÖNÜŞÜ (flip) — sadece dönüş barında sinyal."""
    a = atr_fn(d["high"], d["low"], d["close"], n).values
    hl2 = (d["high"].values + d["low"].values) / 2
    c = d["close"].values
    up = hl2 - k * a; dn = hl2 + k * a
    trend = np.ones(len(c))
    for i in range(1, len(c)):
        if not np.isfinite(a[i]): trend[i] = trend[i-1]; continue
        up[i] = max(up[i], up[i-1]) if c[i-1] > up[i-1] else up[i]
        dn[i] = min(dn[i], dn[i-1]) if c[i-1] < dn[i-1] else dn[i]
        trend[i] = 1 if c[i] > dn[i-1] else (-1 if c[i] < up[i-1] else trend[i-1])
    flip_up = (trend == 1) & (np.roll(trend, 1) == -1)
    flip_dn = (trend == -1) & (np.roll(trend, 1) == 1)
    flip_up[0] = flip_dn[0] = False
    return flip_up, flip_dn


def t_macd_zero(d):
    c = d["close"]
    macd = (ema_fn(c, 12) - ema_fn(c, 26)).values
    prev = np.roll(macd, 1); prev[0] = np.nan
    return (macd > 0) & (prev <= 0), (macd < 0) & (prev >= 0)


def t_dual_ma(d, f=20, s=50):
    a = ema_fn(d["close"], f).values; b = ema_fn(d["close"], s).values
    pa = np.roll(a, 1); pb = np.roll(b, 1); pa[0] = pb[0] = np.nan
    return (a > b) & (pa <= pb), (a < b) & (pa >= pb)


def t_regression(d, n=40, k=2.0):
    """Doğrusal regresyon kanalı: kapanış, regresyon çizgisi ± k×artık-std dışına taşarsa."""
    c = d["close"].values; N = len(c)
    up = np.zeros(N, bool); dn = np.zeros(N, bool)
    x = np.arange(n); xm = x.mean(); sxx = ((x - xm) ** 2).sum()
    for i in range(n, N):
        w = c[i - n:i]                       # mevcut bar HARİÇ
        b = ((x - xm) * (w - w.mean())).sum() / sxx
        a0 = w.mean() - b * xm
        fit = a0 + b * x
        sd = np.std(w - fit, ddof=2)
        pred = a0 + b * n                    # bir sonraki noktanın beklentisi
        if sd > 0:
            up[i] = c[i] > pred + k * sd
            dn[i] = c[i] < pred - k * sd
    return up, dn


def t_atr_breakout(d, n=20, k=0.5):
    """Önceki n-bar kapanış zirvesi + k×ATR (donchian'ın volatiliteye göre tamponlu hali)."""
    hi = d["close"].rolling(n).max().shift(1).values
    lo = d["close"].rolling(n).min().shift(1).values
    a = atr_fn(d["high"], d["low"], d["close"], 14).shift(1).values
    c = d["close"].values
    return c > hi + k * a, c < lo - k * a


TRIGGERS = {
    "donchian_ref": t_donchian, "close_channel": t_close_channel, "keltner": t_keltner,
    "bollinger": t_bollinger, "supertrend": t_supertrend, "macd_zero": t_macd_zero,
    "dual_ma": t_dual_ma, "regression": t_regression, "atr_break": t_atr_breakout,
}


def gen(m, trig, rand=False):
    """Tetikleyici DIŞINDA her şey deployed_backtest.gen ile AYNI."""
    d = fast_bt.resample(m, "4h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    ema200 = ema_fn(d["close"], 200).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up_mtf = d["close"].values > _dprev
    L, S = trig(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    if rand:                                  # aynı SAYIDA sinyal, RASTGELE barlarda
        nl, ns = int(L[260:n-1].sum()), int(S[260:n-1].sum())
        L = np.zeros(n, bool); S = np.zeros(n, bool)
        pool = RNG.permutation(np.arange(260, n - 1))
        L[pool[:nl]] = True; S[pool[nl:nl + ns]] = True
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if not np.isfinite(ema200[i]): continue
        d_ = 0
        if L[i] and cl[i] > ema200[i]: d_ = 1
        elif S[i] and cl[i] < ema200[i]: d_ = -1
        if d_ == 0: continue
        dup = bool(up_mtf[i]) if not (isinstance(up_mtf[i], float) and np.isnan(up_mtf[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * DB.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


def seat(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for ens, ex, R, sp in ev:
        while openh and openh[0][0].value <= ens: heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(openh, (ex, ctr, R)); taken.append((ens, ex, R, sp))
    return taken


def stats(taken):
    if not taken: return None
    r = np.array([t[2] for t in taken]); sp = np.array([t[3] for t in taken])
    ens = np.array([t[0] for t in taken], dtype="int64")
    ya = np.array([pd.Timestamp(t[1]).year for t in taken])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * sp) * DB.BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    tr = ens < TRAIN_END_NS
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=float(pnl.sum()),
                train=float(pnl[tr].sum()), test=float(pnl[~tr].sum()),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ms = {c: fast_bt.load(c, source=source) for c in DB.DONCH}
    others = []
    for c in DB.SQZ: others += DB.gen("squeeze", fast_bt.load(c, source=source))
    for c in DB.BB_COINS: others += DB.gen_bb(fast_bt.load(c, source=source))

    print(f"\n{'='*108}\n=== TETİKLEYİCİ DEĞİŞTİRME (ekleme değil) — diğer her şey SABİT ===")
    print(f"  {'tetikleyici':>14s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'TRAIN$':>8s} {'TEST$':>8s} "
          f"{'toplam$':>9s}  yıl-yıl                                  ")
    res = {}
    for name, fn in TRIGGERS.items():
        tr = []
        for c in DB.DONCH: tr += gen(ms[c], fn)
        s = stats(seat(tr + others))
        if s is None: continue
        res[name] = s
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        print(f"  {name:>14s} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['train']:>+8.0f} "
              f"{s['test']:>+8.0f} {s['tot']:>+9.0f}  {ys}")

    ref = res.get("donchian_ref")
    print(f"\n  --- MOTOR DOĞRULAMASI ---")
    print(f"  donchian_ref: n={ref['n']} ${ref['tot']:+.0f} | deployed_backtest ANKOR: n=1579 $+1421")
    ok_engine = abs(ref["tot"] - 1421) < 25 and abs(ref["n"] - 1579) < 30
    print(f"  {'✓ motor tutuyor, karşılaştırma GEÇERLİ' if ok_engine else '✗ MOTOR TUTMUYOR — sonuçlar GEÇERSİZ'}")
    if not ok_engine:
        print(f"  (elle yazılan donchian tetikleyicisi DonchianStrategy ile birebir değil; önce bu düzeltilmeli)")
        return

    # TRAIN'den seç
    alts = {k: v for k, v in res.items() if k != "donchian_ref"}
    best = max(alts, key=lambda k: alts[k]["train"])
    b = alts[best]
    print(f"\n  ★ TRAIN ARGMAX (donchian hariç): {best}  TRAIN ${b['train']:+.0f} "
          f"(referans ${ref['train']:+.0f})")
    if b["train"] <= ref["train"]:
        print(f"  → TRAIN'de bile donchian'ı geçen alternatif YOK. TEST açmaya gerek yok. RET.")
    else:
        dy = {y: b["yrs"].get(y, 0) - ref["yrs"].get(y, 0) for y in ref["yrs"]}
        dte = b["test"] - ref["test"]
        print(f"  >>> TEST: ${b['test']:+.0f} vs referans ${ref['test']:+.0f} → Δ${dte:+.0f}")
        print(f"      yıl-yıl Δ " + " ".join(f"{y}:{v:+.0f}" for y, v in dy.items()))
        ok = dte > 0 and all(v > 0 for v in dy.values()) and dte > 0.02 * ref["test"]
        print(f"      {'★ KABUL adayı → permütasyona gidiyor' if ok else 'RET (TEST ya da yıl-yıl ya da büyüklük)'}")

    print(f"\n  --- PERMÜTASYON: tetikleyici ZAMANLAMASI mı, yoksa sadece EMA200+MTF kapısı mı? ---")
    print(f"  (aynı SAYIDA sinyal, RASTGELE barlarda; EMA200/MTF/çıkış makinesi AYNI kalır)")
    for name in ("donchian_ref", best):
        sims = []
        for _ in range(60):
            tr = []
            for c in DB.DONCH: tr += gen(ms[c], TRIGGERS[name], rand=True)
            q = stats(seat(tr + others))
            if q: sims.append(q["tot"])
        sims = np.array(sims); obs = res[name]["tot"]
        p = ((sims >= obs).sum() + 1) / (len(sims) + 1)
        print(f"  {name:>14s}: rastgele ort ${sims.mean():+.0f} sd ${sims.std():.0f} | "
              f"gerçek ${obs:+.0f} → z={(obs-sims.mean())/max(sims.std(),1e-9):+.2f} p={p:.3f}")
    print(f"\n  YORUM: donchian_ref permütasyonu ANLAMLI DEĞİLSE, donchian'ın kendisi de")
    print(f"  zamanlamadan değil EMA200+MTF kapısından kazanıyor demektir — bu, tetikleyici")
    print(f"  değiştirmenin neden fark yaratmadığını açıklar ve ÇOK ÖNEMLİ bir bulgudur.")


if __name__ == "__main__":
    main()
