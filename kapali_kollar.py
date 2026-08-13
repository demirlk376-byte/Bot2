"""
kapali_kollar.py — KODDA DURAN AMA KAPALI OLAN KOLLAR: açmaya değer mi?

BUGÜN HER ŞEY "mevcut üç kolu BUDAMAK" üzerineydi ve hepsi çöktü — budanacak bir şey
yok. Hiç sorulmayan soru: BAŞKA KOL var mı?

Kodda .env ile açılıp kapanan BEŞ kol duruyor (KOD DEĞİŞİKLİĞİ GEREKMİYOR):
  SR_BREAKOUT_ENABLED · FVG_ENABLED · IFVG_ENABLED · ASIA_BO_ENABLED · ORB_ENABLED
Dördü 1h stratejisi ve verimiz 1h → ölçülebilir.

NEDEN BU, COIN EKLEMEKTEN FARKLI:
Coin eklemek battı çünkü 15 coin AYNI donchian mantığıyla birlikte çöküyordu — en kötü
ay −21'den −58.8'e fırladı. Farklı bir STRATEJİ aynı çöküşte farklı davranır.
Kanıt elimizde: negatif ayların kol dağılımında squeeze **+$50** (donchian −$192).
Squeeze zararın kaynağı değil YASTIĞI. İkinci bir yastık aradığımız şey olabilir.

⚠️ BU YÜZDEN ASIL ÖLÇÜT TOPLAM KÂR DEĞİL: her kol için NEGATİF AYLARDAKİ katkı ayrıca
raporlanıyor. Tek başına vasat bir kol, donchian kanarken pozitifse değerlidir.

YÖNTEM:
 · Her kol AYRI AYRI ankorun havuzuna eklenir (aralarında seçim YOK → seçim yanlılığı yok).
 · Koltuk seçimi ortak (MAXPOS=7) — yeni kol mevcut kollarla YARIŞIR, bedava gelmez.
 · TRAIN(<2025)/TEST(>=2025) ayrı raporlanır.
 · Ön-kayıtlı bar (değişmedi): Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek ·
   maxDD +2 puandan fazla artmayacak · EN KÖTÜ AY KÖTÜLEŞMEYECEK.
 · Bu kollar SEVİYE bazlı (sl_price/tp_price üretiyorlar) — R kendi seviyelerinden
   hesaplanır, ankorun ATR mantığı DAYATILMAZ.

⚠️ DOĞRULAMA: yeni kol eklenmeden havuz ankoru BİREBİR üretmeli (1579 / $1420.66).

Kullanım:  py kapali_kollar.py local
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
MAXHOLD = 48          # 1h kol → 2 gün; ankorun squeeze'iyle aynı


def _naive(i):
    return i.tz_localize(None) if getattr(i, "tz", None) is not None else i


def kol_uret(ad, m):
    """Kapalı bir kolun sinyallerini üret. Seviye bazlı: sl/tp stratejiden gelir."""
    d = fast_bt.resample(m, "1h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)

    if ad == "sr":
        from strategies.sr_breakout import SrBreakoutStrategy
        s = SrBreakoutStrategy(); win = 200
    elif ad == "fvg":
        from strategies.fvg import FvgStrategy
        s = FvgStrategy(); win = 120
    elif ad == "ifvg":
        from strategies.ifvg import IfvgStrategy
        s = IfvgStrategy(); win = 120
    elif ad == "asia":
        from strategies.asia_bo import AsiaBoStrategy
        s = AsiaBoStrategy(); win = 60
    else:
        return []

    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ:
            continue
        try:
            sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a))
        except Exception:
            continue
        d_ = getattr(sg, "direction", 0)
        if d_ == 0:
            continue
        e = cl[i]
        slp = float(getattr(sg, "sl_price", 0.0) or 0.0)
        tpp = float(getattr(sg, "tp_price", 0.0) or 0.0)
        if slp <= 0 or tpp <= 0:
            continue
        sld = abs(e - slp)
        if sld <= 0 or sld / e > 0.20:      # saçma stop → at
            continue
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
    if not al:
        return None
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon),
                mon=mon, yr={int(k): float(v) for k, v in yr.items()})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ank = ankor_havuz(source)
    taban_al = koltuk(ank)
    kon = olc(taban_al, cap=A.CAP)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 122}")
    print("=== KAPALI KOLLAR: açmaya değer mi? ===")
    print(f"  DOĞRULAMA: {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    taban = olc(taban_al)
    neg_aylar = taban["mon"][taban["mon"] < 0].index
    print(f"  taban: {taban['n']} işlem ${taban['tot']:+.0f} PF {taban['pf']:.2f} "
          f"maxDD {taban['dd']:.1f} en kötü ay {taban['worst']:+.1f} "
          f"{taban['negay']}/{taban['ay']} neg")
    print(f"\n  ⚠ ASIL ÖLÇÜT TOPLAM KÂR DEĞİL: 'neg ay katkısı' sütunu, donchian kanarken")
    print(f"    o kolun ne yaptığını gösterir. Squeeze orada +$50 (donchian −$192).")

    print(f"\n  {'kol':<8s} {'kendi n':>8s} {'kendi ortR':>11s} {'kendi PF':>9s} | "
          f"{'portföy n':>10s} {'toplam$':>9s} {'Δ$':>7s} {'PF':>5s} {'maxDD%':>7s} "
          f"{'kötü ay%':>9s} {'neg ay katkısı':>15s}")
    sonuc = {}
    for ad in ("sr", "fvg", "ifvg", "asia"):
        kendi = []
        for c in TUM:
            kendi += kol_uret(ad, fast_bt.load(c, source=source))
        if not kendi:
            print(f"  {ad:<8s} {'sinyal YOK':>8s}")
            continue
        kr = np.array([k[2] for k in kendi])
        ksp = np.array([k[3] for k in kendi])
        kpnl = kr * np.minimum(A.RISKF, CAP * ksp) * A.BAL0
        kkaz = kpnl[kpnl > 0].sum(); kkay = -kpnl[kpnl < 0].sum()
        kpf = kkaz / kkay if kkay > 0 else float("inf")

        v = olc(koltuk(ank + kendi))
        # negatif aylardaki katkı: portföy o aylarda ne kadar değişti
        d_neg = float(sum(v["mon"].get(a_, 0.0) - taban["mon"].get(a_, 0.0)
                          for a_ in neg_aylar) / 100 * A.BAL0)
        sonuc[ad] = (v, d_neg)
        print(f"  {ad:<8s} {len(kendi):>8d} {kr.mean():>+11.4f} {kpf:>9.2f} | "
              f"{v['n']:>10d} {v['tot']:>+9.0f} {v['tot']-taban['tot']:>+7.0f} "
              f"{v['pf']:>5.2f} {v['dd']:>7.1f} {v['worst']:>+9.1f} {d_neg:>+15.1f}")

    # ── HÜKÜM ──
    print(f"\n{'=' * 122}\n=== HÜKÜM (ön-kayıtlı bar) ===")
    years = sorted(taban["yr"])
    gecen = []
    for ad, (v, d_neg) in sonuc.items():
        w = []
        if v["tot"] - taban["tot"] <= 28: w.append(f"kâr {v['tot']-taban['tot']:+.0f}$")
        for y in years:
            b = taban["yr"].get(y, 0)
            if abs(b) > 1e-9 and (v["yr"].get(y, 0) - b) / abs(b) < -0.10:
                w.append(f"{y} kötü"); break
        if v["dd"] > taban["dd"] + 2: w.append(f"maxDD {v['dd']:.1f}")
        if v["worst"] < taban["worst"] - 0.05: w.append(f"en kötü ay {v['worst']:.1f}")
        if not w:
            gecen.append(ad); print(f"  ★ GEÇTİ  {ad}  (neg ay katkısı {d_neg:+.1f}$)")
        else:
            ek = f"  [neg ay katkısı {d_neg:+.1f}$]" if d_neg > 0 else ""
            print(f"  ✗ {ad:<6s} — {'; '.join(w)}{ek}")
    if not gecen:
        print(f"\n  Hiçbiri barı geçmedi.")
        iyi = [(a, d) for a, (v, d) in sonuc.items() if d > 0]
        if iyi:
            print(f"  AMA negatif aylarda POZİTİF katkı yapan var: "
                  + ", ".join(f"{a} ({d:+.1f}$)" for a, d in iyi))
            print(f"  → Bu, 'toplam kâr' barını geçmese de ÇEŞİTLENDİRME değeri demektir.")
            print(f"    Ayrı değerlendirilmeli: kuyruk iyileşiyorsa kâr kaybı fiyat olabilir.")
    print(f"\n  NOT: bu kollar .env ile açılıyor (ORB/ASIA_BO/SR_BREAKOUT/FVG/IFVG_ENABLED)")
    print(f"  — kod değişikliği YOK, geri alınabilir.")


if __name__ == "__main__":
    main()
