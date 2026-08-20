"""
yon_kapi.py — "AYNI RÜZGÂR TERS ESERSE" — yönsel yığılma kapısı ölçülüyor.

KULLANICININ GÖZLEMİ: 6 pozisyon açık ve ALTISI DA LONG. Piyasa dönerse altısı
birlikte stoplanır (%13.5 eşzamanlı risk, tek yönde).

MEVCUT DURUM — kapı VAR ama kapsamı DAR:
    execution.py:21  _CORRELATED_GROUPS = ({BTC, ETH, SOL},)
    execution.py:377 max_correlated_direction = 2   (varsayılan, .env'de ezilmemiş)
Yani ETH+SOL çifti 2/2 ile DOLU ve kapı görevini yapmış; ama ADA/NEAR/BNB/BCH
hiçbir grupta olmadığı için TAMAMEN SERBEST. 6 pozisyonun 4'ü kapsam dışı.

⚠ NEDEN "GRUBU GENİŞLET" DEYİP GEÇMİYORUZ: bugün ic_bar 30 dilimin 30'unun da
POZİTİF olduğunu gösterdi. Donchian'ın kesilecek kötü grubu yok. Yönsel kapı da
sonuçta İŞLEM KESER — ve kesilen işlemler pozitif beklentili. Üstelik yönsel
yığılma muhtemelen TRENDLİ dönemlerde oluşuyor, yani sistemin para kazandığı
dönemde. Kesmek, kârın kaynağını kesmek olabilir.

O YÜZDEN ASIL SORU "kâr arttı mı" DEĞİL. Yönsel kapının işi kuyruk kısmak:
    maxDD düşerse, AYNI drawdown'a AYNI toleransla DAHA YÜKSEK risk alınabilir.
Ölçüt bu yüzden DRAWDOWN-NORMALİZE KÂR:
    normalize = kâr × (maxDD_taban / maxDD_aday)
Yani "aynı acıya katlanarak ne kadar kazanırdık". Bu sayı tabandan büyükse kapı
gerçekten değerli; küçükse kapı sadece kâr kesiyor demektir.

⚠ ÖN-KAYIT: aday, normalize kârı tabandan >%5 iyileştirmeli VE en kötü ay
kötüleşmemeli. Ham kârın düşmesi tek başına ret sebebi DEĞİL (amaç o değil).

Kullanım (VPS'te):
    nohup python3 -u yon_kapi.py local > /tmp/yon.log 2>&1 & disown
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy


def gen_yonlu(sleeve, m, coin):
    """A.gen ile BİREBİR aynı, ama YÖN de saklanıyor (A.gen yönü atıyor)."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
        d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl); out = []; occ = -1
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
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j].value, float(R), float(sld / e), d_, coin))
        occ = j
    return out


def gen_bb_yonlu(m, coin):
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
        e = cl[i]; slp = e - d_ * sld; tp = e + d_ * A.BB_RR * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + A.BB_MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + A.BB_MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j].value, float(R), float(sld / e), d_, coin))
        occ = j
    return out


def koltuk_yonlu(ham, yon_cap: int, kapsam: set | None):
    """A.seat_select + YÖNSEL KAPI.
    yon_cap=0 → kapı YOK (ankor davranışı).
    kapsam=None → TÜM coinler tek korelasyon grubu sayılır."""
    ev = sorted(ham, key=lambda z: z[0])
    oh = []; ctr = 0; al = []; kesilen = 0
    acik = []           # (cikis_ns, yon, coin)
    for e, x, R, slp, d_, coin in ev:
        while oh and oh[0][0] <= e:
            heapq.heappop(oh)
        acik = [p for p in acik if p[0] > e]
        if len(oh) >= A.MAXPOS:
            continue
        if yon_cap > 0 and (kapsam is None or coin in kapsam):
            ayni = sum(1 for _, yy, cc in acik
                       if yy == d_ and (kapsam is None or cc in kapsam))
            if ayni >= yon_cap:
                kesilen += 1
                continue
        ctr += 1
        heapq.heappush(oh, (x, ctr))
        acik.append((x, d_, coin))
        al.append((x, R, slp))
    return al, kesilen


def olc(al):
    if not al:
        return dict(n=0)
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    eff = np.minimum(A.RISKF, A.CAP * sp)
    pnl = r * eff * A.BAL0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yil = pd.Series(pnl).groupby([x.year for x in ex]).sum() / A.BAL0 * 100
    kz = pnl[pnl > 0].sum(); ky = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kz / ky) if ky > 0 else float("inf"),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), yil=yil)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("=" * 108)
    print("=== YÖNSEL YIĞILMA KAPISI — 'aynı rüzgâr ters eserse' ===")
    print("  Kapı ZATEN VAR (execution.py:377, max_correlated_direction=2) ama grubu")
    print("  yalnız {BTC,ETH,SOL}. Canlıdaki 6 long'un 4'ü (ADA/NEAR/BNB/BCH) kapsam")
    print("  DIŞINDA. Soru: grubu genişletmek işe yarar mı, yoksa kârı mı keser?")

    ham = []
    for c in A.DONCH:
        ham += gen_yonlu("donchian", fast_bt.load(c, source=source), c)
    for c in A.SQZ:
        ham += gen_yonlu("squeeze", fast_bt.load(c, source=source), c)
    for c in A.BB_COINS:
        ham += gen_bb_yonlu(fast_bt.load(c, source=source), c)

    al0, _ = koltuk_yonlu(ham, 0, None)
    T = olc(al0)
    ok = T["n"] == 1579 and abs(T["tot"] - 1420.66) < 1.0
    print(f"\n  DOĞRULAMA (kapı YOK == ankor): {T['n']} işlem / ${T['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — durduruldu'}")
    if not ok:
        print("    (tutmuyorsa: git checkout -- data/)")
        return

    y = np.array([t[4] for t in ham])
    print(f"\n  ham sinyal yön dağılımı: long {int((y>0).sum())} · short {int((y<0).sum())}")
    print(f"\n  TABAN: {T['n']} işlem  ${T['tot']:+.0f}  PF {T['pf']:.2f}  "
          f"maxDD {T['dd']:.1f}  en kötü ay {T['worst']:+.1f}")

    print(f"\n{'='*108}")
    print("  ÖLÇÜT: normalize kâr = kâr × (maxDD_taban / maxDD_aday)")
    print("  Yani 'aynı acıya katlanarak ne kadar kazanırdık'. Ham kârın düşmesi")
    print("  tek başına ret sebebi DEĞİL — kapının işi kuyruk kısmak.")
    print(f"\n  {'kapsam':<18s} {'cap':>4s} {'işlem':>6s} {'kesilen':>8s} {'kâr$':>7s} "
          f"{'maxDD':>7s} {'kötü ay':>8s} {'NORMALİZE':>10s} {'Δnorm':>7s}  BAR")
    print(f"  {'TABAN (kapısız)':<18s} {'—':>4s} {T['n']:>6d} {'—':>8s} {T['tot']:>+7.0f} "
          f"{T['dd']:>7.1f} {T['worst']:>+8.1f} {T['tot']:>10.0f} {'—':>7s}")
    tum = set(A.DONCH) | set(A.SQZ) | set(A.BB_COINS)
    btc_eth_sol = {"ETH", "SOL"}          # canlıdaki grup (BTC evrende yok)
    en_iyi = None
    for ad, kaps in (("mevcut {ETH,SOL}", btc_eth_sol), ("TÜM coinler", tum)):
        for cap in (2, 3, 4, 5):
            al, kes = koltuk_yonlu(ham, cap, kaps)
            M = olc(al)
            if not M.get("n"):
                continue
            norm = M["tot"] * (T["dd"] / M["dd"]) if M["dd"] > 0 else 0.0
            dn = norm - T["tot"]
            gecti = (norm > T["tot"] * 1.05) and (M["worst"] >= T["worst"] - 0.05)
            print(f"  {ad:<18s} {cap:>4d} {M['n']:>6d} {kes:>8d} {M['tot']:>+7.0f} "
                  f"{M['dd']:>7.1f} {M['worst']:>+8.1f} {norm:>10.0f} {dn:>+7.0f}  "
                  f"{'✓ GEÇTİ' if gecti else '✗'}")
            if gecti and (en_iyi is None or norm > en_iyi[1]):
                en_iyi = (f"{ad} cap={cap}", norm, M, kes)

    print(f"\n{'='*108}\n=== HÜKÜM ===")
    if en_iyi is None:
        print("  ✗ Hiçbir yönsel kapı normalize kârı %5'ten fazla iyileştirmedi.")
        print("    Yönsel yığılma GERÇEK bir risk ama kesmenin bedeli kazancından büyük.")
        print("    Muhtemel sebep: yığılma TRENDLİ dönemlerde oluşuyor — yani sistemin")
        print("    para kazandığı dönemde. Kesmek kârın kaynağını kesiyor.")
        print("\n  → Mevcut {ETH,SOL} kapısı yerinde kalsın; genişletme YAPILMASIN.")
        print("    'Altı long birlikte stoplanır' riski gerçek ama FİYATI VAR ve fiyat")
        print("    faydadan büyük. Riski azaltmanın yolu kapı değil, bakiye büyümesi.")
        return
    ad, norm, M, kes = en_iyi
    print(f"  ✓ EN İYİ: {ad}")
    print(f"    ham kâr ${M['tot']:+.0f} (taban ${T['tot']:+.0f}) · {kes} işlem kesildi")
    print(f"    maxDD {M['dd']:.1f} (taban {T['dd']:.1f}) → NORMALİZE ${norm:.0f} "
          f"({norm-T['tot']:+.0f})")
    print(f"    Yorum: aynı drawdown toleransıyla riski "
          f"{T['dd']/M['dd']:.2f}× artırıp bu kârı alabilirdik.")
    print(f"\n  ⚠ Bu bir BACKTEST. Canlıda uygulaması: execution.py:21")
    print(f"    _CORRELATED_GROUPS genişletilir + MAX_CORRELATED_DIRECTION ayarlanır.")
    print(f"    Risk artışı AYRI bir karardır ve DURUM.md kuralı hâlâ geçerli:")
    print(f"    bakiye $1.000'e kadar riske DOKUNMA.")


if __name__ == "__main__":
    main()
