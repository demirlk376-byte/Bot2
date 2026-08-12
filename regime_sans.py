"""
regime_sans.py — HİÇ SORMADIĞIM SORU: kötü aylar "kötü rejim" mi, yoksa KÖTÜ ŞANS mı?

BUGÜN ÜÇ REJİM DENEMESİ DE ÇÖKTÜ (kapı, günlük fren, koşullu koltuk). Her seferinde
zayıf bir sinyal bulundu, kapıya çevrilince dağıldı. Bu kadar tutarlı başarısızlık
tesadüf değil — altında yapısal bir sebep olmalı. Bu betik o sebebi ölçer.

Bot %43.5 kazanma oranıyla çalışıyor. Yani her ay zaten bir zar atışı. Eğer 8 negatif ay,
AYNI işlemlerin sonuçları rastgele karıştırıldığında da ortaya çıkıyorsa, o aylarda
BULUNACAK HİÇBİR REJİM BİLGİSİ YOKTUR ve bütün denemelerin neden çöktüğü tek cümleyle
açıklanır.

[A] KARIŞTIRMA TESTİ — kesin cevap veren test
    Aynı 1579 işlemin (R, sl_pct) çiftleri rastgele PERMÜTE edilir; çıkış tarihleri
    ve ay başına işlem sayısı AYNEN korunur. Yani soru şu: iyi/kötü sonuçların AYLARA
    DAĞILIMI rastgeleden farklı mı?
     · Gerçek en kötü ay, karıştırılmış dağılımın İÇİNDEyse → kayıplar zamanda
       kümelenmiyor → rejim bilgisi YOK → hiçbir filtre çalışamaz. Eksen matematiksel
       olarak kapanır, deneyerek değil.
     · DIŞINDAysa → kayıplar gerçekten kümeleniyor → rejim VAR, aramaya devam etmek
       anlamlı.
    10.000 permütasyon.

[B] NET YÖN YOĞUNLAŞMASI — kullanıcı fikrinin en keskin hâli, hiç ölçülmedi
    Korelasyon testi çöktü çünkü defter hem long hem short taşıyor; coin korelasyonu
    ancak pozisyonlar AYNI TARAFA bakıyorsa riski yoğunlaştırır. Yedi pozisyonun yedisi
    de long ise o gerçekten TEK bahistir; dört long üç short ise değildir.
    Ölçülen: her işlemin girişinde açık defterin tek-yanlılığı
        tek_yan = |long - short| / toplam   (0 = dengeli, 1 = tamamen tek taraflı)
    ve günlük portföy sonucunun bu değişkene göre dağılımı.

⚠️ YÖN BİLGİSİ: A.gen yönü içeride hesaplıyor (d_) ama DÖNDÜRMÜYOR. Döngü burada
yönü de verecek şekilde çoğaltıldı. DAHA ÖNCE STRATEJİ TAKLİT EDİP YANLIŞ SONUÇ
ÜRETTİM (pw_mtf_sleeve: 1697 işlem/$1366 vs ankor 1579/$1421). Bu yüzden çoğaltılan
döngünün ürettiği HER İŞLEM ankorunkiyle BİREBİR karşılaştırılıyor; tek bir sapma
varsa betik hiçbir sayı yazmadan DURUR.

Kullanım:  py regime_sans.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

CAP_YENI = 1.50
PERM = 10000


def gen_dir(sleeve, m):
    """A.gen'in BİREBİR kopyası + yön (d_). Eşdeğerliği main()'de KANITLANIYOR."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
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
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, d_)); occ = j
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 112}")
    print("=== KÖTÜ AYLAR: REJİM Mİ, ŞANS MI? ===")

    # ── EŞDEĞERLİK KANITI ──
    ham = []
    sapma = 0
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            m = fast_bt.load(c, source=source)
            ref = A.gen(kol, m)
            mine = gen_dir(kol, m)
            if len(ref) != len(mine) or any(
                    r[0] != k[0] or r[1] != k[1] or abs(r[2] - k[2]) > 1e-12
                    or abs(r[3] - k[3]) > 1e-12 for r, k in zip(ref, mine)):
                sapma += 1
            for t in mine:
                ham.append((t[0], t[1].value, t[2], t[3], t[4]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3], 0))   # bb: yön yok, nötr say
    print(f"\n  EŞDEĞERLİK KANITI (yön ekli döngü == ankor): "
          f"{'✓ 11 coinin hepsinde BİREBİR' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}")
    if sapma:
        print("  Çoğaltılan döngü ankordan farklı üretiyor. HİÇBİR SAYI OKUNMAZ.")
        return

    ham.sort(key=lambda z: z[0])
    openh = []; ctr = 0; al = []
    for e_ns, x_ns, R, slp, d_ in ham:
        while openh and openh[0][0] <= e_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (x_ns, ctr))
            al.append((e_ns, x_ns, R, slp, d_))
    r = np.array([a[2] for a in al]); sp = np.array([a[3] for a in al])
    kon = float((r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0).sum())
    ok = len(al) == 1579 and abs(kon - 1420.66) < 0.01
    print(f"  KONTROL: {len(al)} işlem / ${kon:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return

    eff = np.minimum(A.RISKF, CAP_YENI * sp)
    pnl = r * eff * A.BAL0
    ay = pd.Series([pd.Timestamp(a[1]).to_period("M") for a in al])

    ger = pd.Series(pnl).groupby(ay).sum() / A.BAL0 * 100
    g_neg = int((ger < 0).sum()); g_worst = float(ger.min()); g_ay = len(ger)

    # ── [A] KARIŞTIRMA TESTİ ──
    print(f"\n[A] KARIŞTIRMA TESTİ — {PERM} permütasyon")
    print(f"    Çıkış tarihleri ve ay başına işlem sayısı SABİT; yalnız hangi sonucun")
    print(f"    hangi işleme düştüğü karıştırılıyor.")
    rng = np.random.default_rng(20260812)
    kod = ay.astype(str).values
    _, inv = np.unique(kod, return_inverse=True)
    K = inv.max() + 1
    negler = np.empty(PERM, dtype=int); worstler = np.empty(PERM)
    for it in range(PERM):
        p = rng.permutation(len(pnl))
        toplam = np.bincount(inv, weights=pnl[p], minlength=K) / A.BAL0 * 100
        negler[it] = int((toplam < 0).sum())
        worstler[it] = toplam.min()

    p_neg = float((negler >= g_neg).mean())
    p_worst = float((worstler <= g_worst).mean())
    print(f"\n    {'ölçüt':<22s} {'GERÇEK':>9s} {'karışık medyan':>15s} "
          f"{'karışık %5-%95':>20s} {'p-değeri':>10s}")
    print(f"    {'negatif ay sayısı':<22s} {g_neg:>9d} {np.median(negler):>15.0f} "
          f"{f'{np.percentile(negler,5):.0f} … {np.percentile(negler,95):.0f}':>20s} "
          f"{p_neg:>10.3f}")
    print(f"    {'en kötü ay %':<22s} {g_worst:>+9.1f} {np.median(worstler):>+15.1f} "
          f"{f'{np.percentile(worstler,5):+.1f} … {np.percentile(worstler,95):+.1f}':>20s} "
          f"{p_worst:>10.3f}")

    print(f"\n    HÜKÜM:")
    if p_neg > 0.05 and p_worst > 0.05:
        print(f"    → KÖTÜ AYLAR ŞANSTAN AYIRT EDİLEMİYOR (p={p_neg:.3f} / {p_worst:.3f}).")
        print(f"      Kayıplar zamanda KÜMELENMİYOR. Aynı işlemler rastgele sıralandığında")
        print(f"      da bu kadar kötü ay ve bu derinlikte bir dip çıkıyor.")
        print(f"      → İçinde REJİM BİLGİSİ OLMAYAN bir şeyi filtrelemeye çalışıyorduk.")
        print(f"        Üç denemenin de çökmesinin sebebi bu. Eksen deneyerek değil,")
        print(f"        MATEMATİKSEL olarak kapanır.")
    else:
        print(f"    → Kayıplar rastgeleden FARKLI kümeleniyor (p={p_neg:.3f} / {p_worst:.3f}).")
        print(f"      Rejim bilgisi VAR; aramaya devam etmek anlamlı.")

    # ── [B] NET YÖN YOĞUNLAŞMASI ──
    print(f"\n[B] NET YÖN YOĞUNLAŞMASI — defter ne kadar tek taraflı?")
    openh2 = []; tek_yan = []
    aktif = []
    for e_ns, x_ns, R, slp, d_ in al:
        aktif = [q for q in aktif if q[0] > e_ns]
        if aktif:
            yon = np.array([q[1] for q in aktif])
            nz = yon[yon != 0]
            ty = abs(nz.sum()) / len(nz) if len(nz) else 0.0
        else:
            ty = 0.0
        tek_yan.append(ty)
        aktif.append((x_ns, d_))
    tek_yan = np.array(tek_yan)

    gun = [pd.Timestamp(a[1]).normalize() for a in al]
    gt = pd.DataFrame({"pnl": pnl, "ty": tek_yan, "gun": gun})
    gg = gt.groupby("gun").agg(pnl=("pnl", "sum"), ty=("ty", "mean"))
    gg["dilim"] = pd.qcut(gg["ty"], 5, labels=False, duplicates="drop")
    print(f"\n    {'dilim':>6s} {'tek-yanlılık':>13s} {'gün':>5s} {'ort PnL$':>9s} "
          f"{'std PnL$':>9s} {'en kötü gün$':>13s}")
    for q in sorted(gg["dilim"].dropna().unique()):
        s = gg[gg.dilim == q]
        print(f"    {'Q'+str(int(q)+1):>6s} {s['ty'].mean():>13.3f} {len(s):>5d} "
              f"{s['pnl'].mean():>+9.2f} {s['pnl'].std():>9.2f} {s['pnl'].min():>+13.2f}")
    a1 = gg[gg.dilim == 0]["pnl"]; a5 = gg[gg.dilim == gg["dilim"].max()]["pnl"]
    F = a5.var(ddof=1) / a1.var(ddof=1)
    print(f"\n    yayılma oranı Q5/Q1 = {F:.2f}")
    BOL = pd.Timestamp("2025-01-01")
    for ad, alt in (("TRAIN", gg[gg.index < BOL]), ("TEST", gg[gg.index >= BOL])):
        b1 = alt[alt.dilim == 0]["pnl"]; b5 = alt[alt.dilim == alt["dilim"].max()]["pnl"]
        if len(b1) > 10 and len(b5) > 10:
            print(f"    {ad:<5s} yayılma {b5.var(ddof=1)/b1.var(ddof=1):>5.2f}  "
                  f"ort {b5.mean():+.2f}$ vs {b1.mean():+.2f}$  "
                  f"en kötü {b5.min():+.2f}$ vs {b1.min():+.2f}$")
    print(f"\n    ⚠ Tam dönem oranı tek başına YETMEZ: korelasyon testinde tam dönem")
    print(f"      1.28 çıkmıştı ama TRAIN 0.58 / TEST 1.50 idi — zıt dönemlerin ortalaması.")
    print(f"      Karar TRAIN ve TEST satırlarının AYNI YÖNDE olmasına bakar.")


if __name__ == "__main__":
    main()
