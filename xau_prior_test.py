"""
xau_prior_test.py — EKSEN 2: XAU (altın) kolunun ÖN-BİLGİ ve MEKANİK testi.

BU BETİK ALTIN VERİSİ KULLANMAZ. Altın verisi bu konteynerde YOK (ağ kapalı, 403).
Yaptığı şey: ALTINA GEÇMEDEN ÖNCE, kendi verimizden ölçülebilen HER ŞEYİ ölçmek,
ve altın için gereken tek girdiyi (yıllık volatilite) AÇIK BİR VARSAYIM olarak
bırakmak. Böylece "altın verisi gelince ne olacağı" sayıyla önceden bilinir.

Dört ölçüm (hepsi yerel data/*.csv ve ÜRETİM sınıflarıyla):
  M1  Koltuk doluluğu (MAXPOS=7) — altın kolu kripto işlemi düşürür mü?
  M2  Marjin profili — 10x'te eşzamanlı marjin ne kadar, altın eklenirse ne olur?
  M3  Vol → SL% ölçek yasası — 22 coinden ölçülür, altına EKSTRAPOLE edilir (c şıkkı)
  M4  Trend mekanizması — varyans oranı + kırılım-sonrası sürüklenme (b şıkkı)

Kullanım:  python3 xau_prior_test.py local
"""
from __future__ import annotations

import sys
import heapq
import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn
import deployed_backtest as DB   # ÜRETİM ANKORU — gen() / gen_bb() yeniden yazılmıyor

BAL0 = DB.BAL0          # 190
RISKF = DB.RISKF        # 0.0225
CAP = DB.CAP            # 1.25
MAXPOS = DB.MAXPOS      # 7
LEV = 10.0              # .env LEVERAGE=10

ALL_COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE",
             "DOT", "ETC", "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX",
             "VET", "XLM", "XMR", "XRP"]


# ──────────────────────────────────────────────────────────────────────
# Ankorun işlemlerini ÜRET (deployed_backtest ile birebir), ama koltuk
# seçimini ZAMAN ÇİZELGESİYLE yap ki doluluk ve marjin ölçülebilsin.
# ──────────────────────────────────────────────────────────────────────
def anchor_trades(source="local"):
    tr = []
    for c in DB.DONCH:
        for t in DB.gen("donchian", fast_bt.load(c, source=source)):
            tr.append((*t, c, "donchian"))
    for c in DB.SQZ:
        for t in DB.gen("squeeze", fast_bt.load(c, source=source)):
            tr.append((*t, c, "squeeze"))
    for c in DB.BB_COINS:
        for t in DB.gen_bb(fast_bt.load(c, source=source)):
            tr.append((*t, c, "bb"))
    return tr


def seat_timeline(trades, maxpos=MAXPOS):
    """deployed_backtest.seat_select ile AYNI mantık, ama neyin reddedildiğini
    ve her an kaç koltuğun dolu olduğunu da döndürür."""
    ev = sorted(trades, key=lambda t: t[0])
    openh = []          # (exit_ts, ctr, ...)
    taken, rejected = [], []
    occupancy = []      # (entry_ts, kaç koltuk doluydu GİRİŞ ANINDA (kabul öncesi))
    ctr = 0
    for entry_ns, exit_ts, R, slp, coin, sleeve in ev:
        while openh and openh[0][0].value <= entry_ns:
            heapq.heappop(openh)
        occupancy.append((entry_ns, len(openh)))
        if len(openh) < maxpos:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((entry_ns, exit_ts, R, slp, coin, sleeve))
        else:
            rejected.append((entry_ns, exit_ts, R, slp, coin, sleeve))
    return taken, rejected, occupancy


def m1_m2_seat_and_margin(taken, rejected, occupancy, bal=BAL0):
    print("=" * 84)
    print("M1 — KOLTUK DOLULUĞU (MAXPOS=%d).  Altın kolu kripto işlemi DÜŞÜRÜR MÜ?" % MAXPOS)
    print("=" * 84)
    occ = np.array([o for _, o in occupancy])
    n_raw = len(occ)
    print(f"  ham sinyal {n_raw} → kabul {len(taken)}, koltuk-dolu-reddi {len(rejected)} "
          f"({len(rejected)/n_raw*100:.1f}%)")
    print("  giriş anında dolu koltuk sayısının dağılımı (ham sinyal başına):")
    for k in range(MAXPOS + 1):
        c = int((occ == k).sum())
        if c:
            print(f"     {k} dolu: {c:5d} sinyal ({c/n_raw*100:5.1f}%)")
    print(f"  ≥{MAXPOS-1} koltuk dolu iken gelen sinyal oranı: "
          f"{(occ >= MAXPOS-1).mean()*100:.1f}%   (bu, altının kripto ile ÇAKIŞMA riski)")

    # ZAMAN ağırlıklı doluluk: her an kaç pozisyon açık?
    ev = []
    for e_ns, x_ts, *_ in taken:
        ev.append((e_ns, +1)); ev.append((pd.Timestamp(x_ts).value, -1))
    ev.sort()
    cur = 0; prev = ev[0][0]; tw = np.zeros(MAXPOS + 1); tot = 0.0
    for ts, d in ev:
        dt = (ts - prev) / 1e9 / 3600.0
        if dt > 0:
            tw[cur] += dt; tot += dt
        cur += d; prev = ts
    print("\n  ZAMAN ağırlıklı doluluk (açık pozisyon sayısı, saat payı):")
    for k in range(MAXPOS + 1):
        if tw[k] > 0:
            print(f"     {k} açık: {tw[k]/tot*100:5.1f}% zaman")
    mean_open = sum(k * tw[k] for k in range(MAXPOS + 1)) / tot
    print(f"  ortalama açık pozisyon: {mean_open:.2f} / {MAXPOS}  "
          f"→ boş koltuk ortalama {MAXPOS-mean_open:.2f}")

    print()
    print("=" * 84)
    print("M2 — MARJİN PROFİLİ (LEVERAGE=%gx, bakiye $%.0f)" % (LEV, bal))
    print("=" * 84)
    slp = np.array([t[3] for t in taken])
    eff = np.minimum(RISKF, CAP * slp)
    notional = eff / slp * bal          # = min(risk/slp, CAP) * bal
    margin = notional / LEV
    print(f"  SL% (SL mesafesi/giriş):  medyan {np.median(slp)*100:.2f}%  "
          f"ort {slp.mean()*100:.2f}%  p10 {np.percentile(slp,10)*100:.2f}%  "
          f"p90 {np.percentile(slp,90)*100:.2f}%")
    print(f"  CAP'e takılan işlem: {(eff < RISKF-1e-12).mean()*100:.0f}%  "
          f"(CAP bağlar ⇔ SL% < {RISKF/CAP*100:.2f}%)")
    print(f"  efektif risk/işlem: ort {eff.mean()*100:.2f}% (hedef {RISKF*100:.2f}%)")
    print(f"  nominal/işlem: medyan ${np.median(notional):.0f}  ort ${notional.mean():.0f}  "
          f"maks ${notional.max():.0f} (= CAP×bakiye ${CAP*bal:.0f})")
    print(f"  MARJİN/işlem: medyan ${np.median(margin):.2f}  ort ${margin.mean():.2f}  "
          f"maks ${margin.max():.2f}")

    # eşzamanlı marjin zaman serisi
    ev2 = []
    for (e_ns, x_ts, R, s, coin, sl) in taken:
        e = min(RISKF, CAP * s); m = (e / s * bal) / LEV
        ev2.append((e_ns, +m)); ev2.append((pd.Timestamp(x_ts).value, -m))
    ev2.sort()
    cur = 0.0; peak = 0.0; prev = ev2[0][0]; area = 0.0; span = 0.0
    over = 0.0
    for ts, dm in ev2:
        dt = (ts - prev) / 1e9 / 3600.0
        if dt > 0:
            area += cur * dt; span += dt
            if cur > 0.5 * bal:
                over += dt
        cur += dm; prev = ts
        peak = max(peak, cur)
    print(f"  EŞZAMANLI marjin: ortalama ${area/span:.2f}  TEPE ${peak:.2f}  "
          f"(bakiyenin %{peak/bal*100:.0f}'i)")
    print(f"  bakiyenin >%50'si marjinde geçen zaman: {over/span*100:.1f}%")
    return dict(slp=slp, eff=eff, notional=notional, margin=margin,
                peak_margin=peak, mean_margin=area / span, mean_open=mean_open,
                occ=occ, taken=taken)


# ──────────────────────────────────────────────────────────────────────
# M3 — VOL → SL% ÖLÇEK YASASI.  22 coinden ölç, altına ekstrapole et.
# ──────────────────────────────────────────────────────────────────────
def m3_vol_scaling(source="local"):
    print()
    print("=" * 84)
    print("M3 — VOL → SL% ÖLÇEK YASASI (c şıkkı).  22 coinden ÖLÇÜLÜR, altına EKSTRAPOLE.")
    print("=" * 84)
    rows = []
    for c in ALL_COINS:
        try:
            m = fast_bt.load(c, source=source)
        except Exception as e:
            print(f"  {c}: yüklenemedi ({e})"); continue
        d = fast_bt.resample(m, "4h")
        a = atr_fn(d["high"], d["low"], d["close"], 14).values
        cl = d["close"].values
        slp = 2.0 * a / cl                       # donchian SL_ATR=2.0 → SL%
        r = np.diff(np.log(cl))
        sig4 = np.nanstd(r)                      # 4h log-getiri std
        ann = sig4 * np.sqrt(6 * 365)            # yıllıklaştırılmış
        ok = np.isfinite(slp) & (slp > 0)
        rows.append(dict(coin=c, ann_vol=ann, sig4=sig4,
                         slp_med=np.median(slp[ok]), slp_mean=slp[ok].mean(),
                         ratio=np.median(slp[ok]) / sig4))
    df = pd.DataFrame(rows).sort_values("ann_vol")
    print(f"\n  {'coin':6s} {'yıllık vol':>11s} {'medyan SL%':>11s} {'SL%/σ_4h':>10s}")
    for _, r in df.iterrows():
        print(f"  {r.coin:6s} {r.ann_vol*100:10.1f}% {r.slp_med*100:10.2f}% {r.ratio:10.2f}")
    k = df["ratio"].median()
    kmin, kmax = df["ratio"].min(), df["ratio"].max()
    print(f"\n  ÖLÇÜLEN SABİT k = medyanSL% / σ_4h = {k:.2f}  (aralık {kmin:.2f}–{kmax:.2f}, "
          f"22 coin, n≈{len(df)})")
    print(f"  → SL%(varlık) ≈ k × yıllıkVol / sqrt(6×365) = yıllıkVol × {k/np.sqrt(6*365):.4f}")
    # doğrusal regresyon kontrolü (sıfırdan geçen)
    b = float((df.ann_vol * df.slp_med).sum() / (df.ann_vol ** 2).sum())
    resid = df.slp_med - b * df.ann_vol
    r2 = 1 - float((resid ** 2).sum() / ((df.slp_med - df.slp_med.mean()) ** 2).sum())
    print(f"  regresyon (orijinden): SL% = {b:.4f} × yıllıkVol,  R² = {r2:.3f}")

    print("\n  ── ALTINA EKSTRAPOLASYON ──")
    print("  ⚠ Altının yıllık volu bu konteynerde ÖLÇÜLEMEZ (veri yok). Aşağıdaki")
    print("    yıllık vol değerleri EĞİTİM VERİSİNDEN HATIRLANANDIR, ölçüm DEĞİL.")
    print("    'hatırladığım kadarıyla': XAU spot yıllık vol tarihsel ~%12-16 bandında,")
    print("    stres yıllarında (2011, 2020, 2022-23) ~%20-25'e çıkıyor.")
    print(f"\n  {'yıllık vol':>10s} {'2×ATR SL%':>10s} {'CAP×SL%':>9s} {'efektif risk':>13s} "
          f"{'hedefin %':>10s} {'nominal':>9s} {'marjin@10x':>11s}")
    out = {}
    for av in [0.12, 0.15, 0.18, 0.22, 0.30, 0.45, 0.60]:
        s = b * av
        eff = min(RISKF, CAP * s)
        notional = eff / s * BAL0
        tag = ""
        if av <= 0.25: tag = "  ← altın bandı"
        if av >= 0.45: tag = "  ← kripto bandı"
        print(f"  {av*100:9.0f}% {s*100:9.2f}% {CAP*s*100:8.2f}% {eff*100:12.2f}% "
              f"{eff/RISKF*100:9.0f}% ${notional:8.0f} ${notional/LEV:10.2f}{tag}")
        out[av] = (s, eff)
    print(f"\n  KIRILMA NOKTASI: CAP ancak SL% > {RISKF/CAP*100:.2f}% olduğunda GEVŞER")
    print(f"  → bu, yıllık vol > {RISKF/CAP/b*100:.0f}% demek. Altın bu eşiğin ÇOK ALTINDA.")
    return df, b


# ──────────────────────────────────────────────────────────────────────
# M4 — TREND MEKANİZMASI: varyans oranı + kırılım sonrası sürüklenme
# ──────────────────────────────────────────────────────────────────────
def m4_mechanism(source="local"):
    print()
    print("=" * 84)
    print("M4 — TREND MEKANİZMASI (b şıkkı): kriptoda otokorelasyon büyüklüğü nedir?")
    print("=" * 84)
    print("  Varyans oranı VR(q) = Var(q-bar getiri) / (q × Var(1-bar getiri)), 4h barlar.")
    print("  VR>1 = pozitif otokorelasyon (trend), VR<1 = geri dönüş, VR=1 = rastgele yürüyüş.")
    qs = [2, 6, 12, 30, 60, 120]
    rows = []
    drift_rows = []
    for c in ALL_COINS:
        try:
            m = fast_bt.load(c, source=source)
        except Exception:
            continue
        d = fast_bt.resample(m, "4h")
        cl = d["close"].values
        r = np.diff(np.log(cl))
        r = r[np.isfinite(r)]
        v1 = r.var()
        row = {"coin": c}
        for q in qs:
            rq = pd.Series(r).rolling(q).sum().dropna().values
            row[f"VR{q}"] = rq.var() / (q * v1)
        rows.append(row)

        # donchian kırılımı sonrası sürüklenme (40-bar kanal, üretimdeki değer)
        hi = pd.Series(d["high"].values); lo = pd.Series(d["low"].values)
        ch_hi = hi.rolling(40).max().shift(1).values
        ch_lo = lo.rolling(40).min().shift(1).values
        H = 30                                     # maxhold=30 bar
        fwd = (pd.Series(np.log(cl)).shift(-H) - pd.Series(np.log(cl))).values
        up = np.isfinite(ch_hi) & (cl > ch_hi) & np.isfinite(fwd)
        dn = np.isfinite(ch_lo) & (cl < ch_lo) & np.isfinite(fwd)
        base = np.nanstd(fwd)
        drift_rows.append(dict(
            coin=c, n_up=int(up.sum()), n_dn=int(dn.sum()),
            up_drift=float(np.nanmean(fwd[up])) if up.sum() else np.nan,
            dn_drift=float(np.nanmean(fwd[dn])) if dn.sum() else np.nan,
            uncond=float(np.nanmean(fwd[np.isfinite(fwd)])),
            fwd_sd=float(base)))
    vr = pd.DataFrame(rows)
    print(f"\n  {'q(4h bar)':>10s} {'≈süre':>8s} {'medyan VR':>10s} {'VR>1 coin':>10s}")
    for q in qs:
        col = vr[f"VR{q}"]
        print(f"  {q:10d} {q*4/24:7.1f}g {col.median():10.3f} {int((col>1).sum()):6d}/{len(col)}")
    print("\n  YORUM: VR'nin 1'den sapması trend/geri-dönüş etkisinin BÜYÜKLÜĞÜDÜR.")

    dr = pd.DataFrame(drift_rows)
    print(f"\n  40-bar DONCHIAN KIRILIMI sonrası {30*4/24:.0f} günlük sürüklenme (log getiri):")
    up_z = ((dr.up_drift - dr.uncond) / dr.fwd_sd)
    dn_z = ((dr.dn_drift - dr.uncond) / dr.fwd_sd)
    print(f"    YUKARI kırılım: ort sürüklenme {dr.up_drift.mean()*100:+.2f}%  "
          f"(koşulsuz {dr.uncond.mean()*100:+.2f}%)  → z-fark {up_z.mean():+.3f} σ")
    print(f"    AŞAĞI  kırılım: ort sürüklenme {dr.dn_drift.mean()*100:+.2f}%  "
          f"→ z-fark {dn_z.mean():+.3f} σ  (SHORT için işareti ters oku)")
    print(f"    yukarı-kırılımda pozitif z olan coin: {int((up_z>0).sum())}/{len(dr)}")
    print(f"    aşağı-kırılımda NEGATİF z olan coin: {int((dn_z<0).sum())}/{len(dr)}")
    print("\n  Bu iki sayı 'kriptoda kırılım-momentum etkisi' büyüklüğüdür. Altın için")
    print("  AYNI hesabı yapan VPS betiği: xau_prior_vps.py — karşılaştırma orada.")
    return vr, dr


# ──────────────────────────────────────────────────────────────────────
# M5 — ALTIN KOLU EKLENİRSE koltuk/marjin ne olur (senaryo)
# ──────────────────────────────────────────────────────────────────────
def m5_scenario(stats, b, bal_live=215.0):
    print()
    print("=" * 84)
    print("M5 — SENARYO: ALTIN KOLU EKLENİRSE (d şıkkı). Canlı bakiye $%.0f varsayımı." % bal_live)
    print("=" * 84)
    slp_g = b * 0.15                       # yıllık vol %15 varsayımı (HATIRLANAN)
    eff_g = min(RISKF, CAP * slp_g)
    notional_g = eff_g / slp_g * bal_live
    margin_g = notional_g / LEV
    print(f"  altın varsayımı: yıllık vol %15 → SL% {slp_g*100:.2f}% → CAP BAĞLAR")
    print(f"    efektif risk {eff_g*100:.2f}% (hedefin %{eff_g/RISKF*100:.0f}'i)")
    print(f"    nominal ${notional_g:.0f} = CAP×bakiye · MARJİN ${margin_g:.2f}/pozisyon")
    mk = stats["margin"].mean() / BAL0 * bal_live
    print(f"  kripto işlem başına ortalama marjin (aynı bakiyeye ölçekli): ${mk:.2f}")
    print(f"  → altın pozisyonu kriptonun {margin_g/mk:.2f}× marjinini tutuyor")
    peak = stats["peak_margin"] / BAL0 * bal_live
    print(f"\n  mevcut TEPE eşzamanlı marjin: ${peak:.2f} (bakiyenin %{peak/bal_live*100:.0f}'i)")
    for n_gold in (1, 2, 3):
        print(f"  + {n_gold} eşzamanlı altın pozisyonu → tepe ${peak + n_gold*margin_g:.2f} "
              f"(%{(peak+n_gold*margin_g)/bal_live*100:.0f})"
              + ("   ⚠ TEHLİKE: marjin bakiyeyi zorluyor"
                 if (peak + n_gold*margin_g) > 0.7*bal_live else ""))
    print(f"\n  7 koltuğun HEPSİ altın olsaydı: marjin ${7*margin_g:.2f} "
          f"(%{7*margin_g/bal_live*100:.0f} of ${bal_live:.0f})")
    print(f"  NOT: MAXPOS ayrı bir kol için AYRILMAZSA, altın kripto koltuğu ile yarışır.")
    print(f"       Ölçülen koltuk-dolu-reddi oranı yukarıda M1'de.")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    tr = anchor_trades(src)
    taken, rejected, occ = seat_timeline(tr)
    print(f"\n(kontrol: kabul edilen işlem {len(taken)} — ankor 1579 olmalı)\n")
    stats = m1_m2_seat_and_margin(taken, rejected, occ)
    df, b = m3_vol_scaling(src)
    m4_mechanism(src)
    m5_scenario(stats, b)


if __name__ == "__main__":
    main()
