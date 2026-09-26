"""
kar_geri_verme.py — kazancı geri verme davranışının çevrimdışı ölçümü (salt okur).

Girdi : ikiz_k25_cap25_islemler.csv (canlı-birebir ikiz, 936 işlem) + data/{COIN}_fut_1h.csv
Çıktı : bu klasöre islem_mfe_mae.csv, equity_saatlik.csv, sonuclar.json, filtre_106.csv
Çalıştır (repo kökünden):  python3 arastirma/kar_geri_verme/kar_geri_verme.py

Zaman kuralları (fiyat verisinde doğrulandı, bkz. rapor §1):
  · ts = 1h barın AÇILIŞ saati. "T saat işareti" = T anındaki durum = ts=T−1h barının KAPANIŞ fiyatı.
  · Giriş: entry_time barının açılışında (= sinyal barının kapanışı = intended_entry).
  · Ekonomik çıkış: ts = exit_time−2h olan barın İÇİNDE (SL/TP) ya da KAPANIŞINDA (max_hold).
    Kayıt (exit_time) bundan 1 saat işareti geç. Pozisyon exit_time−1h işaretinden itibaren KAPALI sayılır.
  · Giriş ücreti girişte ödenmiş sayılır; pnl_usdt (giriş+çıkış ücreti dahil) çıkış işaretinde gerçekleşir.
  · Funding: ikiz pnl'inde YOK; burada da eklenmedi.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(KOK, "ikiz_k25_cap25_islemler.csv")
CSV_ESKI = os.path.join(KOK, "ikiz_k25_eski_islemler.csv")
BAS = 10_000.0
CIKIS_UCRET = 0.0001
RISK, CAP = 0.035, 2.5
H = pd.Timedelta("1h")
ESIKLER = (0.5, 1.0, 1.5)


def fiyatlar(coinler):
    out = {}
    for c in coinler:
        b = pd.read_csv(os.path.join(KOK, "data", f"{c}_fut_1h.csv"))
        b["ts"] = pd.to_datetime(b.ts, utc=True)
        out[c] = b.drop_duplicates("ts").set_index("ts").sort_index()
    return out


def hazirla():
    d = pd.read_csv(CSV)
    sc = d.strategy_scores.map(json.loads)
    d["coin"] = d.symbol.str.split("/").str[0]
    d["yon"] = np.where(d.side == "long", 1.0, -1.0)
    d["niyet"] = sc.map(lambda s: s["intended_entry"])
    d["sl0"] = sc.map(lambda s: s["sl0"])
    d["ucret_giris_oran"] = sc.map(lambda s: s["entry_fee_rate"])
    d["max_hold"] = sc.map(lambda s: s.get("max_hold", 48))
    d["giris"] = pd.to_datetime(d.entry_time, utc=True)
    d["kayit_cikis"] = pd.to_datetime(d.exit_time, utc=True)
    d["risk0"] = (d.niyet - d.sl0).abs()
    d["R_net"] = d.pnl_usdt / (d.quantity * d.risk0)
    d["ucret_giris"] = d.ucret_giris_oran * d.entry_price * d.quantity
    d["ucret_cikis"] = CIKIS_UCRET * d.exit_price * d.quantity
    d["fiyat_pnl_cikis"] = d.yon * (d.exit_price - d.entry_price) * d.quantity
    d["pnl_yeniden"] = d.fiyat_pnl_cikis - d.ucret_giris - d.ucret_cikis
    d["kayma_giris_usd"] = d.yon * (d.entry_price - d.niyet) * d.quantity
    return d


def cikis_simule(d, px):
    """Kayıttaki fiyat/stop/hedefle bar bar yürü; ekonomik çıkış barını ve tipini bul."""
    rr = {"donchian": 2.5, "squeeze": 2.5, "mean_rev": 5.0 / 3.0}
    sim_bar, sim_tip, cift = [], [], []
    for t in d.itertuples():
        b = px[t.coin]
        tp = t.niyet + t.yon * rr[t.kol] * t.risk0
        i0 = b.index.get_indexer([t.giris])[0]
        sl = t.sl_price
        tip, bar, iki = "max_hold", None, False
        for j in range(i0, min(i0 + int(t.max_hold), len(b))):
            hi, lo = b.high.iat[j], b.low.iat[j]
            sl_d = lo <= sl if t.yon > 0 else hi >= sl
            tp_d = hi >= tp if t.yon > 0 else lo <= tp
            if sl_d or tp_d:
                tip, bar, iki = ("sl_hit" if sl_d else "tp_hit"), b.index[j], (sl_d and tp_d)
                break
        if bar is None:
            bar = b.index[min(i0 + int(t.max_hold) - 1, len(b) - 1)]
        sim_bar.append(bar); sim_tip.append(tip); cift.append(iki)
    d["cikis_bari"] = sim_bar
    d["sim_tip"] = sim_tip
    d["cift_dokunus"] = cift
    d["tp"] = d.niyet + d.yon * d.kol.map(rr) * d.risk0
    d["cikis_isaret"] = d.cikis_bari + H          # ekonomik: bu işaretten itibaren kapalı
    return d


def mfe_mae(d, px):
    rows = []
    for t in d.itertuples():
        b = px[t.coin]
        i0 = b.index.get_indexer([t.giris])[0]
        j = b.index.get_indexer([t.cikis_bari])[0]
        hi, lo = b.high.values[i0:j + 1], b.low.values[i0:j + 1]
        fav = (hi - t.entry_price) if t.yon > 0 else (t.entry_price - lo)
        adv = (t.entry_price - lo) if t.yon > 0 else (hi - t.entry_price)
        tp_mes = t.yon * (t.tp - t.entry_price)
        sl_mes = t.yon * (t.entry_price - t.sl_price)
        onceki_fav = max(0.0, fav[:-1].max()) if len(fav) > 1 else 0.0
        onceki_adv = max(0.0, adv[:-1].max()) if len(adv) > 1 else 0.0
        if t.sim_tip == "max_hold":             # çıkış barın kapanışında: bar tamamen işlemin içinde
            mfe_k = mfe_u = max(0.0, fav.max()); mae_k = mae_u = max(0.0, adv.max())
        elif t.sim_tip == "sl_hit":             # çıkış barında olumlu uç stoptan önce mi sonra mı: belirsiz
            mfe_k = onceki_fav
            mfe_u = max(onceki_fav, min(max(0.0, fav[-1]), tp_mes))
            mae_k = mae_u = max(onceki_adv, sl_mes)
        else:                                   # tp_hit: hedefte kapandı, olumsuz uç belirsiz
            mfe_k = mfe_u = tp_mes
            mae_k = onceki_adv
            mae_u = max(onceki_adv, min(max(0.0, adv[-1]), sl_mes))
        r0 = t.risk0
        rows.append(dict(mfe_R_kesin=mfe_k / r0, mfe_R_ust=mfe_u / r0,
                         mae_R_kesin=mae_k / r0, mae_R_ust=mae_u / r0, bar_sayisi=j - i0 + 1))
    return pd.concat([d.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def saatlik(d, px):
    bas = d.giris.min().floor("h"); son = d.cikis_isaret.max()
    isaret = pd.date_range(bas, son, freq="h", tz="UTC")
    n = len(isaret)
    kapanis = {}
    for c in d.coin.unique():                   # T işareti = ts=T−1h barının kapanışı; eksik bar ileri doldurulur
        s = px[c].close.copy(); s.index = s.index + H
        kapanis[c] = s.reindex(isaret).ffill().values
    gerceklesen = np.full(n, BAS); gerceklesmemis = np.zeros(n); acik = np.zeros(n, int)
    long_n = np.zeros(n); short_n = np.zeros(n); stop_ek = np.zeros(n)
    for t in d.itertuples():
        a = isaret.get_indexer([t.giris])[0]
        b = isaret.get_indexer([t.cikis_isaret])[0]
        if a < 0 or b < 0:
            raise SystemExit(f"işaret bulunamadı: {t.symbol} {t.giris} {t.cikis_isaret}")
        p = kapanis[t.coin][a:b]
        gerceklesmemis[a:b] += t.yon * (p - t.entry_price) * t.quantity
        gerceklesen[a:b] -= t.ucret_giris
        gerceklesen[b:] += t.pnl_usdt
        acik[a:b] += 1
        (long_n if t.yon > 0 else short_n)[a:b] += p * t.quantity
        stop_ek[a:b] += t.yon * (t.sl_price - p) * t.quantity   # negatif: stoplara gidilirse ek PnL
    e = pd.DataFrame({"zaman": isaret, "gerceklesmis_bakiye": gerceklesen,
                      "gerceklesmemis_pnl": gerceklesmemis})
    e["hesap_degeri"] = e.gerceklesmis_bakiye + e.gerceklesmemis_pnl
    e["acik_pozisyon"] = acik
    e["long_notional"] = long_n; e["short_notional"] = short_n
    e["stoplara_ek_kayip"] = stop_ek
    for c in ("gerceklesmemis_pnl", "long_notional", "short_notional", "stoplara_ek_kayip"):
        e[c + "_oran"] = e[c] / e.hesap_degeri
    return e


def katki(d, zaman):
    """Her pozisyonun T işaretindeki hesap değerine katkısı: (fiyat kısmı, ücret kısmı)."""
    fiyat = np.zeros(len(d)); ucret = np.zeros(len(d))
    for i, t in enumerate(d.itertuples()):
        if zaman < t.giris:
            continue
        if zaman >= t.cikis_isaret:
            fiyat[i] = t.fiyat_pnl_cikis; ucret[i] = t.ucret_giris + t.ucret_cikis
        else:
            fiyat[i] = t.yon * (zaman_fiyat(t, zaman) - t.entry_price) * t.quantity
            ucret[i] = t.ucret_giris
    return fiyat, ucret


_PX = {}
def zaman_fiyat(t, zaman):
    b = _PX[t.coin]
    return float(b.close.asof(zaman - H))


def dususler(e, adet=3):
    v = e.hesap_degeri.values; z = e.zaman.values
    epi, i, n = [], 0, len(v)
    tepe_i = 0
    while i < n:
        if v[i] >= v[tepe_i]:
            tepe_i = i; i += 1; continue
        j = i
        while j < n and v[j] < v[tepe_i]:
            j += 1
        seg = slice(tepe_i, j)
        dip_i = tepe_i + int(np.argmin(v[seg]))
        epi.append(dict(tepe_i=tepe_i, dip_i=dip_i, toparlanma_i=(j if j < n else None),
                        derinlik=1 - v[dip_i] / v[tepe_i]))
        tepe_i = j if j < n else tepe_i
        i = j
    epi.sort(key=lambda x: -x["derinlik"])
    return epi[:adet]


def main():
    d = hazirla()
    px = fiyatlar(d.coin.unique()); _PX.update(px)
    sonuc = {}

    # 1) dayanak
    fark = (d.pnl_usdt - d.pnl_yeniden).abs()
    sonuc["pnl_yeniden_kurulum"] = dict(n=len(d), tolerans_usd=0.01, uyusmayan=int((fark > 0.01).sum()),
                                        max_fark_usd=float(fark.max()))
    d = cikis_simule(d, px)
    kayit_bar = d.kayit_cikis - 2 * H
    sonuc["cikis_eslesme"] = dict(tip_eslesen=int((d.sim_tip == d.exit_reason).sum()),
                                  bar_eslesen_kayit_eksi_2s=int((d.cikis_bari == kayit_bar).sum()),
                                  cift_dokunus=int(d.cift_dokunus.sum()))
    sonuc["R_net"] = dict(ort=float(d.R_net.mean()), toplam=float(d.R_net.sum()))

    # 3) MFE/MAE
    m = mfe_mae(d, px)
    kol = ["symbol", "kol", "side", "entry_time", "exit_time", "cikis_isaret", "exit_reason", "sim_tip",
           "cift_dokunus", "entry_price", "exit_price", "niyet", "sl0", "tp", "quantity", "pnl_usdt",
           "R_net", "mfe_R_kesin", "mfe_R_ust", "mae_R_kesin", "mae_R_ust", "bar_sayisi"]
    m[kol].to_csv(os.path.join(BURA, "islem_mfe_mae.csv"), index=False)
    tablo = {}
    for grup, g in list(m.groupby("kol")) + [("HEPSI", m)]:
        r = {"n": len(g)}
        for x in ESIKLER:
            k = g.mfe_R_kesin >= x; u = g.mfe_R_ust >= x
            r[f"{x}R_gorup_zarar_kesin"] = int((k & (g.R_net < 0)).sum())
            r[f"{x}R_gorup_zarar_ust"] = int((u & (g.R_net < 0)).sum())
            r[f"{x}R_gorup_kar_kesin"] = int((k & (g.R_net > 0)).sum())
            r[f"{x}R_gorulen_kesin"] = int(k.sum())
            sl = g[g.sim_tip == "sl_hit"]
            r[f"sl_{x}R_hic_ulasmayan"] = int((sl.mfe_R_ust < x).sum())
            r["sl_n"] = len(sl)
        tablo[grup] = r
    sonuc["mfe_tablo"] = tablo

    # 2) saatlik hesap değeri
    e = saatlik(d, px)
    e.to_csv(os.path.join(BURA, "equity_saatlik.csv"), index=False, float_format="%.6f")
    son = e.iloc[-1]
    sonuc["saatlik"] = dict(isaret=len(e), son_deger=float(son.hesap_degeri),
                            son_gerceklesmis=float(son.gerceklesmis_bakiye),
                            csv_toplam_pnl=float(BAS + d.pnl_usdt.sum()),
                            veri_sonu_acik=int(son.acik_pozisyon))
    v = e.hesap_degeri.values
    sonuc["maxdd_saatlik"] = float((1 - v / np.maximum.accumulate(v)).max())
    g_ = e.gerceklesmis_bakiye.values
    sonuc["maxdd_gerceklesmis_saatlik"] = float((1 - g_ / np.maximum.accumulate(g_)).max())
    sonuc["stop_ek_kayip_oran"] = {q: float(e.stoplara_ek_kayip_oran.quantile(q)) for q in (0.5, 0.95, 0.99)}
    sonuc["stop_ek_kayip_oran"]["min"] = float(e.stoplara_ek_kayip_oran.min())

    # 4) boyutlama tabanı: her girişte hesap değeri, içindeki gerçekleşmemiş PnL, ima edilen taban
    zi = e.set_index("zaman")
    giris_rows = []
    for t in d.itertuples():
        onceki = d[(d.giris < t.giris) & (d.cikis_isaret > t.giris)]   # aynı işaretteki diğer girişler hariç
        fiyat, ucret = 0.0, 0.0
        for o in onceki.itertuples():
            fiyat += o.yon * (zaman_fiyat(o, t.giris) - o.entry_price) * o.quantity
            ucret += o.ucret_giris
        gerc = BAS + float(d.loc[d.cikis_isaret <= t.giris, "pnl_usdt"].sum()) - ucret
        V = gerc + fiyat
        stop_pct = t.risk0 / t.niyet
        ima = max(t.quantity * t.risk0 / RISK, t.quantity * t.niyet / CAP)
        ayni = int(((onceki.yon == t.yon)).sum()); ters = int(((onceki.yon != t.yon)).sum())
        giris_rows.append(dict(idx=t.Index, hesap_degeri=V, gerceklesmemis=fiyat, gerceklesmis=gerc,
                               ima_taban=ima, cap_bagladi=bool(t.quantity * t.niyet / CAP >= t.quantity * t.risk0 / RISK),
                               ayni_yon_acik=ayni, ters_yon_acik=ters, notional_oran=t.quantity * t.entry_price / V))
    gi = pd.DataFrame(giris_rows).set_index("idx")
    d = d.join(gi)
    d["U_pay"] = d.gerceklesmemis / d.hesap_degeri
    d["taban_orani"] = d.ima_taban / d.hesap_degeri
    sonuc["boyutlama_dogrulama"] = dict(taban_orani_medyan=float(d.taban_orani.median()),
                                        p05=float(d.taban_orani.quantile(0.05)),
                                        p95=float(d.taban_orani.quantile(0.95)))
    d[["symbol", "kol", "side", "entry_time", "hesap_degeri", "gerceklesmis", "gerceklesmemis", "U_pay",
       "ima_taban", "taban_orani", "cap_bagladi", "ayni_yon_acik", "ters_yon_acik", "notional_oran",
       "quantity", "pnl_usdt", "R_net"]].to_csv(os.path.join(BURA, "giris_boyutlama.csv"), index=False)

    # 4) hipotez: girişteki açık kâr payına göre sonuç (betimsel; kural değil). Hafta-kümeli bootstrap.
    def grup(r):
        if r.ayni_yon_acik + r.ters_yon_acik == 0:
            return "0_acik_pozisyon_yok"
        if r.U_pay <= 0:
            return "1_acik_kar_yok_veya_zarar"
        return "2_acik_kar_0-3%" if r.U_pay <= 0.03 else "3_acik_kar_>3%"
    d["U_grup"] = d.apply(grup, axis=1)
    hafta = d.giris.dt.tz_localize(None).dt.to_period("W").astype(str).values
    rng = np.random.default_rng(20260926)
    hs = np.unique(hafta); ix = {h: np.where(hafta == h)[0] for h in hs}
    a_m = (d.U_grup == "3_acik_kar_>3%").values; b_m = (d.U_grup == "0_acik_pozisyon_yok").values
    fr = []
    for _ in range(4000):
        sel = np.concatenate([ix[h] for h in rng.choice(hs, len(hs))])
        a, b = d.R_net.values[sel][a_m[sel]], d.R_net.values[sel][b_m[sel]]
        if len(a) and len(b):
            fr.append(a.mean() - b.mean())
    sonuc["U_grup"] = {k: dict(n=int(len(g)), R_ort=float(g.R_net.mean()), WR=float((g.R_net > 0).mean()),
                               ayni_yon_ort=float(g.ayni_yon_acik.mean()), pnl=float(g.pnl_usdt.sum()))
                       for k, g in d.groupby("U_grup")}
    sonuc["U_grup_fark_3_eksi_0"] = dict(fark=float(d.R_net[a_m].mean() - d.R_net[b_m].mean()),
                                         ci95_hafta=[float(np.percentile(fr, 2.5)), float(np.percentile(fr, 97.5))])
    ust = d[d.U_pay > 0.03]
    sonuc["U>3%_ayni_yon"] = {("ayni yonde acik var" if k else "ayni yonde acik yok"):
                               dict(n=int(len(g)), R_ort=float(g.R_net.mean()))
                               for k, g in ust.groupby(ust.ayni_yon_acik >= 1)}

    # 4) en büyük üç düşüş ve ayrıştırma
    epi_out = []
    for ep in dususler(e):
        P, Q = e.zaman.iat[ep["tepe_i"]], e.zaman.iat[ep["dip_i"]]
        fP, uP = katki(d, P); fQ, uQ = katki(d, Q)
        acikP = ((d.giris <= P) & (d.cikis_isaret > P)).values
        yeni = ((d.giris > P) & (d.giris <= Q)).values
        A_fiyat = float((fQ - fP)[acikP].sum()); A_ucret = float((uQ - uP)[acikP].sum())
        B_fiyat = float(fQ[yeni].sum()); B_ucret = float(uQ[yeni].sum())
        dV = float(e.hesap_degeri.iat[ep["dip_i"]] - e.hesap_degeri.iat[ep["tepe_i"]])
        kalan = dV - (A_fiyat + B_fiyat - A_ucret - B_ucret)
        kapanan_pencere = ((d.cikis_isaret > P) & (d.cikis_isaret <= Q)).values
        kayma_bilgi = float(d.kayma_giris_usd[yeni].sum()
                            + (d.exit_price * d.quantity * 0.24e-4)[kapanan_pencere].sum())
        satir = lambda i: e.iloc[i]
        def durum(i):
            s = satir(i)
            return dict(zaman=str(s.zaman), deger=float(s.hesap_degeri), acik=int(s.acik_pozisyon),
                        long_oran=float(s.long_notional_oran), short_oran=float(s.short_notional_oran),
                        stop_ek_kayip_oran=float(s.stoplara_ek_kayip_oran),
                        gerceklesmemis_oran=float(s.gerceklesmemis_pnl_oran))
        Bd = d[yeni]
        epi_out.append(dict(
            derinlik=ep["derinlik"], tutar=dV, tepe=durum(ep["tepe_i"]), dip=durum(ep["dip_i"]),
            toparlanma=(str(e.zaman.iat[ep["toparlanma_i"]]) if ep["toparlanma_i"] is not None else None),
            A_tepede_acik_fiyat=A_fiyat, A_n=int(acikP.sum()),
            B_sonradan_acilan_fiyat=B_fiyat, B_n=int(yeni.sum()),
            C_ucret=-(A_ucret + B_ucret), kayma_fiyat_icinde_bilgi=-kayma_bilgi, aciklanamayan=kalan,
            B_kaybedenlerde_U_kaynakli=float((Bd.pnl_usdt * Bd.U_pay.clip(lower=0))[Bd.pnl_usdt < 0].sum()),
            B_kazananlarda_U_kaynakli=float((Bd.pnl_usdt * Bd.U_pay.clip(lower=0))[Bd.pnl_usdt > 0].sum()),
            B_U_pay_medyan=float(Bd.U_pay.median()) if len(Bd) else None,
            B_ayni_yon_medyan=float(Bd.ayni_yon_acik.median()) if len(Bd) else None,
            B_R_ort=float(Bd.R_net.mean()) if len(Bd) else None))
    sonuc["dususler"] = epi_out
    sonuc["U_pay_girislerde"] = {q: float(d.U_pay.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    q = pd.qcut(d.U_pay, 5, duplicates="drop")
    sonuc["U_pay_dilim_R"] = {str(k): dict(n=int(len(g)), R_ort=float(g.R_net.mean()),
                                           pnl=float(g.pnl_usdt.sum()))
                              for k, g in d.groupby(q, observed=True)}

    # 5) hacim filtresi: 1107 − 801 = 306 vs 412
    sonuc["filtre"] = filtre_106(px)
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(sonuc, f, indent=1, default=str, ensure_ascii=False)
    print(json.dumps({k: v for k, v in sonuc.items() if k not in ("dususler", "mfe_tablo")},
                     indent=1, default=str, ensure_ascii=False))


def filtre_106(px):
    def don(yol):
        x = pd.read_csv(yol); x = x[x.kol == "donchian"].copy()
        x["giris"] = pd.to_datetime(x.entry_time, utc=True); x["cikis"] = pd.to_datetime(x.exit_time, utc=True)
        x["coin"] = x.symbol.str.split("/").str[0]
        return x
    yeni, eski = don(CSV), don(CSV_ESKI)
    anahtar = ["symbol", "side", "giris"]
    m = eski.merge(yeni[anahtar], on=anahtar, how="left", indicator=True)
    oran = {}
    for c in eski.coin.unique():                 # kırılım barı = entry_time'da kapanan 4h bar
        b = px[c] if c in px else fiyatlar([c])[c]
        v4 = b.volume.resample("4h", origin="epoch").sum()
        ort = v4.shift(1).rolling(20).mean()
        oran[c] = (v4 / ort)
    def r(row):
        s = oran[row.coin]; t = row.giris - pd.Timedelta("4h")
        return float(s.get(t, np.nan))
    eski["hacim_orani"] = eski.apply(r, axis=1)
    yeni["hacim_orani"] = yeni.apply(r, axis=1)
    m["hacim_orani"] = eski["hacim_orani"].values
    ortak = m["_merge"] == "both"
    elenen = (~ortak) & (m.hacim_orani < 2.5)
    yerinden = (~ortak) & (m.hacim_orani >= 2.5)
    y = yeni.merge(eski[anahtar], on=anahtar, how="left", indicator=True)
    yalniz_yeni = yeni[(y["_merge"] == "left_only").values].copy()

    def slot_dolu(run, row):
        o = run[(run.symbol == row.symbol) & (run.giris < row.giris) & (run.cikis > row.giris)]
        return len(o) > 0
    yalniz_yeni["eskide_ayni_coin_donchian_acik"] = yalniz_yeni.apply(lambda rw: slot_dolu(eski, rw), axis=1)
    ortak_set = set(map(tuple, m.loc[ortak, anahtar].astype(str).values))

    def sebep(row):
        o = eski[(eski.symbol == row.symbol) & (eski.giris < row.giris) & (eski.cikis > row.giris)]
        if len(o):
            tk = tuple(map(str, o.iloc[0][anahtar].values))
            return "yuva dolu: filtrenin eledigi islem" if tk not in ortak_set else "yuva dolu: ortak islem"
        p = eski[(eski.symbol == row.symbol) & (eski.cikis <= row.giris)].sort_values("cikis")
        if (len(p) >= 2 and (p.pnl_usdt.tail(2) < 0).all()
                and row.giris - p.cikis.iloc[-1] <= pd.Timedelta("240min")):
            return "eskide 2 ardisik zarar sogumasi"
        return "aciklanamadi (farkli risk/CAP/TRX: marjin veya koltuk olabilir)"
    yalniz_yeni["sebep"] = yalniz_yeni.apply(sebep, axis=1)
    yer = eski[(~ortak).values & (m.hacim_orani >= 2.5).values].copy()
    yer["yenide_ayni_coin_donchian_acik"] = yer.apply(lambda rw: slot_dolu(yeni, rw), axis=1)
    kayit = pd.concat([
        yalniz_yeni.assign(grup="yalniz_filtreli")[["grup", "symbol", "side", "entry_time", "hacim_orani",
                                                    "eskide_ayni_coin_donchian_acik", "sebep"]],
        yer.assign(grup="yerinden_edilen")[["grup", "symbol", "side", "entry_time", "hacim_orani",
                                            "yenide_ayni_coin_donchian_acik"]]])
    kayit.to_csv(os.path.join(BURA, "filtre_106.csv"), index=False)
    return dict(filtresiz_donchian=len(eski), filtreli_donchian=len(yeni), ortak=int(ortak.sum()),
                elenen_oran_alti=int(elenen.sum()), yerinden_oran_ustu=int(yerinden.sum()),
                oran_bilinmeyen=int(((~ortak) & m.hacim_orani.isna()).sum()),
                yalniz_filtreli=len(yalniz_yeni),
                yalniz_filtreli_oran_ustu=int((yalniz_yeni.hacim_orani >= 2.5).sum()),
                yalniz_filtreli_eskide_slot_dolu=int(yalniz_yeni.eskide_ayni_coin_donchian_acik.sum()),
                yerinden_yenide_slot_dolu=int(yer.yenide_ayni_coin_donchian_acik.sum()),
                yalniz_filtreli_sebep=yalniz_yeni.sebep.value_counts().to_dict())


if __name__ == "__main__":
    main()
