"""
fake_kirilim.py — SAHTE KIRILIM: sinyalin KENDİ kalitesi ayırt edilebilir mi?

⚠️ BUGÜN "REJİM EKSENİ KAPANDI" DEDİM AMA İKİ FARKLI ŞEYİ KARIŞTIRDIM:
 · REJİM   = o anki piyasa ORTAMI (oynaklık, korelasyon, trend genişliği).
             Bütün coinler için aynı anda AYNI değer. → test edildi, kapandı.
 · SİNYAL KALİTESİ = O KIRILIMIN KENDİ özellikleri (mum gövdesi, kanalı ne kadar
             aştığı, hacim teyidi, kanal yaşı). Her işleme ÖZEL. → HİÇ TEST EDİLMEDİ.

Karıştırma testi "kayıplar zamanda kümelenmiyor" diyor. Sahte kırılım ZAMANLA ilgili
değil, O MUMUN kendisiyle ilgili. Dolayısıyla o test bu ekseni KAPATMIYOR.

NEDEN BİLGİ POTANSİYELİ DAHA YÜKSEK: rejim değişkenleri paylaşılıyor (aynı gün 7 coin
aynı değeri görüyor → efektif örneklem gün sayısı kadar). Kırılım özellikleri her işleme
özel → efektif örneklem İŞLEM sayısı kadar. Donchian'da 1008 bağımsız gözlem.

ÖLÇÜLEN ÖZELLİKLER (hepsi giriş barında BİLİNİYOR, lookahead yok):
  taşma        kanalı kaç ATR aştı (kırılımın gücü). Zayıf taşma = sahte kırılım şüphesi.
  gövde        |close-open|/(high-low). Küçükse mum kararsız (uzun fitil).
  kapanış_yeri kırılım yönünde barın neresinde kapandı (1 = tam uçta). Fitille
               kırılıp geri gelen mum burada düşük çıkar — sahte kırılımın klasik imzası.
  hacim        hacim / 20-bar ortalaması. Teyitsiz kırılım şüphelidir.
  kanal_gen    (kanal üst - alt)/ATR. Dar kanaldan çıkış mı geniş kanaldan mı.
  ema_mesafe   (close - EMA200)/ATR, yön işaretli. Erken mi girdik yoksa uzamış mı.
  atr_orani    ATR şimdi / ATR 20 bar önce. Oynaklık genişliyor mu daralıyor mu.
  bar_araligi  (high-low)/ATR. Anormal büyük mum = tükeniş olabilir.

YÖNTEM (rejim testinin aynısı, 23 ekseni reddeden bar):
  beşte birlik dilimler → dilim başına ortalama R → |z|>2 VE TRAIN/TEST aynı yön.
  EN ÖNEMLİ SÜTUN: dilimlerden herhangi birinin ortalama R'si NEGATİF mi?
  Rejim kapısı tam da burada battı: en kötü dilim bile +0.058R idi, yani filtre
  zarar edeni değil AZ KAZANANI kesiyordu. Burada negatif dilim VARSA eksen açılır.

⚠️ ÇOKLU TEST: 8 özellik × 2 kol = 16 test. |z|>2'yi şansla ~1'inin geçmesi beklenir.
Bonferroni eşiği |z|>2.90. Bu eşiği geçenler ayrıca işaretleniyor.

⚠️ EŞDEĞERLİK: A.gen çoğaltılıyor (özellikleri yakalamak için). Üretilen HER işlem
ankorunkiyle karşılaştırılıyor; tek sapmada betik hiçbir sayı yazmadan DURUR.
(pw_mtf_sleeve dersi: elle taklit 1697 işlem/$1366 üretmişti, ankor 1579/$1421.)

Kullanım:  py fake_kirilim.py local
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

BOL = pd.Timestamp("2025-01-01")
OZ = ["tasma", "govde", "kapanis_yeri", "hacim", "kanal_gen", "ema_mesafe",
      "atr_orani", "bar_araligi"]


def gen_oz(sleeve, m):
    """A.gen'in BİREBİR kopyası + giriş barı özellikleri. Eşdeğerliği main()'de kanıtlanır."""
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
    op = d["open"].values; hi = d["high"].values; lo = d["low"].values
    cl = d["close"].values; vo = d["volume"].values
    volma = pd.Series(vo).rolling(20).mean().values
    ema200 = d["close"].ewm(span=200, adjust=False).mean().values
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

        # ── GİRİŞ BARI ÖZELLİKLERİ (hepsi bar i'de biliniyor) ──
        rng = hi[i] - lo[i]
        ch_h = float(getattr(sg, "channel_high", 0.0) or 0.0)
        ch_l = float(getattr(sg, "channel_low", 0.0) or 0.0)
        if ch_h > 0 and ch_l > 0:
            tasma = ((cl[i] - ch_h) if d_ == 1 else (ch_l - cl[i])) / a
            kanal_gen = (ch_h - ch_l) / a
        else:
            tasma = np.nan; kanal_gen = np.nan
        oz = {
            "tasma": tasma,
            "govde": abs(cl[i] - op[i]) / rng if rng > 0 else np.nan,
            # kırılım yönünde barın neresinde kapandı: 1 = tam uçta (güçlü),
            # 0 = ters uçta (fitille kırılıp geri gelmiş = sahte kırılım imzası)
            "kapanis_yeri": (((cl[i] - lo[i]) if d_ == 1 else (hi[i] - cl[i])) / rng
                             if rng > 0 else np.nan),
            "hacim": vo[i] / volma[i] if np.isfinite(volma[i]) and volma[i] > 0 else np.nan,
            "kanal_gen": kanal_gen,
            "ema_mesafe": d_ * (cl[i] - ema200[i]) / a,
            "atr_orani": a / atr_ser[i - 20] if (i >= 20 and np.isfinite(atr_ser[i - 20])
                                                 and atr_ser[i - 20] > 0) else np.nan,
            "bar_araligi": rng / a,
        }
        out.append((idx[i].value, idx[j], R, sld / e, oz)); occ = j
    return out


def dilim(df, degisken, n_dilim=5):
    """Beşte birlik dilimler × TRAIN/TEST. Dönüş: satır metni + hüküm sözlüğü."""
    d = df[df[degisken].notna()].copy()
    if len(d) < 150:
        return f"    {degisken:<13s} yetersiz veri (n={len(d)})", None
    try:
        d["q"] = pd.qcut(d[degisken], n_dilim, labels=False, duplicates="drop")
    except ValueError:
        return f"    {degisken:<13s} dilimlenemedi", None
    tr = d[d.giris < BOL]; te = d[d.giris >= BOL]
    ort = [d[d.q == q]["R"].mean() for q in range(n_dilim)]
    dtr = ((tr[tr.q == n_dilim - 1]["R"].mean() - tr[tr.q == 0]["R"].mean())
           if len(tr) > 50 else np.nan)
    dte = ((te[te.q == n_dilim - 1]["R"].mean() - te[te.q == 0]["R"].mean())
           if len(te) > 50 else np.nan)
    a = d[d.q == 0]["R"]; b = d[d.q == n_dilim - 1]["R"]
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    z = (b.mean() - a.mean()) / se if se > 0 else 0.0
    ayni = (np.isfinite(dtr) and np.isfinite(dte) and np.sign(dtr) == np.sign(dte)
            and abs(dtr) > 0.02 and abs(dte) > 0.02)
    neg = [q for q in range(n_dilim) if ort[q] < 0]
    bay = ""
    if abs(z) > 2.90 and ayni: bay = "  ★★ Bonferroni'yi de geçti"
    elif abs(z) > 2.0 and ayni: bay = "  ★ anlamlı + iki dönem aynı yön"
    elif abs(z) > 2.0: bay = "  ⚠ anlamlı ama dönemler çelişiyor"
    if neg: bay += f"  ⛔ NEGATİF dilim: {[f'Q{q+1}' for q in neg]}"
    satir = (f"    {degisken:<13s} " + "  ".join(f"{v:+.3f}" for v in ort) +
             f"   z={z:+5.2f}  TR={dtr:+.3f} TE={dte:+.3f}{bay}")
    return satir, dict(z=z, ayni=ayni, neg=neg, ort=ort, dtr=dtr, dte=dte)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 124}")
    print("=== SAHTE KIRILIM: sinyalin KENDİ kalitesi ayırt edilebilir mi? ===")
    print("  (rejim = ortam, PAYLAŞILIR → kapandı · kırılım kalitesi = işleme ÖZEL → hiç test edilmedi)")

    ham = []; sapma = 0
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            m = fast_bt.load(c, source=source)
            ref = A.gen(kol, m); mine = gen_oz(kol, m)
            if len(ref) != len(mine) or any(
                    r[0] != k[0] or r[1] != k[1] or abs(r[2] - k[2]) > 1e-12
                    or abs(r[3] - k[3]) > 1e-12 for r, k in zip(ref, mine)):
                sapma += 1
            for t in mine:
                ham.append((kol, t[0], t[1].value, t[2], t[3], t[4]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append(("bb", t[0], t[1].value, t[2], t[3], {}))
    print(f"\n  EŞDEĞERLİK KANITI: "
          f"{'✓ 11 coinin hepsinde BİREBİR' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}")
    if sapma:
        print("  HİÇBİR SAYI OKUNMAZ."); return

    ham.sort(key=lambda z: z[1])
    oh = []; ctr = 0; al = []
    for kol, e, x, R, slp, oz in ham:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr))
            al.append((kol, e, x, R, slp, oz))
    tot = float(sum(R * min(A.RISKF, A.CAP * slp) * A.BAL0 for _, _, _, R, slp, _ in al))
    ok = len(al) == 1579 and abs(tot - 1420.66) < 0.01
    print(f"  KONTROL: {len(al)} işlem / ${tot:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return

    df = pd.DataFrame([{"kol": k, "giris": pd.Timestamp(e), "R": R, **oz}
                       for k, e, x, R, slp, oz in al])

    print(f"\n  Dilim başına ortalama R (düşük→yüksek beşte birlik)")
    print(f"  ARADIĞIMIZ: bir dilimin ortalama R'si NEGATİF olsun. Rejim kapısı tam burada")
    print(f"  battı — en kötü dilimi bile +0.058R idi, yani az kazananı kesiyordu.")
    bulgu = []
    for kol in ("donchian", "squeeze"):
        alt = df[df.kol == kol]
        print(f"\n  ── {kol} (n={len(alt)}, ort R {alt['R'].mean():+.4f}) ──")
        print(f"    {'özellik':<13s} {'Q1':>7s}{'Q2':>9s}{'Q3':>9s}{'Q4':>9s}{'Q5':>9s}")
        for v in OZ:
            satir, h = dilim(alt, v)
            print(satir)
            if h and (h["neg"] or (abs(h["z"]) > 2.0 and h["ayni"])):
                bulgu.append((kol, v, h))

    print(f"\n{'=' * 124}\n=== HÜKÜM ===")
    if not bulgu:
        print("  Hiçbir özellik negatif dilim üretmedi ve hiçbiri anlamlı+tutarlı çıkmadı.")
        print("  → Sahte kırılım, giriş barının bu özelliklerinden AYIRT EDİLEMİYOR.")
        return
    print(f"  {len(bulgu)} aday:")
    for kol, v, h in bulgu:
        ns = ", ".join(f"Q{q+1}={h['ort'][q]:+.3f}" for q in h["neg"]) or "yok"
        print(f"    · {kol:<9s} {v:<13s} z={h['z']:+.2f} TR={h['dtr']:+.3f} "
              f"TE={h['dte']:+.3f}  negatif dilim: {ns}")
    print(f"\n  ⚠ BU YETMEZ. Negatif dilim bulmak filtre kurmak için gerekli ama yeterli")
    print(f"    değil. Sıradaki adım: eşiği YALNIZ TRAIN'de seçip TEST'te ve walk-forward'da")
    print(f"    portföy etkisini ölçmek (regime_kapi.py'deki yöntemin aynısı). Rejim kapısı")
    print(f"    da teşhiste dört aday bulmuştu ve kapıya çevrilince ÇÖKTÜ.")


if __name__ == "__main__":
    main()
