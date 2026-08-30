"""
genis_stop.py — "geniş stoplu %2.3 bize ne kaybettiriyor?"

BULGUNUN KAYNAĞI: kaldirac_kademe.py TABAN yapılandırmada İHL=36 raporladı.
36 işlemin (%2.3) 2×ATR stopu, 10x'te likidasyon mesafesini (1/10 − %0.5 = %9.5)
AŞIYOR. O işlemlerde stop ÇALIŞMADAN likide olunur. Bu adayın getirdiği bir şey
değil — BUGÜN CANLIDA VAR.

⚠ ANKORUN KÖR NOKTASI: ankor sim'i likidasyona HİÇ bakmıyor. Fiyat stopa değince
−1R yazıyor. Ama likidasyon stoptan DAHA YAKIN olduğunda fiyat oraya ÖNCE değer:
  • kaybeden işlem: −1R yerine TÜM MARJİN gider
  • KAZANAN işlem bile: aleyhte hareket likidasyonu geçtiyse, ankor onu kazanç
    yazmış ama gerçekte pozisyon çoktan patlamıştır. ASIL TEHLİKE BU.

O yüzden burada MAE (en büyük aleyhte hareket) barlardan yeniden ölçülüyor ve
likidasyon stoptan ÖNCE kontrol ediliyor.

ÖLÇÜLEN:
  1) 36 işlem kim? (coin, yıl, stop mesafesi, nominal, marjin)
  2) Kaçı GERÇEKTEN likidasyon seviyesine değdi? (MAE ≥ likidasyon hareketi)
  3) Ankor ne yazdı, gerçekte ne olurdu → DOLAR farkı
  4) ÇÖZÜMLER: (a) o işlemleri alma  (b) onlarda kaldıracı düşür
     Maliyet: kaldıraç düşünce marjin büyür → bazı işlemler REDDEDİLİR.

Marjin modu .env'de ISOLATED (config.py:381) → likidasyon yalnız o pozisyonu
öldürür, hesabı değil. Bu zararı SINIRLIYOR ama sıfırlamıyor.

Kullanım:  python3 genis_stop.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn

BAKIM = 0.005          # MEXC bakım marjini (muhafazakâr) — kaldirac_kademe ile aynı
BAL = 190.0
ONK = 0.95             # canlı marjin ön-kontrolü


def lik_hareket(L: int) -> float:
    """Likidasyona kadar gereken aleyhte hareket (oran)."""
    return 1.0 / L - BAKIM


# ─────────── ANKORLA AYNI ÜRETİM, ARTI MAE ───────────
def gen_mae(sleeve, m, coin):
    """deployed_backtest.gen ile BİREBİR — tek fark: her işlemin MAE'sini
    (en büyük aleyhte hareket, giriş fiyatına oran) de döner.

    MAE stop/TP kontrolünden ÖNCE, aynı bar döngüsünde ölçülür; bar içi sıra
    bilinmediği için KÖTÜMSER varsayım: aleyhte uç önce görülür."""
    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
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
        e = cl[i]; sld = sl_a * a; slp_ = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i; mae = 0.0
        for j in range(i + 1, min(i + 1 + mh, n)):
            # MAE ÖNCE: bar içi sıra bilinmiyor, kötümser taraf
            aleyh = (e - lo[j]) / e if d_ == 1 else (hi[j] - e) / e
            mae = max(mae, aleyh)
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, mae, coin, sleeve))
        occ = j
    return out


def gen_bb_mae(m, coin):
    """BB kolu — deployed_backtest.gen_bb ile birebir + MAE."""
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, A.BB_TF)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    out = []; occ = -1
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1 or i <= occ: continue
        if idx[i].weekday() < 5: continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= A.BB_ADX_MAX: continue
        d_ = s.analyze(sub).direction
        if d_ == 0: continue
        a = float(av); sld = A.BB_SL_ATR * a
        e = cl[i]; slp_ = e - d_ * sld; tp = e + d_ * A.BB_RR * sld
        ep = None; j = i; mae = 0.0
        for j in range(i + 1, min(i + 1 + A.BB_MH, n)):
            aleyh = (e - lo[j]) / e if d_ == 1 else (hi[j] - e) / e
            mae = max(mae, aleyh)
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + A.BB_MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, mae, coin, "bb"))
        occ = j
    return out


def topla(source):
    ham = []
    for c in A.DONCH: ham += gen_mae("donchian", fast_bt.load(c, source=source), c)
    for c in A.SQZ:   ham += gen_mae("squeeze", fast_bt.load(c, source=source), c)
    for c in A.BB_COINS: ham += gen_bb_mae(fast_bt.load(c, source=source), c)
    return sorted(ham, key=lambda t: t[0])


def kademe_lev(slp, kademeler, guvenlik):
    """Stopun likidasyondan güvenli kaldığı EN YÜKSEK kaldıraç."""
    en = kademeler[0]
    for L in kademeler:
        if slp * guvenlik < lik_hareket(L):
            en = max(en, L)
    return en


def calistir(ham, cap, kademeler, guvenlik, likidasyon_uygula: bool):
    """Koltuk + marjin ön-kontrolü + (istenirse) LİKİDASYON uygulaması.
    Döner: (satirlar, red, tepe%, lik_sayisi)"""
    koltuk = []; ctr = 0; al = []; red = 0
    kullanim = 0.0; tepe = 0.0; lik = 0
    for e, x, R, slp, mae, coin, sleeve in ham:
        while koltuk and koltuk[0][0] <= e:
            _, _, mj = heapq.heappop(koltuk); kullanim -= mj
        if len(koltuk) >= A.MAXPOS:
            continue
        L = kademe_lev(slp, kademeler, guvenlik)
        nom = min(A.RISKF * BAL / slp, cap * BAL)
        marjin = nom / L
        if marjin > (BAL - kullanim) * ONK:
            red += 1
            continue
        kullanim += marjin; tepe = max(tepe, kullanim)
        ctr += 1
        heapq.heappush(koltuk, (x, ctr, marjin))
        # ── LİKİDASYON: aleyhte hareket likidasyon mesafesini geçti mi?
        patladi = likidasyon_uygula and (mae >= lik_hareket(L))
        if patladi:
            lik += 1
            pnl = -marjin                     # isolated: tüm marjin gider
        else:
            pnl = R * min(A.RISKF, cap * slp) * BAL
        al.append((x, pnl, R, slp, mae, coin, sleeve, L, nom, marjin, patladi))
    return al, red, tepe / BAL * 100, lik


def maxdd(pnl):
    eq = BAL + np.cumsum(pnl)
    e = np.concatenate([[BAL], eq])
    peak = np.maximum.accumulate(e)
    return ((peak - e) / peak).max() * 100


def ozet(al):
    pnl = np.array([r[1] for r in al])
    exits = [pd.Timestamp(r[0]) for r in al]
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in exits]
                    ).groupby(level=0).sum() / BAL * 100
    return pnl.sum(), maxdd(pnl), mon.min(), len(al)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("genis_stop.py — geniş stoplu işlemler bize ne kaybettiriyor?\n")
    print(f"  bakiye ${BAL:.0f} · bakım marjini %{BAKIM*100:.1f} · "
          f"10x'te likidasyon hareketi %{lik_hareket(10)*100:.1f}")
    ham = topla(source)
    print(f"  ham sinyal {len(ham)}")

    # ── DOĞRULAMA: likidasyon KAPALIYKEN ankorla birebir olmalı
    al0, red0, tepe0, _ = calistir(ham, A.CAP, [10], 2.0, likidasyon_uygula=False)
    tot0, dd0, ay0, n0 = ozet(al0)
    ok = (n0 == 1579) and abs(tot0 - 1420.66) < 0.5
    print(f"\n  DOĞRULAMA (likidasyon kapalı, CAP={A.CAP}): {n0} işlem / ${tot0:+.2f} "
          f"→ {'✓ ANKORLA BİREBİR' if ok else '⛔ ANKORDAN SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — bu araçla hüküm verilemez.")

    # ── 1) 36 KİM? ───────────────────────────────────────────────────────────
    tehlike = [r for r in al0 if r[3] >= lik_hareket(10)]
    print(f"\n{'='*78}\n1) STOPU LİKİDASYONU AŞAN İŞLEMLER\n{'='*78}")
    print(f"  {len(tehlike)} işlem / {n0}  (%{len(tehlike)/n0*100:.1f}) — "
          f"stop mesafesi ≥ %{lik_hareket(10)*100:.1f}")
    if tehlike:
        slps = np.array([r[3] for r in tehlike]) * 100
        Rs = np.array([r[2] for r in tehlike])
        pn = np.array([r[1] for r in tehlike])
        print(f"  stop mesafesi: medyan %{np.median(slps):.1f} · "
              f"en geniş %{slps.max():.1f}")
        print(f"  ankorun yazdığı: ort {Rs.mean():+.3f}R · toplam ${pn.sum():+.2f} "
              f"({pn.sum()/tot0*100:+.1f}% toplam kârın)")
        print(f"  nominal ort ${np.mean([r[8] for r in tehlike]):.0f} · "
              f"marjin ort ${np.mean([r[9] for r in tehlike]):.2f}")
        cs = pd.Series([r[5] for r in tehlike]).value_counts()
        print(f"  coinler: " + ", ".join(f"{k}:{v}" for k, v in cs.items()))
        ys = pd.Series([pd.Timestamp(r[0]).year for r in tehlike]).value_counts().sort_index()
        print(f"  yıllar : " + ", ".join(f"{k}:{v}" for k, v in ys.items()))

    # ── 2) KAÇI GERÇEKTEN PATLARDI? ──────────────────────────────────────────
    print(f"\n{'='*78}\n2) KAÇI GERÇEKTEN LİKİDASYONA DEĞDİ? (MAE ölçüldü)\n{'='*78}")
    al1, red1, tepe1, lik1 = calistir(ham, A.CAP, [10], 2.0, likidasyon_uygula=True)
    tot1, dd1, ay1, n1 = ozet(al1)
    patlayan = [r for r in al1 if r[10]]
    print(f"  Ankorun görmediği likidasyon: {lik1} işlem")
    if patlayan:
        kazanan_ama_patlayan = [r for r in patlayan if r[2] > 0]
        print(f"    bunlardan {len(kazanan_ama_patlayan)} tanesini ankor KAZANÇ yazmıştı")
        print(f"    (fiyat likidasyona değdi, sonra dönüp TP'ye gitti — gerçekte")
        print(f"     pozisyon çoktan patlamış olurdu)")
        for r in sorted(patlayan, key=lambda r: -abs(r[1]))[:8]:
            print(f"      {pd.Timestamp(r[0]).date()} {r[5]:<5s} {r[6]:<8s} "
                  f"stop %{r[3]*100:4.1f} MAE %{r[4]*100:5.1f} "
                  f"ankor {r[2]:+.2f}R → gerçek ${r[1]:+.2f}")
    print(f"\n  {'':22s}{'işlem':>7s} {'toplam$':>9s} {'maxDD':>7s} {'kötü ay':>8s}")
    print(f"  {'ANKOR (likidasyon YOK)':22s}{n0:>7d} {tot0:>+9.0f} {dd0:>7.1f} {ay0:>8.1f}")
    print(f"  {'GERÇEK (likidasyonlu)':22s}{n1:>7d} {tot1:>+9.0f} {dd1:>7.1f} {ay1:>8.1f}")
    print(f"  → GİZLİ MALİYET: ${tot1-tot0:+.2f} "
          f"({(tot1-tot0)/tot0*100:+.1f}%) · maxDD {dd1-dd0:+.1f} puan")

    # ── 3) ÇÖZÜMLER ──────────────────────────────────────────────────────────
    print(f"\n{'='*78}\n3) ÇÖZÜMLER — maliyeti ne?\n{'='*78}")
    print(f"  {'çözüm':<34s}{'işlem':>6s} {'RED':>4s} {'LİK':>4s} {'toplam$':>9s} "
          f"{'Δ$':>7s} {'maxDD':>7s} {'kötü ay':>8s} {'tepe%':>6s}")
    print(f"  {'GERÇEK taban (10x sabit)':<34s}{n1:>6d} {red1:>4d} {lik1:>4d} "
          f"{tot1:>+9.0f} {0:>7.0f} {dd1:>7.1f} {ay1:>8.1f} {tepe1:>6.0f}")

    # (a) geniş stoplu işlemi HİÇ ALMA
    ham_a = [t for t in ham if t[3] < lik_hareket(10)]
    ala, reda, tepea, lika = calistir(ham_a, A.CAP, [10], 2.0, True)
    tota, dda, aya, na = ozet(ala)
    print(f"  {'(a) stop≥%9.5 ise İŞLEMİ ALMA':<34s}{na:>6d} {reda:>4d} {lika:>4d} "
          f"{tota:>+9.0f} {tota-tot1:>+7.0f} {dda:>7.1f} {aya:>8.1f} {tepea:>6.0f}")

    # (b) kaldıraç kademesi AŞAĞI — geniş stopta düşük kaldıraç
    for kad in ([5, 10], [3, 10], [2, 5, 10], [2, 3, 5, 10], [1, 2, 3, 5, 10]):
        for guv in (1.0, 2.0):
            alb, redb, tepeb, likb = calistir(ham, A.CAP, kad, guv, True)
            totb, ddb, ayb, nb = ozet(alb)
            et = f"(b) kaldıraç {'/'.join(map(str,kad))}x güv{guv:g}"
            print(f"  {et:<34s}{nb:>6d} {redb:>4d} {likb:>4d} {totb:>+9.0f} "
                  f"{totb-tot1:>+7.0f} {ddb:>7.1f} {ayb:>8.1f} {tepeb:>6.0f}")

    print(f"\n  RED = marjin yetmediği için alınamayan işlem (kaldıraç düşünce marjin büyür)")
    print(f"  LİK = likide olan işlem (stop çalışmadan)")


if __name__ == "__main__":
    main()
