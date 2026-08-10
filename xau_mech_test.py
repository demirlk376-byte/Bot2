"""
xau_mech_test.py — EKSEN 2 (b): "kripto trend edge'i ile altın trend edge'i AYNI
mekanizma mı?" sorusunun BİZİM TARAFIMIZI ölçer.

Mantık: "Donchian+ATR = Turtle = belgelenmiş emtia trend primi, o yüzden altına
taşınır" iddiası İKİ ayağa dayanır:
   (i)  altında trend primi var  → BU KONTEYNERDE ÖLÇÜLEMEZ (veri yok)
   (ii) BİZİM edge'imiz DE o trend primi → BU ÖLÇÜLEBİLİR, burada ölçülüyor.
Eğer (ii) yanlışsa, (i) doğru olsa bile transfer iddiası çöker: aynı şeyi
harvest etmiyoruz demektir.

Ölçümler:
  T1  Lo-MacKinlay varyans oranı + heteroskedastisiteye-dayanıklı z (rastgele
      yürüyüş boş hipotezine karşı). Trend primi ⇒ VR>1 beklenir.
  T2  Kırılım-sonrası KOŞULLU sürüklenme, YÖNE göre ayrı (yukarı vs aşağı).
      Gerçek zaman-serisi momentumu ⇒ yukarı poz, aşağı NEG olmalı.
  T3  Üretim donchian kolunun LONG/SHORT kâr ayrışması + yoğunlaşma.
      Kâr yalnız LONG'tan geliyorsa mekanizma "trend primi" değil, boğa betası.
  T4  Aylık kâr serisini CSV'ye yazar (altın trend serisiyle korelasyon için).

Kullanım:  python3 xau_mech_test.py local
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as DB
from strategies.donchian import DonchianStrategy
from indicators import atr as atr_fn

ALL_COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE",
             "DOT", "ETC", "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX",
             "VET", "XLM", "XMR", "XRP"]


def lo_mackinlay_vr(r, q):
    """Lo-MacKinlay (1988) örtüşen varyans oranı + heteroskedastisiteye dayanıklı z.
    VR>1 pozitif otokorelasyon (trend), VR<1 geri dönüş."""
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r)
    mu = r.mean()
    sa = ((r - mu) ** 2).sum() / (n - 1)
    s = pd.Series(r).rolling(q).sum().dropna().values
    m = q * (n - q + 1) * (1 - q / n)
    sc = ((s - q * mu) ** 2).sum() / m
    vr = sc / sa
    # heteroskedastisiteye dayanıklı varyans (Lo-MacKinlay Teorem 5)
    d = (r - mu) ** 2
    theta = 0.0
    for j in range(1, q):
        num = (d[j:] * d[:-j]).sum()
        den = (d.sum()) ** 2 / n
        dj = num / den if den > 0 else 0.0
        theta += ((2 * (q - j) / q) ** 2) * dj
    z = (vr - 1) / np.sqrt(theta / n) if theta > 0 else np.nan
    return vr, z


def t1_t2(source="local"):
    print("=" * 86)
    print("T1 — VARYANS ORANI (Lo-MacKinlay, hetero-dayanıklı z). 4h barlar.")
    print("     Trend primi mekanizması VR>1 GEREKTİRİR. VR<1 = geri dönüş.")
    print("=" * 86)
    qs = [6, 12, 30, 60]
    rows = []
    for c in ALL_COINS:
        d = fast_bt.resample(fast_bt.load(c, source=source), "4h")
        r = np.diff(np.log(d["close"].values))
        row = {"coin": c, "n": len(r)}
        for q in qs:
            vr, z = lo_mackinlay_vr(r, q)
            row[f"VR{q}"] = vr; row[f"z{q}"] = z
        rows.append(row)
    df = pd.DataFrame(rows)
    print(f"\n  {'q':>4s} {'≈süre':>7s} {'medyan VR':>10s} {'medyan z':>9s} "
          f"{'VR>1':>6s} {'z>+1.96':>8s} {'z<-1.96':>8s}")
    for q in qs:
        v = df[f"VR{q}"]; z = df[f"z{q}"]
        print(f"  {q:4d} {q*4/24:6.1f}g {v.median():10.3f} {z.median():9.2f} "
              f"{int((v>1).sum()):4d}/22 {int((z>1.96).sum()):6d}/22 "
              f"{int((z<-1.96).sum()):6d}/22")
    print("\n  |z|>1.96 = %5 seviyesinde anlamlı. Coinler BİRBİRİYLE KORELE olduğu için")
    print("  22 test bağımsız DEĞİLDİR — 'kaç coinde anlamlı' sayısı şişik okunmamalı.")

    print()
    print("=" * 86)
    print("T2 — KIRILIM SONRASI KOŞULLU SÜRÜKLENME, YÖNE GÖRE (40-bar kanal, H=30 bar).")
    print("     Gerçek zaman-serisi momentumu: YUKARI kırılım sonrası +, AŞAĞI sonrası −.")
    print("=" * 86)
    rows = []
    for c in ALL_COINS:
        d = fast_bt.resample(fast_bt.load(c, source=source), "4h")
        cl = d["close"].values
        ch_hi = pd.Series(d["high"].values).rolling(40).max().shift(1).values
        ch_lo = pd.Series(d["low"].values).rolling(40).min().shift(1).values
        H = 30
        lg = np.log(cl)
        fwd = np.concatenate([lg[H:] - lg[:-H], np.full(H, np.nan)])
        ok = np.isfinite(fwd)
        up = ok & np.isfinite(ch_hi) & (cl > ch_hi)
        dn = ok & np.isfinite(ch_lo) & (cl < ch_lo)
        base_mu = np.nanmean(fwd[ok]); base_sd = np.nanstd(fwd[ok])
        se_up = base_sd / np.sqrt(max(up.sum(), 1))
        se_dn = base_sd / np.sqrt(max(dn.sum(), 1))
        rows.append(dict(coin=c,
                         up_n=int(up.sum()), dn_n=int(dn.sum()),
                         up_mu=np.nanmean(fwd[up]), dn_mu=np.nanmean(fwd[dn]),
                         base=base_mu,
                         up_t=(np.nanmean(fwd[up]) - base_mu) / se_up,
                         dn_t=(np.nanmean(fwd[dn]) - base_mu) / se_dn))
    dr = pd.DataFrame(rows)
    print(f"\n  koşulsuz 5-günlük sürüklenme (22 coin ort): {dr.base.mean()*100:+.2f}%")
    print(f"  YUKARI kırılım sonrası: {dr.up_mu.mean()*100:+.2f}%  "
          f"(fazla {(dr.up_mu-dr.base).mean()*100:+.2f}%, medyan t={dr.up_t.median():+.2f})")
    print(f"  AŞAĞI  kırılım sonrası: {dr.dn_mu.mean()*100:+.2f}%  "
          f"(fazla {(dr.dn_mu-dr.base).mean()*100:+.2f}%, medyan t={dr.dn_t.median():+.2f})")
    print(f"\n  MOMENTUM İMZASI TESTİ (yukarı fazla > 0 VE aşağı fazla < 0):")
    good = ((dr.up_mu - dr.base) > 0) & ((dr.dn_mu - dr.base) < 0)
    print(f"    her iki yönde de momentum imzası gösteren coin: {int(good.sum())}/22")
    print(f"    yalnız yukarı yönde: {int((((dr.up_mu-dr.base)>0) & ~good).sum())}/22")
    print(f"    HİÇ momentum imzası olmayan (aşağı kırılım sonrası da YÜKSELEN): "
          f"{int((((dr.dn_mu-dr.base)>0)).sum())}/22")
    print("\n  Yukarı ve aşağı FAZLA sürüklenmeler AYNI İŞARETLİ ise bu YÖNSÜZ bir etkidir")
    print("  (oynaklık genişlemesi / örneklem boğa eğilimi) — zaman-serisi momentumu DEĞİL.")
    return df, dr


def t3_long_short(source="local"):
    """Üretim donchian kolunu YÖNE göre ayır. DB.gen() yön döndürmüyor, o yüzden
    aynı üretim sınıfını kullanıp yönü de kaydeden ince bir sarmalayıcı — mekanik
    DB.gen ile birebir aynı; kontrolü toplam işlem sayısı ve toplam R ile yapılır."""
    print()
    print("=" * 86)
    print("T3 — ÜRETİM DONCHIAN KOLU: LONG vs SHORT kâr ayrışması + yoğunlaşma")
    print("=" * 86)
    tf, win, sl_a, rr, mh = DB.CFG["donchian"]
    allt = []
    for c in DB.DONCH:
        m = fast_bt.load(c, source=source)
        d = fast_bt.resample(m, tf)
        atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
        _dc = d["close"].resample("1D").last().dropna()
        _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
            d.index.normalize()).values
        up = d["close"].values > _dprev
        s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
        hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
        idx = d.index; n = len(cl); occ = -1
        for i in range(260, n - 1):
            a = atr_ser[i]
            if not np.isfinite(a) or a <= 0: continue
            sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
            if d_ == 0 or i <= occ: continue
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
            R = d_ * (ep - e) / sld - 2 * DB.FEE * e / sld
            allt.append(dict(coin=c, dir=d_, R=R, slp=sld / e,
                             entry=idx[i], exit=idx[j])); occ = j
    df = pd.DataFrame(allt)
    print(f"  kontrol: donchian ham sinyal {len(df)} "
          f"(DB.gen ile aynı mekanik; ankor breakout toplamı 1440'ın donchian payı)")
    df["pnl"] = df.R * np.minimum(DB.RISKF, DB.CAP * df.slp) * DB.BAL0
    for nm, sub in [("LONG", df[df.dir == 1]), ("SHORT", df[df.dir == -1])]:
        if len(sub) == 0: continue
        gp = sub.R[sub.R > 0].sum(); gl = -sub.R[sub.R < 0].sum()
        print(f"  {nm:6s} n={len(sub):4d} ({len(sub)/len(df)*100:4.1f}%)  "
              f"ort {sub.R.mean():+.3f}R  PF {gp/max(gl,1e-9):.2f}  "
              f"WR {(sub.R>0).mean()*100:4.1f}%  kâr ${sub.pnl.sum():+7.0f} "
              f"({sub.pnl.sum()/df.pnl.sum()*100:5.1f}% toplamın)")
    print("\n  YOĞUNLAŞMA (ders 1):")
    p = np.sort(df.pnl.values)[::-1]
    tot = p.sum()
    for k in (1, 5, 10, 20):
        print(f"    en iyi {k:3d} işlem = kârın %{p[:k].sum()/tot*100:.0f}'i")
    print(f"    en iyi 10 işlem çıkarılırsa kol: ${tot:+.0f} → ${p[10:].sum():+.0f}")
    return df


def t4_monthly(df, out="donchian_monthly.csv"):
    print()
    print("=" * 86)
    print("T4 — AYLIK KÂR SERİSİ → %s  (altın trend serisiyle korelasyon için)" % out)
    print("=" * 86)
    d = df.copy()
    d["m"] = [pd.Timestamp(x).tz_localize(None).to_period("M") for x in d.exit]
    mon = d.groupby("m")["pnl"].sum()
    mon.index = mon.index.astype(str)
    mon.to_frame("donchian_pnl_usd").to_csv(out)
    print(f"  {len(mon)} ay yazıldı. ort {mon.mean():+.1f}$ · std {mon.std():.1f}$ · "
          f"poz-ay %{(mon>0).mean()*100:.0f}")
    print("  KULLANIM: VPS'te altın trend kolunun aylık serisini üretip bu dosyayla")
    print("  korelasyonunu ölç. r>+0.4 ise 'aynı rejime bağlı' = çeşitlendirme SAHTE.")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    t1_t2(src)
    df = t3_long_short(src)
    t4_monthly(df)


if __name__ == "__main__":
    main()
