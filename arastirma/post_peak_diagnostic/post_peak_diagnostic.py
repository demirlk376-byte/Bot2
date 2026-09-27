"""
post_peak_diagnostic.py — giriş anında bilinen durum ile işlem sonucu (R_net) ilişkisi.

ÇEVRİMDIŞI TEŞHİS. Filtre/threshold optimizasyonu YOK: sürekli değişkenler yalnız sabit
Q1-Q5 dilimleriyle betimlenir; hipotez tanımları kodda ÖNCEDEN sabittir.

Girdi : ikiz_k25_cap25_islemler.csv (936), arastirma/kar_geri_verme/{islem_mfe_mae,equity_saatlik}.csv,
        data/{COIN}_fut_1h.csv
Çıktı : entry_state.csv, ozellik_tablosu.csv, hipotezler.json (bu klasörde)
Çalıştır (repo kökünden):  python3 arastirma/post_peak_diagnostic/post_peak_diagnostic.py

LOOKAHEAD KURALLARI
  · ts = 1h bar AÇILIŞI. Giriş T = entry_time; T'de bilinen son 1h kapanış = ts=T−1h barı.
  · 4h bar = [s, s+4h) (UTC 0/4/8..). T'de kapanmış son 4h bar: s+4h ≤ T.
  · Portföy: T'den ÖNCE açılmış ve ekonomik çıkışı T'den SONRA olan pozisyonlar (aynı saatte açılanlar hariç).
  · Strateji geçmişi: ekonomik çıkışı ≤ T olan (kapanmış) Donchian işlemleri.
  · Ekonomik çıkış işareti = kar_geri_verme analizindeki `cikis_isaret` (kayıttaki exit_time değil).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
KGV = os.path.join(KOK, "arastirma", "kar_geri_verme")
BAS = 10_000.0
H = pd.Timedelta("1h")
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
B_BOOT = 2000
RNG = np.random.default_rng(20260927)


# ─────────────────────────── veri ───────────────────────────
def yukle_1h(coin):
    b = pd.read_csv(os.path.join(KOK, "data", f"{coin}_fut_1h.csv"))
    b["ts"] = pd.to_datetime(b.ts, utc=True)
    return b.drop_duplicates("ts").set_index("ts").sort_index()


def dort_saat(b1):
    g = b1.resample("4h", origin="epoch", label="left")
    b4 = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                       "close": g.close.last(), "volume": g.volume.sum(), "n": g.close.count()})
    b4 = b4[b4.n == 4].drop(columns="n")                  # yalnız 4 tam saati olan barlar
    b4["ema200"] = b4.close.ewm(span=200, adjust=False).mean()
    tr = pd.concat([b4.high - b4.low, (b4.high - b4.close.shift()).abs(),
                    (b4.low - b4.close.shift()).abs()], axis=1).max(axis=1)
    b4["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    yon = np.sign(b4.close - b4.open)
    seri = np.zeros(len(b4), int)
    for i in range(len(b4)):                              # geriye doğru: yalnız geçmiş barlar
        seri[i] = (seri[i - 1] + 1) if i and yon.iat[i] == yon.iat[i - 1] and yon.iat[i] != 0 else 1
    b4["yon"] = yon; b4["seri"] = seri
    return b4


def son_4h(b4, T):
    """T anında kapanmış son 4h bar (başlangıç + 4h ≤ T)."""
    i = b4.index.searchsorted(T - pd.Timedelta("4h"), side="right") - 1
    return b4.iloc[i] if i >= 0 else None


def ema_hazir(b4, T):
    """EMA200 en az 200 kapanmış 4h bar sonra anlamlı; öncesi NaN (tahmin yok)."""
    return b4.index.searchsorted(T - pd.Timedelta("4h"), side="right") >= 200


def kapanis_T(b1, T, geri=0):
    """T−geri anında bilinen son 1h kapanış (ts ≤ T−geri−1h)."""
    s = b1.close.loc[:T - pd.Timedelta(hours=geri) - H]
    return float(s.iat[-1]) if len(s) else np.nan


# ─────────────────────────── özellikler ───────────────────────────
def ozellikler():
    d = pd.read_csv(os.path.join(KOK, "ikiz_k25_cap25_islemler.csv"))
    sc = d.strategy_scores.map(json.loads)
    d["niyet"] = sc.map(lambda s: s["intended_entry"]); d["sl0"] = sc.map(lambda s: s["sl0"])
    d["R_net"] = d.pnl_usdt / (d.quantity * (d.niyet - d.sl0).abs())
    d["giris"] = pd.to_datetime(d.entry_time, utc=True)
    d["coin"] = d.symbol.str.split("/").str[0]
    d["yon"] = np.where(d.side == "long", 1, -1)
    d["ucret_giris"] = sc.map(lambda s: s["entry_fee_rate"]) * d.entry_price * d.quantity
    m = pd.read_csv(os.path.join(KGV, "islem_mfe_mae.csv"))
    m["giris"] = pd.to_datetime(m.entry_time, utc=True)
    d = d.merge(m[["symbol", "giris", "side", "cikis_isaret"]], on=["symbol", "giris", "side"], how="left")
    assert d.cikis_isaret.notna().all() and len(d) == 936, "ekonomik çıkış eşleşmesi eksik"
    d["cikis_isaret"] = pd.to_datetime(d.cikis_isaret, utc=True)
    d = d.sort_values(["giris", "symbol"]).reset_index(drop=True)
    d["yari"] = np.where(d.giris < BOLME, "TRAIN", "TEST")

    px1 = {c: yukle_1h(c) for c in set(d.coin) | set(DONCH) | {"BTC"}}
    btc4 = dort_saat(px1["BTC"]); d4 = {c: dort_saat(px1[c]) for c in DONCH}
    eq = pd.read_csv(os.path.join(KGV, "equity_saatlik.csv"), parse_dates=["zaman"])
    eq_z = eq.zaman.values; eq_v = eq.hesap_degeri.values
    eq_ath = np.maximum.accumulate(eq_v)

    rows = []
    donch = d[d.kol == "donchian"]
    for t in d.itertuples():
        T, y = t.giris, t.yon
        r = {}
        # A) BTC rejimi
        b = son_4h(btc4, T)
        c0 = kapanis_T(px1["BTC"], T)
        r["btc_4h_son_yon"] = int(b.yon)
        r["btc_4h_ardisik"] = int(b.seri)
        r["btc_4h_ardisik_isaretli"] = int(b.seri * b.yon)
        r["btc_ret24"] = c0 / kapanis_T(px1["BTC"], T, 24) - 1
        r["btc_ret48"] = c0 / kapanis_T(px1["BTC"], T, 48) - 1
        r["btc_ema200_atr"] = (b.close - b.ema200) / b.atr14 if ema_hazir(btc4, T) else np.nan
        r["btc_atr_oran"] = b.atr14 / b.close
        r["btc_hizali_24h"] = int(np.sign(r["btc_ret24"]) == y)
        r["btc_ret48_islem_yonunde"] = r["btc_ret48"] * y
        r["btc_ardisik_islem_yonunde"] = int(b.seri * b.yon * y)       # + = trade yönünde koşu
        # B) genişlik (Donchian evreni, 7 coin)
        ust, poz, ayni = [], [], []
        for c in DONCH:
            bb = son_4h(d4[c], T)
            if bb is not None and ema_hazir(d4[c], T):
                ust.append(float(bb.close > bb.ema200))
            rr = kapanis_T(px1[c], T) / kapanis_T(px1[c], T, 24) - 1
            if np.isfinite(rr):
                poz.append(float(rr > 0)); ayni.append(float(np.sign(rr) == y))
        r["gen_ema200_ustu"] = np.mean(ust) if len(ust) == len(DONCH) else np.nan
        r["gen_ema200_alti"] = 1 - r["gen_ema200_ustu"] if len(ust) == len(DONCH) else np.nan
        r["gen_ret24_pozitif"] = np.mean(poz) if len(poz) == len(DONCH) else np.nan
        r["gen_islem_yonunde"] = np.mean(ayni) if len(ayni) == len(DONCH) else np.nan
        # C) portföy (girişten hemen önce; aynı saatte açılanlar hariç)
        acik = d[(d.giris < T) & (d.cikis_isaret > T)]
        kap = d[d.cikis_isaret <= T]
        fiyat = {c: kapanis_T(px1[c], T) for c in acik.coin.unique()}
        not_long = sum(o.quantity * fiyat[o.coin] for o in acik.itertuples() if o.yon > 0)
        not_short = sum(o.quantity * fiyat[o.coin] for o in acik.itertuples() if o.yon < 0)
        upnl = sum(o.yon * (fiyat[o.coin] - o.entry_price) * o.quantity for o in acik.itertuples())
        V = BAS + kap.pnl_usdt.sum() - acik.ucret_giris.sum() + upnl
        i = np.searchsorted(eq_z, np.datetime64(T.tz_localize(None)), side="left") - 1
        ath = max(eq_ath[i] if i >= 0 else BAS, V)
        r["port_acik"] = len(acik)
        r["port_ayni_yon"] = int((acik.yon == y).sum()); r["port_ters_yon"] = int((acik.yon != y).sum())
        r["port_gross_not"] = (not_long + not_short) / V
        r["port_net_not_islem_yonunde"] = (not_long - not_short) * y / V
        r["port_upnl"] = upnl / V
        r["port_dd_ath"] = 1 - V / ath
        r["port_donch_24h"] = int(((donch.giris < T) & (donch.giris >= T - pd.Timedelta("24h"))).sum())
        r["port_donch_72h"] = int(((donch.giris < T) & (donch.giris >= T - pd.Timedelta("72h"))).sum())
        r["ayni_bar_ayni_yon_donch"] = int(((donch.giris == T) & (donch.yon == y)).sum())
        # D) Donchian yakın geçmişi (yalnız kapanmış)
        gec = donch[donch.cikis_isaret <= T].sort_values(["cikis_isaret", "giris"])
        R = gec.R_net.values
        r["don_son5_R"] = R[-5:].sum() if len(R) >= 5 else np.nan
        r["don_son10_R"] = R[-10:].sum() if len(R) >= 10 else np.nan
        r["don_son5_WR"] = (R[-5:] > 0).mean() if len(R) >= 5 else np.nan
        r["don_son10_WR"] = (R[-10:] > 0).mean() if len(R) >= 10 else np.nan
        k = 0
        for x in R[::-1]:
            if x < 0: k += 1
            else: break
        r["don_ardisik_kayip"] = k
        rows.append(r)
    f = pd.concat([d[["symbol", "coin", "kol", "side", "yon", "entry_time", "giris", "cikis_isaret",
                      "exit_reason", "R_net", "pnl_usdt", "yari"]], pd.DataFrame(rows)], axis=1)
    # dönem etiketi: kar_geri_verme'deki en büyük üç düşüş
    epi = json.load(open(os.path.join(KGV, "sonuclar.json")))["dususler"]
    f["donem"] = "normal"
    for e in epi:
        P = pd.Timestamp(e["tepe"]["zaman"]); Q = pd.Timestamp(e["dip"]["zaman"])
        f.loc[(f.giris <= P) & (f.cikis_isaret > P), "donem"] = "tepede_acik"
        f.loc[(f.giris > P) & (f.giris <= Q), "donem"] = "tepeden_sonra"
    f["hafta"] = f.giris.dt.tz_localize(None).dt.to_period("W").astype(str)
    return f


# ─────────────────────────── istatistik ───────────────────────────
def boot_fark(f, a, b):
    """a grubu ort R − b grubu ort R; hafta-kümeli bootstrap %95."""
    hs = f.hafta.values; u = np.unique(hs); ix = {h: np.where(hs == h)[0] for h in u}
    Rv = f.R_net.values; out = []
    for _ in range(B_BOOT):
        s = np.concatenate([ix[h] for h in RNG.choice(u, len(u))])
        x, z = Rv[s][a[s]], Rv[s][b[s]]
        if len(x) and len(z):
            out.append(x.mean() - z.mean())
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))) if out else (np.nan, np.nan)


def satir(f, ad, grup, alt, etki_a, etki_b):
    """Bir özelliğin grup tablosu + etki (etki_a − etki_b) TRAIN/TEST/HEPSİ."""
    out = []
    for g in grup.dropna().unique():
        k = grup == g
        s = dict(ozellik=ad, alt=alt, grup=str(g), n=int(k.sum()), R_ort=f.R_net[k].mean(),
                 WR=(f.R_net[k] > 0).mean())
        for y in ("TRAIN", "TEST"):
            kk = k & (f.yari == y)
            s[f"n_{y}"] = int(kk.sum()); s[f"R_{y}"] = f.R_net[kk].mean() if kk.any() else np.nan
        out.append(s)
    et = {}
    for y, msk in (("HEPSI", np.ones(len(f), bool)), ("TRAIN", (f.yari == "TRAIN").values),
                   ("TEST", (f.yari == "TEST").values)):
        a = (grup == etki_a).values & msk; b = (grup == etki_b).values & msk
        if a.sum() >= 5 and b.sum() >= 5:
            fark = f.R_net.values[a].mean() - f.R_net.values[b].mean()
            et[y] = dict(fark=float(fark), ci=boot_fark(f, a, b), n_a=int(a.sum()), n_b=int(b.sum()))
    return out, dict(ozellik=ad, alt=alt, karsilastirma=f"{etki_a} − {etki_b}", **et)


def q5(s):
    return pd.qcut(s.rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])


SUREKLI = ["btc_ret24", "btc_ret48", "btc_ret48_islem_yonunde", "btc_ema200_atr", "btc_atr_oran",
           "gen_ema200_ustu", "gen_ret24_pozitif", "gen_islem_yonunde",
           "port_gross_not", "port_net_not_islem_yonunde", "port_upnl", "port_dd_ath",
           "don_son5_R", "don_son10_R", "don_son5_WR", "don_son10_WR"]
KATEGORIK = {"btc_4h_son_yon": (1, -1), "btc_hizali_24h": (1, 0),
             "btc_4h_ardisik": None, "btc_ardisik_islem_yonunde": None,
             "port_acik": None, "port_ayni_yon": None, "port_donch_24h": None, "port_donch_72h": None,
             "ayni_bar_ayni_yon_donch": None, "don_ardisik_kayip": None, "donem": ("tepeden_sonra", "normal")}


def kova(s, adi):
    """Sayma değişkenleri için sabit kovalar (optimizasyon değil; yalnız seyrek uçları birleştirir)."""
    if adi in ("btc_4h_ardisik",):
        return pd.cut(s, [0, 1, 2, 3, 99], labels=["1", "2", "3", "4+"]).astype(str)
    if adi == "btc_ardisik_islem_yonunde":
        return pd.cut(s, [-99, -3, -1, 1, 3, 99], labels=["≤−3", "−2..−1", "1", "2..3", "≥4"]).astype(str)
    return pd.cut(s, [-1, 0, 1, 2, 99], labels=["0", "1", "2", "3+"]).astype(str)


def tablo(f, alt):
    satirlar, etkiler = [], []
    for c in SUREKLI:
        g = q5(f[c]).astype(str).where(f[c].notna())
        o, e = satir(f, c, g, alt, "Q5", "Q1"); satirlar += o; etkiler.append(e)
    for c, et in KATEGORIK.items():
        g = f[c].astype(str) if c in ("donem", "btc_4h_son_yon", "btc_hizali_24h") else kova(f[c], c)
        a, b = (str(et[0]), str(et[1])) if et else (sorted(g.unique())[-1], sorted(g.unique())[0])
        if c == "btc_ardisik_islem_yonunde":
            a, b = "≥4", "1"
        o, e = satir(f, c, g, alt, a, b); satirlar += o; etkiler.append(e)
    return satirlar, etkiler


def hipotezler(f):
    """Önceden sabit tanımlar. Q sınırları TÜM örneklemden, sabit beşte-birler."""
    out = {}
    def karsilastir(ad, a, b, aciklama, alt=f):
        res = {"tanim": aciklama}
        for y, msk in (("HEPSI", np.ones(len(alt), bool)), ("TRAIN", (alt.yari == "TRAIN").values),
                       ("TEST", (alt.yari == "TEST").values)):
            aa, bb = a & msk, b & msk
            res[y] = dict(n_a=int(aa.sum()), n_b=int(bb.sum()),
                          R_a=float(alt.R_net[aa].mean()) if aa.any() else None,
                          R_b=float(alt.R_net[bb].mean()) if bb.any() else None,
                          WR_a=float((alt.R_net[aa] > 0).mean()) if aa.any() else None,
                          fark=(float(alt.R_net[aa].mean() - alt.R_net[bb].mean()) if aa.any() and bb.any() else None),
                          ci=(boot_fark(alt, aa, bb) if aa.sum() >= 5 and bb.sum() >= 5 else None))
        out[ad] = res
    guclu = f.btc_ret48.abs() >= f.btc_ret48.abs().quantile(0.8)
    zayif = np.sign(f.btc_4h_son_yon) == -np.sign(f.btc_ret48)
    karsilastir("H1_btc_kosu_sonrasi_zayiflama", (guclu & zayif).values, (~(guclu & zayif)).values,
                "|BTC 48h getiri| üst beşte-bir (Q5) VE son kapanmış 4h mum 48h yönüne TERS")
    karsilastir("H1b_btc_kosu_suruyor", (guclu & ~zayif).values, (~guclu).values,
                "|BTC 48h| Q5 VE son 4h mum aynı yönde (karşılaştırma: Q1-Q4)")
    tek = f.gen_islem_yonunde == 1.0
    karsilastir("H2_genislik_tek_yonlu_ve_zayiflama", (tek & zayif).values, (~(tek & zayif)).values,
                "7/7 Donchian coini 24h'te işlem yönünde VE BTC son 4h mumu 48h yönüne ters")
    karsilastir("H2b_genislik_tek_yonlu", tek.values, (~tek).values, "7/7 coin 24h'te işlem yönünde")
    kum = f.port_donch_72h >= 3
    karsilastir("H3_donchian_birikmesi_72h", kum.values, (f.port_donch_72h == 0).values,
                "son 72h'te ≥3 Donchian girişi vs hiç yok")
    ayni = f.port_ayni_yon >= 2
    karsilastir("H3b_ayni_yonde_2plus_acik", ayni.values, (f.port_ayni_yon == 0).values,
                "girişte aynı yönde ≥2 açık pozisyon vs 0")
    don = f.kol == "donchian"
    ust10 = f.don_son10_R >= f.don_son10_R.quantile(0.8)
    karsilastir("H4_don_son10_R_Q5", (ust10 & f.don_son10_R.notna()).values,
                ((~ust10) & f.don_son10_R.notna()).values, "önceki 10 Donchian toplam R'si Q5 vs Q1-Q4 (tüm işlemler)")
    fd = f[don].reset_index(drop=True)
    u = fd.don_son10_R >= f.don_son10_R.quantile(0.8)
    karsilastir("H4b_donchian_islemleri_son10_Q5", (u & fd.don_son10_R.notna()).values,
                ((~u) & fd.don_son10_R.notna()).values, "yalnız Donchian işlemleri: önceki 10 Q5 vs Q1-Q4", alt=fd)
    karsilastir("H4c_ath_yakininda", (f.port_dd_ath <= 0.02).values, (f.port_dd_ath > 0.02).values,
                "girişte hesap ATH'nin %2 içinde vs değil (sabit, önceden seçilmiş)")
    return out


def saglamlik(f):
    """H2b ve H4c için önceden sabit tanımlarla kırılımlar (kol, büyük düşüş dışı, örtüşme)."""
    out = {}
    def fark(df, a):
        r = {}
        for y in ("HEPSI", "TRAIN", "TEST"):
            m = np.ones(len(df), bool) if y == "HEPSI" else (df.yari == y).values
            sub = df[m].reset_index(drop=True); aa = a[m]
            if aa.sum() >= 5 and (~aa).sum() >= 5:
                r[y] = dict(n=int(aa.sum()), R_a=float(sub.R_net[aa].mean()), R_b=float(sub.R_net[~aa].mean()),
                            fark=float(sub.R_net[aa].mean() - sub.R_net[~aa].mean()), ci=boot_fark(sub, aa, ~aa))
        return r
    tanim = {"H4c_ATH_2yuzde": lambda x: (x.port_dd_ath <= 0.02).values,
             "H2b_genislik_7_7": lambda x: (x.gen_islem_yonunde == 1.0).values}
    for ad, fn in tanim.items():
        out[ad] = {"tum": fark(f, fn(f))}
        g = f[f.donem == "normal"].reset_index(drop=True); out[ad]["uc_dusus_disi"] = fark(g, fn(g))
        for k in ("donchian", "squeeze", "mean_rev"):
            g = f[f.kol == k].reset_index(drop=True); out[ad][k] = fark(g, fn(g))
    a, b = tanim["H4c_ATH_2yuzde"](f), tanim["H2b_genislik_7_7"](f)
    out["ortusme"] = {f"ATH={int(i)}_GEN={int(j)}": dict(n=int(((a == i) & (b == j)).sum()),
                                                         R=float(f.R_net[(a == i) & (b == j)].mean()))
                      for i in (0, 1) for j in (0, 1)}
    return out


def main():
    f = ozellikler()
    kol = [c for c in f.columns if c not in ("giris", "hafta")]
    f[kol].to_csv(os.path.join(BURA, "entry_state.csv"), index=False, float_format="%.6g")
    satirlar, etkiler = tablo(f, "HEPSI")
    fd = f[f.kol == "donchian"].reset_index(drop=True)
    s2, e2 = tablo(fd, "DONCHIAN")
    pd.DataFrame(satirlar + s2).to_csv(os.path.join(BURA, "ozellik_tablosu.csv"), index=False, float_format="%.4f")
    sonuc = dict(n=len(f), R_ort=float(f.R_net.mean()),
                 TRAIN=dict(n=int((f.yari == "TRAIN").sum()), R=float(f.R_net[f.yari == "TRAIN"].mean())),
                 TEST=dict(n=int((f.yari == "TEST").sum()), R=float(f.R_net[f.yari == "TEST"].mean())),
                 donem=f.groupby("donem").R_net.agg(["size", "mean"]).to_dict(),
                 etkiler=etkiler + e2, hipotezler=hipotezler(f), saglamlik=saglamlik(f))
    with open(os.path.join(BURA, "hipotezler.json"), "w") as fh:
        json.dump(sonuc, fh, indent=1, default=str, ensure_ascii=False)
    print(json.dumps({k: sonuc[k] for k in ("n", "R_ort", "TRAIN", "TEST")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
