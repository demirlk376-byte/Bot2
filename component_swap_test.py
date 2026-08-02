"""
component_swap_test.py — Sistemin DİĞER parçalarını da YERİNE koyarak değiştir.

BAĞLAM: trigger_swap_test tetikleyiciyi değiştirdi (donchian → bollinger/keltner/supertrend/...).
Sonuç: kanal ailesi $1256-1577, MA-kesişim ailesi $642-726 → aile önemli, üye değil.
AMA o testte DİĞER HER ŞEY SABİTTİ. Hiç sorgulanmayan üç parça kaldı:
  1. TREND KAPISI  — hep EMA200 (long için close>EMA200). Neden 200? Neden EMA? Neden bu kapı?
  2. STOP TANIMI   — hep 2×ATR. Neden ATR? Neden 2?
  3. HEDEF TANIMI  — hep rr×SL (sabit oran). Neden SL'e bağlı? Neden sabit?
Bu üçü de "üstüne ekleme" değil "YERİNE koyma" sorusu ve hiç test edilmedi.

TEK DEĞİŞKEN KURALI: her seferinde SADECE bir parça değişir, diğer ikisi TABANDA kalır.
Tetikleyici hep donchian(40). Aynı 7 coin · 4h · MTF · mh30 · occ · ortak 7 koltuk
(squeeze+bb tabanda) · eff = min(RISKF, CAP×sl_pct).

METODOLOJİ: TRAIN(2023-24)'te seç → TEST BİR KEZ → HER YIL → büyüklük eşiği %2.
Not: bu turda 3 aile × ~5 varyant = ~15 hipotez; çoklu-test yükü düşük ama sıfır değil.

Kullanım:  py component_swap_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, ema as ema_fn, adx as adx_fn

TRAIN_END_NS = pd.Timestamp("2025-01-01", tz="UTC").value
MH = 30


# ── 1) TREND KAPILARI: (long_izin, short_izin) boolean dizileri ──
def tr_ema200(d):
    e = ema_fn(d["close"], 200).values; c = d["close"].values
    return c > e, c < e


def tr_ema100(d):
    e = ema_fn(d["close"], 100).values; c = d["close"].values
    return c > e, c < e


def tr_sma200(d):
    e = d["close"].rolling(200).mean().values; c = d["close"].values
    return c > e, c < e


def tr_slope(d, n=100):
    """200 yerine: son n barın regresyon EĞİMİ pozitif mi? (seviye değil YÖN)"""
    c = d["close"].values; N = len(c); s = np.full(N, np.nan)
    x = np.arange(n); xm = x.mean(); sxx = ((x - xm) ** 2).sum()
    for i in range(n, N):
        w = c[i - n:i]                      # mevcut bar HARİÇ
        s[i] = ((x - xm) * (w - w.mean())).sum() / sxx
    return s > 0, s < 0


def tr_ema_stack(d):
    """EMA50 > EMA200 (klasik 'golden' dizilim) — seviye değil SIRALAMA."""
    f = ema_fn(d["close"], 50).values; s = ema_fn(d["close"], 200).values
    return f > s, f < s


def tr_none(d):
    n = len(d)
    return np.ones(n, bool), np.ones(n, bool)


TRENDS = {"ema200(taban)": tr_ema200, "ema100": tr_ema100, "sma200": tr_sma200,
          "regresyon_eğimi": tr_slope, "ema50>ema200": tr_ema_stack, "KAPI YOK": tr_none}


# ── 2) STOP TANIMLARI: (sl_mesafesi dizisi) ──
def sl_atr2(d, a):
    return 2.0 * a


def sl_atr3(d, a):
    return 3.0 * a


def sl_swing(d, a, n=10):
    """Son n barın en düşüğü/yükseği (yapısal stop) — yöne göre seçilir, gen içinde ele alınır."""
    return None       # özel işaret


def sl_pct(d, a, p=0.04):
    return p * d["close"].values


def sl_keltner(d, a, k=2.0):
    """EMA20'den k×ATR uzaklık — girişin kendisine değil ORTALAMAYA çapalı."""
    e = ema_fn(d["close"], 20).values
    return np.abs(d["close"].values - e) + k * a


STOPS = {"2×ATR(taban)": sl_atr2, "3×ATR": sl_atr3, "swing10": sl_swing,
         "%4 sabit": sl_pct, "keltner": sl_keltner}


def gen(m, trend_fn=tr_ema200, stop_fn=sl_atr2, rr=2.5, tgt="rr"):
    d = fast_bt.resample(m, "4h")
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up_mtf = d["close"].values > _dprev
    ch_hi = d["high"].rolling(40).max().shift(1).values
    ch_lo = d["low"].rolling(40).min().shift(1).values
    sw_lo = d["low"].rolling(10).min().shift(1).values
    sw_hi = d["high"].rolling(10).max().shift(1).values
    tl, ts = trend_fn(d)
    sl_arr = None if stop_fn is sl_swing else stop_fn(d, a_ser)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl); out = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        c = cl[i]
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i])): continue
        d_ = 0
        if c > ch_hi[i] and tl[i]: d_ = 1
        elif c < ch_lo[i] and ts[i]: d_ = -1
        if d_ == 0: continue
        dup = bool(up_mtf[i]) if not (isinstance(up_mtf[i], float) and np.isnan(up_mtf[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        # stop mesafesi
        if sl_arr is None:
            ref = sw_lo[i] if d_ == 1 else sw_hi[i]
            if not np.isfinite(ref): continue
            sld = abs(c - ref)
        else:
            sld = sl_arr[i]
        if not np.isfinite(sld) or sld <= 0: continue
        e = c; slp = e - d_ * sld
        # hedef
        # HEDEF: taban rr*SL = 2.5*2ATR = 5*ATR. Anlamlı alternatifler SL'e ORANTILI OLMAYANLAR.
        if tgt == "rr": tp = e + d_ * rr * sld
        elif tgt == "atr3": tp = e + d_ * 3.0 * a          # SL'den bağımsız, DAR
        elif tgt == "atr8": tp = e + d_ * 8.0 * a          # SL'den bağımsız, GENİŞ
        elif tgt == "mm1":                                  # ölçülmüş hareket: kanal genişliği
            w = ch_hi[i] - ch_lo[i]
            tp = e + d_ * w if np.isfinite(w) and w > 0 else e + d_ * rr * sld
        elif tgt == "mm05":                                 # yarım kanal genişliği
            w = ch_hi[i] - ch_lo[i]
            tp = e + d_ * 0.5 * w if np.isfinite(w) and w > 0 else e + d_ * rr * sld
        else: tp = e + d_ * rr * sld
        ep = None; j = i
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


def seat(tr):
    ev = sorted(tr, key=lambda t: t[0]); openh = []; tk = []; ctr = 0
    for ens, ex, R, sp in ev:
        while openh and openh[0][0].value <= ens: heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(openh, (ex, ctr, R)); tk.append((ens, ex, R, sp))
    return tk


def stats(tk):
    if not tk: return None
    r = np.array([t[2] for t in tk]); sp = np.array([t[3] for t in tk])
    ens = np.array([t[0] for t in tk], dtype="int64")
    ya = np.array([pd.Timestamp(t[1]).year for t in tk])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * sp) * DB.BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); tr_ = ens < TRAIN_END_NS
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=float(pnl.sum()),
                train=float(pnl[tr_].sum()), test=float(pnl[~tr_].sum()),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def run(ms, others, **kw):
    tr = []
    for c in DB.DONCH: tr += gen(ms[c], **kw)
    return stats(seat(tr + others))


def show(title, items, ref_key, ms, others, kwname):
    print(f"\n  {'─'*100}\n  ### {title}")
    print(f"  {'varyant':>16s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'TRAIN$':>8s} {'TEST$':>8s} "
          f"{'toplam$':>9s}  yıl-yıl")
    res = {}
    for name, val in items.items():
        s = run(ms, others, **{kwname: val})
        if not s: continue
        res[name] = s
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        print(f"  {name:>16s} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['train']:>+8.0f} "
              f"{s['test']:>+8.0f} {s['tot']:>+9.0f}  {ys}")
    ref = res[ref_key]
    alts = {k: v for k, v in res.items() if k != ref_key}
    if not alts: return
    best = max(alts, key=lambda k: alts[k]["train"])
    b = alts[best]
    print(f"  → TRAIN argmax: {best} (${b['train']:+.0f} vs taban ${ref['train']:+.0f})", end="")
    if b["train"] <= ref["train"]:
        print("  → TRAIN'de bile geçemiyor, TEST açılmadı. RET.")
    else:
        dte = b["test"] - ref["test"]
        dy = {y: b["yrs"].get(y, 0) - ref["yrs"].get(y, 0) for y in ref["yrs"]}
        ok = dte > 0 and all(v > 0 for v in dy.values()) and dte > 0.02 * ref["test"]
        print(f"\n    TEST Δ${dte:+.0f} | yıl-yıl " + " ".join(f"{y}:{v:+.0f}" for y, v in dy.items())
              + f"  {'★ KABUL' if ok else 'RET'}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ms = {c: fast_bt.load(c, source=source) for c in DB.DONCH}
    others = []
    for c in DB.SQZ: others += DB.gen("squeeze", fast_bt.load(c, source=source))
    for c in DB.BB_COINS: others += DB.gen_bb(fast_bt.load(c, source=source))
    print(f"\n{'='*108}\n=== PARÇA DEĞİŞTİRME — 'üstüne değil YERİNE' (tetikleyici=donchian sabit) ===")
    show("TREND KAPISI (long: close>EMA200 yerine ...)", TRENDS, "ema200(taban)", ms, others, "trend_fn")
    show("STOP TANIMI (2×ATR yerine ...)", STOPS, "2×ATR(taban)", ms, others, "stop_fn")
    show("HEDEF TANIMI (rr×SL yerine ...)",
         {"rr×SL(taban)": "rr", "3×ATR (dar)": "atr3", "8×ATR (geniş)": "atr8",
          "kanal genişliği": "mm1", "½ kanal": "mm05"},
         "rr×SL(taban)", ms, others, "tgt")
    print(f"\n  NOT: her aile TEK DEĞİŞKEN — diğer parçalar tabanda. 'KAPI YOK' satırı trend")
    print(f"  filtresinin ne kadar katkı sağladığını doğrudan ölçer (kaldırınca ne oluyor).")


if __name__ == "__main__":
    main()
