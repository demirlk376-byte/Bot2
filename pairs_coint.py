"""
pairs_coint.py — Pairs, DOĞRU metodolojiyle: OLS hedge oranı + kointegrasyon/half-life seçimi.

ÖNCEKİ TESTİMDE İKİ METODOLOJİK HATA VARDI (kendi denetimimde bulundu):
 1) Çiftleri KORELASYONLA seçtim. Doğrusu KOİNTEGRASYON: korele çiftler kalıcı ayrışabilir,
    kointegre çiftler yapısı gereği ortalamaya döner. Pairs trading'in temel kuralı.
 2) log(A/B) yazdım = 1:1 hedge oranı VARSAYIMI. Doğrusu OLS ile tahmin edilen β:
    spread = log(A) − β·log(B). Yanlış β → spread trend'li kalır → sahte sinyal.

BU ARAÇ: serbest evrende (deploy'da OLMAYAN 10 coin → ÇAKIŞMA YOK, hedge mode GEREKMEZ) doğru
metodolojiyle çift arar. scipy yok → Engle-Granger'ı elle: OLS β, kalıntı, AR(1) ile HALF-LIFE
(ortalamaya dönüş hızı) + kalıntı stabilite kontrolü.

SEÇİM SADECE EĞİTİMDEN (2023-24): β, half-life, sıralama — hepsi train'den. Test (2025-26) dokunulmaz.
Half-life kriteri p-değerinden pratik olarak daha kullanışlı: kısa half-life = hızlı dönüş = işlenebilir.
Aşırı kısa (<2 gün) gürültü, aşırı uzun (>30 gün) sermaye kilitler → 2-30 gün bandı.

KARAR: HER YIL pozitif + TEST(2025-26) pozitif + kitapla korr<+0.3. Yoksa red (ve pairs kolu biter).

Kullanım:  py pairs_coint.py local
"""
import sys, itertools
import numpy as np, pandas as pd
import fast_bt

BAL0 = 190.0; FEE = 0.0001
DEPLOYED = {"ADA", "BCH", "BNB", "DOGE", "ETH", "ICP", "LTC", "NEAR", "SOL", "TRX", "XLM", "XRP"}
FREE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
ZWIN = 60          # z-score penceresi (gün)


def load_px(source):
    px = {}
    for c in FREE:
        try: px[c] = fast_bt.resample(fast_bt.load(c, source=source), "1d")["close"]
        except Exception as e: print(f"  {c}: {e}")
    return pd.DataFrame(px).dropna(how="all").ffill()


def ols_beta(y, x):
    """log(A) = a + β·log(B) + ε  → β (hedge oranı)."""
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[1]), float(coef[0])


def half_life(resid):
    """AR(1): Δr_t = λ·r_{t-1} + ε → half-life = −ln2/ln(1+λ). Kısa = hızlı dönüş."""
    r = np.asarray(resid); dr = np.diff(r); rl = r[:-1]
    if len(dr) < 30: return np.inf
    X = np.column_stack([np.ones(len(rl)), rl])
    coef, *_ = np.linalg.lstsq(X, dr, rcond=None)
    lam = float(coef[1])
    if lam >= 0 or lam <= -1: return np.inf          # dönüş yok / aşırı salınım
    return -np.log(2) / np.log(1 + lam)


def pick_pairs(px, n_pairs):
    """SADECE eğitim verisinden: OLS β + half-life ile kointegre çift seç."""
    tr = px[px.index < TRAIN_END]
    lg = np.log(tr)
    cands = []
    for a, b in itertools.combinations(lg.columns, 2):
        s = lg[[a, b]].dropna()
        if len(s) < 250: continue
        beta, alpha = ols_beta(s[a].values, s[b].values)
        if not (0.2 < beta < 5.0): continue          # dejenere hedge oranı ele
        resid = s[a].values - beta * s[b].values - alpha
        hl = half_life(resid)
        if not (2.0 <= hl <= 30.0): continue         # işlenebilir dönüş hızı
        # kalıntı stabilitesi: eğitim içi ikinci yarıda da makul mü
        h = len(resid) // 2
        if abs(np.std(resid[h:]) / max(np.std(resid[:h]), 1e-9) - 1.0) > 1.0: continue
        cands.append((hl, a, b, beta, alpha))
    cands.sort(key=lambda t: t[0])                   # en hızlı dönüş önce
    return cands[:n_pairs]


def run_pair(px, a, b, beta, z_in, z_out, z_stop, maxbars):
    lg = np.log(px[[a, b]].dropna())
    sp = lg[a] - beta * lg[b]                        # OLS spread (1:1 DEĞİL)
    mu = sp.rolling(ZWIN).mean(); sd = sp.rolling(ZWIN).std()
    z = ((sp - mu) / sd).values                      # sadece geçmiş pencere
    idx = sp.index
    ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
    n = len(z); out = []; i = ZWIN + 1
    while i < n - 1:
        if not np.isfinite(z[i]) or abs(z[i]) < z_in: i += 1; continue
        d_ = -1 if z[i] > 0 else +1
        ea, eb = ra[i], rb[i]
        exit_j = None
        for j in range(i + 1, min(i + 1 + maxbars, n)):
            if not np.isfinite(z[j]): continue
            if abs(z[j]) < z_out or abs(z[j]) > z_stop: exit_j = j; break
        if exit_j is None: exit_j = min(i + maxbars, n - 1)
        xa, xb = ra[exit_j], rb[exit_j]
        r_a = d_ * (xa - ea) / ea
        r_b = -d_ * beta * (xb - eb) / eb            # β ile ağırlıklı bacak
        w = 1.0 + beta                               # toplam nominal (normalize)
        ret = (r_a + r_b) / w - 2 * (1 + beta) / w * FEE * 2
        out.append({"ret": ret, "ts": idx[exit_j]})
        i = exit_j + 1
    return out


def book_monthly():
    import deployed_backtest as DB
    tr = []
    for c in DB.DONCH: tr += DB.gen("donchian", fast_bt.load(c, source="local"))
    for c in DB.SQZ: tr += DB.gen("squeeze", fast_bt.load(c, source="local"))
    taken = DB.seat_select(tr)
    r = np.array([R for _, R, _ in taken]); sl = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * sl) * DB.BAL0
    return pd.Series(pnl, index=[pd.Timestamp(x).to_period("M") for x, _, _ in taken]).groupby(level=0).sum()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    px = load_px(source)
    print(f"\n{'='*100}\n=== PAIRS (DOĞRU METODOLOJİ): OLS β + half-life seçimi, SERBEST evren ===")
    print(f"  serbest coinler ({len(FREE)}): {', '.join(FREE)} — çakışma YOK, hedge mode GEREKMEZ")
    for n_pairs in (4, 6, 8):
        sel = pick_pairs(px, n_pairs)
        if not sel:
            print(f"\n  {n_pairs} çift: kointegre aday BULUNAMADI"); continue
        print(f"\n{'='*100}\n=== en iyi {len(sel)} kointegre çift (eğitimden: half-life, β) ===")
        print("  " + " | ".join(f"{a}/{b} hl{hl:.1f}g β{beta:.2f}" for hl, a, b, beta, _ in sel))
        for z_in, z_out, z_stop in ((2.0, 0.5, 3.5), (2.0, 0.0, 3.0), (2.5, 0.5, 4.0)):
            allr = []
            for hl, a, b, beta, _ in sel:
                allr += run_pair(px, a, b, beta, z_in, z_out, z_stop, 20)
            if not allr: continue
            d = np.array([t["ret"] * BAL0 for t in allr])
            ya = np.array([pd.Timestamp(t["ts"]).year for t in allr])
            gp = d[d > 0].sum(); gl = -d[d < 0].sum(); pf = gp / max(gl, 1e-9)
            te = d[ya >= 2025].sum(); trn = d[ya < 2025].sum()
            yrs = {y: d[ya == y].sum() for y in sorted(set(ya))}
            pos = all(v > 0 for v in yrs.values())
            ys = " ".join(f"{y}:${v:+.0f}" for y, v in yrs.items())
            flag = "HER-YIL+" if pos else ""
            if pos and te > 0: flag += " ★ADAY"
            print(f"  z{z_in}/{z_out}/{z_stop}: n={len(d):>4d} WR{(d>0).mean()*100:>3.0f}% PF{pf:5.2f} "
                  f"${d.sum():>+7.0f} | TRAIN ${trn:>+6.0f} TEST ${te:>+6.0f} | {ys}  {flag}")
            if pos and te > 0:
                m = pd.Series(d, index=[pd.Timestamp(t["ts"]).to_period("M") for t in allr]).groupby(level=0).sum()
                bk = book_monthly()
                j = pd.concat({"p": m, "b": bk}, axis=1).dropna()
                bad = j[j["b"] < 0]
                print(f"      → kitapla korr {j['p'].corr(j['b']):+.2f} | kitabın kayıp aylarında "
                      f"${bad['p'].sum():+.0f} ({(bad['p']>0).sum()}/{len(bad)} ay+) | "
                      f"birlikte ${(j['p']+j['b']).sum():+.0f} vs kitap ${j['b'].sum():+.0f}")
    print(f"\n  ★ADAY yoksa: doğru metodolojiyle de serbest evrende pairs YOK → kol kapanır.")


if __name__ == "__main__":
    main()
