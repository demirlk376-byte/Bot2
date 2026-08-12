"""
kok_neden.py — NEGATİF DÖNEMLERİN KÖK NEDEN ANALİZİ (filtre EKLEMEDEN önce).

Kullanıcının altı sorusu, sırayla. Üçü hiç yapılmamıştı (kol bazında zarar ayrımı,
long/short ayrımı, saat analizi, ardışık kayıp koşulları).

⚠️ ÖN BİLGİ — DÜŞÜK BEKLENTİ, AMA ÖLÇÜLECEK:
regime_sans.py karıştırma testi (10.000 permütasyon) kötü ayların şanstan AYIRT
EDİLEMEDİĞİNİ gösterdi (negatif ay sayısı p=0.32, en kötü ay p=0.53). Yani kayıplar
zamanda kümelenmiyor. Bu, [3][5][6]'da yapısal bir şey bulma ihtimalini düşürüyor —
ama o test AY seviyesindeydi; saat/yön/kol kesitleri AYRI sorulardır ve ölçülmedi.

⚠️ ÇOKLU TEST — bu betiğin en büyük tuzağı:
saat (24) × kol (3) × yön (2) = çok sayıda hücre. Saf şansla bazıları negatif çıkar.
Bu yüzden HER hücre için: n, ortalama R, güven aralığı, ve TRAIN/TEST AYRI raporlanır.
Bir hücre ancak şunları BİRLİKTE sağlarsa aday sayılır:
  · ortalama R NEGATİF
  · n >= 30 (altında güven aralığı anlamsız genişlikte)
  · TRAIN ve TEST'te İKİSİNDE DE negatif
  · |z| > Bonferroni eşiği (hücre sayısına göre hesaplanıp yazdırılır)

KULLANICI KISITLARI (hepsi uygulandı):
 · Takvim ayı filtresi YOK — ay yalnız RAPORLAMA için, filtre değişkeni olarak KULLANILMAZ.
 · Yeni indikatör YOK — yalnız sistemde zaten olanlar: ATR, ADX, EMA200, kanal, hacim.
 · Retest zorunlu değil — bu betikte retest hiç yok.
 · Eşik optimizasyonu YOK — sınıf sınırları TRAIN yüzdeliklerinden, kâra bakılmadan.
 · Walk-forward bozulursa filtre REDDEDİLİR.

BUGÜN DOĞRULANAN İKİ ŞARTLI KURAL (DURUM.md):
 1. Kesilecek grubun ortalama R'si NEGATİF olmalı.
 2. O gruptan çıkmanın bedeli, grubun zararından KÜÇÜK olmalı.
Bu betik (1)'i arar; bulursa (2) walk-forward'da ölçülür.

Kullanım:  py kok_neden.py local
"""
import heapq
import math
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from regime_sans import gen_dir            # eşdeğerliği regime_sans'ta KANITLANDI

BOL = pd.Timestamp("2025-01-01")
CAP = 1.50


def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


def portfoy_rejim(source, coins):
    """Portföy seviyesi rejim (shift(1) — lookahead yok)."""
    ser = {c: fast_bt.load(c, source=source)["close"].resample("1D").last() for c in coins}
    px = pd.DataFrame(ser).dropna(how="all").ffill()
    px.index = _naive(px.index)
    ret = px.pct_change()
    ema200 = px.ewm(span=200, adjust=False).mean()
    return pd.DataFrame({
        "vol20": ret.rolling(20).std().mean(axis=1),
        "trend_pay": (px > ema200).mean(axis=1),
    }).shift(1)


def coin_rejim(m, tf):
    d = fast_bt.resample(m, tf)
    a = adx_fn(d["high"], d["low"], d["close"], 14)
    at = atr_fn(d["high"], d["low"], d["close"], 14) / d["close"]
    out = pd.DataFrame({"adx": a.values, "atr_pct": at.values}, index=d.index).shift(1)
    out.index = _naive(out.index)
    return out


def havuz(source):
    tum = A.DONCH + A.SQZ + A.BB_COINS
    rej = portfoy_rejim(source, tum)
    ham = []; sapma = 0
    for kol, coins, tf in (("donchian", A.DONCH, "4h"), ("squeeze", A.SQZ, "1h")):
        for c in coins:
            m = fast_bt.load(c, source=source)
            ref = A.gen(kol, m); mine = gen_dir(kol, m)
            if len(ref) != len(mine) or any(
                    r[0] != k[0] or r[1] != k[1] or abs(r[2] - k[2]) > 1e-12
                    for r, k in zip(ref, mine)):
                sapma += 1
            cr = coin_rejim(m, tf)
            for t in mine:
                ham.append((kol, c, t[0], t[1].value, t[2], t[3], t[4], cr))
    for c in A.BB_COINS:
        m = fast_bt.load(c, source=source)
        cr = coin_rejim(m, "1h")
        for t in A.gen_bb(m):
            ham.append(("bb", c, t[0], t[1].value, t[2], t[3], 0, cr))

    ham.sort(key=lambda z: z[2])
    oh = []; ctr = 0; al = []
    for kol, c, e, x, R, slp, d_, cr in ham:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr))
            al.append((kol, c, e, x, R, slp, d_, cr))

    sat = []
    for kol, c, e, x, R, slp, d_, cr in al:
        ts = pd.Timestamp(e); xs = pd.Timestamp(x)
        row = {"kol": kol, "coin": c, "giris": ts, "cikis": xs, "R": R, "slp": slp,
               "yon": ("long" if d_ == 1 else ("short" if d_ == -1 else "—")),
               "saat": int(ts.hour), "pnl": R * min(A.RISKF, CAP * slp) * A.BAL0}
        g = ts.normalize()
        row.update(rej.loc[g].to_dict() if g in rej.index
                   else {k: np.nan for k in rej.columns})
        pos = cr.index.searchsorted(ts, side="right") - 1
        row["adx"] = cr["adx"].values[pos] if pos >= 0 else np.nan
        row["atr_pct"] = cr["atr_pct"].values[pos] if pos >= 0 else np.nan
        sat.append(row)
    return pd.DataFrame(sat), sapma


def hucre(d, ad, hucre_sayisi):
    """Bir alt küme için: n, ort R, z, TRAIN/TEST. Aday mı değil mi karar verir."""
    n = len(d)
    if n < 5:
        return None
    r = d["R"].values
    se = r.std(ddof=1) / math.sqrt(n) if n > 1 else float("inf")
    z = r.mean() / se if se > 0 else 0.0
    tr = d[d.giris < BOL]["R"]; te = d[d.giris >= BOL]["R"]
    bonf = 2.807 if hucre_sayisi <= 0 else abs(_bonferroni(hucre_sayisi))
    aday = (r.mean() < 0 and n >= 30 and len(tr) >= 10 and len(te) >= 10
            and tr.mean() < 0 and te.mean() < 0 and abs(z) > bonf)
    return dict(ad=ad, n=n, ort=float(r.mean()), z=float(z),
                tr=float(tr.mean()) if len(tr) else np.nan,
                te=float(te.mean()) if len(te) else np.nan,
                ntr=len(tr), nte=len(te), aday=aday, pnl=float(d["pnl"].sum()))


def _bonferroni(k):
    """k test için iki yönlü %5 eşiğinin z karşılığı."""
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - 0.05 / (2 * max(k, 1)))


def yaz_hucre(h, bonf):
    if h is None:
        return
    bay = ""
    if h["aday"]:
        bay = "  ★★ ADAY"
    elif h["ort"] < 0 and h["n"] >= 30:
        neden = []
        if not (h["tr"] < 0 and h["te"] < 0): neden.append("dönem çelişki")
        if abs(h["z"]) <= bonf: neden.append(f"|z|<{bonf:.2f}")
        bay = "  ⛔ negatif ama: " + ", ".join(neden)
    elif h["ort"] < 0:
        bay = f"  (negatif ama n={h['n']}<30)"
    print(f"    {h['ad']:<26s} {h['n']:>5d} {h['ort']:>+8.3f} {h['z']:>+6.2f} "
          f"{h['tr']:>+8.3f}({h['ntr']:>3d}) {h['te']:>+8.3f}({h['nte']:>3d}) "
          f"{h['pnl']:>+8.1f}{bay}")


BASLIK = (f"    {'hücre':<26s} {'n':>5s} {'ort R':>8s} {'z':>6s} "
          f"{'TRAIN':>8s}      {'TEST':>8s}      {'PnL$':>8s}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    df, sapma = havuz(source)
    tot = df["R"].mul(np.minimum(A.RISKF, A.CAP * df["slp"])).mul(A.BAL0).sum()
    ok = len(df) == 1579 and abs(tot - 1420.66) < 0.01
    print(f"\n{'=' * 116}")
    print("=== KÖK NEDEN ANALİZİ: bot hangi koşulda para kaybediyor? ===")
    print(f"  EŞDEĞERLİK: {'✓' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}   "
          f"KONTROL: {len(df)} işlem / ${tot:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if sapma or not ok:
        print("  HİÇBİR SAYI OKUNMAZ."); return
    print(f"  (aşağıdaki PnL'ler CAP={CAP} tabanında — paket sonrası hâl)")

    df["ay"] = df["cikis"].dt.to_period("M")
    ay = df.groupby("ay")["pnl"].sum()
    neg_aylar = ay[ay < 0]

    # ── [1] + [2] NEGATİF AYLAR ve KOL AYRIMI ──
    print(f"\n[1][2] NEGATİF AYLAR ve zararın KOL DAĞILIMI  ({len(neg_aylar)}/{len(ay)} ay)")
    print(f"    {'ay':<9s} {'toplam$':>9s} {'donchian$':>10s} {'squeeze$':>9s} {'bb$':>8s} "
          f"{'işlem':>6s} {'en büyük kayıp':>15s}")
    kol_top = {"donchian": 0.0, "squeeze": 0.0, "bb": 0.0}
    for a_, v in neg_aylar.items():
        s = df[df.ay == a_]
        pk = {k: s[s.kol == k]["pnl"].sum() for k in kol_top}
        for k in kol_top: kol_top[k] += pk[k]
        enk = s.nsmallest(1, "pnl")
        print(f"    {str(a_):<9s} {v:>+9.1f} {pk['donchian']:>+10.1f} {pk['squeeze']:>+9.1f} "
              f"{pk['bb']:>+8.1f} {len(s):>6d} "
              f"{enk['pnl'].iloc[0]:>+9.1f} {enk['coin'].iloc[0]:<6s}")
    tn = sum(kol_top.values())
    print(f"    {'TOPLAM':<9s} {tn:>+9.1f} {kol_top['donchian']:>+10.1f} "
          f"{kol_top['squeeze']:>+9.1f} {kol_top['bb']:>+8.1f}")
    print(f"    payı:                {kol_top['donchian']/tn*100:>9.0f}% "
          f"{kol_top['squeeze']/tn*100:>8.0f}% {kol_top['bb']/tn*100:>7.0f}%")
    tum_pay = {k: df[df.kol == k]["pnl"].sum() for k in kol_top}
    print(f"    KIYAS — tüm dönemdeki kol payları: "
          + " · ".join(f"{k} ${tum_pay[k]:+.0f}" for k in kol_top))
    print(f"    → Bir kol negatif aylarda ORANSIZ pay alıyorsa suçlu odur.")

    # ── [3] REJİM SINIFI ──
    print(f"\n[3] KAYBEDEN İŞLEMLERİN REJİMİ (sınıf sınırları TRAIN yüzdeliğinden)")
    tr = df[df.giris < BOL]
    q_adx = tr["adx"].quantile([0.33, 0.67]).values
    q_vol = tr["atr_pct"].quantile([0.33, 0.67]).values
    def sinif(r):
        t = "güçlü trend" if r.adx >= q_adx[1] else ("range" if r.adx < q_adx[0] else "ara")
        v = "yüksek vol" if r.atr_pct >= q_vol[1] else ("düşük vol" if r.atr_pct < q_vol[0]
                                                        else "orta vol")
        return f"{t}/{v}"
    df["rejim"] = df.apply(sinif, axis=1)
    hs = df["rejim"].nunique() * 1
    bonf = _bonferroni(hs)
    print(f"    (Bonferroni eşiği {hs} hücre için |z|>{bonf:.2f})")
    print(BASLIK)
    adaylar = []
    for r_, g in sorted(df.groupby("rejim"), key=lambda kv: kv[1]["R"].mean()):
        h = hucre(g, r_, hs); yaz_hucre(h, bonf)
        if h and h["aday"]: adaylar.append(("rejim", r_, h))

    # ── [4] LONG / SHORT ──
    print(f"\n[4] YÖN — long vs short, kol bazında")
    hs4 = 6; b4 = _bonferroni(hs4)
    print(f"    (Bonferroni eşiği {hs4} hücre için |z|>{b4:.2f})")
    print(BASLIK)
    for kol in ("donchian", "squeeze"):
        for y in ("long", "short"):
            g = df[(df.kol == kol) & (df.yon == y)]
            h = hucre(g, f"{kol} {y}", hs4); yaz_hucre(h, b4)
            if h and h["aday"]: adaylar.append(("yon", (kol, y), h))

    # ── [5] SAAT ──
    print(f"\n[5] SAAT (giriş, UTC) — kol bazında")
    for kol in ("donchian", "squeeze"):
        alt = df[df.kol == kol]
        saatler = sorted(alt["saat"].unique())
        hs5 = len(saatler); b5 = _bonferroni(hs5)
        print(f"\n    ── {kol} ({hs5} farklı saat · Bonferroni |z|>{b5:.2f}) ──")
        print(BASLIK)
        for s_ in saatler:
            g = alt[alt.saat == s_]
            h = hucre(g, f"{kol} {s_:02d}:00", hs5); yaz_hucre(h, b5)
            if h and h["aday"]: adaylar.append(("saat", (kol, s_), h))

    # ── [6] ARDIŞIK KAYIPLAR ──
    print(f"\n[6] ARDIŞIK KAYIPLAR — seri hâlinde gelen kayıpların ortak koşulu")
    d2 = df.sort_values("cikis").reset_index(drop=True)
    seri = 0; seri_no = []
    for r_ in d2["R"].values:
        seri = seri + 1 if r_ < 0 else 0
        seri_no.append(seri)
    d2["seri"] = seri_no
    print(f"    en uzun kayıp serisi: {max(seri_no)} işlem")
    print(f"    {'seri konumu':<14s} {'n':>5s} {'ort vol20':>10s} {'ort trend_pay':>14s} "
          f"{'ort adx':>8s} {'ort atr%':>9s}")
    for lo_, hi_, ad in ((1, 1, "1. kayıp"), (2, 3, "2-3. kayıp"),
                         (4, 99, "4+ kayıp"), (0, 0, "kazanç sonrası")):
        g = d2[(d2.seri >= lo_) & (d2.seri <= hi_)] if lo_ > 0 else d2[d2.seri == 0]
        if len(g) < 10: continue
        print(f"    {ad:<14s} {len(g):>5d} {g['vol20'].mean():>10.4f} "
              f"{g['trend_pay'].mean():>14.3f} {g['adx'].mean():>8.2f} "
              f"{g['atr_pct'].mean()*100:>8.2f}%")
    print(f"    → Uzun serilerin rejim ortalamaları diğerlerinden BELİRGİN farklı DEĞİLSE,")
    print(f"      ardışık kayıp özel bir koşulun ürünü değil, %43.5 WR'nin aritmetiğidir.")

    # ── HÜKÜM ──
    print(f"\n{'=' * 116}\n=== CEVAP: bot hangi koşulda para kaybediyor? ===")
    if not adaylar:
        print("\n  HİÇBİR koşul dört şartı birden sağlamadı:")
        print("    ortalama R negatif · n>=30 · TRAIN ve TEST'te İKİSİNDE DE negatif ·")
        print("    Bonferroni eşiğini geçen |z|")
        print("\n  → Sistematik olarak para kaybettiren TESPİT EDİLEBİLİR bir koşul YOK.")
        print("    Negatif aylar belirli bir rejimden, yönden ya da saatten gelmiyor;")
        print("    %43.5 kazanma oranıyla çalışan bir sistemin normal dağılımı.")
        print("    Bu, karıştırma testinin (p=0.32) bağımsız bir teyidi.")
        print("\n  → FİLTRE EKLENMEZ. Kesilecek bir grup yok; her kesim kârlı işlem keser")
        print("    (bugün dört kez ölçüldü: skor kapısı, atr kapısı, teyit, erken çıkış).")
    else:
        print(f"\n  {len(adaylar)} koşul dört şartı da geçti — walk-forward'a gidebilir:")
        for tur, k, h in adaylar:
            print(f"    · [{tur}] {h['ad']}: n={h['n']} ort R {h['ort']:+.3f} "
                  f"(TRAIN {h['tr']:+.3f} / TEST {h['te']:+.3f}) z={h['z']:+.2f} "
                  f"PnL ${h['pnl']:+.0f}")
        print(f"\n  ⚠ İKİNCİ ŞART HENÜZ SINANMADI: bu gruptan çıkmanın bedeli zarardan")
        print(f"    küçük mü? Sahte kırılımda birinci şart sağlanmıştı (−0.2488R, z=6.39)")
        print(f"    ama üç uygulama yolu da kaybettirdi. Walk-forward şart.")


if __name__ == "__main__":
    main()
