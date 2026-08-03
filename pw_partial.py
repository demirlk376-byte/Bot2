"""
pw_partial.py — KISMİ ÇIKIŞ (scale-out): 88 hücreli ölçüm + ANKOR + CEBİRSEL DEJENERASYON TESTİ.

SORU: pozisyonun YARISINI rr2.5'te bankaya yaz, kalan yarıyı koştur. Bugün kanıtlandı ki
kuyruk GERÇEK (rr1.5 +0.053R → rr6.0 +0.136R, hem long hem short, iki dönemde de) ama TAM
pozisyonu genişletmek portföyde 2025'i her seviyede bozdu ve en kötü ayı −21 → −29.7 yaptı.
Hipotez: kısmi çıkış kuyruk faydasını alıp aylık kuyruk cezasını ödemeyebilir.

⚠️ ÖNCE CEBİR — bu oturumda İKİ KEZ dejenere varyant yakalandı, üçüncüsünü aramadan yazıyorum:
    Kısmi çıkışın ilk kademesi TABANIN hedefiyle (rr2.5) AYNI seviyedeyse, işlem başına R
    şuna CEBİRSEL OLARAK EŞİTTİR:
            R_kısmi(f)  =  f × R_taban  +  (1−f) × R_X
    burada X = "TAM pozisyon, koşucunun politikasıyla" (örn. rr5.0, trailing, maxhold).
    Kanıt: rr2.5'e ULAŞMAYAN işlemlerde taban ve X birebir aynı çıkışı verir (aynı stop, aynı
    maxhold) → kısmi de aynısıdır. rr2.5'e ULAŞAN işlemlerde f kadarı 2.5R'de (=taban), kalan
    (1−f) X'in yolunu izler (aynı stop, aynı hedef) → tanım gereği ağırlıklı ortalama.
    SONUÇ: ortalama R HER ZAMAN taban ile X'in ARASINDA kalır. Kısmi çıkış ikisini de geçemez.
    Üstelik KOLTUK X'in koltuğudur (pozisyon tam kapanana kadar dolu) → portföyde X'in tutuş
    maliyetini ödeyip X'in faydasının sadece (1−f)'ini alırsın.
    Bu betikte bu özdeşlik SAYIYLA doğrulanıyor (aynı-bar dolum izniyle birebir eşitlik).

O halde neden yine de koşuyorum? Çünkü portföy seviyesi DOĞRUSAL DEĞİL:
  - koltuk seçimi X'in çıkış zamanlarına göre yapılır → alınan işlem KÜMESİ değişir,
  - kabul barındaki "en kötü ay" ve "yıl kırılımı" kısıtları doğrusal olmayan istatistikler.
  Yani portföyde ara nokta, uçların ortalaması OLMAYABİLİR. Asıl soru bu ve ancak ankorda sorulur.
  Ve BAŞABAŞ (BE) kolu gerçekten YENİ bir X üretir (tabanda ve rr taramasında yoktu).

YÖNTEM (power_test/power_rr/power_mh iskeleti, değiştirilmedi):
  1. ÖLÇÜM: 22 coin × 4 tf = 88 hücre, koltuk seçimi YOK, occ guard ZORUNLU
     (occ = TAM kapanış barı — kısmi çıkış koltuğu BOŞALTMAZ).
  2. Dört sahtelik testi: (a) işaret testi + binom p, (b) havuzlanmış z, (c) YÖN ayrımı
     (etki sadece long'daysa beta), (d) DÖNEM ayrımı (TRAIN/TEST işareti).
  3. DOZ-YANIT: f = 0.00 … 1.00 yedi nokta.
  4. R/bar (koltuk maliyeti).
  5. ANKOR: hayatta kalırsa deployed_backtest üstünde dolara çevir (yıl kırılımı + maxDD +
     en kötü ay). Taban satırı değiştirilmemiş A.gen ile BİREBİR doğrulanıyor.

BAR-İÇİ KÖTÜMSERLİK (hep tabanın lehine):
  - her barda ÖNCE stop kontrol edilir (aynı barda hem hedef hem stop varsa STOP sayılır),
  - bir barda EN FAZLA BİR kademe dolar (dev barda 2.5R ve 5.0R aynı anda dolmaz),
  - BE ancak kademe dolduktan SONRAKİ bardan itibaren korur.
  Ücret: her varyantta işlem gören notional 2 birim (1 giriş + toplam 1 çıkış) → taban ile
  aynı ücret formülü (2×FEE×fiyat/sl_mesafesi) kullanılıyor; kademeli çıkış ücreti ARTIRMAZ.

Kullanım:  py pw_partial.py local            (ölçüm + dejenerasyon + ankor)
           py pw_partial.py local measure    (sadece 88 hücre)
"""
import sys
from math import comb

import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, ema as ema_fn

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
TFS = ["2h", "4h", "6h", "12h"]
FEE = 0.0001
SL_A, MH = 2.0, 30
BASE_RR = 2.5
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")

# ── VARYANT TANIMI ────────────────────────────────────────────────────────────────────
# legs: [(pay, mod, param), ...] sırayla dolar. mod: "tp"=sabit hedef(R), "trail"=k×ATR
# chandelier (yalnız son kademe), "mh"=hedef yok (stop ya da maxhold).
# be: ilk kademe dolduktan sonra kalan pozisyonun stopu GİRİŞE çekilsin mi.
def V(legs, be=False):
    return {"legs": legs, "be": be}


VARIANTS = {
    "TABAN rr2.5":                 V([(1.00, "tp", 2.5)]),
    "a  %50@2.5 + %50@5.0":        V([(0.50, "tp", 2.5), (0.50, "tp", 5.0)]),
    "a' %50@2.5 + %50@5.0 +BE":    V([(0.50, "tp", 2.5), (0.50, "tp", 5.0)], be=True),
    "b  %50@2.5 + trail3ATR":      V([(0.50, "tp", 2.5), (0.50, "trail", 3.0)]),
    "b' %50@2.5 + trail3ATR +BE":  V([(0.50, "tp", 2.5), (0.50, "trail", 3.0)], be=True),
    "c  %50@2.5 + maxhold":        V([(0.50, "tp", 2.5), (0.50, "mh", None)]),
    "c' %50@2.5 + maxhold +BE":    V([(0.50, "tp", 2.5), (0.50, "mh", None)], be=True),
    "d  %33@2.5/4.0/6.0":          V([(1 / 3, "tp", 2.5), (1 / 3, "tp", 4.0), (1 / 3, "tp", 6.0)]),
    "d' %33@2.5/4.0/6.0 +BE":      V([(1 / 3, "tp", 2.5), (1 / 3, "tp", 4.0), (1 / 3, "tp", 6.0)], be=True),
    "e  %70@2.0 + %30@6.0":        V([(0.70, "tp", 2.0), (0.30, "tp", 6.0)]),
    "e' %70@2.0 + %30@6.0 +BE":    V([(0.70, "tp", 2.0), (0.30, "tp", 6.0)], be=True),
}
BASE = "TABAN rr2.5"
# Šidák: 10 karşılaştırma → 1−(1−0.05)^(1/10)
SIDAK = 1 - (1 - 0.05) ** (1 / 10)

DOSE_F = [0.00, 0.25, 1 / 3, 0.50, 2 / 3, 0.75, 1.00]


def trig_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def walk(spec, d_, c, sld, hi, lo, cl, a_ser, i, n, mh, same_bar=False):
    """Kademeli çıkış yürüyüşü. Dönüş: (ağırlıklı R (ücretsiz), çıkış barı j, ilk kademe doldu mu,
    son kademenin çıkış sebebi 0=stop 1=hedef/trail 2=maxhold).

    KÖTÜMSER SIRA: her barda ÖNCE stop; sonra (en fazla) BİR kademe dolumu; trail güncellemesi
    stop kontrolünden SONRA (power_exit.ex_trail ile aynı konvansiyon).
    same_bar=True yalnız DEJENERASYON İSPATI için: bir barda birden fazla kademenin dolmasına
    izin verir → cebirsel özdeşlik birebir çıkmalı."""
    legs = spec["legs"]
    slp = c - d_ * sld                 # stop fiyatı
    entry = c
    best = c                           # trailing için ulaşılan en iyi seviye
    li = 0                             # sıradaki kademe
    acc = 0.0                          # gerçekleşen ağırlıklı R
    rem = 1.0                          # kalan pay
    first_hit = False
    for j in range(i + 1, min(i + 1 + mh, n)):
        # 1) STOP HER ZAMAN ÖNCE (kötümser: aynı barda hem hedef hem stop varsa STOP)
        if (d_ == 1 and lo[j] <= slp) or (d_ == -1 and hi[j] >= slp):
            acc += rem * d_ * (slp - entry) / sld
            return acc, j, first_hit, 0
        # 2) zirve takibi (her bar; kademe dolan barın uç noktası da sayılır)
        best = max(best, hi[j]) if d_ == 1 else min(best, lo[j])
        # 3) trailing AKTİFSE (önceki kademeler dolmuşsa) stop çekilir — bir SONRAKİ
        #    bardan itibaren korur (power_exit.ex_trail ile aynı kötümser sıra)
        if li < len(legs) and legs[li][1] == "trail":
            k = legs[li][2]; aj = a_ser[j]
            if np.isfinite(aj) and aj > 0:
                slp = max(slp, best - k * aj) if d_ == 1 else min(slp, best + k * aj)
        # 4) sabit hedefli kademe dolumu — bir barda EN FAZLA BİR kademe (kötümser)
        while li < len(legs) and legs[li][1] == "tp":
            frac, _m, prm = legs[li]
            tp = entry + d_ * prm * sld
            if not ((d_ == 1 and hi[j] >= tp) or (d_ == -1 and lo[j] <= tp)):
                break
            acc += frac * d_ * (tp - entry) / sld
            rem -= frac; li += 1; first_hit = True
            if spec["be"]:                       # BE: kalan kısmın stopu girişe
                slp = max(slp, entry) if d_ == 1 else min(slp, entry)
            if rem <= 1e-12:
                return acc, j, first_hit, 1
            if not same_bar:
                break
    j = min(i + mh, n - 1)
    acc += rem * d_ * (cl[j] - entry) / sld
    return acc, j, first_hit, 2


def run(d, spec, mh=MH, same_bar=False):
    """occ'lu üretim, koltuk seçimi YOK. occ = TAM kapanış barı (kısmi çıkış koltuğu boşaltmaz).
    Dönüş: R, giriş zamanları, tutulan bar, yön, çıkış sebebi, ilk-kademe-doldu bayrağı."""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    L, S = trig_donchian(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    ok = np.isfinite(a_ser) & (a_ser > 0) & np.isfinite(e200)
    dirs = np.where(ok & L & (cl > e200), 1, np.where(ok & S & (cl < e200), -1, 0))
    cand = np.where(dirs != 0)[0]
    cand = cand[(cand >= 260) & (cand < n - 1)]
    Rs = []; ts = []; bars = []; ds = []; why = []; hit1 = []; occ = -1
    for i in cand:
        i = int(i)
        if i <= occ:
            continue
        a = a_ser[i]; c = cl[i]; d_ = int(dirs[i])
        sld = SL_A * a
        if not np.isfinite(sld) or sld <= 0:
            continue
        R, j, f1, w = walk(spec, d_, c, sld, hi, lo, cl, a_ser, i, n, mh, same_bar)
        Rs.append(R - 2 * FEE * c / sld)
        ts.append(idx[i]); bars.append(j - i); ds.append(d_); why.append(w); hit1.append(f1)
        occ = j
    return (np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([]),
            np.array(bars, float), np.array(ds, int), np.array(why, int),
            np.array(hit1, bool))


def identity_check(d, f=0.5, rr2=5.0):
    """DEJENERASYON İSPATI — işlem işlem, AYNI GİRİŞLER üzerinde.

    Dikkat: kısmi varyantın işlem KÜMESİ tabanınkiyle aynı DEĞİL (occ koşucunun çıkışına
    bağlı → daha az işlem). O yüzden özdeşlik "havuz ortalaması" ile değil, kısmi varyantın
    KABUL ETTİĞİ HER GİRİŞTE, aynı girişte tabanın ve TAM-koşucunun ne yapacağı hesaplanarak
    kontrol edilir. Dönüş: (kısmi R, taban-kuralı R, tam-koşucu R) aynı girişler için."""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    L, S = trig_donchian(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    n = len(cl)
    ok = np.isfinite(a_ser) & (a_ser > 0) & np.isfinite(e200)
    dirs = np.where(ok & L & (cl > e200), 1, np.where(ok & S & (cl < e200), -1, 0))
    cand = np.where(dirs != 0)[0]
    cand = cand[(cand >= 260) & (cand < n - 1)]
    sp_p = V([(f, "tp", BASE_RR), (1 - f, "tp", rr2)])
    sp_b = V([(1.0, "tp", BASE_RR)])
    sp_x = V([(1.0, "tp", rr2)])
    Rp = []; Rb = []; Rx = []; occ = -1
    for i in cand:
        i = int(i)
        if i <= occ:
            continue
        a = a_ser[i]; c = cl[i]; d_ = int(dirs[i]); sld = SL_A * a
        if not np.isfinite(sld) or sld <= 0:
            continue
        rp, j, _, _ = walk(sp_p, d_, c, sld, hi, lo, cl, a_ser, i, n, MH, same_bar=True)
        rb, _, _, _ = walk(sp_b, d_, c, sld, hi, lo, cl, a_ser, i, n, MH, same_bar=True)
        rx, _, _, _ = walk(sp_x, d_, c, sld, hi, lo, cl, a_ser, i, n, MH, same_bar=True)
        Rp.append(rp); Rb.append(rb); Rx.append(rx); occ = j
    return np.array(Rp), np.array(Rb), np.array(Rx)


def sign_p(w, n):
    if n == 0:
        return 1.0
    p = (2 * sum(comb(n, k) for k in range(w, n + 1)) / 2 ** n) if w >= n / 2 else \
        (2 * sum(comb(n, k) for k in range(0, w + 1)) / 2 ** n)
    return min(1.0, p)


# ══════════════════════════════════════════════════════════════════════════════════════
def measure(raw):
    print(f"\n{'=' * 108}")
    print(f"=== ÖLÇÜM: KISMİ ÇIKIŞ, {len(raw)} coin × {len(TFS)} tf, koltuk seçimi YOK ===")
    print("  giriş donchian-40 + EMA200 sabit, stop 2×ATR sabit, maxhold 30 sabit. SADECE çıkış.")

    names = list(VARIANTS)
    cells = {k: {} for k in names}
    pool = {k: {"R": [], "T": [], "B": [], "D": [], "W": [], "H": []} for k in names}
    deg = {"p": [], "b": [], "x": [], "n": 0}      # cebirsel özdeşlik verisi

    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400:
                continue
            out = {k: run(d, VARIANTS[k]) for k in names}
            if any(len(out[k][0]) < 20 for k in names):
                continue
            for k in names:
                R, T, B, D, W, H = out[k]
                cells[k][(tf, c)] = float(R.mean())
                pool[k]["R"].append(R); pool[k]["T"].append(T); pool[k]["B"].append(B)
                pool[k]["D"].append(D); pool[k]["W"].append(W); pool[k]["H"].append(H)
            ip, ib, ix = identity_check(d)          # aynı girişlerde kısmi / taban / tam-rr5
            deg["p"].append(ip); deg["b"].append(ib); deg["x"].append(ix); deg["n"] += 1

    ncell = len(cells[BASE])
    if ncell == 0:
        print("  hücre yok"); return None, None

    P = {}
    for k in names:
        Ts = pool[k]["T"]
        P[k] = (np.concatenate(pool[k]["R"]),
                Ts[0].append(Ts[1:]) if len(Ts) > 1 else Ts[0],
                np.concatenate(pool[k]["B"]), np.concatenate(pool[k]["D"]),
                np.concatenate(pool[k]["W"]), np.concatenate(pool[k]["H"]))
    Rb, Tb, Bb, Db = P[BASE][0], P[BASE][1], P[BASE][2], P[BASE][3]
    print(f"\n  ÖRNEKLEM: {ncell} hücre × {len(names)} varyant | taban {len(Rb)} işlem, "
          f"toplam {sum(len(P[k][0]) for k in names)} işlem")

    # ── 0. ARAÇ DOĞRULAMASI: taban power_rr ile BİREBİR mi? ──
    try:
        import power_rr
        okc = 0; badc = 0
        for tf in ("4h",):
            for c, m in raw.items():
                d = fast_bt.resample(m, tf)
                if len(d) < 400:
                    continue
                mine = run(d, VARIANTS[BASE])[0]
                theirs = power_rr.run(d, 2.5)[0]
                if len(mine) == len(theirs) and np.allclose(mine, theirs, atol=1e-12):
                    okc += 1
                else:
                    badc += 1
        print(f"  ARAÇ DOĞRULAMASI (taban == power_rr.run(rr2.5), 4h): {okc} coin BİREBİR, "
              f"{badc} coin SAPMA {'✓' if badc == 0 else '✗ SONUÇLAR GEÇERSİZ'}")
        if badc:
            return None, None
    except Exception as e:                                     # noqa: BLE001
        print(f"  ARAÇ DOĞRULAMASI yapılamadı: {e}")

    # ── 1. CEBİRSEL DEJENERASYON İSPATI ──
    print(f"\n  --- DEJENERASYON: kısmi çıkış YENİ bir şey mi, yoksa ara nokta mı? ---")
    if deg["n"]:
        Ip = np.concatenate(deg["p"]); Ib = np.concatenate(deg["b"]); Ix = np.concatenate(deg["x"])
        pred = 0.5 * Ib + 0.5 * Ix
        mx = float(np.abs(Ip - pred).max())
        print(f"      AYNI GİRİŞLERDE (n={len(Ip)}, {deg['n']} hücre), ücret hariç:")
        print(f"      R_kısmi(%50@2.5 + %50@5.0)  ==  0.5×R_taban + 0.5×R_[TAM rr5.0] ?")
        print(f"         max|fark| = {mx:.3e}   → "
              f"{'BİREBİR ÖZDEŞ (dejenere: yeni bilgi YOK)' if mx < 1e-9 else 'FARKLI'}")
        print(f"      ort R: kısmi {Ip.mean():+.4f} = 0.5×taban {Ib.mean():+.4f} "
              f"+ 0.5×TAM-rr5.0 {Ix.mean():+.4f}")
        print(f"      → Kısmi çıkış ORTALAMA R'de taban ile koşucunun ARASINDA kalmak ZORUNDA;")
        print(f"        ikisini birden geçemez. Ama KOLTUK koşucunun koltuğudur (aşağıda 'bar').")
    print("      (BE kolları bu özdeşliğin DIŞINDA: yeni bir koşucu politikası üretiyorlar.)")

    # ── 2. ANA TABLO: işaret testi + z + R/bar ──
    print(f"\n  --- ANA TABLO (taban = {BASE}) | Šidák p eşiği {SIDAK:.4f} ---")
    hdr = (f"  {'varyant':<28s} {'ort R':>9s} {'fark':>8s} {'z':>6s} {'hücre':>8s} {'p':>8s} "
           f"{'bar':>5s} {'R/bar':>9s} {'ΔR/bar':>9s} | {'kadem%':>7s} {'stop%':>6s} {'süre%':>6s}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    stats = {}
    for k in names:
        R, T, B, D, W, H = P[k]
        se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb))
        diff = R.mean() - Rb.mean()
        z = diff / se if (se > 0 and k != BASE) else 0.0
        w = sum(1 for kk in cells[k] if cells[k][kk] > cells[BASE][kk])
        p = sign_p(w, ncell) if k != BASE else 1.0
        rpb = R.mean() / B.mean()
        stats[k] = dict(diff=diff, z=z, w=w, p=p, rpb=rpb, bar=B.mean())
        base_rpb = Rb.mean() / Bb.mean()
        print(f"  {k:<28s} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} {w:>4d}/{ncell:<3d} "
              f"{p:>8.4f} {B.mean():>5.1f} {rpb:>+9.5f} {rpb - base_rpb:>+9.5f} | "
              f"{100 * H.mean():>7.1f} {100 * (W == 0).mean():>6.1f} {100 * (W == 2).mean():>6.1f}"
              + ("  ← TABAN" if k == BASE else ""))
    print("  kadem% = ilk kademenin dolduğu işlem payı (0 ise varyant tabana dejenere)")

    # ── 3. YÖN AYRIMI ──
    print(f"\n  --- YÖN AYRIMI (etki sadece LONG'da ise piyasa BETASI, edge değil) ---")
    print(f"  {'varyant':<28s} {'LONG ΔR':>9s} {'n':>6s} | {'SHORT ΔR':>10s} {'n':>6s}   hüküm")
    for k in names:
        if k == BASE:
            continue
        R, T, B, D = P[k][0], P[k][1], P[k][2], P[k][3]
        row = f"  {k:<28s}"
        dl = {}
        for s in (1, -1):
            v = R[D == s]; b = Rb[Db == s]
            dl[s] = v.mean() - b.mean() if len(b) else np.nan
        both = np.isfinite(dl[1]) and np.isfinite(dl[-1]) and np.sign(dl[1]) == np.sign(dl[-1])
        print(row + f" {dl[1]:>+9.4f} {(D == 1).sum():>6d} | {dl[-1]:>+10.4f} "
                    f"{(D == -1).sum():>6d}   {'iki taraf AYNI' if both else 'TERS → beta şüphesi'}")
        stats[k]["dir_same"] = both

    # ── 4. DÖNEM AYRIMI ──
    print(f"\n  --- DÖNEM (TRAIN < 2025-01-01 ≤ TEST) ---")
    print(f"  {'varyant':<28s} {'TRAIN Δ':>10s} {'TEST Δ':>10s} {'işaret':>8s}")
    for k in names:
        if k == BASE:
            continue
        R, T = P[k][0], P[k][1]
        ds = []
        for mv, mb in ((T < TRAIN_END, Tb < TRAIN_END), (T >= TRAIN_END, Tb >= TRAIN_END)):
            rv, rb = R[mv], Rb[mb]
            ds.append(rv.mean() - rb.mean() if len(rv) >= 50 and len(rb) >= 50 else np.nan)
        same = np.isfinite(ds[0]) and np.isfinite(ds[1]) and np.sign(ds[0]) == np.sign(ds[1])
        stats[k]["per_same"] = same
        print(f"  {k:<28s} {ds[0]:>+10.4f} {ds[1]:>+10.4f} {'AYNI' if same else 'FARKLI':>8s}")

    # ── 5. ÖN-KAYITLI BARIN TAMAMI ──
    print(f"\n  --- ÖN-KAYITLI BAR: p<{SIDAK:.4f} + |z|>1.96 + yön AYNI + dönem AYNI + ΔR/bar>0 ---")
    survivors = []
    for k in names:
        if k == BASE:
            continue
        s = stats[k]
        fails = []
        if s["p"] >= SIDAK: fails.append("p")
        if s["z"] <= 1.96: fails.append("z")
        if not s.get("dir_same"): fails.append("yön")
        if not s.get("per_same"): fails.append("dönem")
        if s["rpb"] <= Rb.mean() / Bb.mean(): fails.append("R/bar")
        if not fails:
            survivors.append(k)
        print(f"  {k:<28s} {'✓ GEÇTİ' if not fails else '✗ ' + ', '.join(fails)}")
    return survivors, P


def dose(raw):
    """DOZ-YANIT: f (ilk kademede alınan pay) 0→1. Koşucu rr5.0. BE'li ve BE'siz."""
    print(f"\n{'=' * 108}")
    print("=== DOZ-YANIT: ilk kademe payı f (f=1.00 taban, f=0.00 TAM rr5.0) ===")
    print("  BE'siz kolun DOĞRUSAL çıkması BEKLENİYOR (cebirsel interpolasyon). Bilgi BE kolunda.")
    specs = {}
    for f in DOSE_F:
        legs = ([(1.0, "tp", 2.5)] if f >= 1 - 1e-9 else
                ([(1.0, "tp", 5.0)] if f <= 1e-9 else [(f, "tp", 2.5), (1 - f, "tp", 5.0)]))
        specs[("düz", f)] = V(legs)
        legs_be = ([(1.0, "tp", 2.5)] if f >= 1 - 1e-9 else
                   [(f, "tp", 2.5), (1 - f, "tp", 5.0)])
        specs[("BE", f)] = V(legs_be, be=True)
    res = {k: {"R": [], "B": [], "cell": {}} for k in specs}
    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400:
                continue
            o = {k: run(d, s) for k, s in specs.items()}
            if any(len(v[0]) < 20 for v in o.values()):
                continue
            for k, (R, T, B, D, W, H) in o.items():
                res[k]["R"].append(R); res[k]["B"].append(B); res[k]["cell"][(tf, c)] = R.mean()
    base_key = ("düz", 1.00)
    nb = len(res[base_key]["cell"])
    Rb = np.concatenate(res[base_key]["R"])
    print(f"\n  {'kol':>4s} {'f':>6s} {'ort R':>9s} {'fark':>8s} {'z':>6s} {'hücre':>8s} "
          f"{'p':>8s} {'bar':>5s} {'R/bar':>9s}")
    for arm in ("düz", "BE"):
        for f in DOSE_F:
            k = (arm, f)
            R = np.concatenate(res[k]["R"]); B = np.concatenate(res[k]["B"])
            se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb))
            diff = R.mean() - Rb.mean()
            z = diff / se if se > 0 else 0.0
            w = sum(1 for kk in res[k]["cell"] if res[k]["cell"][kk] > res[base_key]["cell"][kk])
            print(f"  {arm:>4s} {f:>6.2f} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} "
                  f"{w:>4d}/{nb:<3d} {sign_p(w, nb):>8.4f} {B.mean():>5.1f} "
                  f"{R.mean() / B.mean():>+9.5f}")
        print()


# ══════════════════════════════════════════════════════════════════════════════════════
# ANKOR — deployed_backtest üstünde dolar/koltuk/maxDD/yıl
# ══════════════════════════════════════════════════════════════════════════════════════
def anchor(source, want):
    import deployed_backtest as A

    raw_d = [fast_bt.load(c, source=source) for c in A.DONCH]
    raw_s = [fast_bt.load(c, source=source) for c in A.SQZ]
    raw_b = [fast_bt.load(c, source=source) for c in A.BB_COINS]

    def precompute(m):
        """rr_anchor_sweep.precompute_donchian ile AYNI: yön occ'tan ve çıkıştan bağımsız."""
        tf, win, sl_a, _rr, mh = A.CFG["donchian"]
        d = A.fast_bt.resample(m, tf)
        atr_ser = A.atr_fn(d["high"], d["low"], d["close"], 14).values
        _dc = d["close"].resample("1D").last().dropna()
        _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
        up = d["close"].values > _dprev
        s = A.DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
        n = len(d); dirs = np.zeros(n, dtype=np.int8)
        for i in range(260, n - 1):
            a = atr_ser[i]
            if not np.isfinite(a) or a <= 0:
                continue
            d_ = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
            if d_ == 0:
                continue
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)):
                continue
            dirs[i] = d_
        return d, atr_ser, dirs

    def gen_partial(pre, spec, mh=None, same_bar=False):
        d, atr_ser, dirs = pre
        tf, win, sl_a, _rr, _mh = A.CFG["donchian"]
        mh = _mh if mh is None else mh
        hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
        idx = d.index; n = len(cl)
        out = []; occ = -1
        for i in range(260, n - 1):
            d_ = int(dirs[i])
            if d_ == 0 or i <= occ:
                continue
            a = atr_ser[i]; e = cl[i]; sld = sl_a * a
            R, j, _f1, _w = walk(spec, d_, e, sld, hi, lo, cl, atr_ser, i, n, mh, same_bar)
            out.append((idx[i].value, idx[j], R - 2 * A.FEE * e / sld, sld / e))
            occ = j
        return out

    def evaluate(spec, pre_d, other, same_bar=False):
        trades = []
        for p in pre_d:                       # SLEEVE SIRASI: DONCH → SQZ → BB (kararlı)
            trades += gen_partial(p, spec, same_bar=same_bar)
        trades += other
        taken = A.seat_select(trades)
        r = np.array([R for _, R, _ in taken])
        exits = [pd.Timestamp(x) for x, _, _ in taken]
        slpct = np.array([sp for _, _, sp in taken])
        pnl = r * np.minimum(A.RISKF, A.CAP * slpct) * A.BAL0
        eq = A.BAL0 + np.cumsum(pnl)
        dd = A.maxdd(np.concatenate([[A.BAL0], eq]))
        mon = (pd.DataFrame({"p": pnl, "m": [x.tz_localize(None).to_period("M") for x in exits]})
               .groupby("m")["p"].sum() / A.BAL0 * 100)
        yr = np.array([x.year for x in exits])
        return dict(n=len(taken), tot=float(pnl.sum()), dd=float(dd),
                    wr=float((r > 0).mean() * 100),
                    pf=float(r[r > 0].sum() / max(-r[r < 0].sum(), 1e-9)),
                    worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                    yr={int(y): float(pnl[yr == y].sum()) for y in sorted(set(yr))})

    print(f"\n{'=' * 108}")
    print("=== ANKOR: kısmi çıkış donchian koluna uygulandı (koltuk + boyut + maxDD + yıl) ===")
    print(f"  12 coin, MAXPOS={A.MAXPOS}, CAP={A.CAP}, RISKF={A.RISKF}, BAL0=${A.BAL0:.0f}")

    pre_d = [precompute(m) for m in raw_d]
    other = []
    for m in raw_s:
        other += A.gen("squeeze", m)
    for m in raw_b:
        other += A.gen_bb(m)

    # DOĞRULAMA: taban satırı değiştirilmemiş A.gen ile BİREBİR mi?
    ref = []
    for m in raw_d:
        ref += A.gen("donchian", m)
    ref_taken = A.seat_select(ref + other)
    rr_ = np.array([R for _, R, _ in ref_taken])
    sl_ = np.array([sp for _, _, sp in ref_taken])
    ref_tot = float((rr_ * np.minimum(A.RISKF, A.CAP * sl_) * A.BAL0).sum())
    base = evaluate(VARIANTS[BASE], pre_d, other)
    ok = base["n"] == len(ref_taken) and abs(base["tot"] - ref_tot) < 0.01
    print(f"\n  DOĞRULAMA: hızlı taban = {base['n']} işlem / ${base['tot']:+.2f}  vs  "
          f"A.gen = {len(ref_taken)} işlem / ${ref_tot:+.2f}  → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — tablo GEÇERSİZ'}")
    if not ok:
        return

    res = {BASE: base}
    for k in want:
        res[k] = evaluate(VARIANTS[k], pre_d, other)
    years = sorted({y for v in res.values() for y in v["yr"]})
    hdr = (f"  {'varyant':<28s} {'işlem':>6s} {'toplam$':>9s} {'Δ$':>7s} {'PF':>5s} {'WR%':>5s} "
           f"{'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay%':>8s} | " + " ".join(f"{y:>7d}" for y in years))
    print("\n" + hdr); print("  " + "-" * (len(hdr) - 2))
    for k, v in res.items():
        print(f"  {k:<28s} {v['n']:>6d} {v['tot']:>+9.0f} {v['tot'] - base['tot']:>+7.0f} "
              f"{v['pf']:>5.2f} {v['wr']:>5.1f} {v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>8.0f} | "
              + " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years)
              + ("  ← CANLI" if k == BASE else ""))

    # ── ANKOR DOZ-YANIT: koltuk maliyeti SABİT mi, orantılı mı? ──
    # Ölçümde tutuş süresi f=0.25/0.50/0.75'te BİREBİR aynı (18.3 bar) çıktı: koşucu payı
    # ne olursa olsun koltuk aynı süre dolu. Yani koltuk maliyeti SABİT bir gider, kuyruk
    # faydası ise (1−f) ile ORANTILI. Doğruysa ankorda işlem sayısı f<1'in her yerinde
    # aynı olmalı ve yalnız f=1'de sıçramalı. Bu, hipotezin can damarı.
    print(f"\n  --- ANKOR DOZ-YANIT: ilk kademe payı f (koşucu rr5.0) ---")
    print(f"      f=1.00 taban (koşucu yok) | f=0.00 kısmi çıkış YOK, TAM pozisyon rr5.0")
    dh = (f"  {'f':>6s} {'işlem':>6s} {'toplam$':>9s} {'Δ$':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} | "
          + " ".join(f"{y:>7d}" for y in years))
    print(dh); print("  " + "-" * (len(dh) - 2))
    for f in (0.00, 0.25, 0.50, 0.75, 1.00):
        legs = ([(1.0, "tp", 5.0)] if f <= 1e-9 else
                ([(1.0, "tp", BASE_RR)] if f >= 1 - 1e-9 else
                 [(f, "tp", BASE_RR), (1 - f, "tp", 5.0)]))
        v = evaluate(V(legs), pre_d, other)
        print(f"  {f:>6.2f} {v['n']:>6d} {v['tot']:>+9.0f} {v['tot'] - base['tot']:>+7.0f} "
              f"{v['dd']:>7.1f} {v['worst']:>+9.1f} | "
              + " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years))

    print(f"\n  --- KABUL BARI (ön-kayıt: Δ$>+28 & hiçbir yıl >%10 kötü & maxDD +2p içinde & "
          f"en kötü ay kötüleşmeyecek) ---")
    for k, v in res.items():
        if k == BASE:
            continue
        bad = []
        for y in years:
            b = base["yr"].get(y, 0.0); c = v["yr"].get(y, 0.0)
            rel = (c - b) / abs(b) * 100 if abs(b) > 1e-9 else 0.0
            if rel < -10:
                bad.append(f"{y}:{rel:+.0f}%")
        why = []
        if v["tot"] - base["tot"] < 0.02 * abs(base["tot"]):
            why.append(f"kâr artışı yetersiz ({v['tot'] - base['tot']:+.0f}$)")
        if bad:
            why.append("yıl kötüleşti " + ",".join(bad))
        if v["dd"] > base["dd"] + 2.0:
            why.append(f"maxDD +{v['dd'] - base['dd']:.1f}p")
        if v["worst"] < base["worst"] - 0.05:
            why.append(f"en kötü ay {base['worst']:+.1f}→{v['worst']:+.1f}")
        print(f"  {k:<28s} {'✓ GEÇTİ' if not why else '✗ ' + '; '.join(why)}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    raw = {}
    for c in COINS:
        try:
            raw[c] = fast_bt.load(c, source=source)
        except SystemExit:
            pass
    if only != "anchor":
        measure(raw)
        dose(raw)
    if only == "measure":
        return
    # ÖLÇÜM barını geçen olmasa bile ankor koşuluyor: hipotezin İDDİASI zaten portföy
    # seviyesinde ("kuyruk faydası evet, aylık kuyruk cezası hayır"), ve bu doğrusal
    # olmayan tek yer orası. Ölçüm barı geçilmediyse ankor sonucu KANIT DEĞİL, teşhistir.
    anchor(source, list(VARIANTS)[1:])


if __name__ == "__main__":
    main()
