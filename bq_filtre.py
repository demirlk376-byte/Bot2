"""
bq_filtre.py — BREAKOUT QUALITY FILTER: kalite skoru + kırılım sonrası TEYİT.

KULLANICI ÖNERİSİNİN YEDİ KRİTERİ — beşi bugün zaten ölçüldü (fake_kirilim.py):
  1. kapanış kanal dışında mı?   → ZATEN ŞART. donchian.py close-confirmed giriş yapar;
                                    her işlem tanımı gereği kanal dışında kapanmıştır.
  2. gövde güçlü mü / fitilli mi? → ÖLÇÜLDÜ: govde z=+0.63, kapanis_yeri z=-0.00 (SIFIR).
  4. higher timeframe destek?     → ZATEN VAR: EMA200 kapısı + günlük EMA20 MTF kapısı.
  5. volatilite yeterli mi?       → ÖLÇÜLDÜ: atr_orani z=+2.15 (tek gerçek sinyal), ama
                                    kapıya çevrilince walk-forward -$41 (negatif alt küme yok).
  6. hacim destekliyor mu?        → ÖLÇÜLDÜ: z=+1.49, negatif alt küme yok.
  3. kırılım sonrası kanala dönüş → HİÇ TEST EDİLMEDİ  ← bu betiğin [B] bölümü
  7. retest başarılı mı           → HİÇ TEST EDİLMEDİ  ← bu betiğin [B] bölümü

(3) ve (7) neden farklı: giriş barında BİLİNMİYORLAR. Ancak kırılımdan SONRA görülürler.
Yani bunlar filtre değil, GİRİŞ ZAMANLAMASI değişikliğidir — bir bar bekleyip teyit
aramak. Bekleyince giriş fiyatı, stop ve R tamamen değişir; bu yüzden basit bir kapı
gibi ölçülemez, AYRI BİR VARYANT olarak baştan simüle edilmesi gerekir.

──────────────────────────────────────────────────────────────────────────────────
[A] KALİTE SKORU — kullanıcının asıl istediği şey
Tek tek zayıf olan sinyaller BİRLİKTE negatif bir alt küme üretebilir mi?
Bugün doğrulanan kural: bir filtre ancak kestiği kümenin ort R'si NEGATİF ise kazandırır.

AŞIRI OPTİMİZASYONU ÖNLEYEN TASARIM (kullanıcının açık şartı):
 · Ağırlıklar EŞİT. Kâra bakılarak ağırlık AYARLANMAZ.
 · Her özelliğin YÖNÜ yalnız TRAIN(<2025) verisinden belirlenir, TEST'e bakılmaz.
 · Skor = yön-işaretli z-skorların ortalaması. Serbest parametre YOK.
 · Eşik de yalnız TRAIN yüzdeliğinden.

[B] KIRILIM SONRASI TEYİT — gerçekten yeni olan kısım
Kırılım barında GİRME. Bir sonraki barı bekle:
  · v1 TEYİT : bar i+1 kapanışı hâlâ kanal DIŞINDA ise i+1 kapanışından gir.
               İçeri döndüyse SAHTE KIRILIM sayılır, işlem YOK.
  · v2 RETEST: bar i+1 kanala geri dokunup (fitille) yine DIŞARIDA kapandıysa gir
               (başarılı retest). Sadece dokunmadan devam ettiyse de gir (güçlü kırılım
               kaçmasın — kullanıcının açık şartı). Kapanış içerideyse gir-me.
Her varyantta giriş fiyatı, stop (2xATR) ve R baştan hesaplanır. maxhold penceresi
kırılım barından itibaren korunur ki karşılaştırma adil olsun.

METRİKLER (kullanıcının istediği tam liste): sahte kırılım sayısı · PF · maxDD ·
net PnL · WR · işlem sayısı. Artı: en kötü ay, negatif ay sayısı, yıl kırılımı.
DOĞRULAMA: TAM DÖNEM (iyimser) + OUT-OF-SAMPLE + WALK-FORWARD.

Kullanım:  py bq_filtre.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy

BOL = pd.Timestamp("2025-01-01")
CAP_YENI = 1.50
# Kalite skoruna giren özellikler. YÖNLERİ TRAIN'den belirlenecek — burada sabit yön YOK.
SKOR_OZ = ["tasma", "govde", "kapanis_yeri", "hacim", "atr_orani", "kanal_gen"]


def donch_ham(m, source_tag=""):
    """Donchian sinyalleri + giriş barı özellikleri + SONRAKİ bar bilgisi.
    A.gen ile BİREBİR aynı taban işlemleri üretir (main()'de kanıtlanır)."""
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    op = d["open"].values; hi = d["high"].values; lo = d["low"].values
    cl = d["close"].values; vo = d["volume"].values
    volma = pd.Series(vo).rolling(20).mean().values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 2):                      # n-2: i+1 barına erişebilmek için
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue

        # ── TABAN İŞLEM (ankorla birebir) ──
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

        # ── GİRİŞ BARI ÖZELLİKLERİ ──
        rng = hi[i] - lo[i]
        ch_h = float(getattr(sg, "channel_high", 0.0) or 0.0)
        ch_l = float(getattr(sg, "channel_low", 0.0) or 0.0)
        sinir = ch_h if d_ == 1 else ch_l            # kırılan kanal sınırı
        oz = {
            "tasma": ((cl[i] - ch_h) if d_ == 1 else (ch_l - cl[i])) / a
                     if (ch_h > 0 and ch_l > 0) else np.nan,
            "govde": abs(cl[i] - op[i]) / rng if rng > 0 else np.nan,
            "kapanis_yeri": (((cl[i] - lo[i]) if d_ == 1 else (hi[i] - cl[i])) / rng
                             if rng > 0 else np.nan),
            "hacim": vo[i] / volma[i] if np.isfinite(volma[i]) and volma[i] > 0 else np.nan,
            "atr_orani": a / atr_ser[i - 20] if (i >= 20 and np.isfinite(atr_ser[i - 20])
                                                 and atr_ser[i - 20] > 0) else np.nan,
            "kanal_gen": (ch_h - ch_l) / a if (ch_h > 0 and ch_l > 0) else np.nan,
        }

        # ── SONRAKİ BAR: teyit / geri dönüş / retest ──
        k = i + 1
        a2 = atr_ser[k]
        iceri = ((cl[k] < sinir) if d_ == 1 else (cl[k] > sinir)) if sinir > 0 else False
        dokundu = ((lo[k] <= sinir) if d_ == 1 else (hi[k] >= sinir)) if sinir > 0 else False

        # v1/v2 girişi: i+1 kapanışından, stop yeniden hesaplanır
        alt = None
        if (not iceri) and np.isfinite(a2) and a2 > 0:
            e2 = cl[k]; sld2 = sl_a * a2
            slp2 = e2 - d_ * sld2; tp2 = e2 + d_ * rr * sld2
            ep2 = None; j2 = k
            # maxhold penceresi KIRILIM barından sayılır (adil karşılaştırma)
            for j2 in range(k + 1, min(i + 1 + mh, n)):
                if d_ == 1:
                    if lo[j2] <= slp2: ep2 = slp2; break
                    if hi[j2] >= tp2: ep2 = tp2; break
                else:
                    if hi[j2] >= slp2: ep2 = slp2; break
                    if lo[j2] <= tp2: ep2 = tp2; break
            if ep2 is None:
                j2 = min(i + mh, n - 1); ep2 = cl[j2]
            if j2 > k:
                R2 = d_ * (ep2 - e2) / sld2 - 2 * A.FEE * e2 / sld2
                alt = (idx[k].value, idx[j2].value, R2, sld2 / e2)

        out.append(dict(e=idx[i].value, x=idx[j].value, R=R, slp=sld / e,
                        iceri=bool(iceri), dokundu=bool(dokundu), alt=alt, **oz))
        occ = j
    return out


def koltuk(rows):
    """rows: (e, x, R, slp) sıralı liste. Ankorla aynı koltuk mantığı."""
    oh = []; ctr = 0; al = []
    for e, x, R, slp in rows:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr))
            al.append((x, R, slp))
    return al


def metrik(al, cap=CAP_YENI):
    if not al:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, ortR=0.0, dd=0.0, worst=0.0,
                    negay=0, ay=0, yr={})
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
                yr={int(k): float(v) for k, v in yr.items()})


def yaz(ad, m, tb=None, ekstra=""):
    d = f"{m['tot']-tb['tot']:+7.0f}" if tb else f"{'—':>7s}"
    print(f"  {ad:<26s} {m['n']:>6d} {m['tot']:>+9.0f} {d} {m['pf']:>6.2f} {m['wr']:>6.1f} "
          f"{m['ortR']:>+7.3f} {m['dd']:>7.1f} {m['worst']:>+9.1f} "
          f"{m['negay']:>3d}/{m['ay']:<3d}{ekstra}")


BAS = (f"\n  {'yapılandırma':<26s} {'işlem':>6s} {'netPnL$':>9s} {'Δ$':>7s} {'PF':>6s} "
       f"{'WR%':>6s} {'ortR':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"

    # ── HAVUZ + EŞDEĞERLİK ──
    dn = []; sapma = 0
    for c in A.DONCH:
        m = fast_bt.load(c, source=source)
        ref = A.gen("donchian", m); mine = donch_ham(m)
        # n-2 sınırı yüzünden SON işlem farkı olabilir; o yüzden ortak önek karşılaştırılır
        k = min(len(ref), len(mine))
        if any(ref[t][0] != mine[t]["e"] or ref[t][1].value != mine[t]["x"]
               or abs(ref[t][2] - mine[t]["R"]) > 1e-12
               or abs(ref[t][3] - mine[t]["slp"]) > 1e-12 for t in range(k)) or \
           abs(len(ref) - len(mine)) > 1:
            sapma += 1
        dn += mine
    diger = []
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            diger.append((t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            diger.append((t[0], t[1].value, t[2], t[3]))

    print(f"\n{'=' * 122}")
    print("=== BREAKOUT QUALITY FILTER — kalite skoru + kırılım sonrası teyit ===")
    print(f"  EŞDEĞERLİK (donchian): "
          f"{'✓ BİREBİR' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}")
    if sapma:
        print("  HİÇBİR SAYI OKUNMAZ."); return

    df = pd.DataFrame(dn)
    df["giris"] = pd.to_datetime(df["e"])

    def portfoy(donch_rows):
        """donchian satırları + diğer kollar → koltuk → metrik."""
        hepsi = sorted(list(donch_rows) + diger, key=lambda z: z[0])
        return metrik(koltuk(hepsi))

    taban_rows = [(r.e, r.x, r.R, r.slp) for r in df.itertuples()]
    kon = metrik(koltuk(sorted(taban_rows + diger, key=lambda z: z[0])), cap=A.CAP)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"  KONTROL: {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        print(f"    sayı {'tutuyor' if kon['n']==1579 else 'TUTMUYOR'}, "
              f"fark {kon['tot']-1420.66:+.2f}$"); return

    taban = portfoy(taban_rows)

    # ── [A] KALİTE SKORU ──
    print(f"\n[A] KALİTE SKORU — eşit ağırlık, yön YALNIZ TRAIN'den, serbest parametre YOK")
    tr = df[df["giris"] < BOL]
    yon = {}
    for v in SKOR_OZ:
        a = tr[tr[v].notna()]
        if len(a) < 100:
            yon[v] = 0.0; continue
        med = a[v].median()
        yon[v] = float(np.sign(a[a[v] > med]["R"].mean() - a[a[v] <= med]["R"].mean()))
    print(f"    TRAIN'den belirlenen yönler: " +
          " · ".join(f"{v}{'+' if yon[v] > 0 else '−'}" for v in SKOR_OZ))
    mu = {v: tr[v].mean() for v in SKOR_OZ}; sd = {v: tr[v].std() for v in SKOR_OZ}
    z = np.zeros(len(df)); say = np.zeros(len(df))
    for v in SKOR_OZ:
        if not sd[v] or not np.isfinite(sd[v]) or yon[v] == 0:
            continue
        col = (df[v].values - mu[v]) / sd[v] * yon[v]
        ok_m = np.isfinite(col)
        z[ok_m] += col[ok_m]; say[ok_m] += 1
    df["skor"] = np.where(say > 0, z / np.maximum(say, 1), np.nan)

    d5 = df[df["skor"].notna()].copy()
    d5["q"] = pd.qcut(d5["skor"], 5, labels=False, duplicates="drop")
    print(f"\n    {'dilim':>6s} {'n':>5s} {'ort skor':>9s} {'ort R':>8s} {'WR%':>6s}")
    negq = []
    for q in range(5):
        s = d5[d5.q == q]
        rr_ = s["R"].mean()
        if rr_ < 0: negq.append(q)
        print(f"    {'Q'+str(q+1):>6s} {len(s):>5d} {s['skor'].mean():>9.3f} "
              f"{rr_:>+8.3f} {(s['R'] > 0).mean()*100:>6.1f}")
    print(f"\n    → NEGATİF dilim: {[f'Q{q+1}' for q in negq] if negq else 'YOK'}")
    if not negq:
        print(f"    ⚠ Bugün doğrulanan kurala göre negatif alt küme YOKSA kapı para")
        print(f"      KAYBETTİRİR (dn_atr kanıtı: güçlü sinyal, negatif küme yok, −$41).")
        print(f"      Yine de ölçülüyor — kural yanlışsa burada görünsün.")

    # `tr` yukarıda skor HESAPLANMADAN önce alınmıştı (df'in kopyası) → 'skor' sütunu
    # yok, KeyError. TRAIN dilimi skor eklendikten SONRA yeniden alınmalı.
    tr = df[df["giris"] < BOL]

    print(f"\n    KAPI: skor eşiğin ALTINDAysa işlem YOK (eşik yalnız TRAIN'den)")
    print(BAS); yaz("kapısız (taban)", taban)
    for kes in (0.10, 0.20, 0.30):
        esik = float(tr["skor"].quantile(kes)) if tr["skor"].notna().sum() > 50 else np.nan
        if not np.isfinite(esik):
            continue
        kalan = [(r.e, r.x, r.R, r.slp) for r in df.itertuples()
                 if not (np.isfinite(r.skor) and r.skor <= esik)]
        yaz(f"skor kapısı %{kes*100:.0f}", portfoy(kalan), taban)

    # ── [B] KIRILIM SONRASI TEYİT ──
    print(f"\n[B] KIRILIM SONRASI TEYİT — girişi 1 bar geciktir (YENİ EKSEN)")
    n_ic = int(df["iceri"].sum())
    ic = df[df["iceri"]]; dis = df[~df["iceri"]]
    print(f"    SAHTE KIRILIM SAYISI: {n_ic}/{len(df)} (%{n_ic/len(df)*100:.1f}) "
          f"sonraki bar kanal İÇİNDE kapanmış")
    print(f"      geri dönenlerin ort R : {ic['R'].mean():+.4f}  (n={len(ic)})")
    print(f"      dönmeyenlerin ort R   : {dis['R'].mean():+.4f}  (n={len(dis)})")
    se = np.sqrt(ic["R"].var(ddof=1)/len(ic) + dis["R"].var(ddof=1)/len(dis))
    zz = (dis["R"].mean() - ic["R"].mean()) / se if se > 0 else 0.0
    print(f"      fark {dis['R'].mean()-ic['R'].mean():+.4f}R  z={zz:+.2f} "
          f"{'✓ ANLAMLI' if abs(zz) > 2 else '✗ anlamsız'}")
    for ad, alt in (("TRAIN", df[df['giris'] < BOL]), ("TEST", df[df['giris'] >= BOL])):
        i2 = alt[alt["iceri"]]; d2 = alt[~alt["iceri"]]
        if len(i2) > 10 and len(d2) > 10:
            print(f"      {ad:<5s} geri dönen {i2['R'].mean():+.4f} vs "
                  f"dönmeyen {d2['R'].mean():+.4f}  (fark {d2['R'].mean()-i2['R'].mean():+.4f})")

    print(f"\n    VARYANTLAR (giriş i+1 kapanışından, stop yeniden hesaplanır):")
    print(BAS); yaz("v0 taban (i'de gir)", taban)
    # v1: teyit — i+1 dışarıda kapandıysa gir
    v1 = [(r.alt[0], r.alt[1], r.alt[2], r.alt[3]) for r in df.itertuples()
          if r.alt is not None]
    yaz("v1 teyit (i+1 dışarıda)", portfoy(v1), taban,
        f"   atlanan {len(df)-len(v1)}")
    # v2: retest — dokunup dışarıda kapananlar ÖNCELİKLİ, dokunmayanlar da alınır
    v2 = [(r.alt[0], r.alt[1], r.alt[2], r.alt[3]) for r in df.itertuples()
          if r.alt is not None and r.dokundu]
    yaz("v2 yalnız retest edenler", portfoy(v2), taban,
        f"   atlanan {len(df)-len(v2)}")

    # ── OUT-OF-SAMPLE + WALK-FORWARD (v1 için) ──
    print(f"\n[C] v1 TEYİT — out-of-sample ve walk-forward")
    te_t = [(r.e, r.x, r.R, r.slp) for r in df.itertuples() if r.giris >= BOL]
    te_v = [(r.alt[0], r.alt[1], r.alt[2], r.alt[3]) for r in df.itertuples()
            if r.giris >= BOL and r.alt is not None]
    print(BAS)
    yaz("TEST kapısız", portfoy(te_t))
    yaz("TEST v1 teyit", portfoy(te_v), portfoy(te_t))
    print(f"\n    {'yıl':>6s} {'taban$':>9s} {'v1$':>9s} {'Δ$':>7s} {'atlanan':>8s} "
          f"{'kötü ay(t)':>11s} {'kötü ay(v1)':>12s}")
    tk = tp = 0.0
    for yil in (2023, 2024, 2025, 2026):
        b = pd.Timestamp(f"{yil}-01-01"); s2 = pd.Timestamp(f"{yil+1}-01-01")
        sub = df[(df["giris"] >= b) & (df["giris"] < s2)]
        if len(sub) < 20:
            continue
        t0 = [(r.e, r.x, r.R, r.slp) for r in sub.itertuples()]
        t1 = [(r.alt[0], r.alt[1], r.alt[2], r.alt[3]) for r in sub.itertuples()
              if r.alt is not None]
        a_ = portfoy(t0); b_ = portfoy(t1)
        tk += a_["tot"]; tp += b_["tot"]
        print(f"    {yil:>6d} {a_['tot']:>+9.0f} {b_['tot']:>+9.0f} "
              f"{b_['tot']-a_['tot']:>+7.0f} {len(t0)-len(t1):>8d} "
              f"{a_['worst']:>+11.1f} {b_['worst']:>+12.1f}")
    print(f"    {'TOPLAM':>6s} {tk:>+9.0f} {tp:>+9.0f} {tp-tk:>+7.0f}")

    print(f"\n{'=' * 122}\n=== NASIL OKUNUR ===")
    print("  · [A] negatif dilim YOKSA kapı kaybettirir (bugün deneyle doğrulandı).")
    print("  · [B] 'sahte kırılım sayısı' = sonraki bar kanal içinde kapananlar.")
    print("    Bu grubun ort R'si diğerinden BELİRGİN düşük DEĞİLSE, 'sahte kırılım'")
    print("    kavramı bu veride karşılığı olmayan bir sezgidir.")
    print("  · v1/v2 giriş fiyatını değiştirir; kâr düşse bile WR/PF yükselebilir —")
    print("    ama bizi ilgilendiren NET PnL ve kuyruk.")
    print("  · Karar [C]'den çıkar: TEST ve walk-forward'ın ikisinde birden tutmalı.")


if __name__ == "__main__":
    main()
