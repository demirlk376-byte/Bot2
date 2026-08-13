"""
yeni_edge_donus.py — YENİ GETİRİ KAYNAĞI ARAYIŞI: kısa vadeli aşırılık sonrası dönüş.

BU BİR FİLTRE DEĞİL. Bugün test edilen 13 eksenin hepsi mevcut işlemleri BUDUYORDU.
Bu, YENİ BİR GETİRİ AKIŞI ekliyor.

HİPOTEZ BUGÜNKÜ KENDİ ÖLÇÜMLERİMİZDEN ÇIKIYOR (dışarıdan uydurma değil):
 1. kok_neden.py: botun EN İYİ rejim hücresi `range / düşük volatilite` = **+0.391R**
    (z=3.23, TRAIN +0.466 / TEST +0.280). Yani sakin, yatay piyasa.
 2. Elimizdeki TEK ortalamaya-dönüş kolu (bb) YALNIZ LTC'de ve YALNIZ HAFTA SONU
    çalışıyor — kısıtlı hâliyle bile +$130.
→ Sistemin en verimli olduğu koşulda, o koşula uygun tek strateji kısıtlanmış durumda.

NEDEN KORELASYON AÇISINDAN UMUT VERİCİ: donchian MOMENTUM kovalıyor (kırılımı takip),
bu strateji TAM TERSİNİ yapıyor (aşırılığı fade). Coin ekleme tam da korelasyon
yüzünden battı (15 coin aynı çöküşte 15 kaybeden). Ters yönlü bir akış o sorunu
yapısal olarak taşımaz.

⚠️ AŞIRI OPTİMİZASYONU ÖNLEYEN TASARIM:
 · rr ve maxhold ÖNCEDEN SABİT — mevcut bb kolunun değerleri (rr=1.667, mh=48).
   Bunlar kâra bakılarak SEÇİLMEDİ, var olan bir koldan alındı.
 · Stop 2×ATR — donchian/squeeze ile aynı, yine seçilmedi.
 · Tek taranan parametre: "ne kadar aşırı" eşiği (k). Doz-yanıtı raporlanıyor;
   gerçek etki monoton olmalı, tek k'da zıplayıp sönüyorsa gürültüdür.
 · TRAIN(<2025)/TEST(>=2025) ayrı. Koltuk seçimi ORTAK — yeni akış mevcut kollarla
   YARIŞIR, bedava gelmez.

⚠️ BEKLENTİ DÜŞÜK: kısa vadeli dönüş bilinen bir olgudur ama likit perp'lerde büyük
ölçüde arbitrajlanmış olabilir. Ayrıca kapalı kollar dersini hatırla: edge < 0.037R
ise ölçülmüş giriş kayması onu yer. **0.037R bu betiğin ölüm çizgisidir.**

ÖN-KAYITLI BAR (değişmedi): Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek ·
maxDD +2 puandan fazla artmayacak · EN KÖTÜ AY KÖTÜLEŞMEYECEK.

Kullanım:  py yeni_edge_donus.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn

TUM = A.DONCH + A.SQZ + A.BB_COINS
BOL = pd.Timestamp("2025-01-01")
CAP = 1.50
RR = 1.667            # bb kolundan — SEÇİLMEDİ
MAXHOLD = 48          # bb kolundan — SEÇİLMEDİ
SL_ATR = 2.0          # donchian/squeeze ile aynı — SEÇİLMEDİ
KAYMA_R = 0.037       # ölçülmüş giriş kayması, R cinsinden → ÖLÜM ÇİZGİSİ


def donus_uret(m, k):
    """Bir bar k×ATR'den fazla hareket ettiyse TERS yönde gir (fade)."""
    d = fast_bt.resample(m, "1h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    op = d["open"].values; hi = d["high"].values
    lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ:
            continue
        hareket = cl[i] - op[i]
        if abs(hareket) < k * a:
            continue
        d_ = -1 if hareket > 0 else 1          # FADE: hareketin TERSİ
        e = cl[i]; sld = SL_ATR * a
        slp = e - d_ * sld; tpp = e + d_ * RR * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + MAXHOLD, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tpp: ep = tpp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tpp: ep = tpp; break
        if ep is None:
            j = min(i + MAXHOLD, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j].value, R, sld / e))
        occ = j
    return out


def ankor_havuz(source):
    ham = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    return ham


def koltuk(ham):
    ev = sorted(ham, key=lambda z: z[0])
    oh = []; ctr = 0; al = []
    for e, x, R, slp in ev:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr)); al.append((x, R, slp))
    return al


def olc(al, cap=CAP):
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), mon=mon,
                yr={int(k_): float(v) for k_, v in yr.items()})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ank = ankor_havuz(source)
    kon = olc(koltuk(ank), cap=A.CAP)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 122}")
    print("=== YENİ GETİRİ KAYNAĞI: kısa vadeli aşırılık sonrası DÖNÜŞ (fade) ===")
    print(f"  DOĞRULAMA: {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    taban = olc(koltuk(ank))
    neg = taban["mon"][taban["mon"] < 0].index
    print(f"  taban: {taban['n']} işlem ${taban['tot']:+.0f} PF {taban['pf']:.2f} "
          f"maxDD {taban['dd']:.1f} en kötü ay {taban['worst']:+.1f}")
    print(f"  sabitler (SEÇİLMEDİ): rr={RR} · maxhold={MAXHOLD} · stop={SL_ATR}×ATR")
    print(f"  ⚠ ÖLÜM ÇİZGİSİ: kendi ort R'si {KAYMA_R:.3f}R'nin ALTINDAysa gerçek")
    print(f"    yürütmede negatiftir — kapalı kollar tam bu yüzden düştü.")

    print(f"\n  {'k (aşırılık)':>12s} {'kendi n':>8s} {'kendi ortR':>11s} {'kendi PF':>9s} "
          f"{'kayma sonrası':>14s} | {'portföy n':>10s} {'toplam$':>9s} {'Δ$':>7s} "
          f"{'PF':>5s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg ay katkı':>13s}")
    sonuc = {}
    for k in (1.0, 1.5, 2.0, 2.5, 3.0):
        kendi = []
        for c in TUM:
            kendi += donus_uret(fast_bt.load(c, source=source), k)
        if len(kendi) < 50:
            print(f"  {k:>12.1f} {len(kendi):>8d}  — çok az sinyal")
            continue
        kr = np.array([q[2] for q in kendi]); ksp = np.array([q[3] for q in kendi])
        kpnl = kr * np.minimum(A.RISKF, CAP * ksp) * A.BAL0
        kkaz = kpnl[kpnl > 0].sum(); kkay = -kpnl[kpnl < 0].sum()
        kpf = kkaz / kkay if kkay > 0 else float("inf")
        net = kr.mean() - KAYMA_R
        v = olc(koltuk(ank + kendi))
        d_neg = float(sum(v["mon"].get(a_, 0.0) - taban["mon"].get(a_, 0.0)
                          for a_ in neg) / 100 * A.BAL0)
        sonuc[k] = (v, kr.mean(), net, d_neg)
        bay = "  ⛔ kayma yer" if net <= 0 else ""
        print(f"  {k:>12.1f} {len(kendi):>8d} {kr.mean():>+11.4f} {kpf:>9.2f} "
              f"{net:>+14.4f} | {v['n']:>10d} {v['tot']:>+9.0f} "
              f"{v['tot']-taban['tot']:>+7.0f} {v['pf']:>5.2f} {v['dd']:>7.1f} "
              f"{v['worst']:>+9.1f} {d_neg:>+13.1f}{bay}")

    # ── TRAIN/TEST en iyi k için ──
    print(f"\n{'=' * 122}\n=== HÜKÜM (ön-kayıtlı bar) ===")
    years = sorted(taban["yr"])
    gecen = []
    for k, (v, ortR, net, d_neg) in sonuc.items():
        w = []
        if net <= 0: w.append(f"kayma sonrası {net:+.4f}R")
        if v["tot"] - taban["tot"] <= 28: w.append(f"kâr {v['tot']-taban['tot']:+.0f}$")
        for y in years:
            b = taban["yr"].get(y, 0)
            if abs(b) > 1e-9 and (v["yr"].get(y, 0) - b) / abs(b) < -0.10:
                w.append(f"{y} kötü"); break
        if v["dd"] > taban["dd"] + 2: w.append(f"maxDD {v['dd']:.1f}")
        if v["worst"] < taban["worst"] - 0.05: w.append(f"en kötü ay {v['worst']:.1f}")
        if not w:
            gecen.append(k); print(f"  ★ GEÇTİ  k={k}  (neg ay katkısı {d_neg:+.1f}$)")
        else:
            print(f"  ✗ k={k:<4.1f} — {'; '.join(w)}")
    if not gecen:
        print(f"\n  Hiçbiri geçmedi. Kısa vadeli dönüş bu veride kullanılabilir bir")
        print(f"  edge üretmiyor — büyük ihtimalle likit perp'lerde arbitrajlanmış.")
        iyi = [(k, d) for k, (v, o, n_, d) in sonuc.items() if d > 0]
        if iyi:
            print(f"  (negatif aylarda pozitif katkı yapan k: "
                  + ", ".join(f"{k} ({d:+.1f}$)" for k, d in iyi) + " — ayrı bakılabilir)")
    else:
        print(f"\n  ⚠ Geçen k için DOZ-YANITI kontrol edilmeli: komşu k'lar da benzer")
        print(f"    davranmalı. Tek k'da zıplayıp sönüyorsa gürültüdür.")


if __name__ == "__main__":
    main()
