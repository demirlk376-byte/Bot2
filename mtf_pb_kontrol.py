"""
mtf_pb_kontrol.py — MTF-PULLBACK kontrolleri.

A) ARAÇ DENETİMİ: boyutlandırma (eff), yön dağılımı, coin/yıl dağılımı, çıkış tipi.
B) PERMÜTASYON: trend-uygun barlardan AYNI SAYIDA RASTGELE giriş (tetik yok sayılır).
   Tetik bilgi taşıyor mu? (repo dersi: 290 filtre denemesinde rastgele silme bariydi)
C) MEKANİZMA TESTİ: aynı trend evreninde "geri çekilmede gir" vs "devamda gir"
   (20-bar yeni tepe). Repo dersi: "geri çekilme verenler zaten başarısız olacaklar".
D) KORELASYON: kolun aylık PnL'i ↔ mevcut kitabın aylık PnL'i.
E) YÜRÜYEN-İLERİ: train argmax → test Δ$ (4 kat, ortak koltuk).

Kullanım:  py mtf_pb_kontrol.py
"""
import itertools, os, pickle
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A
import mtf_pullback as P
from mtf_pb_taban import ham_taban, strip, olc
from mtf_pb_tara import COINS, TRENDS, TETIK, STOPS, RRS, veri, kol_uret, tek_basina
from mtf_pb_asama2 import tum_hucreler, kes

SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
EN_IYI = dict(trend="T1", tetik="rsi", stop=("swing", 10), rr=2.5)   # aşama1 argmax


def a_denetim(V):
    print("\n" + "=" * 92)
    print("A) ARAÇ DENETİMİ — en iyi hücre (T1/rsi/swing10/rr2.5)")
    t = kol_uret(V, **EN_IYI)
    R = np.array([x[2] for x in t]); sp = np.array([x[3] for x in t])
    eff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp)
    print(f"  n={len(t)}  ortR {R.mean():+.4f}  R std {R.std():.4f}  "
          f"min {R.min():+.2f} max {R.max():+.2f}")
    print(f"  SL mesafesi (slp) ort %{sp.mean()*100:.3f} (medyan %{np.median(sp)*100:.3f})")
    print(f"  eff ort %{eff.mean()*100:.3f} (hedef %{A.CANLI_RISKF*100:.2f}) — "
          f"tavana takılan %{(eff < A.CANLI_RISKF-1e-12).mean()*100:.0f}")
    print(f"  $/işlem ort ${(R*eff*A.BAL0).mean():+.4f}")
    # ankor donchian'ın slp'si ile kıyas
    d = ham_taban(); dsp = np.array([x[4] for x in d["donch"]])
    deff = np.minimum(A.CANLI_RISKF, A.CANLI_CAP * dsp)
    print(f"  KIYAS donchian: slp ort %{dsp.mean()*100:.3f} · eff ort %{deff.mean()*100:.3f}")
    print(f"  ⚠ 1h ATR stopu 4h'tan DAR → eff küçük → işlem başına $ riski küçük.")
    # çıkış tipi: R ~ rr (TP) / ~ -1 (SL) / arası (maxhold)
    tp = (R > EN_IYI["rr"] - 0.05).mean(); sl = (R < -0.95).mean()
    print(f"  çıkış: TP %{tp*100:.1f} · SL %{sl*100:.1f} · maxhold %{(1-tp-sl)*100:.1f}")
    return t


def b_permutasyon(V, tekrar=30):
    print("\n" + "=" * 92)
    print(f"B) PERMÜTASYON — trend-uygun barlardan AYNI SAYIDA RASTGELE giriş ({tekrar} tekrar)")
    d = ham_taban(); taban_ham = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
    T = olc(A.seat_select(taban_ham))
    for kw, ad in [(EN_IYI, "T1/rsi/swing10/rr2.5 (en iyi)"),
                   (dict(trend="T1", tetik="ema20", stop=("atr", 2.0), rr=2.5),
                    "T1/ema20/atr2.0/rr2.5 (en kötü aile)")]:
        ger = tek_basina(kol_uret(V, **kw))
        kars = []
        for s in range(tekrar):
            rng = np.random.default_rng(1000 + s)
            m = tek_basina(kol_uret(V, rnd=rng, **kw))
            kars.append(m["kar"])
        kars = np.array(kars)
        z = (ger["kar"] - kars.mean()) / kars.std()
        print(f"  {ad}")
        print(f"    GERÇEK tetik : n={ger['n']:5d}  ${ger['kar']:+8.2f}  ortR {ger['ortR']:+.4f}")
        print(f"    RASTGELE     : ${kars.mean():+8.2f} ± {kars.std():.2f}  "
              f"(aralık {kars.min():+.0f}..{kars.max():+.0f})   z = {z:+.2f}")


def c_mekanizma(V):
    """Aynı trend evreninde GERİ ÇEKİLME vs DEVAM girişi."""
    print("\n" + "=" * 92)
    print("C) MEKANİZMA — aynı trend evreninde 'geri çekilmede gir' vs 'devamda gir'")
    import mtf_pullback as MP
    from indicators import ema as ema_fn, atr as atr_fn
    res = {}
    for mod in ("pullback_ema20", "devam_20bar"):
        tot = []
        for c in COINS:
            m = V[c]
            d1 = fast_bt.resample(m, "1h"); d4 = fast_bt.resample(m, "4h")
            c4 = d4["close"]; e200 = ema_fn(c4, 200); e50 = ema_fn(c4, 50)
            up4 = ((c4 > e200) & (e50 > e200)).astype(float)
            dn4 = ((c4 < e200) & (e50 < e200)).astype(float)
            up = np.nan_to_num(MP.ust_e_alt(up4, d1.index)) > .5
            dn = np.nan_to_num(MP.ust_e_alt(dn4, d1.index)) > .5
            hi = d1["high"].values; lo = d1["low"].values; cl = d1["close"].values
            a1 = atr_fn(d1["high"], d1["low"], d1["close"], 14).values
            n = len(cl)
            if mod == "pullback_ema20":
                ev = ema_fn(d1["close"], 20).values
                pu = np.concatenate([[False], cl[:-1] > ev[:-1]])
                pa = np.concatenate([[False], cl[:-1] < ev[:-1]])
                tl = (lo <= ev) & (cl > ev) & pu; ts = (hi >= ev) & (cl < ev) & pa
            else:   # DEVAM: 20-bar yeni tepe/dip (geri çekilme YOK)
                rh = pd.Series(hi).rolling(20).max().shift(1).values
                rl = pd.Series(lo).rolling(20).min().shift(1).values
                tl = cl > rh; ts = cl < rl
            sl = np.nan_to_num(tl.astype(float)) > .5; ss = np.nan_to_num(ts.astype(float)) > .5
            sl = sl & up; ss = ss & dn
            occ = -1
            for i in np.where(sl | ss)[0]:
                i = int(i)
                if i < 260 or i >= n - 1 or i <= occ: continue
                a = a1[i]
                if not np.isfinite(a) or a <= 0: continue
                d_ = 1 if sl[i] else -1
                e = cl[i]; sld = 2.0 * a
                slp_ = e - d_ * sld; tp = e + d_ * 2.5 * sld; ep = None; j = i
                for j in range(i + 1, min(i + 49, n)):
                    if d_ == 1:
                        if lo[j] <= slp_: ep = slp_; break
                        if hi[j] >= tp: ep = tp; break
                    else:
                        if hi[j] >= slp_: ep = slp_; break
                        if lo[j] <= tp: ep = tp; break
                if ep is None: j = min(i + 48, n - 1); ep = cl[j]
                Rv = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
                tot.append((d1.index[i].value, d1.index[j], Rv, sld / e)); occ = j
        res[mod] = tek_basina(tot)
        r = res[mod]
        print(f"  {mod:16s} n={r['n']:5d}  ortR {r['ortR']:+.4f}  WR %{r['wr']:.1f}  "
              f"${r['kar']:+8.2f}  poz-yıl {r['pos_yil']}/{r['n_yil']}")
    print("  → TEK DEĞİŞKEN: tetik (geri çekilme vs devam). Trend kapısı, stop, hedef,")
    print("    maxhold, occ, coin evreni AYNI.")


def d_korelasyon(V):
    print("\n" + "=" * 92)
    print("D) KORELASYON — kolun aylık PnL'i ↔ mevcut kitabın aylık PnL'i")
    d = ham_taban(); taban_ham = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
    T = olc(A.seat_select(taban_ham))
    kit = T["ay"]
    for kw, ad in [(EN_IYI, "T1/rsi/swing10/rr2.5"),
                   (dict(trend="T2", tetik="rsi", stop=("atr", 1.5), rr=3.0), "T2/rsi/atr1.5/rr3.0"),
                   (dict(trend="T1", tetik="ema20", stop=("atr", 2.0), rr=2.5), "T1/ema20/atr2.0/rr2.5")]:
        t = kol_uret(V, **kw)
        R = np.array([x[2] for x in t]); sp = np.array([x[3] for x in t])
        pnl = R * np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp) * A.BAL0
        ex = pd.to_datetime([x[1] for x in t])
        ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()
        j = pd.concat([kit.rename("kitap"), ay.rename("kol")], axis=1).dropna()
        r = j["kitap"].corr(j["kol"])
        kayip = j[j.kitap < 0]
        print(f"  {ad:24s}  aylık korelasyon {r:+.3f}  (n={len(j)} ay)")
        print(f"     kitabın KAYIP aylarında kol: ${kayip['kol'].sum():+.2f} "
              f"({(kayip['kol']>0).sum()}/{len(kayip)} ay pozitif)")


def e_yuruyen(V):
    print("\n" + "=" * 92)
    print("E) YÜRÜYEN-İLERİ — train argmax → test (ortak koltuk, Δ$ taban)")
    d = ham_taban(); taban_ham = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
    H = tum_hucreler(V)
    sinir = [pd.Timestamp(x, tz="UTC") for x in
             ["2024-10-01", "2025-04-01", "2025-10-01", "2026-07-19"]]
    bas = pd.Timestamp("2023-04-01", tz="UTC")
    tot_d = 0.0
    for k in range(len(sinir) - 1):
        tr0, tr1 = bas, sinir[k]; te0, te1 = sinir[k], sinir[k + 1]
        # TRAIN argmax
        tb_tr = kes(taban_ham, tr0, tr1)
        base_tr = olc(A.seat_select(tb_tr))["kar"]
        en = None
        for key, t in H.items():
            c = olc(A.seat_select(tb_tr + kes(t, tr0, tr1)))["kar"] - base_tr
            if en is None or c > en[1]: en = (key, c)
        # TEST
        tb_te = kes(taban_ham, te0, te1)
        base_te = olc(A.seat_select(tb_te))["kar"]
        dte = olc(A.seat_select(tb_te + kes(H[en[0]], te0, te1)))["kar"] - base_te
        tot_d += dte
        print(f"  train→{tr1.date()}  seçilen {str(en[0]):40s} trainΔ ${en[1]:+8.2f}  "
              f"| test {te0.date()}→{te1.date()} tabanı ${base_te:+8.2f}  testΔ ${dte:+8.2f}")
    print(f"  TOPLAM OOS Δ$ = ${tot_d:+.2f}   (bar: > 0 ve anlamlı olmalı)")


if __name__ == "__main__":
    V = veri()
    a_denetim(V)
    c_mekanizma(V)
    d_korelasyon(V)
    e_yuruyen(V)
    b_permutasyon(V)
