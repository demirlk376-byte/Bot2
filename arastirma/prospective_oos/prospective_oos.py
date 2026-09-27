"""
prospective_oos.py — dondurulmuş iki koşulun İLERİYE DÖNÜK (OOS) gözlem defteri. SALT GÖZLEM.

Sinyale, execution'a, riske DOKUNMAZ; işlem engellemez. Yalnız bir işlem listesini okur,
giriş anındaki iki koşulu hesaplar ve defter dosyasına yazar.

DONDURULMUŞ (2026-09-27, post_peak_diagnostic §7) — DEĞİŞTİRME:
  1) ath_near_2pct  = port_dd_ath <= 0.02
  2) breadth_7of7   = gen_islem_yonunde == 1.0
  Formüller aşağıdaki `port_dd_ath_hesapla` ve `gen_islem_yonunde_hesapla` içinde; `--dogrula`
  bunların geçmiş 936 işlemde entry_state.csv'yi birebir ürettiğini sınar.

CUTOFF: entry_time >= PROSPECTIVE_OOS_START olan işlemler deftere girer; öncesi ASLA girmez.
Özellikler için geçmiş işlemler/fiyatlar yalnız "T anında bilinen" kısmıyla kullanılır.

Kullanım (repo kökünden):
  python3 arastirma/prospective_oos/prospective_oos.py --dogrula
  python3 arastirma/prospective_oos/prospective_oos.py --islemler <ikiz_islem.csv> --veri <1h_veri_dizini>
  python3 arastirma/prospective_oos/prospective_oos.py --rapor
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(KOK, "arastirma", "kar_geri_verme"))

PROSPECTIVE_OOS_START = pd.Timestamp("2026-09-27", tz="UTC")
ATH_ESIK = 0.02            # dondurulmuş
GENISLIK_ESIK = 1.0        # dondurulmuş (7/7)
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
BAS = 10_000.0
H = pd.Timedelta("1h")
DEFTER = os.path.join(BURA, "prospective_oos_ledger.csv")
# Karar için önceden kayıtlı asgari örneklem (değiştirme): her karşılaştırılan grupta
# en az 30 KAPANMIŞ işlem VE cutoff sonrası en az 26 farklı hafta.
MIN_ISLEM, MIN_HAFTA = 30, 26
DEFTER_KOLON = ["symbol", "strategy", "side", "entry_time", "exit_time", "ekonomik_cikis", "R_net",
                "port_dd_ath", "ath_near_2pct", "gen_islem_yonunde", "breadth_7of7", "iki_kosul_birlikte",
                "ilk_kayit_utc", "sonuc_kayit_utc", "kaynak_sha256"]


# ─────────────────── ortak parçalar ───────────────────
def yukle_1h(veri, coin):
    b = pd.read_csv(os.path.join(veri, f"{coin}_fut_1h.csv"))
    b["ts"] = pd.to_datetime(b.ts, utc=True)
    return b.drop_duplicates("ts").set_index("ts").sort_index()


def kapanis_T(b1, T, geri=0):
    s = b1.close.loc[:T - pd.Timedelta(hours=geri) - H]
    return float(s.iat[-1]) if len(s) else np.nan


def hazirla(yol):
    d = pd.read_csv(yol)
    sc = d.strategy_scores.map(json.loads)
    d["strategy"] = d["kol"] if "kol" in d.columns else sc.map(lambda s: s.get("strategy"))
    d["coin"] = d.symbol.str.split("/").str[0]
    d["yon"] = np.where(d.side == "long", 1, -1)
    d["niyet"] = sc.map(lambda s: s.get("intended_entry"))
    d["sl0"] = sc.map(lambda s: s.get("sl0"))
    d["max_hold"] = sc.map(lambda s: s.get("max_hold", 48))
    d["ucret_giris"] = sc.map(lambda s: s.get("entry_fee_rate", 0.0)) * d.entry_price * d.quantity
    d["giris"] = pd.to_datetime(d.entry_time, utc=True)
    d["kapali"] = d.exit_time.notna() & d.pnl_usdt.notna()
    d["risk0"] = (d.niyet - d.sl0).abs()
    d["R_net"] = np.where(d.kapali, d.pnl_usdt / (d.quantity * d.risk0), np.nan)
    d["kol"] = d.strategy
    return d.sort_values(["giris", "symbol"]).reset_index(drop=True)


def ekonomik_cikis(d, px):
    """Kapanmış işlemler için kar_geri_verme'deki bar simülasyonu (SL önce); açıklar: +sonsuz."""
    import kar_geri_verme as K
    kap = d[d.kapali].copy()
    kap["kayit_cikis"] = pd.to_datetime(kap.exit_time, utc=True)
    kap = K.cikis_simule(kap.rename(columns={}), px)
    d["cikis_isaret"] = pd.Series(pd.to_datetime(kap.cikis_isaret, utc=True), index=kap.index).reindex(d.index)
    return d


def saatlik_deger(d, px):
    """Saat işaretlerinde hesap değeri (kar_geri_verme.saatlik ile aynı kurallar; açık işlemler desteklenir)."""
    bas = d.giris.min().floor("h")
    son = max(d.cikis_isaret.max() if d.cikis_isaret.notna().any() else bas,
              max(b.index.max() for b in px.values()) + H)
    isaret = pd.date_range(bas, son, freq="h", tz="UTC"); n = len(isaret)
    kap = {}
    for c in d.coin.unique():
        s = px[c].close.copy(); s.index = s.index + H
        kap[c] = s.reindex(isaret).ffill().values
    v = np.full(n, BAS)
    for t in d.itertuples():
        a = isaret.get_indexer([t.giris])[0]
        b = isaret.get_indexer([t.cikis_isaret])[0] if pd.notna(t.cikis_isaret) else n
        p = kap[t.coin][a:b]
        v[a:b] += t.yon * (p - t.entry_price) * t.quantity - t.ucret_giris
        if b < n:
            v[b:] += t.pnl_usdt
    return pd.Series(v, index=isaret)


# ─────────────────── DONDURULMUŞ FORMÜLLER ───────────────────
def port_dd_ath_hesapla(d, px, V_saat, i):
    """1 − V(T)/ATH(T); V(T) = 10000 + Σ kapalı pnl − Σ açık giriş ücreti + Σ açık fiyat PnL (close ts≤T−1h);
    açık = giriş < T ve ekonomik çıkış > T; ATH = max(hesap değeri işaretleri < T, V(T))."""
    T = d.giris.iat[i]
    cik = d.cikis_isaret
    acik = d[(d.giris < T) & (cik.isna() | (cik > T))]
    kap = d[cik.notna() & (cik <= T)]
    upnl = sum(o.yon * (kapanis_T(px[o.coin], T) - o.entry_price) * o.quantity for o in acik.itertuples())
    V = BAS + kap.pnl_usdt.sum() - acik.ucret_giris.sum() + upnl
    once = V_saat[V_saat.index < T]
    ath = max(float(once.max()) if len(once) else BAS, V)
    return 1 - V / ath


def gen_islem_yonunde_hesapla(px, T, yon):
    """7 Donchian coininde sign(close(T)/close(T−24h) − 1) == yön oranı; eksik coin varsa NaN."""
    ayni = []
    for c in DONCH:
        rr = kapanis_T(px[c], T) / kapanis_T(px[c], T, 24) - 1
        if np.isfinite(rr):
            ayni.append(float(np.sign(rr) == yon))
    return float(np.mean(ayni)) if len(ayni) == len(DONCH) else np.nan


def ozellik_hesapla(d, px, indeksler):
    V_saat = saatlik_deger(d, px)
    out = {}
    for i in indeksler:
        dd = port_dd_ath_hesapla(d, px, V_saat, i)
        gen = gen_islem_yonunde_hesapla(px, d.giris.iat[i], d.yon.iat[i])
        out[i] = (dd, gen)
    return out


# ─────────────────── defter ───────────────────
def defter_guncelle(yol_islem, veri):
    sk = yol_islem + ".sureklilik.json"                  # ikiz_ileri.py çıktısı: 936/936 PASS şart
    if not os.path.exists(sk) or json.load(open(sk)).get("sonuc") != "PASS":
        raise SystemExit(f"süreklilik PASS değil ya da yok ({sk}); defter güncellenmedi.")
    d = hazirla(yol_islem)
    px = {c: yukle_1h(veri, c) for c in set(d.coin) | set(DONCH)}
    d = ekonomik_cikis(d, px)
    veri_sonu = min(b.index.max() for b in px.values()) + H
    yeni = [i for i in d.index if d.giris.iat[i] >= PROSPECTIVE_OOS_START]
    sha = hashlib.sha256(open(yol_islem, "rb").read()).hexdigest()[:16]
    simdi = datetime.now(timezone.utc).isoformat(timespec="seconds")
    eski = (pd.read_csv(DEFTER, dtype=str, keep_default_na=False) if os.path.exists(DEFTER)
            else pd.DataFrame(columns=DEFTER_KOLON))           # boş alan "" kalmalı, NaN değil
    anahtar = lambda r: (r["symbol"], r["side"], r["entry_time"])
    kayit = {anahtar(r): r for r in eski.to_dict("records")}
    ozl = ozellik_hesapla(d, px, [i for i in yeni if anahtar(d.loc[i]) not in kayit])
    for i in yeni:
        t = d.loc[i]; k = anahtar(t)
        if k not in kayit:                                   # giriş özellikleri İLK görüldüğünde dondurulur
            dd, gen = ozl[i]
            kayit[k] = dict(symbol=t.symbol, strategy=t.strategy, side=t.side, entry_time=t.entry_time,
                            exit_time="", ekonomik_cikis="", R_net="",
                            port_dd_ath=repr(float(dd)), ath_near_2pct=str(bool(dd <= ATH_ESIK)),
                            gen_islem_yonunde=repr(float(gen)),
                            breadth_7of7=("" if np.isnan(gen) else str(bool(gen == GENISLIK_ESIK))),
                            iki_kosul_birlikte=("" if np.isnan(gen) else str(bool(dd <= ATH_ESIK and gen == GENISLIK_ESIK))),
                            ilk_kayit_utc=simdi, sonuc_kayit_utc="", kaynak_sha256=sha)
        r = kayit[k]
        if (not r.get("R_net")) and t.kapali and pd.notna(t.cikis_isaret) and t.cikis_isaret <= veri_sonu:
            r.update(exit_time=t.exit_time, ekonomik_cikis=str(t.cikis_isaret), R_net=repr(float(t.R_net)),
                     sonuc_kayit_utc=simdi)                  # sonuç YALNIZ ekonomik çıkıştan sonra
    df = pd.DataFrame(list(kayit.values()), columns=DEFTER_KOLON).sort_values(["entry_time", "symbol"])
    assert (pd.to_datetime(df.entry_time, utc=True) >= PROSPECTIVE_OOS_START).all()
    df.to_csv(DEFTER, index=False)
    print(f"defter: {len(df)} satır (kapanmış {int((df.R_net != '').sum())}) · kaynak {sha}")


# ─────────────────── rapor ───────────────────
def rapor():
    if not os.path.exists(DEFTER):
        print("defter yok — YETERSİZ VERİ"); return
    df = pd.read_csv(DEFTER)
    k = df[df.R_net.notna()].copy()
    k["hafta"] = pd.to_datetime(k.entry_time, utc=True).dt.tz_localize(None).dt.to_period("W").astype(str)
    print(f"PROSPECTIVE_OOS_START = {PROSPECTIVE_OOS_START.date()} · kayıt {len(df)} · kapanmış {len(k)} · "
          f"hafta {k.hafta.nunique()}")
    rng = np.random.default_rng(20260927)
    for ad in ("ath_near_2pct", "breadth_7of7", "iki_kosul_birlikte"):
        a = k[ad].astype(str) == "True"; b = k[ad].astype(str) == "False"
        na, nb = int(a.sum()), int(b.sum())
        satir = f"  {ad}: TRUE n={na} R={k.R_net[a].mean():+.3f}  FALSE n={nb} R={k.R_net[b].mean():+.3f}" if na and nb \
            else f"  {ad}: TRUE n={na} FALSE n={nb}"
        if na < MIN_ISLEM or nb < MIN_ISLEM or k.hafta.nunique() < MIN_HAFTA:
            print(satir + f"  → YETERSİZ VERİ (gerekli: grup başı ≥{MIN_ISLEM} kapanmış, ≥{MIN_HAFTA} hafta)")
            continue
        hs = k.hafta.values; u = np.unique(hs); ix = {h: np.where(hs == h)[0] for h in u}
        R = k.R_net.values; A = a.values; B = b.values; fr = []
        for _ in range(2000):
            s = np.concatenate([ix[h] for h in rng.choice(u, len(u))])
            if A[s].any() and B[s].any():
                fr.append(R[s][A[s]].mean() - R[s][B[s]].mean())
        lo, hi = np.percentile(fr, [2.5, 97.5])
        print(satir + f"  fark {R[A].mean() - R[B].mean():+.3f} [%95 {lo:+.3f}, {hi:+.3f}] (hafta-kümeli)")


# ─────────────────── öz-test: formüller dondurulmuş mu ───────────────────
def dogrula():
    ref = pd.read_csv(os.path.join(KOK, "arastirma", "post_peak_diagnostic", "entry_state.csv"))
    d = hazirla(os.path.join(KOK, "ikiz_k25_cap25_islemler.csv"))
    px = {c: yukle_1h(os.path.join(KOK, "data"), c) for c in set(d.coin) | set(DONCH)}
    d = ekonomik_cikis(d, px)
    ozl = ozellik_hesapla(d, px, list(d.index))
    d["port_dd_ath"] = [ozl[i][0] for i in d.index]; d["gen"] = [ozl[i][1] for i in d.index]
    m = d.merge(ref[["symbol", "side", "entry_time", "port_dd_ath", "gen_islem_yonunde"]],
                on=["symbol", "side", "entry_time"], suffixes=("", "_ref"))
    dd_fark = (m.port_dd_ath - m.port_dd_ath_ref).abs().max()
    # entry_state.csv 6 anlamlı basamakla yazıldı (%.6g) -> 1e-5 tolerans; eşik SINIFLARI birebir aranır
    gen_ok = (((m.gen - m.gen_islem_yonunde).abs() < 1e-5) | (m.gen.isna() & m.gen_islem_yonunde.isna())).all()
    esik_ok = ((m.port_dd_ath <= ATH_ESIK) == (m.port_dd_ath_ref <= ATH_ESIK)).all()
    gen_sinif_ok = ((m.gen == GENISLIK_ESIK) == (m.gen_islem_yonunde == GENISLIK_ESIK)).all()
    ok = len(m) == 936 and dd_fark < 1e-5 and gen_ok and esik_ok and gen_sinif_ok
    print(f"öz-test: eşleşen {len(m)}/936 · port_dd_ath en büyük fark {dd_fark:.2e} · "
          f"gen (±1e-5) {gen_ok} · ATH sınıfı birebir {esik_ok} · 7/7 sınıfı birebir {gen_sinif_ok} → {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dogrula", action="store_true")
    ap.add_argument("--rapor", action="store_true")
    ap.add_argument("--islemler")
    ap.add_argument("--veri", default=os.path.join(KOK, "data"))
    a = ap.parse_args()
    if a.dogrula:
        sys.exit(0 if dogrula() else 1)
    if a.islemler:
        defter_guncelle(a.islemler, a.veri)
    if a.rapor:
        rapor()
