"""
ankor_denetim.py — ANKORUN KENDİSİ DOĞRU MU? (bugün doğrulanmayan TEK şey)

BÜTÜN GÜN araçların ankoru YENİDEN ÜRETTİĞİ doğrulandı (1579 / $1420.66 birebir).
Ama ankorun DOĞRU olduğu hiç kontrol edilmedi. Her test onun üstüne kuruldu; ankor
yanlışsa bugünkü 14 hükmün hepsi yanlış tabana dayanıyor.

SOMUT ŞÜPHE — GİRİŞ FİYATI:
`A.gen` girişi O BARIN KAPANIŞINDAN yapıyor (`e = cl[i]`). Ama canlı bot barı ancak
KAPANDIKTAN SONRA görüyor ve piyasa emriyle giriyor. Yani ankor, emrin verildiği anda
ARTIK VAR OLMAYAN bir fiyattan alıyor. Bu bir "lookahead" değil (bar i'nin verisi
kapanışta bilinir) ama GERÇEKLEŞTİRİLEMEZ bir fiyattır.

DÖRT KADEMELİ DENETİM — her biri ankoru gerçeğe bir adım yaklaştırır:
  A0  ANKOR         giriş cl[i] · ücret 2×1bp · kayma YOK · fonlama YOK   ← bugünkü taban
  A1  +KAYMA        giriş cl[i] ama ölçülmüş 13.4bp giriş kayması düşülür
  A2  SONRAKİ AÇILIŞ giriş op[i+1] — CANLIDA GERÇEKTEN OLAN. Bar kapanışını
                     kaçırmanın bedeli burada görünür.
  A3  A2 + KAYMA + FONLAMA (−%2.2/yıl, tutma süresine orantılı)  ← EN DÜRÜST SAYI

⚠️ A2 KRİTİK: eğer edge burada ÇÖKÜYORSA, ankorun kârı kapanış fiyatına erişebilmekten
geliyor demektir ve canlıda ASLA elde edilemez. Bu, canlının neden ankorun altında
kaldığının gerçek açıklaması olurdu — ve bugüne kadar "örneklem küçük" diye
açıkladığım şeyin yerine geçerdi.

⚠️ A2 hayatta kalırsa ankor SAĞLAM demektir ve canlı-ankor farkı gerçekten örneklem
gürültüsüdür. İki sonuç da değerli.

DOĞRULAMA: A0 satırı ankoru BİREBİR üretmeli (1579 / $1420.66). Üretmiyorsa denetim
aracının kendisi bozuktur ve hiçbir satır okunmaz.

Kullanım:  py ankor_denetim.py local
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

CAP = 1.50
KAYMA_BP = 13.4          # ölçülmüş giriş kayması (live_verify)
FONLAMA_YIL = 0.022      # ölçülmüş fonlama maliyeti


def gen_mod(sleeve, m, sonraki_acilis, kayma_bp):
    """A.gen + iki değişiklik: (a) giriş sonraki barın AÇILIŞI, (b) giriş kayması.
    sonraki_acilis=False, kayma_bp=0 → A.gen ile BİREBİR aynı olmalı."""
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
    op = d["open"].values; hi = d["high"].values
    lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 2):
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

        # ── GİRİŞ FİYATI ──
        if sonraki_acilis:
            e = op[i + 1]           # canlıda gerçekten olan: bar kapandı, sonra gir
            bas = i + 1
        else:
            e = cl[i]               # ankorun varsayımı
            bas = i
        if kayma_bp:                # kayma HER ZAMAN aleyhe
            e = e * (1 + d_ * kayma_bp / 10000.0)

        sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = bas
        for j in range(bas + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        gun = (idx[j].value - idx[bas].value) / 1e9 / 86400
        out.append((idx[bas].value, idx[j].value, R, sld / e, gun))
        occ = j
    return out


def bb_havuz(source, kayma_bp):
    """BB kolu: A.gen_bb'yi olduğu gibi kullan, yalnız kaymayı R'den düş."""
    out = []
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            R = t[2]
            if kayma_bp:
                R -= (kayma_bp / 10000.0) / t[3]     # kayma / stop mesafesi = R kaybı
            gun = (t[1].value - t[0]) / 1e9 / 86400
            out.append((t[0], t[1].value, R, t[3], gun))
    return out


def koltuk(ham):
    ev = sorted(ham, key=lambda z: z[0])
    oh = []; ctr = 0; al = []
    for e, x, R, slp, gun in ev:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr)); al.append((x, R, slp, gun))
    return al


def olc(al, cap, fonlama=False):
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    gun = np.array([a[3] for a in al])
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    if fonlama:
        # fonlama nominale ve tutma süresine orantılı
        nom = np.minimum(A.RISKF / sp, cap) * A.BAL0
        pnl -= nom * FONLAMA_YIL * gun / 365.0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon))


def havuz(source, sonraki, kayma):
    ham = []
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            ham += gen_mod(kol, fast_bt.load(c, source=source), sonraki, kayma)
    ham += bb_havuz(source, kayma)
    return ham


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 118}")
    print("=== ANKOR DENETİMİ: ölçümün kendisi doğru mu? ===")
    print(f"  Bugün 14 hükmün hepsi ankorun üstüne kuruldu ama ankor hiç denetlenmedi.")

    a0 = olc(koltuk(havuz(source, False, 0.0)), A.CAP)
    ok = abs(a0["tot"] - 1420.66) < 1.0
    print(f"\n  DOĞRULAMA (A0 == ankor): {a0['n']} işlem / ${a0['tot']:+.2f} → "
          f"{'✓' if ok else '✗ SAPMA — denetim aracı bozuk, hiçbir satır okunmaz'}")
    if not ok:
        print(f"    (n-2 sınırı yüzünden birkaç işlem farkı olabilir; tutar ±$1 içinde olmalı)")
        return

    print(f"\n  {'kademe':<34s} {'işlem':>6s} {'toplam$':>9s} {'Δ%':>7s} {'PF':>6s} "
          f"{'WR%':>6s} {'ortR':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s}")
    kad = [
        ("A0 ANKOR (bugünkü taban)", False, 0.0, False),
        ("A1 +giriş kayması 13.4bp", False, KAYMA_BP, False),
        ("A2 SONRAKİ BARIN AÇILIŞI", True, 0.0, False),
        ("A3 A2 + kayma + fonlama", True, KAYMA_BP, True),
    ]
    ilk = None
    for ad, sonraki, kayma, fon in kad:
        v = olc(koltuk(havuz(source, sonraki, kayma)), CAP, fonlama=fon)
        if ilk is None:
            ilk = v["tot"]
        d = (v["tot"] / ilk - 1) * 100 if ilk else 0.0
        print(f"  {ad:<34s} {v['n']:>6d} {v['tot']:>+9.0f} {d:>+6.0f}% {v['pf']:>6.2f} "
              f"{v['wr']:>6.1f} {v['ortR']:>+7.3f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
              f"{v['negay']:>3d}/{v['ay']:<3d}")
        if ad.startswith("A2"):
            a2 = v
        if ad.startswith("A3"):
            a3 = v

    print(f"\n{'=' * 118}\n=== HÜKÜM ===")
    print(f"\n  A2 (sonraki barın açılışı) KRİTİK SATIR:")
    if a2["tot"] > 0 and a2["ortR"] > 0.10:
        print(f"    ✓ Edge HAYATTA. Ankorun kârı kapanış fiyatına erişmekten GELMİYOR.")
        print(f"      → Ankor sağlam; canlı-ankor farkı gerçekten örneklem gürültüsü.")
    elif a2["tot"] > 0:
        print(f"    ~ Edge zayıflayarak hayatta (ort R {a2['ortR']:+.3f}). Kapanışa erişmek")
        print(f"      kârın kayda değer bir kısmını açıklıyor.")
    else:
        print(f"    ⛔ EDGE ÇÖKTÜ. Ankorun kârı GERÇEKLEŞTİRİLEMEZ bir fiyattan geliyor.")
        print(f"      → Bugünkü bütün projeksiyonlar ve 'canlı neden geride' açıklaması")
        print(f"        YENİDEN YAZILMALI. Canlı geride çünkü ankor ulaşılamaz.")
    print(f"\n  A3 EN DÜRÜST SAYI: ${a3['tot']:+.0f} (ankorun %{a3['tot']/ilk*100:.0f}'i)")
    print(f"    ort R {a3['ortR']:+.4f} · PF {a3['pf']:.2f} · en kötü ay {a3['worst']:+.1f}")
    print(f"    Canlıda ölçülen ort R +0.0555 [%95: −0.357, +0.468] — A3 bu aralığın")
    print(f"    {'İÇİNDE' if -0.357 <= a3['ortR'] <= 0.468 else 'DIŞINDA'}.")


if __name__ == "__main__":
    main()
