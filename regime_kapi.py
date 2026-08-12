"""
regime_kapi.py — ADIM 2/3: REJİM KAPISI — eşik YALNIZ TRAIN'de seçilir, TEST'te ölçülür.

ADIM 1 (regime_teshis.py) dört aday buldu; bunlar aslında İKİ bağımsız bulgu:
  · squeeze: atr_pct (z=-2.48) ve adx (z=-2.26) — ikisi de oynaklık/trend gücü ölçüyor
  · bb     : dagilim (z=-2.84) ve vol20 (z=-2.08) — ikisi de piyasa oynaklığı ölçüyor
Her ikisinde de yön aynı: OYNAKLIK YÜKSELDİKÇE EDGE KAYBOLUYOR, en üst dilimde negatif.

MEKANİZMA (bu, salt korelasyondan ayıran şey):
 · squeeze bir SIKIŞMADAN ÇIKIŞ stratejisi. Giriş anında ATR zaten yüksekse ortada
   sıkışma yoktur — kurulumun ön şartı sağlanmamıştır.
 · bb ORTALAMAYA DÖNÜŞ. Yüksek oynaklıkta bant teması "aşırılık" değil, gerçek bir
   trend hareketinin başlangıcıdır.
Donchian'da anlamlı bir şey ÇIKMADI; en yakını trend_pay (z=+1.43, eşiğin altında)
ama TRAIN/TEST yönü tutarlı (+0.329 / +0.355). Ayrı bir varyant olarak ölçülüyor.

⚠️ ÇOKLU TEST: adım 1'de 8 değişken × 3 kol = 24 test yapıldı. |z|>2'yi şansla ~1
tanesinin geçmesi beklenir. Bonferroni eşiği |z|>3.08 olurdu ve DÖRDÜ DE KALIRDI.
Yani bu adaylar "kesin" değil "bakmaya değer" seviyesinde. Adım 2 bu yüzden var.

EŞİK SEÇİMİ — EZBERİ ÖNLEYEN TASARIM:
Eşik, kârı EN İYİLEYEN değer olarak SEÇİLMEZ (bu, TRAIN içinde overfit olurdu).
ÖNCEDEN KAYITLI kural: "en kötü dilimi at". Kesim noktası yalnız TRAIN verisinin
yüzdelik değerinden hesaplanır, TEST verisine HİÇ bakılmaz.

ÜÇ ÖLÇÜM:
 1. TRAIN/TEST: eşik TRAIN'den, sonuç TEST'te (out-of-sample).
 2. WALK-FORWARD: her yıl için eşik YALNIZ O YILDAN ÖNCEKİ veriden hesaplanır.
    Gerçek kullanımın simülasyonu; her yıl ayrı raporlanır.
 3. DOZ-YANITI: %10/%20/%30 kesim. Gerçek etki monoton olmalı; zikzak = gürültü.

⚠️ KAPI KOLTUK SEÇİMİNDEN ÖNCE uygulanır — atılan işlem koltuğu boşaltır ve başka
bir işlem o koltuğu kullanabilir. Sonradan filtrelemek yanlış olurdu.

METRİKLER (kullanıcının istediği tam liste): PF · Net PnL · MaxDD · WR · ort R · işlem sayısı
Ek olarak en kötü ay ve yıl kırılımı, çünkü amaç negatif ayları azaltmak.

Kullanım:  py regime_kapi.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import adx as adx_fn, atr as atr_fn

TUM = A.DONCH + A.SQZ + A.BB_COINS
BOL = pd.Timestamp("2025-01-01")
CAP_YENI = 1.50


def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


def gunluk_rejim(source):
    ser = {}
    for c in TUM:
        ser[c] = fast_bt.load(c, source=source)["close"].resample("1D").last()
    px = pd.DataFrame(ser).dropna(how="all").ffill()
    px.index = _naive(px.index)
    ret = px.pct_change()
    vol20 = ret.rolling(20).std().mean(axis=1)
    dagilim = ret.std(axis=1).rolling(20).mean()
    ema200 = px.ewm(span=200, adjust=False).mean()
    trend_pay = (px > ema200).mean(axis=1)
    return pd.DataFrame({"vol20": vol20, "dagilim": dagilim,
                         "trend_pay": trend_pay}).shift(1)


def coin_rejim(m, tf):
    d = fast_bt.resample(m, tf)
    a = adx_fn(d["high"], d["low"], d["close"], 14)
    at = atr_fn(d["high"], d["low"], d["close"], 14) / d["close"]
    out = pd.DataFrame({"adx": a.values, "atr_pct": at.values}, index=d.index).shift(1)
    out.index = _naive(out.index)
    return out


def havuz(source, rej):
    """Koltuk seçiminden ÖNCEKİ tam sinyal havuzu + rejim değerleri."""
    ham = []
    for kol, coins, tf in (("donchian", A.DONCH, "4h"), ("squeeze", A.SQZ, "1h")):
        for c in coins:
            m = fast_bt.load(c, source=source)
            cr = coin_rejim(m, tf)
            for t in A.gen(kol, m):
                ham.append((kol, c, t[0], t[1], t[2], t[3], cr))
    for c in A.BB_COINS:
        m = fast_bt.load(c, source=source)
        cr = coin_rejim(m, "1h")
        for t in A.gen_bb(m):
            ham.append(("bb", c, t[0], t[1], t[2], t[3], cr))

    satir = []
    for kol, c, e_ns, x_ts, R, slp, cr in ham:
        ts = pd.Timestamp(e_ns)
        g = ts.normalize()
        d = {"kol": kol, "e_ns": e_ns, "x_ns": pd.Timestamp(x_ts).value,
             "giris": ts, "R": R, "slp": slp}
        if g in rej.index:
            d.update(rej.loc[g].to_dict())
        else:
            d.update({k: np.nan for k in rej.columns})
        pos = cr.index.searchsorted(ts, side="right") - 1
        d["adx"] = cr["adx"].values[pos] if pos >= 0 else np.nan
        d["atr_pct"] = cr["atr_pct"].values[pos] if pos >= 0 else np.nan
        satir.append(d)
    # KARARLI SIRALAMA ŞART: A.seat_select Python'un `sorted`'ını kullanıyor (kararlı),
    # yani AYNI entry_ns'e sahip sinyaller EKLENME sırasını korur (donchian coinleri →
    # squeeze → bb). pandas'ın varsayılan quicksort'u kararsız; eşit anahtarlarda sırayı
    # bozunca koltuk yarışını farklı sinyal kazanıyor ve işlem SAYISI aynı kalsa bile
    # KÜME değişiyor (kontrol testi: 1579 işlem ama $1409.71 ≠ $1420.66).
    return (pd.DataFrame(satir)
            .sort_values("e_ns", kind="mergesort")      # ← kararlı
            .reset_index(drop=True))


def koltuk(df):
    """Koltuk seçimi (ankorla birebir) — verilen (filtrelenmiş) havuz üzerinde."""
    openh = []; ctr = 0; al = []
    for r in df.itertuples():
        while openh and openh[0][0] <= r.e_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (r.x_ns, ctr))
            al.append((r.x_ns, r.R, r.slp))
    return al


def metrik(al, cap=CAP_YENI):
    if not al:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, ortR=0.0, dd=0.0, worst=0.0, yr={})
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ex = [pd.Timestamp(a[0]) for a in al]
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon),
                yr={int(k): float(v) for k, v in yr.items()})


# ── KAPI TANIMLARI — her biri "o kolun kendi rejimi yokken kapat" kuralı ──
KAPILAR = {
    "squeeze_atr":  ("squeeze",  "atr_pct",   "ust"),   # yüksek ATR → sıkışma yok
    "squeeze_adx":  ("squeeze",  "adx",       "ust"),
    "bb_dagilim":   ("bb",       "dagilim",   "ust"),
    "bb_vol":       ("bb",       "vol20",     "ust"),
    "donch_trend":  ("donchian", "trend_pay", "alt"),   # az coin trendde → kapat
}


def uygula(df, secim, esikler):
    """Kapıları uygula. esikler: {kapi_adi: esik_degeri}"""
    tut = np.ones(len(df), dtype=bool)
    for ad in secim:
        kol, dgs, yon = KAPILAR[ad]
        e = esikler.get(ad)
        if e is None or not np.isfinite(e):
            continue
        hedef = (df["kol"] == kol).values
        v = df[dgs].values
        if yon == "ust":
            kes = hedef & np.isfinite(v) & (v >= e)
        else:
            kes = hedef & np.isfinite(v) & (v <= e)
        tut &= ~kes
    return df[tut]


def esik_hesapla(df, secim, kesim, bitis):
    """Eşikleri YALNIZ `bitis` tarihinden ÖNCEKİ veriden hesapla (out-of-sample koruma)."""
    egitim = df[df["giris"] < bitis]
    out = {}
    for ad in secim:
        kol, dgs, yon = KAPILAR[ad]
        v = egitim[egitim["kol"] == kol][dgs].dropna()
        if len(v) < 50:
            out[ad] = np.nan; continue
        out[ad] = float(v.quantile(1 - kesim)) if yon == "ust" else float(v.quantile(kesim))
    return out


def yaz(ad, m, taban=None):
    d = f"{m['tot']-taban['tot']:+7.0f}" if taban else f"{'—':>7s}"
    print(f"  {ad:<26s} {m['n']:>6d} {m['tot']:>+9.0f} {d} {m['pf']:>6.2f} "
          f"{m['wr']:>6.1f} {m['ortR']:>+7.3f} {m['dd']:>7.1f} {m['worst']:>+9.1f} "
          f"{m.get('negay', 0):>3d}/{m.get('ay', 0):<3d}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    rej = gunluk_rejim(source)
    df = havuz(source, rej)

    tam = koltuk(df)
    kon = metrik(tam, cap=A.CAP)
    ok = len(tam) == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 122}")
    print("=== ADIM 2/3 — REJİM KAPISI: eşik YALNIZ TRAIN'de seçilir ===")
    print(f"  KONTROL (kapısız, CAP=1.25): {len(tam)} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — betik BOZUK'}")
    if not ok:
        # Kontrol düşerse hiçbir satır okunmaz. Teşhis için sapmanın türünü yaz:
        # sayı tutup TUTAR tutmuyorsa seçilen KÜME farklıdır (sıralama/koltuk yarışı).
        print(f"    sayı {'tutuyor' if len(tam) == 1579 else 'TUTMUYOR'}, "
              f"tutar farkı {kon['tot']-1420.66:+.2f}$ → "
              f"{'KÜME farklı (sıralama/koltuk)' if len(tam) == 1579 else 'üretim farklı'}")
        return
    print(f"  (aşağıdaki tüm ölçümler CAP={CAP_YENI} tabanında — paket sonrası hâl)")

    baslik = (f"\n  {'yapılandırma':<26s} {'işlem':>6s} {'netPnL$':>9s} {'Δ$':>7s} "
              f"{'PF':>6s} {'WR%':>6s} {'ortR':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s}")

    # ── [1] TAM DÖNEM (bilgi amaçlı — eşik tüm veriden, OVERFİT RİSKLİ) ──
    taban = metrik(koltuk(df))
    print(f"\n[1] TAM DÖNEM — eşik TÜM veriden (⚠ bu ölçüm overfit riskli, yalnız yön için)")
    print(baslik)
    yaz("kapısız (taban)", taban)
    for kesim in (0.10, 0.20, 0.30):
        es = esik_hesapla(df, KAPILAR, kesim, pd.Timestamp("2099-01-01"))
        for secim, ad in ((["squeeze_atr"], "squeeze_atr"),
                          (["bb_dagilim"], "bb_dagilim"),
                          (["squeeze_atr", "bb_dagilim"], "squeeze+bb"),
                          (["squeeze_atr", "bb_dagilim", "donch_trend"], "üçü birden")):
            yaz(f"{ad} %{kesim*100:.0f}", metrik(koltuk(uygula(df, secim, es))), taban)

    # ── [2] OUT-OF-SAMPLE: eşik TRAIN'den, ölçüm TEST'te ──
    print(f"\n[2] OUT-OF-SAMPLE — eşik YALNIZ TRAIN(<2025)'den, sonuç TEST(>=2025)'te")
    te = df[df["giris"] >= BOL]
    t_taban = metrik(koltuk(te))
    print(baslik)
    yaz("kapısız (TEST tabanı)", t_taban)
    for kesim in (0.10, 0.20, 0.30):
        es = esik_hesapla(df, KAPILAR, kesim, BOL)
        for secim, ad in ((["squeeze_atr"], "squeeze_atr"),
                          (["bb_dagilim"], "bb_dagilim"),
                          (["squeeze_atr", "bb_dagilim"], "squeeze+bb"),
                          (["squeeze_atr", "bb_dagilim", "donch_trend"], "üçü birden")):
            yaz(f"{ad} %{kesim*100:.0f}", metrik(koltuk(uygula(te, secim, es))), t_taban)

    # ── [3] WALK-FORWARD ──
    print(f"\n[3] WALK-FORWARD — her yıl için eşik YALNIZ ÖNCEKİ yıllardan")
    secim = ["squeeze_atr", "bb_dagilim"]
    for kesim in (0.10, 0.20, 0.30):
        print(f"\n  kesim %{kesim*100:.0f} (squeeze_atr + bb_dagilim)")
        print(f"    {'yıl':>6s} {'kapısız$':>10s} {'kapılı$':>10s} {'Δ$':>7s} "
              f"{'işlem':>7s} {'atılan':>7s}")
        tk = tp = 0.0
        for yil in (2024, 2025, 2026):
            bas = pd.Timestamp(f"{yil}-01-01"); son = pd.Timestamp(f"{yil+1}-01-01")
            dilim = df[(df["giris"] >= bas) & (df["giris"] < son)]
            if len(dilim) < 20:
                continue
            es = esik_hesapla(df, secim, kesim, bas)      # ← yalnız geçmiş
            a = metrik(koltuk(dilim)); b = metrik(koltuk(uygula(dilim, secim, es)))
            tk += a["tot"]; tp += b["tot"]
            print(f"    {yil:>6d} {a['tot']:>+10.0f} {b['tot']:>+10.0f} "
                  f"{b['tot']-a['tot']:>+7.0f} {b['n']:>7d} {a['n']-b['n']:>7d}")
        print(f"    {'TOPLAM':>6s} {tk:>+10.0f} {tp:>+10.0f} {tp-tk:>+7.0f}")

    print(f"\n{'=' * 122}\n=== NASIL OKUNUR ===")
    print(f"  · [1] TAM DÖNEM eşiği tüm veriden aldığı için İYİMSER; karar ondan VERİLMEZ.")
    print(f"  · [2] ve [3] out-of-sample. Kapı gerçekse ORADA da iyileştirmeli.")
    print(f"  · DOZ-YANITI: %10→%20→%30 giderek daha çok kesiyor. Gerçek etki MONOTON")
    print(f"    olmalı; zikzak yapıyorsa gürültüdür.")
    print(f"  · Amaç negatif ayları azaltmak: 'neg/ay' ve 'kötü ay%' sütunlarına bak,")
    print(f"    yalnız net PnL'e değil.")


if __name__ == "__main__":
    main()
