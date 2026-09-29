"""
top_trader_analizi.py — Hyperliquid lider traderlarının GERÇEK dolumlarından strateji analizi +
"bota eklenebilir mi" testi. SALT OKUR (yalnız halka açık Hyperliquid info API'si; anahtar yok,
emir yok, .env okunmaz, bota dokunmaz). Veri /tmp/top_trader/ altına yazılır.

NEDEN HYPERLIQUID: Binance/MEXC lider tabloları yalnız özet ve seçilmiş pozisyon gösterir. Hyperliquid'de
her dolum zincir üstünde ve herkese açıktır → "hangi durumda hangi işlemi açıyorlar" gerçek veriden
ölçülebilir.

VPS'te:
  cd /opt/bot2 && git pull
  venv/bin/python arastirma/top_trader_analizi/top_trader_analizi.py --indir     # ~5-15 dk
  venv/bin/python arastirma/top_trader_analizi/top_trader_analizi.py            # analiz + hüküm

ÖNCEDEN SABİT KURALLAR (sonuçtan önce; TOP_TRADER_RAPORU.md):
  Evren: lider tablosu, hesap değeri ≥ $100k, AY ve TÜM ZAMAN PnL > 0 → aylık PnL'ye göre ilk 40.
  Tip (dolumlardan): HFT/piyasa yapıcı = günde > 150 dolum VEYA (maker payı ≥ %60 ve medyan tutuş < 1 sa);
                     gün içi = medyan tutuş < 24 sa; swing = ≥ 24 sa.
  "Hangi durumda hangi işlem" (yön alan traderlar, bizim 11 coinimiz): giriş anındaki bağlam, giriş
    ANINDAN ÖNCE KAPANMIŞ 4h mumlardan: trend (EMA200'e göre), Donchian-40 kırılımı, 24s momentum yönü,
    RSI14 bölgesi, oynaklık dilimi. Her bağlamda işlem sayısı, kazanma oranı, ort. PnL.
  Entegrasyon testi (seçim yanlılığına karşı ZAMAN BÖLMELİ):
    Her trader'ın dolum geçmişi zamanda ikiye bölünür (medyan zaman). Trader'lar İLK yarıdaki
    gerçekleşmiş PnL'ye göre seçilir (>0). Sinyal yalnız İKİNCİ yarıda ölçülür:
      S = seçili yön alan traderların bir 4h barda AÇTIĞI yeni pozisyonların net yönü (coin başına)
      çıktı = sonraki 24 saatlik getiri, S yönünde, bizim maliyetimiz düşülmüş (2×(15.85+1) bp)
    Karar: n(olay) < 50 → D; hafta-kümeli %95 GA tamamen > 0 → A (ikiz testine aday);
           ortalama > 0 ama GA 0'ı içeriyor → B; ortalama ≤ 0 → C.
    Ayrıca: bizim Donchian kırılım barlarında (Donchian-40 + EMA200, HL 4h mumlarıyla) top-trader
    yönü AYNI olanlar vs olmayanlar — yalnız betimsel.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

VERI = os.environ.get("TT_DIR", "/tmp/top_trader")
INFO = "https://api.hyperliquid.xyz/info"
LB = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
BIZIM = ("SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "XLM", "LTC")
N_TOP = 40
MIN_DEGER = 100_000
HFT_DOLUM_GUN = 150
MAKER_ESIK, HFT_TUTUS_SA = 0.60, 1.0
GUNICI_SA = 24.0
MALIYET_BP = 2 * (15.85 + 1.0)
UFUK_SA = 24
N_BOOT, TOHUM = 5000, 20260929
MIN_OLAY = 50


# ─────────────────────────── indirme (VPS) ───────────────────────────
def _post(S, body, deneme=5):
    for k in range(deneme):
        try:
            r = S.post(INFO, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** k); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(2 ** k)
    return None


def indir():
    import requests
    os.makedirs(VERI, exist_ok=True)
    S = requests.Session()
    S.headers.update({"User-Agent": "bot2-research/1.0", "Content-Type": "application/json"})
    lb = S.get(LB, timeout=60).json()
    rows = lb.get("leaderboardRows", lb if isinstance(lb, list) else [])
    tab = []
    for r in rows:
        wp = {w[0]: w[1] for w in r.get("windowPerformances", [])}
        tab.append(dict(adres=r.get("ethAddress"), ad=r.get("displayName"),
                        deger=float(r.get("accountValue") or 0),
                        pnl_ay=float(wp.get("month", {}).get("pnl") or 0),
                        roi_ay=float(wp.get("month", {}).get("roi") or 0),
                        pnl_tum=float(wp.get("allTime", {}).get("pnl") or 0),
                        hacim_ay=float(wp.get("month", {}).get("vlm") or 0)))
    tab = pd.DataFrame(tab)
    tab.to_csv(os.path.join(VERI, "lider_tablosu.csv"), index=False)
    sec = tab[(tab.deger >= MIN_DEGER) & (tab.pnl_ay > 0) & (tab.pnl_tum > 0)].nlargest(N_TOP, "pnl_ay")
    sec.to_csv(os.path.join(VERI, "secilen.csv"), index=False)
    print(f"lider tablosu {len(tab)} satır → seçilen {len(sec)}", flush=True)
    simdi = int(time.time() * 1000)
    for i, a in enumerate(sec.adres):
        dolum, bas_ms = [], 0
        for _ in range(8):                  # yanıt ≤ 2000 dolum; API yalnız son ~10k dolumu tutar
            b = _post(S, {"type": "userFillsByTime", "user": a, "startTime": bas_ms, "endTime": simdi})
            if not b:
                break
            dolum += b
            son = max(int(x["time"]) for x in b)
            if len(b) < 2000 or son + 1 <= bas_ms:
                break
            bas_ms = son + 1                # ileri sayfalama (yanıt başlangıçtan itibaren döner)
            time.sleep(0.3)
        with open(os.path.join(VERI, f"dolum_{a}.json"), "w") as f:
            json.dump(dolum, f)
        print(f"  [{i + 1}/{len(sec)}] {a[:10]}… {len(dolum)} dolum", flush=True)
        time.sleep(0.3)
    bas = simdi - 400 * 86400 * 1000
    for c in BIZIM:
        m = _post(S, {"type": "candleSnapshot", "req": {"coin": c, "interval": "4h",
                                                          "startTime": bas, "endTime": simdi}})
        with open(os.path.join(VERI, f"mum4h_{c}.json"), "w") as f:
            json.dump(m or [], f)
        print(f"  mum {c}: {len(m or [])}", flush=True)
        time.sleep(0.3)


# ─────────────────────────── analiz ───────────────────────────
def dolum_df(a):
    y = os.path.join(VERI, f"dolum_{a}.json")
    if not os.path.exists(y):
        return pd.DataFrame()
    d = pd.DataFrame(json.load(open(y)))
    if d.empty:
        return d
    d = d.drop_duplicates(subset=[c for c in ("tid", "hash", "oid", "time", "px", "sz") if c in d.columns])
    d = d[~d["coin"].astype(str).str.startswith("@")]          # spot/diğer
    for c in ("px", "sz", "closedPnl", "fee", "startPosition"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d["t"] = pd.to_datetime(d["time"].astype("int64"), unit="ms", utc=True)
    d["isaret"] = np.where(d["side"] == "B", 1.0, -1.0)
    d["maker"] = ~d.get("crossed", pd.Series(True, index=d.index)).astype(bool)
    return d.sort_values("t").reset_index(drop=True)


def islemlere(d):
    """Coin başına net pozisyon yolu → tur (0'dan açılıp 0'a/ters yöne dönen) işlemler."""
    out = []
    for c, g in d.groupby("coin"):
        poz, acik = None, None
        for r in g.itertuples():
            once = r.startPosition if np.isfinite(r.startPosition) else (poz or 0.0)
            sonra = once + r.isaret * r.sz
            if acik is None and abs(once) < 1e-12 and abs(sonra) > 1e-12:
                acik = dict(coin=c, yon=int(np.sign(sonra)), giris=r.t, giris_px=r.px, pnl=0.0,
                            ucret=0.0, not_max=0.0, n=0)
            if acik is not None:
                acik["pnl"] += (r.closedPnl or 0.0)
                acik["ucret"] += (r.fee or 0.0)
                acik["not_max"] = max(acik["not_max"], abs(sonra) * r.px)
                acik["n"] += 1
                if abs(sonra) < 1e-12 or np.sign(sonra) != acik["yon"]:
                    acik.update(cikis=r.t, cikis_px=r.px)
                    out.append(acik)
                    acik = None
                    if abs(sonra) > 1e-12:              # ters yöne dönüş = yeni işlem
                        acik = dict(coin=c, yon=int(np.sign(sonra)), giris=r.t, giris_px=r.px,
                                    pnl=0.0, ucret=0.0, not_max=abs(sonra) * r.px, n=1)
            poz = sonra
    t = pd.DataFrame(out)
    if len(t):
        t["tutus_sa"] = (t.cikis - t.giris).dt.total_seconds() / 3600
        t["net"] = t.pnl - t.ucret
    return t


def profil(a, d, t):
    gun = max((d.t.max() - d.t.min()).total_seconds() / 86400, 1e-9)
    ayni_dk = 0
    for c, g in d.groupby("coin"):
        s = g.set_index("t")["isaret"]
        ayni_dk += int((s.rolling("60s").apply(lambda x: (x.min() < 0) & (x.max() > 0), raw=True) > 0).sum())
    dolum_gun = len(d) / gun
    maker = float(d.maker.mean())
    tut = float(t.tutus_sa.median()) if len(t) else float("nan")
    if dolum_gun > HFT_DOLUM_GUN or (maker >= MAKER_ESIK and tut < HFT_TUTUS_SA):
        tip = "HFT/piyasa yapıcı"
    elif tut < GUNICI_SA:
        tip = "gün içi"
    else:
        tip = "swing/trend"
    kc = d.groupby("coin").apply(lambda g: (g.px * g.sz).sum()).sort_values(ascending=False)
    return dict(adres=a, gun=gun, dolum=len(d), dolum_gun=dolum_gun, maker_pay=maker,
                iki_yon_60sn_pay=ayni_dk / max(len(d), 1), medyan_tutus_sa=tut, islem=len(t),
                kazanma=float((t.net > 0).mean()) if len(t) else float("nan"),
                net_pnl=float((d.closedPnl - d.fee).sum()),
                bizim_coin_payi=float(kc[kc.index.isin(BIZIM)].sum() / kc.sum()) if kc.sum() > 0 else 0.0,
                en_cok=",".join(kc.index[:4]), tip=tip)


def mumlar(c):
    y = os.path.join(VERI, f"mum4h_{c}.json")
    if not os.path.exists(y):
        return None
    m = pd.DataFrame(json.load(open(y)))
    if m.empty:
        return None
    m["t"] = pd.to_datetime(m["t"].astype("int64"), unit="ms", utc=True)
    for k in ("o", "h", "l", "c", "v"):
        m[k] = pd.to_numeric(m[k])
    m = m.set_index("t").sort_index()
    m["ema200"] = m.c.ewm(span=200, adjust=False).mean()
    m["don_h"] = m.h.shift(1).rolling(40).max()
    m["don_l"] = m.l.shift(1).rolling(40).min()
    d = m.c.diff()
    m["rsi"] = 100 - 100 / (1 + d.clip(lower=0).rolling(14).mean() / (-d.clip(upper=0)).rolling(14).mean())
    tr = pd.concat([m.h - m.l, (m.h - m.c.shift()).abs(), (m.l - m.c.shift()).abs()], axis=1).max(axis=1)
    m["atr_pct"] = tr.rolling(14).mean() / m.c
    m["ret24"] = m.c / m.c.shift(6) - 1
    m["kapanis"] = m.index + pd.Timedelta(hours=4)
    return m


def baglam(t, M):
    """Girişten ÖNCE kapanmış son 4h mum (kapanış ≤ giriş) — ileriye bakmaz."""
    sat = []
    for r in t.itertuples():
        m = M.get(r.coin)
        if m is None:
            sat.append(None); continue
        k = m[m.kapanis <= r.giris]
        if len(k) < 210:
            sat.append(None); continue
        b = k.iloc[-1]
        y = r.yon
        sat.append(dict(
            trend="trend yönünde" if np.sign(b.c - b.ema200) == y else "trende karşı",
            kirilim=("Donchian kırılımı" if (y > 0 and b.c > b.don_h) or (y < 0 and b.c < b.don_l)
                     else "kırılım yok"),
            momentum="24s momentumla" if np.sign(b.ret24) == y else "24s momentuma karşı (dönüş)",
            rsi=("aşırı alım" if b.rsi > 70 else "aşırı satım" if b.rsi < 30 else "nötr"),
            atr=b.atr_pct))
    return sat


def hafta_ga(x, t):
    x = np.asarray(x, float)
    wk = pd.Series(t).dt.tz_convert(None).dt.to_period("W").astype(str).to_numpy()
    gruplar = [x[wk == w] for w in np.unique(wk)]
    rng = np.random.default_rng(TOHUM)
    o = [np.concatenate([gruplar[i] for i in rng.integers(0, len(gruplar), len(gruplar))]).mean()
         for _ in range(N_BOOT)]
    return float(np.percentile(o, 2.5)), float(np.percentile(o, 97.5)), len(gruplar)


def analiz():
    sec = pd.read_csv(os.path.join(VERI, "secilen.csv"))
    M = {c: mumlar(c) for c in BIZIM}
    prof, tum_islem, dolumlar = [], [], {}
    for a in sec.adres:
        d = dolum_df(a)
        if d.empty:
            continue
        t = islemlere(d)
        p = profil(a, d, t)
        prof.append(p)
        dolumlar[a] = (d, p)
        if len(t):
            t["adres"] = a; t["tip"] = p["tip"]
            tum_islem.append(t)
    P = pd.DataFrame(prof)
    P.to_csv(os.path.join(VERI, "trader_profilleri.csv"), index=False)
    print("== 1) TRADER TİPLERİ (lider tablosu: değer ≥ $100k, ay+tüm PnL > 0, aylık PnL ilk "
          f"{N_TOP}; dolum verisi olan {len(P)})")
    print(P.tip.value_counts().to_string())
    print(P[["adres", "tip", "dolum_gun", "maker_pay", "iki_yon_60sn_pay", "medyan_tutus_sa", "islem",
             "kazanma", "net_pnl", "bizim_coin_payi", "en_cok"]].round(3).to_string(index=False))

    T = pd.concat(tum_islem) if tum_islem else pd.DataFrame()
    Y = T[(T.tip != "HFT/piyasa yapıcı") & T.coin.isin(BIZIM)].copy() if len(T) else T
    print(f"\n== 2) YÖN ALAN TRADERLAR — bizim coinlerde {len(Y)} tur işlem")
    if len(Y):
        b = baglam(Y, M)
        ok = [x is not None for x in b]
        Y = Y[ok].copy()
        B = pd.DataFrame([x for x in b if x is not None], index=Y.index)
        Y = pd.concat([Y, B], axis=1)
        Y.to_csv(os.path.join(VERI, "yon_alan_islemler.csv"), index=False)
        for k in ("trend", "kirilim", "momentum", "rsi"):
            g = Y.groupby(k).agg(n=("net", "size"), kazanma=("net", lambda s: (s > 0).mean()),
                                 ort_net_usd=("net", "mean"), medyan_tutus_sa=("tutus_sa", "median"))
            print(f"\n  [{k}]\n" + g.round(3).to_string())
        print("\n  yön: long", int((Y.yon > 0).sum()), "short", int((Y.yon < 0).sum()),
              "· medyan tutuş", round(float(Y.tutus_sa.median()), 1), "sa")

    # ── 3) entegrasyon testi (zaman bölmeli) ──
    olay = []
    for a, (d, p) in dolumlar.items():
        if p["tip"] == "HFT/piyasa yapıcı":
            continue
        orta = d.t.quantile(0.5)
        ilk = d[d.t < orta]
        if float((ilk.closedPnl - ilk.fee).sum()) <= 0:          # ilk yarıda kârlı değilse seçilmez
            continue
        t = islemlere(d[d.t >= orta])
        if not len(t):
            continue
        t = t[t.coin.isin(BIZIM)]
        for r in t.itertuples():
            m = M.get(r.coin)
            if m is None:
                continue
            k = m[m.kapanis > r.giris]                            # giriş SONRASI ilk kapanış
            if len(k) < UFUK_SA // 4 + 1:
                continue
            p0 = k.c.iloc[0]; p1 = k.c.iloc[UFUK_SA // 4]
            olay.append(dict(t=k.index[0], coin=r.coin, yon=r.yon, adres=a,
                             getiri_bp=r.yon * (p1 / p0 - 1) * 1e4 - MALIYET_BP))
    O = pd.DataFrame(olay)
    print(f"\n== 3) ENTEGRASYON TESTİ (seçim ilk yarıda, ölçüm ikinci yarıda; maliyet {MALIYET_BP:.1f}bp)")
    if len(O) < MIN_OLAY:
        hukum = "D"
        print(f"  olay {len(O)} < {MIN_OLAY} → yetersiz")
        ga = (np.nan, np.nan, 0)
    else:
        O = O.groupby(["t", "coin"]).agg(yon=("yon", lambda s: np.sign(s.sum())),
                                         getiri_bp=("getiri_bp", "mean")).reset_index()
        O = O[O.yon != 0]
        ga = hafta_ga(O.getiri_bp, O.t)
        ort = float(O.getiri_bp.mean())
        hukum = "A" if ga[0] > 0 else ("B" if ort > 0 else "C")
        print(f"  bar-coin olayı {len(O)} · ort {ort:+.1f}bp (sonraki {UFUK_SA}s, yönde, maliyet sonrası) · "
              f"hafta-kümeli %95 GA [{ga[0]:+.1f}, {ga[1]:+.1f}] ({ga[2]} hafta)")
        O.to_csv(os.path.join(VERI, "entegrasyon_olaylari.csv"), index=False)
    print("\n" + "=" * 60)
    print("TRADER TİPLERİ:", P.tip.value_counts().to_dict() if len(P) else {})
    print(f"ENTEGRASYON HÜKMÜ: {hukum}  (A = ikiz testine aday · B = işaret var, kanıt yetersiz · "
          "C = işe yaramıyor · D = veri yetersiz)")
    return hukum


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--indir", action="store_true")
    a = ap.parse_args()
    indir() if a.indir else analiz()
