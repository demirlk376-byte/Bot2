"""
kar_kilidi.py — PORTFÖY SEVİYESİ KÂR KİLİDİ. Son büyük test edilmemiş eksen.

NEDEN BU, KAPANAN 28 EKSENDEN FARKLI:
Ağustos olayında −$102'lik düşüşün ayrıştırması şuydu (DURUM 4i):
    $51.30 TASARLANMIŞ risk (stoplar çalıştı, olması gereken)
  + $50.62 GERİ VERİLEN AÇIK KÂR  ← bu tasarlanmış değil
İkinci kalem hiç ele alınmadı. İşlem-bazlı kısmi TP zaten REDDEDİLMİŞTİ
(kazananları erken kesmek şişman kuyruğu öldürüyor). Bu ONDAN FARKLI: tek
işleme değil, PORTFÖYÜN TOPLAM açık kârına bakıyor. Yani yalnız "altı pozisyon
birden kâra geçmiş" gibi ANLARDA devreye giriyor — tam da Ağustos'taki an.

İKİ KURAL SINANIYOR (ikisi de lookahead'siz, bar bar):
  A) BAŞABAŞ KİLİDİ — portföyün açık kârı bakiyenin %X'ini geçince TÜM açık
     pozisyonların stopu başabaşa çekilir. Sonra fiyat girişe dönerse 0'da
     çıkılır (maliyet düşülerek).
  B) PORTFÖY TAKİP STOPU — portföyün açık kâr ZİRVESİ takip edilir; zirveden
     %Z geri verilirse TÜM açık pozisyonlar o barda kapatılır.

⚠ KÖTÜMSER MARK: tetikleme bar KAPANIŞIYLA değil, barın ALEYHTEKİ UCUYLA
  ölçülür. Kapanışla ölçmek kilidi olduğundan iyi gösterir.

⚠ ÖN-KAYIT (sonuç görülmeden yazıldı):
  Aday normalize kârı (kâr × maxDD_taban/maxDD_aday) tabandan >%5 iyileştirmeli
  VE en kötü ay kötüleşmemeli. Ham kâr düşüşü tek başına ret sebebi DEĞİL —
  bu kuralın işi kuyruk kısmak.

⚠ Araç önce KURALSIZ halini ankora karşı doğrular; tutmazsa hüküm BASMAZ.

Kullanım:  python3 kar_kilidi.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn

BAL = 190.0
CIKIS_MALIYET = 0.0002      # kilit tetiklenince erken çıkışın ek maliyeti (R değil, oran)


# ─────────────── ankorla aynı üretim + BAR BAR YOL ───────────────
def _yol_donchian_squeeze(sleeve, m, coin):
    """A.gen ile BİREBİR; ek olarak her barın (ts, kapanış R, ALEYHTE uç R)
    üçlüsünü döner. Aleyhte uç kötümser tetikleme için."""
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
        ep = None; j = i; yol = []
        for j in range(i + 1, min(i + 1 + mh, n)):
            # kötümser: aleyhteki uç ÖNCE görülür varsayımı
            aleyh = lo[j] if d_ == 1 else hi[j]
            yol.append((idx[j].value,
                        d_ * (cl[j] - e) / sld,          # kapanış R
                        d_ * (aleyh - e) / sld))         # aleyhte uç R
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append({"e": idx[i].value, "x": idx[j].value, "R": R,
                    "slp": sld / e, "coin": coin, "kol": sleeve, "yol": yol})
        occ = j
    return out


def _yol_bb(m, coin):
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
        ep = None; j = i; yol = []
        for j in range(i + 1, min(i + 1 + A.BB_MH, n)):
            aleyh = lo[j] if d_ == 1 else hi[j]
            yol.append((idx[j].value, d_ * (cl[j] - e) / sld, d_ * (aleyh - e) / sld))
            if d_ == 1:
                if lo[j] <= slp_: ep = slp_; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp_: ep = slp_; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + A.BB_MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append({"e": idx[i].value, "x": idx[j].value, "R": R,
                    "slp": sld / e, "coin": coin, "kol": "bb", "yol": yol})
        occ = j
    return out


def topla(source):
    h = []
    for c in A.DONCH: h += _yol_donchian_squeeze("donchian", fast_bt.load(c, source=source), c)
    for c in A.SQZ:   h += _yol_donchian_squeeze("squeeze", fast_bt.load(c, source=source), c)
    for c in A.BB_COINS: h += _yol_bb(fast_bt.load(c, source=source), c)
    return sorted(h, key=lambda t: t["e"])


def koltuk(ham):
    """A.seat_select ile aynı mantık; sözlükleri döner."""
    openh = []; al = []; ctr = 0
    for t in ham:
        while openh and openh[0][0] <= t["e"]:
            heapq.heappop(openh)
        if len(openh) >= A.MAXPOS:
            continue
        ctr += 1
        heapq.heappush(openh, (t["x"], ctr))
        al.append(t)
    return al


def simule(alinan, kural=None):
    """Bar bar portföy simülasyonu. kural(None) = ankor.
    kural: dict(tip='be'|'takip', esik=..., geri=...)
    Döner: her işlem için (cikis_ns, gerçeklesen_R, slp)."""
    # olay tablosu: (ts, idx, R_kapanis, R_aleyhte)
    olay = []
    for i, t in enumerate(alinan):
        for ts, rk, ra in t["yol"]:
            olay.append((ts, i, rk, ra))
    olay.sort(key=lambda o: o[0])

    eff = [min(A.RISKF, A.CAP * t["slp"]) for t in alinan]
    sonuc = [None] * len(alinan)
    be_aktif = [False] * len(alinan)
    acik = {}                       # idx -> son bilinen R
    zirve = 0.0
    # işlem i'nin doğal çıkış zamanı
    dogal_x = [t["x"] for t in alinan]

    n = len(olay)
    k = 0
    while k < n:
        ts = olay[k][0]
        grup = []
        while k < n and olay[k][0] == ts:
            grup.append(olay[k]); k += 1
        # marklari guncelle
        for _ts, i, rk, ra in grup:
            if sonuc[i] is not None:
                continue
            acik[i] = rk
            # ── A) BAŞABAŞ: kilit aktifse ve ALEYHTE uç 0'ın altına indiyse çık
            if kural and kural["tip"] == "be" and be_aktif[i] and ra <= 0.0:
                sonuc[i] = (_ts, -CIKIS_MALIYET / max(alinan[i]["slp"], 1e-9), alinan[i]["slp"])
                acik.pop(i, None)
                continue
            # doğal çıkış
            if _ts >= dogal_x[i]:
                sonuc[i] = (dogal_x[i], alinan[i]["R"], alinan[i]["slp"])
                acik.pop(i, None)
        if not kural:
            continue
        # portföyün açık kârı ($)
        acik_kar = sum(acik[i] * eff[i] * BAL for i in acik)
        if kural["tip"] == "be":
            if acik_kar >= kural["esik"] * BAL:
                for i in acik:
                    be_aktif[i] = True
        elif kural["tip"] == "takip":
            zirve = max(zirve, acik_kar)
            if zirve >= kural["esik"] * BAL and acik_kar <= zirve * (1 - kural["geri"]):
                for i in list(acik):
                    sonuc[i] = (ts, acik[i] - CIKIS_MALIYET / max(alinan[i]["slp"], 1e-9),
                                alinan[i]["slp"])
                    acik.pop(i, None)
                zirve = 0.0
    for i, t in enumerate(alinan):
        if sonuc[i] is None:
            sonuc[i] = (t["x"], t["R"], t["slp"])
    return sonuc


def olc(sonuc):
    sonuc = sorted(sonuc, key=lambda s: s[0])          # ÇIKIŞ sırası (4w)
    r = np.array([s[1] for s in sonuc]); slp = np.array([s[2] for s in sonuc])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    e = np.concatenate([[BAL], BAL + np.cumsum(pnl)])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    ex = [pd.Timestamp(s[0], tz="UTC") for s in sonuc]
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M")
                                for x in ex]).groupby(level=0).sum() / BAL * 100
    return pnl.sum(), dd, mon.min(), len(sonuc)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("kar_kilidi.py — portföy seviyesi kâr kilidi (son test edilmemiş eksen)\n")
    ham = topla(source)
    alinan = koltuk(ham)
    t_kar, t_dd, t_ay, t_n = olc(simule(alinan, None))
    ok = (t_n == 1579) and abs(t_kar - 1420.66) < 0.5
    print(f"  DOĞRULAMA (kuralsız): {t_n} işlem / ${t_kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ ANKORDAN SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — bu araçla hüküm verilemez.")
    print(f"  taban: maxDD {t_dd:.1f} · en kötü ay {t_ay:.1f}\n")

    print(f"{'='*82}")
    print(f"  ÖLÇÜT: normalize kâr = kâr × (maxDD_taban / maxDD_aday)")
    print(f"  ÖN-KAYIT: normalize >%5 iyileşmeli VE en kötü ay kötüleşmemeli")
    print(f"{'='*82}")
    print(f"  {'kural':<36s}{'kâr$':>8s} {'Δ$':>7s} {'maxDD':>7s} "
          f"{'kötü ay':>8s} {'NORM':>7s} {'Δnorm':>7s}  BAR")
    print(f"  {'TABAN (kilitsiz)':<36s}{t_kar:>+8.0f} {0:>7.0f} {t_dd:>7.1f} "
          f"{t_ay:>8.1f} {t_kar:>7.0f} {0:>7.0f}")

    adaylar = []
    for esik in (0.05, 0.10, 0.15, 0.20):
        adaylar.append((f"A) BAŞABAŞ · açık kâr ≥%{esik*100:.0f}",
                        {"tip": "be", "esik": esik}))
    for esik in (0.10, 0.15, 0.20):
        for geri in (0.25, 0.40, 0.50):
            adaylar.append((f"B) TAKİP · zirve≥%{esik*100:.0f} geri %{geri*100:.0f}",
                            {"tip": "takip", "esik": esik, "geri": geri}))

    gecen = []
    for ad, k in adaylar:
        kar, dd, ay, n = olc(simule(alinan, k))
        norm = kar * (t_dd / dd) if dd > 0 else kar
        bar = ("✓ GEÇTİ" if (norm > t_kar * 1.05 and ay >= t_ay - 0.05)
               else ("✗ ay↓" if ay < t_ay - 0.05 else "✗ norm yetersiz"))
        if bar.startswith("✓"): gecen.append(ad)
        print(f"  {ad:<36s}{kar:>+8.0f} {kar-t_kar:>+7.0f} {dd:>7.1f} "
              f"{ay:>8.1f} {norm:>7.0f} {norm-t_kar:>+7.0f}  {bar}")

    print(f"\n{'='*82}\nHÜKÜM\n{'='*82}")
    if gecen:
        print(f"  ✓ {len(gecen)} aday barajı geçti:")
        for g in gecen:
            print(f"      {g}")
        print(f"  ⚠ Bu bir BACKTEST sonucu. Canlıya almadan önce dayanıklılık")
        print(f"    (ek kayma) ve uygulanabilirlik (tüm pozisyonları aynı anda")
        print(f"    kapatmak MEXC'te ne kadar sürer) ölçülmeli.")
    else:
        print(f"  ✗ Hiçbir kural barajı geçmedi. Portföy kâr kilidi ekseni de")
        print(f"    kapanıyor — 'geri verilen açık kâr' gerçek ama korumanın")
        print(f"    bedeli faydasından büyük.")


if __name__ == "__main__":
    main()
