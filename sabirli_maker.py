"""
sabirli_maker.py — SABIRLI MAKER GİRİŞ. Mezarlıktaki 29 eksenden yapısal olarak
                   FARKLI tek hayatta kalan öneri.

NEDEN FARKLI: 29 kapalı eksenin hepsi işlem KÜMESİNİ ya da BOYUTUNU
değiştiriyordu ve kesilen küme her seferinde pozitif beklentili çıkıyordu.
Bu öneri ikisine de dokunmuyor — AYNI 1579 işlem, aynı boyut, sadece GİRİŞ
FİYATI. Saf yürütme maliyeti.

ÖLÇÜLMÜŞ DAYANAK (kayma_denetim.py, canlı defterden):
    donchian giriş kayması  +15.32bp  [%95: +0.26, +30.38]
    maker yolunu kullanan bb kolu     −2.95bp
    fark                    +14.22bp  [+3.87, +24.57]  → SIFIRI DIŞLIYOR
MEXC ücret modeli iki uçtan doğrulandı: maker ~0 / taker ~1bp.

FİKİR: donchian'ın post-only limit penceresi bugün ~45 saniye. Tam bir BARA
(4 saat) çıkarılırsa dolum oranı artar, dolan her işlem 15.32bp yerine 0
kaymayla girer.

⚠ TUZAK — VE BU ÖLÇÜMÜN ASIL KONUSU: TERS SEÇİM.
Sabırlı bir limit alış, fiyat GERİ GELİRSE dolar. Kırılım koşarsa dolmaz.
Yani limit tercihen ZAYIF kırılımlarda dolar, güçlülerde dolmaz — kazandıran
kuyruğu kaçırırsın. Dolmayınca piyasaya düşülür ama artık 4 saat SONRAKİ
fiyattan. Bu araç her işlemin R'sini GERÇEK giriş fiyatından yeniden hesaplar,
böylece ters seçim otomatik olarak fiyata girer.

⚠ ÇÖZÜNÜRLÜK: 1dk veri yalnız BTC(Binance vekili)+ETH'de var. Ama "fiyat 4
saat içinde limiti GEÇTİ Mİ" sorusu 1h high/low ile TAM cevaplanır — 1dk'nın
eklediği tek şey 'ne zaman', ki dolum ikili kararını değiştirmiyor. Bu yüzden
7 donchian coininin HEPSİNDE ölçülüyor.

⚠ ÖN-KAYIT (sonuca bakılmadan yazıldı, gevşetilmeyecek):
  (1) 4h penceresinde, 2bp derinlik kuralıyla dolum oranı ≥ %42 olmalı.
      Altındaysa fikir ÖLÜ (başabaş noktası).
  (2) Portföy Δ$ ≥ +$28 (ankorun ön-kayıtlı barajı) ve en kötü ay kötüleşmesin.
  (3) Karar EN KÖTÜMSER derinlik satırından verilir (10bp), 0bp'den değil.

Kullanım:  python3 sabirli_maker.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn

BAL = 190.0
KAYMA_BP = 15.32          # ölçülen donchian giriş kayması (taker yolu)
TAKER_BP = 1.0            # MEXC taker, iki uçtan doğrulandı
MAKER_BP = 0.0            # MEXC maker
DERINLIKLER = [0.0, 2.0, 5.0, 10.0]
PENCERELER_H = [1, 2, 4]  # saat


def sinyaller(coin, source):
    """A.gen'in KAPILARIYLA birebir; occ UYGULANMAZ (maliyete bağlı çıkışa göre
    sonra uygulanır). Döner: (d4, d1, [(i, yon, atr)])"""
    from strategies.donchian import DonchianStrategy
    m = fast_bt.load(coin, source=source)
    d4 = fast_bt.resample(m, "4h")
    d1 = fast_bt.resample(m, "1h")
    atr_ser = atr_fn(d4["high"], d4["low"], d4["close"], 14).values
    _dc = d4["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
        d4.index.normalize()).values
    up = d4["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    out = []
    n = len(d4)
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sg = s.analyze(d4.iloc[max(0, i - 259):i + 1], float(a))
        if sg.direction == 0:
            continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((sg.direction == 1 and dup) or (sg.direction == -1 and not dup)):
            continue
        out.append((i, sg.direction, float(a)))
    return d4, d1, out


def _cikis(d4, i0, yon, giris, sld, mh, rr):
    """i0 barından itibaren SL/TP tara. Döner (cikis_bar, cikis_fiyat)."""
    hi = d4["high"].values; lo = d4["low"].values; cl = d4["close"].values
    n = len(cl)
    slp = giris - yon * sld
    tp = giris + yon * rr * sld
    j = i0
    for j in range(i0, min(i0 + mh, n)):
        if yon == 1:
            if lo[j] <= slp: return j, slp
            if hi[j] >= tp: return j, tp
        else:
            if hi[j] >= slp: return j, slp
            if lo[j] <= tp: return j, tp
    j = min(i0 + mh - 1, n - 1)
    return j, cl[j]


def kol(coin, source, mod, pencere_h=4, derinlik_bp=2.0, kovala_bp=20.0):
    """mod: 'ankor'  = A.gen birebir (kaymasız, 1bp×2) — makine doğrulaması
            'taker'  = bugünkü GERÇEK yol: piyasa girişi + 15.32bp kayma
            'sabirli'= post-only limit, pencere_h saat; dolmazsa piyasaya düş
    """
    d4, d1, sig = sinyaller(coin, source)
    cl = d4["close"].values; idx4 = d4.index
    hi1 = d1["high"]; lo1 = d1["low"]; cl1 = d1["close"]
    _, _, sl_a, rr, mh = A.CFG["donchian"]
    out = []
    occ = -1
    for i, yon, a in sig:
        if i <= occ:
            continue
        L = cl[i]
        sld = sl_a * a
        if mod == "ankor":
            giris = L; ucret_bp = 2 * TAKER_BP; i0 = i + 1
        elif mod == "taker":
            giris = L * (1 + yon * KAYMA_BP / 1e4); ucret_bp = 2 * TAKER_BP; i0 = i + 1
        elif mod == "kovala":
            # ── SABIRLI LİMİT + KOVALAMA ─────────────────────────────────────
            # ÖLÇÜLEN KUSURUN ÇARESİ: saf sabırlı limitte dolmayan %5.6, işlem
            # başına $2.28 kaybettiriyor (ortalama işlem +$0.90 kazandırırken)
            # — çünkü dolmayanlar KOŞAN kırılımlar, yani kuyruğun kendisi.
            # Çare: pencereyi sonuna kadar bekleme. Fiyat aleyhe (long'da
            # YUKARI) kovala_bp kadar giderse limiti iptal edip HEMEN piyasaya
            # geç. Geri çekilenlerde tasarruf korunur, koşanlar kaçmaz.
            #
            # ⚠ KÖTÜMSER BERABERLİK: aynı 1h barında hem dolum hem kovalama
            # şartı oluşursa KOVALAMA sayılır (daha pahalı olan).
            t0 = idx4[i] + pd.Timedelta(hours=4)
            t1 = t0 + pd.Timedelta(hours=pencere_h)
            pen = d1.loc[(d1.index >= t0) & (d1.index < t1)]
            if len(pen) == 0:
                continue
            hedef = L * (1 - yon * derinlik_bp / 1e4)
            kov = L * (1 + yon * kovala_bp / 1e4)
            giris = None
            for _, bar in pen.iterrows():
                kacti = (bar["high"] > kov) if yon == 1 else (bar["low"] < kov)
                doldu_b = (bar["low"] < hedef) if yon == 1 else (bar["high"] > hedef)
                if kacti:                                  # kötümser: kovalama önce
                    giris = kov * (1 + yon * KAYMA_BP / 1e4)
                    ucret_bp = 2 * TAKER_BP; i0 = i + 1
                    break
                if doldu_b:
                    giris = L
                    ucret_bp = MAKER_BP + TAKER_BP; i0 = i + 1
                    break
            if giris is None:                              # pencere doldu, dolmadı
                giris = float(pen["close"].iloc[-1]) * (1 + yon * KAYMA_BP / 1e4)
                ucret_bp = 2 * TAKER_BP; i0 = i + 2
        else:
            # ── SABIRLI LİMİT ────────────────────────────────────────────────
            # Bar KAPANDIKTAN sonra pencere_h saatlik 1h barlarına bak.
            t0 = idx4[i] + pd.Timedelta(hours=4)          # 4h bar gerçekten kapanır
            t1 = t0 + pd.Timedelta(hours=pencere_h)
            pen = d1.loc[(d1.index >= t0) & (d1.index < t1)]
            if len(pen) == 0:
                continue                                   # veri boşluğu → sinyali ATLA
            # limit L'de KUYRUĞUN ARKASINDA: fiyatın L'yi derinlik kadar GEÇMESİ şart
            hedef = L * (1 - yon * derinlik_bp / 1e4)
            doldu = (pen["low"].min() < hedef) if yon == 1 else (pen["high"].max() > hedef)
            if doldu:
                giris = L                                  # limit fiyatı, kayma YOK
                ucret_bp = MAKER_BP + TAKER_BP             # giriş maker, çıkış taker
                i0 = i + 1
            else:
                # dolmadı → pencere sonunda PİYASAYA düş (4 saat sonraki fiyat)
                giris = float(pen["close"].iloc[-1]) * (1 + yon * KAYMA_BP / 1e4)
                ucret_bp = 2 * TAKER_BP
                i0 = i + 2                                 # o bar tüketildi
        j, ep = _cikis(d4, i0, yon, giris, sld, mh, rr)
        R = yon * (ep - giris) / sld - (ucret_bp / 1e4) * giris / sld
        out.append((idx4[i].value, idx4[j], R, sld / giris))
        occ = j
    return out


def portfoy(mod, source, pencere_h=4, derinlik_bp=2.0, kovala_bp=20.0):
    ham = []
    for c in A.DONCH:
        ham += kol(c, source, mod, pencere_h, derinlik_bp, kovala_bp)
    for c in A.SQZ:
        ham += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        ham += A.gen_bb(fast_bt.load(c, source=source))
    taken = A.seat_select(sorted(ham, key=lambda t: t[0]))
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    o = np.argsort([x.value for x in ex])
    p = pnl[o]
    e = np.concatenate([[BAL], BAL + np.cumsum(p)])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    mon = pd.Series(p, index=[ex[k].tz_localize(None).to_period("M")
                              for k in o]).groupby(level=0).sum() / BAL * 100
    return pnl.sum(), dd, mon.min(), len(taken)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("sabirli_maker.py — sabırlı maker giriş: dolum mu, ters seçim mi?\n")

    a_kar, a_dd, a_ay, a_n = portfoy("ankor", source)
    ok = (a_n == 1579) and abs(a_kar - 1420.66) < 0.5
    print(f"  MAKİNE DOĞRULAMASI (ankor kolu): {a_n} işlem / ${a_kar:+.2f} → "
          f"{'✓ BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")

    t_kar, t_dd, t_ay, t_n = portfoy("taker", source)
    print(f"\n  GERÇEKÇİ TABAN (bugünkü yol: piyasa girişi + {KAYMA_BP}bp kayma)")
    print(f"    {t_n} işlem · ${t_kar:+.2f} · maxDD {t_dd:.1f} · en kötü ay {t_ay:.1f}")
    print(f"    kaymanın bedeli: ${t_kar - a_kar:+.2f} "
          f"({(t_kar-a_kar)/a_kar*100:+.1f}%)  ← kazanılabilecek en fazla para")

    # ── DOLUM ORANI ÖLÇÜMÜ ───────────────────────────────────────────────────
    print(f"\n{'='*80}\nDOLUM ORANI — limit ne sıklıkla doluyor? (ters seçim dahil)\n{'='*80}")
    print(f"  {'pencere':>8s}  " + "  ".join(f"{d:>5.0f}bp" for d in DERINLIKLER))
    for W in PENCERELER_H:
        satir = []
        for D in DERINLIKLER:
            n_d = n_t = 0
            for c in A.DONCH:
                d4, d1, sig = sinyaller(c, source)
                cl = d4["close"].values; idx4 = d4.index
                for i, yon, a in sig:
                    t0 = idx4[i] + pd.Timedelta(hours=4)
                    pen = d1.loc[(d1.index >= t0) & (d1.index < t0 + pd.Timedelta(hours=W))]
                    if len(pen) == 0:
                        continue
                    L = cl[i]; hedef = L * (1 - yon * D / 1e4)
                    d_ = (pen["low"].min() < hedef) if yon == 1 else (pen["high"].max() > hedef)
                    n_d += int(d_); n_t += 1
            satir.append(n_d / n_t * 100 if n_t else 0.0)
        print(f"  {W:>6d}h  " + "  ".join(f"{v:>6.1f}%" for v in satir))
    print(f"  ⚠ ÖN-KAYIT: 4h × 2bp satırı %42'nin ALTINDAYSA fikir ÖLÜ.")

    # ── PORTFÖY ETKİSİ ───────────────────────────────────────────────────────
    print(f"\n{'='*80}\nPORTFÖY — sabırlı maker vs bugünkü taker yolu\n{'='*80}")
    print(f"  ÖN-KAYIT: Δ$ ≥ +28 VE en kötü ay kötüleşmesin. Karar 10bp satırından.")
    print(f"  {'pencere':>7s} {'derinlik':>9s} {'işlem':>6s} {'kâr$':>8s} "
          f"{'Δ$':>7s} {'maxDD':>7s} {'kötü ay':>8s}  BAR")
    print(f"  {'—':>7s} {'taker':>9s} {t_n:>6d} {t_kar:>+8.0f} {0:>7.0f} "
          f"{t_dd:>7.1f} {t_ay:>8.1f}")
    for W in PENCERELER_H:
        for D in DERINLIKLER:
            k, dd, ay, n = portfoy("sabirli", source, W, D)
            bar = ("✓ GEÇTİ" if (k - t_kar >= 28 and ay >= t_ay - 0.05)
                   else ("✗ ay↓" if ay < t_ay - 0.05 else "✗ Δ$ yetersiz"))
            print(f"  {W:>6d}h {D:>8.0f}bp {n:>6d} {k:>+8.0f} {k-t_kar:>+7.0f} "
                  f"{dd:>7.1f} {ay:>8.1f}  {bar}")

    # ── KOVALAMA: ölçülen kusurun çaresi ────────────────────────────────────
    print(f"\n{'='*80}\nKOVALAMA — koşan kırılımı kaçırma, geri çekileni ucuza al\n{'='*80}")
    print(f"  Saf sabırlı limitin kusuru ÖLÇÜLDÜ: dolmayan %5.6 işlem başına")
    print(f"  ~$2.28 kaybettiriyor (ortalama işlem +$0.90). Kaçanlar KOŞAN")
    print(f"  kırılımlar. Çare: fiyat aleyhe X bp giderse limiti iptal et,")
    print(f"  HEMEN piyasaya geç. Karar yine 10bp derinlik satırından.")
    print(f"  {'kovala':>7s} {'derinlik':>9s} {'işlem':>6s} {'kâr$':>8s} "
          f"{'Δ$':>7s} {'maxDD':>7s} {'kötü ay':>8s}  BAR")
    print(f"  {'—':>7s} {'taker':>9s} {t_n:>6d} {t_kar:>+8.0f} {0:>7.0f} "
          f"{t_dd:>7.1f} {t_ay:>8.1f}")
    for KV in (10.0, 20.0, 30.0, 50.0):
        for D in (2.0, 10.0):
            k, dd, ay, n = portfoy("kovala", source, 4, D, KV)
            bar = ("✓ GEÇTİ" if (k - t_kar >= 28 and ay >= t_ay - 0.05)
                   else ("✗ ay↓" if ay < t_ay - 0.05 else "✗ Δ$ yetersiz"))
            print(f"  {KV:>6.0f}bp {D:>8.0f}bp {n:>6d} {k:>+8.0f} {k-t_kar:>+7.0f} "
                  f"{dd:>7.1f} {ay:>8.1f}  {bar}")

    print(f"\n{'='*80}\nHÜKÜM\n{'='*80}")
    print(f"  Karar 10bp (en kötümser) satırından verilir. Orada ✓ yoksa fikir")
    print(f"  ölür — dolum oranı yüksek çıksa bile ters seçim kazancı yiyor")
    print(f"  demektir: limit ZAYIF kırılımlarda doluyor, güçlülerde dolmuyor.")


if __name__ == "__main__":
    main()
