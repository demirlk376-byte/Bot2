"""
indicator_sizing_test.py — Göstergeyi FİLTRE değil BOYUT olarak kullan.

NEDEN BU AÇI (kendi bulgularımızdan çıkıyor):
1. ~230 hipotez test edildi, HEPSİ aç/kapa kapısıydı ("koşul sağlanmıyorsa işlemi ATLA").
2. Permütasyon testi şunu gösterdi: sinyallerin %4-7'sini RASTGELE atmak bile ortalamada para
   kaybettiriyor (dağılım ortalaması −$9…−$46). Yani bu sistemde İŞLEM SİLMEK, silinen ne olursa
   olsun, beklenen değeri düşürüyor. Filtrelerin başarısızlığının kökü bu.
3. AMA bazı göstergeler sinyal düzeyinde GERÇEK bilgi taşıyor:
     HURST50  → TEST Spearman(gösterge, R) = +0.185, p<0.001  (trendquality_filters)
     ham hacim/kanal-ort → TRAIN +0.0748 p=0.008, TEST +0.0567 p=0.036  (volume_derivative_filters)
   İkisi de FİLTRE olarak parasallaşmadı çünkü filtre işlem sayısını kesiyor.
→ BOYUTLANDIRMA işlem SİLMEZ. Hepsini alır, sadece maruziyeti göstergeye göre oynatır.
   Filtrelemenin yok ettiği bilgiyi çıkarabilecek TEK mekanizma bu ve HİÇ DENENMEDİ.

*** İKİ KRİTİK TUZAK — İKİSİ DE BU OTURUMDA GERÇEKLEŞTİ, İKİSİ DE BURADA KAPATILDI ***

TUZAK 1 — KALDIRAÇ: boyutları oynatmak ortalama dağıtılan riski ARTIRABİLİR; o zaman kazanç
  "daha iyi tahsis"ten değil "daha çok risk"ten gelir. sleeve_risk_test'te tam bu oldu ve testin
  KENDİSİ tuzağa düştü (ikili arama kısıtı sağlayamadan sonuç döndürdü, 2 sahte "KABUL").
  ÇÖZÜM: global bir g ile TÜM çarpan vektörü ölçeklenir, ort dağıtılan risk TABANA eşitlenir.
  g serbestçe küçülebildiği için kısıt HER ZAMAN sağlanır; sağlanamazsa satır GEÇERSİZ basılır.

TUZAK 2 — YÜZDELİK LOOKAHEAD: göstergeyi "tüm örneklemin yüzdeliğine" göre haritalamak
  GELECEĞİ KULLANMAKTIR. Canlıda o dağılımı bilmiyoruz.
  ÇÖZÜM: GENİŞLEYEN yüzdelik — her sinyal, YALNIZCA kendinden ÖNCEKİ sinyallere göre sıralanır.
  İlk MIN_HIST sinyalde çarpan 1.0 (nötr), yani ısınma dönemi bilgi kullanmaz.

KABUL BARI: TRAIN'de seç → TEST'te tabanı geç → HER YIL geç → bütçe-nötr formda geç.
Kullanım:  py indicator_sizing_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy

TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
TRAIN_END_NS = TRAIN_END.value   # ham nanosaniye — birim karışıklığını önler
MIN_HIST = 50          # bu kadar geçmiş sinyal birikene dek çarpan = 1.0 (nötr ısınma)


# ── göstergeler: hepsi PENCERE-YEREL, son N barın saf fonksiyonu, lookahead yok ──
def eff_ratio(c, n):
    """Kaufman Efficiency Ratio: |net| / toplam yol. 1=temiz trend, 0=testere."""
    net = abs(c[-1] - c[-1 - n])
    path = np.abs(np.diff(c[-1 - n:])).sum()
    return net / path if path > 0 else 0.0


def hurst_rs(c, n):
    """Basit R/S: log(R/S)/log(n). >0.5 persistent."""
    x = np.diff(np.log(c[-1 - n:]))
    if len(x) < 8: return 0.5
    y = np.cumsum(x - x.mean())
    R = y.max() - y.min(); S = x.std(ddof=1)
    return np.log(R / S) / np.log(len(x)) if (S > 0 and R > 0) else 0.5


def vhf(c, n):
    """Vertical Horizontal Filter: (maxC-minC)/toplam yol."""
    w = c[-1 - n:]
    path = np.abs(np.diff(w)).sum()
    return (w.max() - w.min()) / path if path > 0 else 0.0


IND = {
    "hurst50": lambda c, v, a: hurst_rs(c, 50),
    "er20":    lambda c, v, a: eff_ratio(c, 20),
    "vhf14":   lambda c, v, a: vhf(c, 14),
    "volrat":  lambda c, v, a: v[-1] / max(v[-21:-1].mean(), 1e-9),
    "adx":     lambda c, v, a: a,
}


def gen_donchian_with_ind(m):
    """Donchian üretimi + her sinyalde gösterge değerleri. DB.gen ile AYNI mekanik."""
    tf, win, sl_a, rr, mh = DB.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    vol = d["volume"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE_ * e / sld
        cw = cl[:i + 1]; vw = vol[:i + 1]
        ax = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
        vals = {k: float(f(cw, vw, ax)) for k, f in IND.items()}
        out.append((idx[i].value, idx[j], R, sld / e, "donchian", vals)); occ = j
    return out


FEE_ = DB.FEE


def other_sleeves(source):
    """squeeze + bb: TABANDA sabit, çarpan hep 1.0 (tek değişken kuralı)."""
    out = []
    for c in DB.SQZ:
        for t in DB.gen("squeeze", fast_bt.load(c, source=source)):
            out.append((t[0], t[1], t[2], t[3], "squeeze", None))
    for c in DB.BB_COINS:
        for t in DB.gen_bb(fast_bt.load(c, source=source)):
            out.append((t[0], t[1], t[2], t[3], "bb", None))
    return out


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, sv, vals in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((entry_ns, exit_ts, R, slp, sv, vals))
    return sorted(taken, key=lambda t: t[0])   # GİRİŞ sırası (genişleyen yüzdelik için şart)


def multipliers(taken, ind, k, mode):
    """GENİŞLEYEN yüzdelik → çarpan. Her sinyal yalnız KENDİNDEN ÖNCEKİLERE göre sıralanır."""
    mults = np.ones(len(taken)); hist = []
    for i, (_, _, _, _, sv, vals) in enumerate(taken):
        if vals is None or ind not in vals:      # squeeze/bb → dokunma
            continue
        x = vals[ind]
        if len(hist) >= MIN_HIST:
            pct = float(np.searchsorted(np.sort(hist), x) / len(hist))   # [0,1], SADECE geçmiş
            if mode == "lin":
                mults[i] = 1.0 + k * (2.0 * pct - 1.0)                   # [1-k, 1+k]
            else:                                                        # üçlü kademe
                mults[i] = 1.0 - k if pct < 1/3 else (1.0 + k if pct > 2/3 else 1.0)
        hist.append(x)
    return mults


def evaluate(taken, mults, g=1.0):
    r = np.array([t[2] for t in taken]); slp = np.array([t[3] for t in taken])
    # entry_ns HAM NANOSANİYE (idx[i].value). tz-aware Timestamp ile karşılaştırmak
    # TypeError verir; ayrıca pandas 3'te .astype(int64) MİKRO-saniye döndürüp sessizce
    # yanlış sonuç üretir. Bu yüzden karşılaştırma ham int nanosaniye üzerinden yapılıyor.
    ent_ns = np.array([t[0] for t in taken], dtype="int64")
    ya = np.array([pd.Timestamp(t[1]).year for t in taken])
    eff = np.minimum(DB.RISKF * mults * g, DB.CAP * slp)
    pnl = r * eff * DB.BAL0
    eq = np.concatenate([[DB.BAL0], DB.BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    tr = ent_ns < TRAIN_END_NS
    return dict(tot=float(pnl.sum()), train=float(pnl[tr].sum()), test=float(pnl[~tr].sum()),
                avg_risk=float(eff.mean()), dd=float(((peak - eq) / peak).max() * 100),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def budget_neutral_g(taken, mults, target, tol=1e-4):
    """Ort dağıtılan riski TABANA eşitleyen global g. Her zaman yakınsar; yoksa None."""
    lo, hi = 1e-3, 1.0
    if evaluate(taken, mults, 1.0)["avg_risk"] < target: hi = 50.0
    for _ in range(60):
        g = (lo + hi) / 2
        if evaluate(taken, mults, g)["avg_risk"] > target: hi = g
        else: lo = g
    g = (lo + hi) / 2
    got = evaluate(taken, mults, g)["avg_risk"]
    return g if abs(got - target) / target < tol else None


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    trades = []
    for c in DB.DONCH: trades += gen_donchian_with_ind(fast_bt.load(c, source=source))
    trades += other_sleeves(source)
    taken = seat_select(trades)
    base = evaluate(taken, np.ones(len(taken)))
    ys = " ".join(f"{y}:${v:+.0f}" for y, v in base["yrs"].items())
    print(f"\n{'='*112}\n=== GÖSTERGE = BOYUT (filtre DEĞİL) — işlem silinmiyor, maruziyet oynatılıyor ===")
    print(f"  TABAN: n={len(taken)} ${base['tot']:+.0f} (TRAIN ${base['train']:+.0f} / "
          f"TEST ${base['test']:+.0f}) maxDD %{base['dd']:.1f} ort risk %{base['avg_risk']*100:.2f}")
    print(f"         {ys}")
    print(f"  (çarpan YALNIZ donchian'a; squeeze/bb tabanda sabit. Yüzdelik GENİŞLEYEN = lookahead yok.)")
    print(f"\n  {'gösterge':>9s} {'mod':>5s} {'k':>5s} {'g':>6s} {'ort risk':>9s} {'TRAIN$':>8s} "
          f"{'TEST$':>8s} {'ΔTEST':>7s} {'maxDD%':>7s}  yıl-yıl Δ                          karar")
    rows = []
    for ind in IND:
        for mode in ("lin", "tier"):
            for k in (0.2, 0.4, 0.6):
                m = multipliers(taken, ind, k, mode)
                g = budget_neutral_g(taken, m, base["avg_risk"])
                if g is None:
                    print(f"  {ind:>9s} {mode:>5s} {k:>5.1f}      —  bütçe kısıtı SAĞLANAMADI → GEÇERSİZ")
                    continue
                s = evaluate(taken, m, g)
                dy = {y: s["yrs"].get(y, 0.0) - base["yrs"].get(y, 0.0) for y in base["yrs"]}
                every = all(v > 0 for v in dy.values())
                dtest = s["test"] - base["test"]
                ok = (s["train"] > base["train"]) and (dtest > 0) and every
                verdict = ("★ KABUL" if ok else
                           "TRAIN+ TEST+ ama yıl bozuk" if (s["train"] > base["train"] and dtest > 0)
                           else "TRAIN+ ama TEST-" if s["train"] > base["train"] else "RET")
                y = " ".join(f"{kk}:{vv:+.0f}" for kk, vv in dy.items())
                print(f"  {ind:>9s} {mode:>5s} {k:>5.1f} {g:>6.3f} {s['avg_risk']*100:>8.2f}% "
                      f"{s['train']:>+8.0f} {s['test']:>+8.0f} {dtest:>+7.0f} {s['dd']:>7.1f}  {y}  {verdict}")
                rows.append((ind, mode, k, s, dtest, every, ok))

    kabul = [r for r in rows if r[6]]
    print(f"\n  {len(rows)} kombinasyon test edildi (5 gösterge × 2 mod × 3 k). KABUL: {len(kabul)}")
    print(f"  Bütçe-nötr: ort dağıtılan risk HER satırda tabanla AYNI → kazanç kaldıraçtan GELEMEZ.")
    print(f"  Yüzdelik GENİŞLEYEN (ilk {MIN_HIST} sinyalde çarpan 1.0) → gelecek bilgisi YOK.")
    if not kabul:
        print(f"  → Boyutlandırma da işe yaramıyorsa: göstergelerdeki sinyal-düzeyi korelasyon")
        print(f"    (Hurst rho +0.185) DOLARA çevrilemiyor demektir; eksen tamamen kapanır.")


if __name__ == "__main__":
    main()
