"""
regime_teshis.py — ADIM 1/3: NEGATİF AYLARIN ORTAK PİYASA KOŞULU VAR MI?

Kullanıcı önerisi: piyasa rejimini tespit edip (güçlü trend / range / kaotik) kollara
göre yönlendiren bir filtre. Doğru kurulmuş bir öneri — takvim filtresini ve geçmiş
ayları ezberlemeyi baştan yasaklıyor. Ama FİLTRE KURMADAN ÖNCE cevaplanması gereken
bir soru var: negatif ayların ölçülebilir bir ortak koşulu VAR MI?

⚠️ İSTATİSTİK GÜCÜ — bu çalışmanın en kritik tasarım kararı:
40 ayın 8'i negatif. SEKİZ OLAYLA rejim modeli kurulamaz; hangi değişkeni denersen
dene, 8 noktayı ayıran bir eşik BULUNUR ve bu ezberdir. Bu yüzden test AY seviyesinde
DEĞİL, İŞLEM seviyesinde kuruluyor (n=1579). Ay, işlemlerin toplamıdır; sinyal varsa
işlem seviyesinde vardır ve orada 200 kat daha çok gözlem var.

REJİM DEĞİŞKENLERİ (hepsi karar anında BİLİNEBİLİR; lookahead yok — günlük seride
hesaplanıp shift(1) ile kaydırılıyor, yani o günün girişleri DÜNE kadarki veriyi görür):

  PORTFÖY SEVİYESİ (tüm evrenden, 12 coin):
   · vol20      — coinlerin 20 günlük gerçekleşen oynaklığının ortalaması
   · korel20    — coinler arası ORTALAMA İKİLİ KORELASYON. Hipotez: kötü aylar
                  "her şey birlikte düştü" ayları ise burada görünür. Yedi koltuk
                  varken yüksek korelasyon = çeşitlendirme YOK demektir.
   · trend_pay  — günlük EMA200'ün ÜSTÜNDEKİ coin oranı (0-1). Rejim yönü.
   · dagilim    — kesitsel getiri standart sapması (dispersion). Düşükse coinler
                  birlikte hareket ediyor = seçicilik işe yaramaz.
   · pyt20      — eşit ağırlıklı piyasa endeksinin 20 günlük getirisi
   · pyt_dd     — endeksin 60 günlük tepeden düşüşü

  COIN SEVİYESİ (işlemin kendi coini, kendi zaman diliminde):
   · adx        — trend gücü. "Güçlü trend → Donchian" fikrinin doğrudan testi.
   · atr_pct    — o coinin oynaklığı

YÖNTEM (bugüne kadar 20 ekseni reddeden yöntemin aynısı):
 1. Her işleme GİRİŞ ANINDAKİ rejim değerleri iliştirilir.
 2. Her değişken için işlemler BEŞTE BİRLİK dilimlere ayrılır, dilim başına ortalama R.
 3. İlişki MONOTON mu? (rastgele gürültü monoton olmaz)
 4. **DÖNEM AYRIMI**: TRAIN (<2025-01-01) ve TEST (>=2025-01-01) AYRI raporlanır.
    İlişki yalnız birinde varsa EZBERDİR. Bu, kullanıcının "overfit etme" şartının
    ölçülebilir hâli.
 5. Kol bazında ayrı (donchian / squeeze), çünkü öneri kolları farklı yönlendiriyor.

BU BETİK FİLTRE KURMAZ, KARAR VERMEZ. Yalnız "ayrıştırıcı bir değişken var mı"
sorusunu yanıtlar. Yoksa eksen burada ucuza kapanır ve filtre yazmaya hiç girilmez.

Kullanım:  py regime_teshis.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import adx as adx_fn, atr as atr_fn

TUM = A.DONCH + A.SQZ + A.BB_COINS
BOL = pd.Timestamp("2025-01-01")


def gunluk_panel(source):
    """Coin bazında günlük kapanış paneli — portföy rejim değişkenleri buradan."""
    ser = {}
    for c in TUM:
        m = fast_bt.load(c, source=source)
        ser[c] = m["close"].resample("1D").last()
    px = pd.DataFrame(ser).dropna(how="all").ffill()
    return px


def portfoy_rejim(px):
    """Portföy seviyesi rejim serileri. HEPSİ shift(1) — o günün girişleri
    yalnız DÜNE kadar tamamlanmış veriyi görür (lookahead yok)."""
    ret = px.pct_change()
    ew = ret.mean(axis=1)                      # eşit ağırlıklı piyasa getirisi
    endeks = (1 + ew.fillna(0)).cumprod()

    vol20 = ret.rolling(20).std().mean(axis=1)
    dagilim = ret.std(axis=1).rolling(20).mean()
    ema200 = px.ewm(span=200, adjust=False).mean()
    trend_pay = (px > ema200).mean(axis=1)
    pyt20 = endeks.pct_change(20)
    pyt_dd = endeks / endeks.rolling(60).max() - 1.0

    # ortalama ikili korelasyon: korelasyon matrisinin köşegen dışı ortalaması
    kor = []
    R = ret.values
    n = R.shape[1]
    for i in range(len(ret)):
        if i < 20:
            kor.append(np.nan); continue
        W = R[i - 19:i + 1]
        if np.isnan(W).any():
            W = pd.DataFrame(W).ffill().bfill().values
        C = np.corrcoef(W, rowvar=False)
        iu = np.triu_indices(n, 1)
        kor.append(np.nanmean(C[iu]))
    korel20 = pd.Series(kor, index=ret.index)

    rej = pd.DataFrame({"vol20": vol20, "korel20": korel20, "trend_pay": trend_pay,
                        "dagilim": dagilim, "pyt20": pyt20, "pyt_dd": pyt_dd})
    return rej.shift(1)                        # ← LOOKAHEAD KORUMASI


def coin_rejim(m, tf):
    """Coin seviyesi: kendi zaman diliminde ADX ve ATR%. gen() ile aynı pencereler."""
    d = fast_bt.resample(m, tf)
    a = adx_fn(d["high"], d["low"], d["close"], 14)
    at = atr_fn(d["high"], d["low"], d["close"], 14) / d["close"]
    return pd.DataFrame({"adx": a.values, "atr_pct": at.values}, index=d.index).shift(1)


def islemler(source, rej):
    """Ankorun ALDIĞI işlemler + giriş anındaki rejim değerleri."""
    tagged = []
    for kol, coins, tf in (("donchian", A.DONCH, "4h"), ("squeeze", A.SQZ, "1h")):
        for c in coins:
            m = fast_bt.load(c, source=source)
            cr = coin_rejim(m, tf)
            for t in A.gen(kol, m):
                tagged.append((kol, c, t[0], t[1], t[2], t[3], cr))
    for c in A.BB_COINS:
        m = fast_bt.load(c, source=source)
        cr = coin_rejim(m, "1h")
        for t in A.gen_bb(m):
            tagged.append(("bb", c, t[0], t[1], t[2], t[3], cr))

    # koltuk seçimi (ankorla birebir)
    import heapq
    ev = sorted(tagged, key=lambda z: z[2])
    openh = []; ctr = 0; alinan = []
    for kol, c, e_ns, x_ts, R, slp, cr in ev:
        while openh and openh[0][0].value <= e_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (x_ts, ctr, R))
            alinan.append((kol, c, e_ns, x_ts, R, slp, cr))

    satir = []
    for kol, c, e_ns, x_ts, R, slp, cr in alinan:
        ts = pd.Timestamp(e_ns)
        d = {"kol": kol, "coin": c, "giris": ts, "cikis": pd.Timestamp(x_ts),
             "R": R, "slp": slp}
        gun = ts.normalize()
        if gun in rej.index:
            d.update(rej.loc[gun].to_dict())
        else:
            d.update({k: np.nan for k in rej.columns})
        # coin seviyesi: girişten önceki son bar
        try:
            pos = cr.index.searchsorted(ts, side="right") - 1
            if pos >= 0:
                d["adx"] = cr["adx"].values[pos]; d["atr_pct"] = cr["atr_pct"].values[pos]
            else:
                d["adx"] = np.nan; d["atr_pct"] = np.nan
        except Exception:
            d["adx"] = np.nan; d["atr_pct"] = np.nan
        satir.append(d)
    return pd.DataFrame(satir)


def dilim_analiz(df, degisken, etiket):
    """Beşte birlik dilimler × TRAIN/TEST. Sinyal varsa iki dönemde de AYNI YÖNDE olmalı."""
    x = df[degisken]
    ok = x.notna()
    if ok.sum() < 100:
        print(f"    {etiket:<10s} yetersiz veri (n={ok.sum()})")
        return None
    d = df[ok].copy()
    try:
        d["dilim"] = pd.qcut(d[degisken], 5, labels=False, duplicates="drop")
    except ValueError:
        print(f"    {etiket:<10s} dilimlenemedi (tekrarlı değerler)")
        return None
    tr = d[d["giris"] < BOL]; te = d[d["giris"] >= BOL]
    satir = f"    {etiket:<10s}"
    tam, trl, tel = [], [], []
    for q in range(5):
        tam.append(d[d.dilim == q]["R"].mean())
        trl.append(tr[tr.dilim == q]["R"].mean() if len(tr[tr.dilim == q]) > 5 else np.nan)
        tel.append(te[te.dilim == q]["R"].mean() if len(te[te.dilim == q]) > 5 else np.nan)
    satir += "  ".join(f"{v:+.3f}" for v in tam)
    # en düşük vs en yüksek dilim farkı ve z
    a = d[d.dilim == 0]["R"]; b = d[d.dilim == 4]["R"]
    se = np.sqrt(a.var(ddof=1)/len(a) + b.var(ddof=1)/len(b))
    z = (b.mean() - a.mean()) / se if se > 0 else 0.0
    # TRAIN ve TEST'te aynı yön mü
    dtr = trl[4] - trl[0] if np.isfinite(trl[0]) and np.isfinite(trl[4]) else np.nan
    dte = tel[4] - tel[0] if np.isfinite(tel[0]) and np.isfinite(tel[4]) else np.nan
    ayni = (np.isfinite(dtr) and np.isfinite(dte) and np.sign(dtr) == np.sign(dte)
            and abs(dtr) > 0.02 and abs(dte) > 0.02)
    bayrak = ""
    if abs(z) > 2.0 and ayni:
        bayrak = "  ★ ANLAMLI ve İKİ DÖNEMDE DE AYNI YÖN"
    elif abs(z) > 2.0:
        bayrak = "  ⚠ anlamlı ama dönemler ÇELİŞİYOR → ezber şüphesi"
    print(f"{satir}   | z={z:+5.2f}  TRAIN Δ={dtr:+.3f} TEST Δ={dte:+.3f}{bayrak}")
    return dict(z=z, dtr=dtr, dte=dte, saglam=bool(abs(z) > 2.0 and ayni))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = gunluk_panel(source)
    rej = portfoy_rejim(px)
    df = islemler(source, rej)

    eff = np.minimum(A.RISKF, A.CAP * df["slp"].values)
    tot = float((df["R"].values * eff * A.BAL0).sum())
    ok = len(df) == 1579 and abs(tot - 1420.66) < 0.01
    print(f"\n{'=' * 118}")
    print("=== ADIM 1/3 — REJİM TEŞHİSİ: negatif ayların ortak koşulu var mı? ===")
    print(f"  KONTROL: {len(df)} işlem / ${tot:+.2f} → "
          f"{'✓ BİREBİR (ankor yeniden üretildi)' if ok else '✗ SAPMA — betik BOZUK'}")
    if not ok:
        return

    # ── AY SEVİYESİ (bağlam, KANIT DEĞİL) ──
    df["ay"] = df["cikis"].dt.to_period("M")
    aylik = (df["R"].values * eff * A.BAL0)
    ay_pnl = pd.Series(aylik, index=df["ay"]).groupby(level=0).sum()
    neg = ay_pnl[ay_pnl < 0].index
    print(f"\n[1] AY SEVİYESİ BAĞLAM — {len(ay_pnl)} ayın {len(neg)}'i negatif")
    print(f"    ⚠ n={len(neg)} olayla rejim modeli KURULAMAZ. Bu bölüm yalnız bağlam;")
    print(f"      hüküm [2]'deki işlem seviyesi analizden çıkar.")
    df["neg_ay"] = df["ay"].isin(neg)
    print(f"\n    {'değişken':<10s} {'negatif aylarda':>16s} {'pozitif aylarda':>16s} {'fark':>8s}")
    for v in ("vol20", "korel20", "trend_pay", "dagilim", "pyt20", "pyt_dd", "adx"):
        a = df[df.neg_ay][v].mean(); b = df[~df.neg_ay][v].mean()
        print(f"    {v:<10s} {a:>16.4f} {b:>16.4f} {a-b:>+8.4f}")

    # ── İŞLEM SEVİYESİ (ASIL TEST) ──
    print(f"\n[2] İŞLEM SEVİYESİ — dilim başına ortalama R (düşük→yüksek beşte birlik)")
    print(f"    Sinyal gerçekse: MONOTON olmalı VE hem TRAIN hem TEST'te AYNI YÖNDE.")
    saglamlar = []
    for kol in ("donchian", "squeeze", "bb"):
        alt = df[df.kol == kol]
        print(f"\n  ── {kol} (n={len(alt)}, ort R {alt['R'].mean():+.4f}) ──")
        print(f"    {'değişken':<10s} {'Q1':>7s}{'Q2':>9s}{'Q3':>9s}{'Q4':>9s}{'Q5':>9s}")
        for v in ("vol20", "korel20", "trend_pay", "dagilim", "pyt20", "pyt_dd",
                  "adx", "atr_pct"):
            r = dilim_analiz(alt, v, v)
            if r and r["saglam"]:
                saglamlar.append((kol, v, r))

    print(f"\n{'=' * 118}\n=== HÜKÜM ===")
    if not saglamlar:
        print("  HİÇBİR rejim değişkeni hem anlamlı hem de iki dönemde tutarlı çıkmadı.")
        print("  → Filtre kurmak için ayrıştırıcı bir sinyal YOK. Eksen burada kapanır;")
        print("    bir eşik zorlanırsa o eşik geçmişi ezberler, geleceği bilmez.")
    else:
        print(f"  {len(saglamlar)} aday sağlam çıktı — ADIM 2'ye (filtre + walk-forward) geçilebilir:")
        for kol, v, r in saglamlar:
            print(f"    · {kol:<9s} {v:<10s} z={r['z']:+.2f}  TRAIN Δ={r['dtr']:+.3f}  "
                  f"TEST Δ={r['dte']:+.3f}")
        print(f"\n  ⚠ SAĞLAM ÇIKMAK YETMEZ: ADIM 2'de bu değişkenlerden kurulan kapı,")
        print(f"    eşiği YALNIZ TRAIN'de seçilip TEST'te ölçülecek. Portföy etkisi")
        print(f"    (PF, net PnL, maxDD, WR, ort R, işlem sayısı) orada raporlanacak.")


if __name__ == "__main__":
    main()
