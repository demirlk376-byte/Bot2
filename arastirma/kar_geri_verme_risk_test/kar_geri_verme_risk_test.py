"""
kar_geri_verme_risk_test.py — JOINT_EXHAUSTION_HALF_RISK: TEK varyantın gerçek ikiz replay'i ve kıyası.

Varyant (yalnız DONCHIAN): port_dd_ath <= 0.02 VE gen_islem_yonunde == 1.0 ise risk × 0.50, değilse × 1.00.
Tanımlar post_peak_diagnostic §7'den AYNEN; yeni eşik/özellik yok.

Uygulama: production dosyaları DİSKTE DEĞİŞMEZ. Bu süreç içinde:
  · ExecutionEngine.enforce_daily_loss sarılır → her yeni saatte varyantın KENDİ hesap değeri
    (executor.current_equity) o saat işaretine kaydedilir (ATH serisi buradan).
  · ExecutionEngine.execute_signal sarılır → Donchian sinyalinde V(T)=current_equity(),
    ATH(T)=max(kayıtlı işaretler < T, V(T)), port_dd_ath = 1 − V/ATH; genişlik T−1h ve T−25h
    kapanışlarından; çarpan belirlenir ve kaydedilir.
  · RiskManager.build_trade_setup_from_levels sarılır → risk_pct_override × çarpan (gerçek boyutlama).

Kullanım (repo kökünden):
  python3 arastirma/kar_geri_verme_risk_test/kar_geri_verme_risk_test.py --kos     # varyant replay (~20 dk)
  python3 arastirma/kar_geri_verme_risk_test/kar_geri_verme_risk_test.py --analiz  # kıyas + rapor verileri

PROFIT GIVEBACK RATIO — sonuçlar görülmeden SABİTLENDİ (değiştirme):
  Saatlik hesap değerinde düşüş epizodu = ATH'den, ATH yeniden aşılana kadar.
  Derinliği ≥ %5 olan epizodlar sayılır (e = 1..k, zaman sırasıyla).
  P_e = epizod tepesi, Tr_e = epizod dibi,
  B_e = önceki sayılan epizodun tepesi ile P_e arasındaki EN DÜŞÜK hesap değeri
        (ilk epizod için başlangıçtan P_e'ye kadarki en düşük değer).
  PGR = Σ_e ln(P_e / Tr_e)  /  Σ_e ln(P_e / B_e)
  = "run-up'larda log cinsinden kazanılanın ne kadarı ardından gelen düşüşte geri verildi".
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sqlite3
import sys
from datetime import timezone

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)
sys.path.insert(0, os.path.join(KOK, "arastirma", "kar_geri_verme"))

VARYANT = "JOINT_EXHAUSTION_HALF_RISK"
CARPAN_YARI = 0.50
ATH_ESIK = 0.02
GENISLIK_ESIK = 1.0
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
H = pd.Timedelta("1h")
BOLME = pd.Timestamp("2025-01-01", tz="UTC")
PGR_MIN_DERINLIK = 0.05
SCR = os.environ.get("KGV_SCRATCH", "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/kgv_risk")
DB = os.path.join(SCR, "ikiz_varyant.db")
KARAR_CSV = os.path.join(BURA, "varyant_donchian_kararlari.csv")
ISLEM_CSV = os.path.join(BURA, "varyant_islemler.csv")


# ─────────────────── varyant replay ───────────────────
def _kapanislar():
    out = {}
    for c in DONCH:
        b = pd.read_csv(os.path.join(KOK, "data", f"{c}_fut_1h.csv"))
        b["ts"] = pd.to_datetime(b.ts, utc=True)
        out[c] = b.drop_duplicates("ts").set_index("ts").sort_index().close
    return out


def _kapanis_T(s, T, geri=0):
    x = s.loc[:T - pd.Timedelta(hours=geri) - H]
    return float(x.iat[-1]) if len(x) else np.nan


def genislik(kap, T, yon):
    """Dondurulmuş gen_islem_yonunde: 7 coinde sign(close(T)/close(T−24h) − 1) == yön oranı."""
    ayni = []
    for c in DONCH:
        rr = _kapanis_T(kap[c], T) / _kapanis_T(kap[c], T, 24) - 1
        if np.isfinite(rr):
            ayni.append(float(np.sign(rr) == yon))
    return float(np.mean(ayni)) if len(ayni) == len(DONCH) else np.nan


class VaryantDefter:
    """Varyantın KENDİ işlemlerinden (replay DB) dondurulmuş formülle V(T) ve ATH(T).

    İlk deneme executor.current_equity()'yi saat başında kaydediyordu; bu değer kapanış/açılış
    ara durumlarında geçici sıçrıyor (ör. 2025-09-22 01:00'da 1.88×) ve ATH'yi bozuyordu.
    Artık post_peak_diagnostic §7 formülü aynen: V = 10000 + Σ kapalı pnl − Σ açık giriş ücreti
    + Σ açık fiyat PnL (ts ≤ T−1h kapanışı); açık = giriş < T ve ekonomik çıkış > T;
    ATH = max(saatlik değer işaretleri < T, V(T)). Ekonomik çıkış = kar_geri_verme bar simülasyonu.
    """
    def __init__(self, db, emule=False):
        import kar_geri_verme as K
        self.emule = emule
        self.K = K; self.db = db
        coinler = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "XLM", "LTC", "TRX"]
        self.px = K.fiyatlar(coinler)
        self.isaret = pd.date_range("2023-04-06", "2026-07-21", freq="h", tz="UTC")
        self.kap = {}
        for c in coinler:
            x = self.px[c].close.copy(); x.index = x.index + H
            self.kap[c] = x.reindex(self.isaret).ffill().values
        self.cikis = {}                                # işlem id → ekonomik çıkış işareti

    def _islemler(self, T):
        c = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=30)
        d = pd.read_sql("SELECT id, symbol, side, entry_price, exit_price, sl_price, quantity, entry_time, "
                        "exit_time, pnl_usdt, strategy_scores FROM trades", c)
        c.close()
        d["giris"] = pd.to_datetime(d.entry_time, utc=True)
        d = d[d.giris < T].copy()
        if d.empty:
            return d
        sc = d.strategy_scores.map(json.loads)
        d["coin"] = d.symbol.str.split("/").str[0]
        d["yon"] = np.where(d.side == "long", 1.0, -1.0)
        d["niyet"] = sc.map(lambda s: s["intended_entry"]); d["sl0"] = sc.map(lambda s: s["sl0"])
        d["kol"] = sc.map(lambda s: s.get("strategy", "?"))
        d["max_hold"] = sc.map(lambda s: s.get("max_hold", 48))
        d["risk0"] = (d.niyet - d.sl0).abs()
        d["ucret_giris"] = sc.map(lambda s: s["entry_fee_rate"]) * d.entry_price * d.quantity
        if self.emule:                                   # test: çalışma anı gecikmesini taklit et
            gec = pd.to_datetime(d.exit_time, utc=True) >= T
            d.loc[gec, ["exit_time", "exit_price", "pnl_usdt"]] = None
        kap = d[d.exit_time.notna() & ~d.id.isin(self.cikis)]
        if len(kap):
            s = self.K.cikis_simule(kap.copy(), self.px)
            self.cikis.update(dict(zip(s.id, s.cikis_isaret)))
        d["cikis_isaret"] = d.id.map(self.cikis)
        d.loc[d.exit_time.isna(), "cikis_isaret"] = pd.NaT
        # İkiz aynı saatin barlarını coin coin işler: T anında DB'de "açık" görünen bir pozisyonun
        # stop/hedefi T−1h barında (ya da öncesinde) zaten değmiş olabilir. Dondurulmuş formül ekonomik
        # çıkışı kullanır; burada YALNIZ ts ≤ T−1h barlarıyla (ileriye bakmadan) aynı çıkışı kurarız.
        for i in d.index[d.exit_time.isna()]:
            t = d.loc[i]; b = self.px[t.coin]
            i0 = b.index.get_indexer([t.giris])[0]
            son = min(i0 + int(t.max_hold) - 1, b.index.searchsorted(T - H, side="right") - 1)
            rr = {"donchian": 2.5, "squeeze": 2.5, "mean_rev": 5.0 / 3.0}.get(t.kol, 2.5)
            tp = t.niyet + t.yon * rr * t.risk0
            cik = None
            for j in range(i0, son + 1):
                hi, lo = b.high.iat[j], b.low.iat[j]
                if (lo <= t.sl_price) if t.yon > 0 else (hi >= t.sl_price):
                    cik = (j, t.sl_price * (1 - t.yon * 0.24e-4)); break
                if (hi >= tp) if t.yon > 0 else (lo <= tp):
                    cik = (j, tp); break
            if cik is None and son == i0 + int(t.max_hold) - 1 and son >= i0:
                cik = (son, float(b.close.iat[son]))
            if cik is not None:
                j, px_c = cik
                d.loc[i, "cikis_isaret"] = b.index[j] + H
                d.loc[i, "pnl_usdt"] = (t.yon * (px_c - t.entry_price) * t.quantity - t.ucret_giris
                                        - self.K.CIKIS_UCRET * px_c * t.quantity)
        return d

    def dd(self, T):
        d = self._islemler(T)
        n = self.isaret.get_indexer([T])[0]
        v = np.full(n + 1, 10_000.0)                   # işaretler [bas .. T]
        for t in d.itertuples():
            a = self.isaret.get_indexer([t.giris])[0]
            b = self.isaret.get_indexer([t.cikis_isaret])[0] if pd.notna(t.cikis_isaret) else n + 1
            b = min(b, n + 1)
            p = self.kap[t.coin][a:b]
            v[a:b] += t.yon * (p - t.entry_price) * t.quantity - t.ucret_giris
            if b <= n:
                v[b:] += t.pnl_usdt
        V = float(v[n]); ath = max(float(v[:n].max()) if n > 0 else V, V)
        return 1 - V / ath, V, ath


async def replay():
    os.makedirs(SCR, exist_ok=True)
    for x in (DB, DB + "-wal", DB + "-shm"):
        if os.path.exists(x):
            os.remove(x)
    os.environ.setdefault("PAPER_SLIP_GIRIS_BP", "15.85")
    os.environ.setdefault("PAPER_SLIP_CIKIS_BP", "0.24")
    os.environ.setdefault("PAPER_FUNDING", "true")
    os.environ["REPLAY_DB"] = DB
    import execution as EX
    import risk as RK
    kap = _kapanislar()
    defter = VaryantDefter(DB)
    kararlar = []
    CARPAN = {"v": 1.0}

    _exe = EX.ExecutionEngine.execute_signal
    async def exe(self, signal, *a, **k):
        CARPAN["v"] = 1.0
        if getattr(signal, "dominant_strategy", "") == "donchian" and getattr(signal, "direction", 0) != 0:
            T = pd.Timestamp(EX.datetime.now(timezone.utc))
            dd, V, ath = defter.dd(T)
            gen = genislik(kap, T, int(signal.direction))
            ortak = bool(dd <= ATH_ESIK and gen == GENISLIK_ESIK)
            CARPAN["v"] = CARPAN_YARI if ortak else 1.0
            kararlar.append(dict(T=str(T), symbol=getattr(signal, "symbol", ""), yon=int(signal.direction),
                                 V=V, ATH=ath, port_dd_ath=dd, gen_islem_yonunde=gen, carpan=CARPAN["v"]))
        try:
            return await _exe(self, signal, *a, **k)
        finally:
            CARPAN["v"] = 1.0
    EX.ExecutionEngine.execute_signal = exe

    _lev = RK.RiskManager.build_trade_setup_from_levels
    def lev(self, *a, risk_pct_override=0.0, **k):
        if CARPAN["v"] != 1.0 and risk_pct_override > 0:
            risk_pct_override = risk_pct_override * CARPAN["v"]
        return _lev(self, *a, risk_pct_override=risk_pct_override, **k)
    RK.RiskManager.build_trade_setup_from_levels = lev

    from ikiz.kos import kur, sur
    M, saat, feed = await kur("2023-04-06", source="local")
    await sur(M, saat, feed, bitis="2026-07-19", ilerleme_her=20000)

    with open(KARAR_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(kararlar[0].keys())); w.writeheader(); w.writerows(kararlar)
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT symbol, side, entry_price, exit_price, sl_price, quantity, entry_time, exit_time, "
                    "pnl_usdt, exit_reason, strategy_scores FROM trades", c)
    c.close()
    d["kol"] = d.strategy_scores.map(lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))
    d.to_csv(ISLEM_CSV, index=False)
    print(f"varyant replay bitti: {len(d)} işlem ({int(d.exit_time.isna().sum())} açık), "
          f"{len(kararlar)} donchian kararı, {sum(k['carpan'] < 1 for k in kararlar)} × 0.50")


# ─────────────────── analiz ───────────────────
def kitap(yol):
    """kar_geri_verme yöntemiyle: ekonomik çıkış, saatlik hesap değeri, maliyetler (kapanmış işlemler)."""
    import kar_geri_verme as K
    d = pd.read_csv(yol)
    d = d[d.exit_time.notna() & d.pnl_usdt.notna()].copy()
    sc = d.strategy_scores.map(json.loads)
    d["coin"] = d.symbol.str.split("/").str[0]
    d["yon"] = np.where(d.side == "long", 1.0, -1.0)
    d["niyet"] = sc.map(lambda s: s["intended_entry"]); d["sl0"] = sc.map(lambda s: s["sl0"])
    d["ucret_giris_oran"] = sc.map(lambda s: s["entry_fee_rate"])
    d["max_hold"] = sc.map(lambda s: s.get("max_hold", 48))
    d["giris"] = pd.to_datetime(d.entry_time, utc=True)
    d["kayit_cikis"] = pd.to_datetime(d.exit_time, utc=True)
    d["risk0"] = (d.niyet - d.sl0).abs()
    d["R_net"] = d.pnl_usdt / (d.quantity * d.risk0)
    d["ucret_giris"] = d.ucret_giris_oran * d.entry_price * d.quantity
    d["ucret_cikis"] = K.CIKIS_UCRET * d.exit_price * d.quantity
    d["fiyat_pnl_cikis"] = d.yon * (d.exit_price - d.entry_price) * d.quantity
    d["kayma_usd"] = d.yon * (d.entry_price - d.niyet) * d.quantity + d.exit_price * d.quantity * 0.24e-4
    d = d.reset_index(drop=True)
    px = K.fiyatlar(d.coin.unique())
    d = K.cikis_simule(d, px)
    e = K.saatlik(d, px)
    return d, e


def epizodlar(e):
    v = e.hesap_degeri.values; z = e.zaman.values; n = len(v)
    out, i, tepe = [], 0, 0
    while i < n:
        if v[i] >= v[tepe]:
            tepe = i; i += 1; continue
        j = i
        while j < n and v[j] < v[tepe]:
            j += 1
        dip = tepe + int(np.argmin(v[tepe:j]))
        out.append(dict(tepe_i=tepe, dip_i=dip, geri_i=(j if j < n else None)))
        tepe = j if j < n else tepe; i = j
    for x in out:
        x.update(tepe_zaman=str(pd.Timestamp(z[x["tepe_i"]])), tepe=float(v[x["tepe_i"]]),
                 dip_zaman=str(pd.Timestamp(z[x["dip_i"]])), dip=float(v[x["dip_i"]]),
                 dusus_usd=float(v[x["dip_i"]] - v[x["tepe_i"]]),
                 dusus_yuzde=float(1 - v[x["dip_i"]] / v[x["tepe_i"]]),
                 ath_geri_zaman=(str(pd.Timestamp(z[x["geri_i"]])) if x["geri_i"] is not None else None),
                 ath_geri_gun=((pd.Timestamp(z[x["geri_i"]]) - pd.Timestamp(z[x["tepe_i"]])).total_seconds() / 86400
                               if x["geri_i"] is not None else None))
    return out


def pgr(e, epi):
    """Sabit formül (modül docstring'i)."""
    v = e.hesap_degeri.values
    say = [x for x in epi if x["dusus_yuzde"] >= PGR_MIN_DERINLIK]
    pay = payda = 0.0; onceki_tepe = 0
    for x in say:
        B = float(v[onceki_tepe:x["tepe_i"] + 1].min())
        pay += np.log(x["tepe"] / x["dip"]); payda += np.log(x["tepe"] / B)
        onceki_tepe = x["tepe_i"]
    return dict(pgr=float(pay / payda) if payda > 0 else None, epizod=len(say),
                geri_verilen_log=float(pay), kazanilan_log=float(payda))


def metrik(d, e, bas=None, bit=None):
    m = np.ones(len(e), bool)
    if bas is not None: m &= (e.zaman >= bas).values
    if bit is not None: m &= (e.zaman < bit).values
    ee = e[m].reset_index(drop=True)
    v = ee.hesap_degeri.values
    dd = 1 - v / np.maximum.accumulate(v); ddi = int(np.argmax(dd))
    tepe_i = int(np.argmax(v[:ddi + 1]))
    di = np.ones(len(d), bool)
    if bas is not None: di &= (d.giris >= bas).values
    if bit is not None: di &= (d.giris < bit).values
    dd_ = d[di]
    kaz = dd_.pnl_usdt[dd_.pnl_usdt > 0].sum(); kay = -dd_.pnl_usdt[dd_.pnl_usdt < 0].sum()
    ay = ee.set_index("zaman").hesap_degeri.resample("ME").last()
    ay_bas = pd.concat([pd.Series([v[0]]), ay.iloc[:-1].reset_index(drop=True)]).values
    ay_get = ay.values / ay_bas - 1
    return dict(bas_deger=float(v[0]), son_deger=float(v[-1]), getiri=float(v[-1] / v[0] - 1),
                net_pnl=float(dd_.pnl_usdt.sum()), maxdd=float(dd.max()),
                maxdd_usd=float(v[tepe_i] - v[ddi]), pf=float(kaz / kay) if kay else None,
                wr=float((dd_.pnl_usdt > 0).mean()), ort_R=float(dd_.R_net.mean()),
                en_kotu_ay=float(ay_get.min()), medyan_ay=float(np.median(ay_get)),
                pozitif_ay=float((ay_get > 0).mean()),
                ucret=float((dd_.ucret_giris + dd_.ucret_cikis).sum()), kayma=float(dd_.kayma_usd.sum()),
                islem=int(len(dd_)))


def analiz():
    bd, be = kitap(os.path.join(KOK, "ikiz_k25_cap25_islemler.csv"))
    vd, ve = kitap(ISLEM_CSV)
    kar = pd.read_csv(KARAR_CSV)
    kar["T"] = pd.to_datetime(kar["T"], utc=True)
    vd = vd.merge(kar[["T", "symbol", "carpan", "port_dd_ath", "gen_islem_yonunde"]]
                  .rename(columns={"T": "giris"}), on=["giris", "symbol"], how="left")
    vd["carpan"] = vd.carpan.fillna(1.0)
    sonuc = {}
    for ad, (d, e) in (("BASELINE", (bd, be)), (VARYANT, (vd, ve))):
        epi = epizodlar(e)
        sonuc[ad] = dict(HEPSI=metrik(d, e), TRAIN=metrik(d, e, bit=BOLME), TEST=metrik(d, e, bas=BOLME),
                         epizod_top5=sorted(epi, key=lambda x: -x["dusus_yuzde"])[:5], PGR=pgr(e, epi))
        for k in ("TRAIN", "TEST"):
            yol = pgr(e[(e.zaman < BOLME) if k == "TRAIN" else (e.zaman >= BOLME)].reset_index(drop=True),
                      epizodlar(e[(e.zaman < BOLME) if k == "TRAIN" else (e.zaman >= BOLME)].reset_index(drop=True)))
            sonuc[ad][k]["PGR"] = yol["pgr"]
    yari = vd[vd.carpan < 1]
    sonuc["yari_risk_sayisi"] = dict(toplam=int(len(yari)), TRAIN=int((yari.giris < BOLME).sum()),
                                     TEST=int((yari.giris >= BOLME).sum()))
    # yarı riskli işlemlerin anatomisi (baseline'daki karşılıkları üzerinden)
    k = ["symbol", "side", "giris"]
    bm = bd.merge(yari[k], on=k)
    top_kayip = -bd.pnl_usdt[bd.pnl_usdt < 0].sum()
    sonuc["yari_risk_anatomi"] = dict(
        baseline_eslesen=int(len(bm)), baseline_ort_R=float(bm.R_net.mean()) if len(bm) else None,
        long=int((yari.side == "long").sum()), short=int((yari.side == "short").sum()),
        coin=yari.coin.value_counts().to_dict(), cikis=yari.sim_tip.value_counts().to_dict(),
        varyant_ort_R=float(yari.R_net.mean()) if len(yari) else None,
        baseline_toplam_kaybin_payi=float(-bm.pnl_usdt[bm.pnl_usdt < 0].sum() / top_kayip) if len(bm) else None,
        baseline_pnl=float(bm.pnl_usdt.sum()))
    # işlem listesi farkları
    m = bd[k + ["kol", "pnl_usdt"]].merge(vd[k + ["kol", "pnl_usdt"]], on=k, how="outer",
                                          suffixes=("_b", "_v"), indicator=True)
    fark = m[m._merge != "both"].copy()
    fark["taraf"] = fark._merge.map({"left_only": "yalniz_baseline", "right_only": "yalniz_varyant"})
    fark[["taraf"] + k + ["kol_b", "kol_v"]].to_csv(os.path.join(BURA, "islem_farklari.csv"), index=False)
    sonuc["islem_farki"] = dict(yalniz_baseline=int((m._merge == "left_only").sum()),
                                yalniz_varyant=int((m._merge == "right_only").sum()),
                                ortak=int((m._merge == "both").sum()))
    ep = []
    for ad in ("BASELINE", VARYANT):
        for i, x in enumerate(sonuc[ad]["epizod_top5"], 1):
            ep.append(dict(kosu=ad, sira=i, **{kk: x[kk] for kk in ("tepe_zaman", "tepe", "dip_zaman", "dip",
                                                                     "dusus_usd", "dusus_yuzde", "ath_geri_zaman",
                                                                     "ath_geri_gun")}))
    pd.DataFrame(ep).to_csv(os.path.join(BURA, "epizodlar_top5.csv"), index=False)
    with open(os.path.join(BURA, "sonuclar.json"), "w") as f:
        json.dump(sonuc, f, indent=1, default=str, ensure_ascii=False)
    print(json.dumps({a: {kk: sonuc[a]["HEPSI"][kk] for kk in ("son_deger", "maxdd")} for a in ("BASELINE", VARYANT)}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kos", action="store_true")
    ap.add_argument("--analiz", action="store_true")
    a = ap.parse_args()
    if a.kos:
        asyncio.run(replay())
        sys.stdout.flush(); os._exit(0)                 # aiosqlite thread'i süreci asılı tutmasın
    if a.analiz:
        analiz()
