"""
fpb_kos.py — FAILED_PULLBACK_V1 için TEK ikiz koşusu (gerçek kronolojik replay).

Mevcut ikizi (ikiz/kos.py: kur + sur → gerçek main.on_candle_close, gerçek
ExecutionEngine, gerçek PaperExchange dolumları) AYNEN kullanır. Aday için ikinci
bir simülatör YOK: aday sinyali executor.execute_signal'e verilir; dolum, ücret,
kayma, stop/hedef ve max-hold PaperExchange + main'in kendi yollarından geçer.
Production dosyaları DEĞİŞMEZ; kancalar yalnız bu sürecin belleğinde.

MOD:
  A   : mevcut bot, değişiklik yok (RISK_SCALE=1.75 — CANLI_ENV). Aday yalnız GÖZLENİR.
  A75 : A'nın işlem riskleri x0.75 (RISK_SCALE=1.3125; tüm kolların risk%'i bununla çarpılır).
  B   : A75 + aday (risk_haritasi.json; A'daki min kol riskinin %25'i).
  S   : aday TEK BAŞINA; bot kollarının sinyalleri yürütülmez. Sabit risk birimi:
        her işlem başlangıç sermayesinin (10.000) %1'i = 100 USDT hedef risk.

Kancalar (yalnız aday pozisyonlarına etki eder; A'da hiçbir şeye dokunmaz):
  1) _fire_callbacks (1h): aday durumu beslemenin KAPANMIŞ mumlarıyla güncellenir.
     Bir damgadaki SON sembolün işleyicisi bittikten sonra (tüm bot kolları o damga
     için çalışmışken) kuyruktaki aday sinyalleri SEMBOL ADINA göre sırayla denenir
     → aynı anda bot sinyali ÖNCELİKLİ. Ardından ortak saatlik özsermaye kaydı.
  2) build_trade_setup_from_levels: aday çağrısında risk_pct_override = harita değeri.
  3) Portfolio.create_position: aday pozisyonuna max_hold=12 (1h mum) yazılır →
     main._enforce_max_hold q+12 kapanışında (= q+13 açılışı) piyasa çıkışı yapar.
  4) PaperExchange.check_sl_tp: aday pozisyonunda mum STOPUN ÖTESİNDE AÇILDIYSA
     stop fiyatından değil AÇILIŞTAN (kayma dahil) kapatılır ("sl_gap").
     Aynı mumda stop+hedef: PaperExchange zaten stopu önce alır (işaretleme analizde).
  5) (isteğe bağlı) ADAY_CIKIS_SLIP_BP: aday stop/zaman çıkışlarına ayrı kayma (stres).

Ortam:
  AD, MOD (A|A75|B|S), SLIP_KAT (1|2: giriş 15.85bp ve çıkış 0.24bp kaymasının katı),
  FIX_FUNDING (0|1; 1 = gerçek funding, Binance vekil verisi), ADAY_CIKIS_SLIP_BP.
Çıktı (cwd): {AD}_islemler.csv, {AD}_aday_sinyaller.csv, {AD}_aday_olaylar.csv.gz,
             {AD}_ozsermaye.csv.gz, {AD}_ozet.json
"""
import os
import sys

# ⚠ Maliyet ortamı exchange İMPORTUNDAN ÖNCE (sınıf öznitelikleri importta okunur)
MOD = os.environ["MOD"]
AD = os.environ["AD"]
KAT = float(os.environ.get("SLIP_KAT", "1"))
TABAN_GIRIS_BP, TABAN_CIKIS_BP = 15.85, 0.24          # 936-işlem referansının maliyeti
os.environ["PAPER_SLIP_GIRIS_BP"] = repr(TABAN_GIRIS_BP * KAT)
os.environ["PAPER_SLIP_CIKIS_BP"] = repr(TABAN_CIKIS_BP * KAT)
os.environ["PAPER_FUNDING"] = "true"                   # referansla aynı (düzeltmesiz = fiilen 0)
os.environ["DONCHIAN_MAKER_ENTRY"] = "false"
os.environ["RISK_SCALE"] = {"A": "1.75", "A75": "1.3125", "B": "1.3125", "S": "1.75"}[MOD]
FIX_FUNDING = os.environ.get("FIX_FUNDING", "0") == "1"
ADAY_CIKIS = os.environ.get("ADAY_CIKIS_SLIP_BP")

import asyncio  # noqa: E402
import csv  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

logging.basicConfig(level=logging.ERROR)
BURA = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(BURA))
sys.path.insert(0, KOK)
sys.path.insert(0, BURA)
import numpy as np  # noqa: E402
import fast_bt  # noqa: E402
import fpb_aday as F  # noqa: E402

fast_bt.CACHE_DIR = os.path.join(KOK, "data")
CIKTI = os.getcwd()
BITIS = os.environ.get("BITIS", "2026-07-19")
S_SABIT_BAKIYE, S_RISK = 10_000.0, 0.01


def risk_haritasi():
    with open(os.path.join(BURA, "risk_haritasi.json")) as f:
        h = json.load(f)["harita"]
    if MOD == "S":
        return {s: {"long": S_RISK, "short": S_RISK} for s in h}
    return h


def funding_onbellek_duzelt():
    """sq_kos.py ile aynı: _funding_toplami'nin dosya seçimi, doğru birimle (epoch sn)."""
    import pandas as pd
    import exchange as EX
    for coin in ("SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"):
        seri = None
        for ad in (f"{coin}_funding_bnc.csv", f"{coin}_funding.csv"):
            y = os.path.join(KOK, "data", ad)
            if not os.path.exists(y):
                continue
            d = pd.read_csv(y)
            k = "dt" if "dt" in d.columns else d.columns[0]
            t = pd.to_datetime(d[k], utc=True, format="mixed")
            yeni = (np.array([x.timestamp() for x in t]), d["rate"].to_numpy(dtype="float64"))
            if seri is None or len(yeni[0]) > len(seri[0]):
                seri = yeni
        EX._FUNDING_ONBELLEK[coin] = seri


def neden_kodu(hata: str, mevcut: list, yon: int) -> str:
    h = hata or ""
    if "already holds a position" in h:
        if not mevcut:
            return "SEMBOLDE_POZISYON"
        ters = any(d != yon for _, d, _ in mevcut)
        return "SEMBOLDE_TERS_POZISYON" if ters else "SEMBOLDE_AYNI_YON_POZISYON"
    for anahtar, kod in (("entry already in flight", "SEMBOLDE_GIRIS_SURUYOR"),
                         ("Max positions", "MAX_POZISYON"),
                         ("Correlation cap", "KORELASYON_SINIRI"),
                         ("Cooldown", "SOGUMA"),
                         ("Trading halted", "GUNLUK_ZARAR_FRENI"),
                         ("Daily loss", "GUNLUK_ZARAR_FRENI"),
                         ("Insufficient free margin", "MARJIN_YETERSIZ"),
                         ("Could not build trade setup", "KURULUM_OLUSMADI"),
                         ("Slot", "SLOT_DOLU"),
                         ("Ayni-yon", "AYNI_YON_SINIRI"),
                         ("Portfoy stopu", "PORTFOY_STOPU")):
        if anahtar in h:
            return kod
    return "DIGER"


class Kancalar:
    """Tüm aday kancaları tek yerde; testler de bunu kullanır."""

    def __init__(self, M, saat, feed, mod, harita, kayit_ozsermaye=True):
        self.M, self.saat, self.feed, self.mod = M, saat, feed, mod
        self.harita = harita
        self.durum = {}                 # sembol → FPBDurum
        self.islenen = {}               # sembol → beslemeden işlenen mum sayısı
        self.kuyruk = []                # bu damganın sinyalleri
        self.sinyaller = []             # sinyal defteri (sonuçlarıyla)
        self.olaylar = []               # hazırlık/iptal/eksik/tekrar
        self.aday_ids = set()
        self.bosluk_ids = set()
        self.aktif_risk = None
        self.ozsermaye = []
        self.kayit_ozsermaye = kayit_ozsermaye
        self.son_sembol = {}            # 1h mum açılış ms → o damgadaki son sembol
        self._son_ts = None
        for sym in M.symbol_ctxs:
            s = feed._s(sym, "1h")
            for t in (s.ts_ns // 1_000_000):
                t = int(t)
                if sym > self.son_sembol.get(t, ""):
                    self.son_sembol[t] = sym

    # ── aday durumu ────────────────────────────────────────────────────────
    def aday_guncelle(self, sym, simdiki_ms):
        s = self.feed._s(sym, "1h")
        k = int(np.searchsorted(s.kapanis_ns, self.feed._simdi_ns(), side="right"))
        d = self.durum.setdefault(sym, F.FPBDurum(sym))
        j0 = self.islenen.get(sym, 0)
        for j in range(j0, k):
            ts = int(s.ts_ns[j] // 1_000_000)
            for ol in d.isle(ts, s.o[j], s.h[j], s.l[j], s.c[j]):
                if ol.tur in ("sinyal", "gecersiz"):
                    kayit = ol.sozluk()
                    if ol.tur == "gecersiz":
                        kayit["sonuc"] = "gecersiz_seviye"
                        self.sinyaller.append(kayit)
                    elif ts != simdiki_ms:
                        kayit["sonuc"] = "gecmis_mum_islenemez"   # yalnız ilk dolumda olabilir
                        self.sinyaller.append(kayit)
                    else:
                        self.kuyruk.append(kayit)
                else:
                    self.olaylar.append(ol.sozluk())
        self.islenen[sym] = k

    async def ts_sonu(self, ts_ms):
        kuyruk, self.kuyruk = sorted(self.kuyruk, key=lambda r: r["sembol"]), []
        for kayit in kuyruk:
            await self.aday_gir(kayit)
        if self.kayit_ozsermaye:
            self.ozsermaye_kaydet(ts_ms + F.SAAT_MS)

    async def aday_gir(self, kayit):
        M = self.M
        sym, yon = kayit["sembol"], kayit["yon"]
        kayit["kosu"] = AD
        if self.mod in ("A", "A75"):
            kayit["sonuc"] = "kosuda_aday_yok"
            self.sinyaller.append(kayit)
            return
        yon_ad = "long" if yon == 1 else "short"
        pct = self.harita.get(sym, {}).get(yon_ad)
        if not pct:
            kayit["sonuc"] = "risk_haritasinda_yok"
            self.sinyaller.append(kayit)
            return
        S, T = kayit["S"], kayit["T"]
        ref = float(M.exchange._price_for(sym))     # q kapanışı = q+1 açılışı (1h veride %99.98 eşit)
        kayit["giris_ref"] = ref
        arada = (T < ref < S) if yon == -1 else (S < ref < T)
        if not arada:
            kayit["sonuc"] = "engellendi"
            kayit["neden_kodu"] = "ACILIS_SEVIYE_DISI"
            self.sinyaller.append(kayit)
            return
        from strategies.signal_combiner import CombinedSignal
        sig = CombinedSignal(
            direction=yon, confidence=1.0, trend_score=0.0, mean_rev_score=0.0,
            breakout_score=0.0, dominant_strategy=F.STRATEJI,
            reasons=[f"FPB {yon_ad} a={kayit['a_ts']} q={kayit['q_ts']}"],
            entry_price=kayit["E_plan"], sl_price=S, tp_price=T, symbol=sym,
            position_slot=f"{sym}:fpb", force_market=True, anchor_is_level=False)
        mevcut = [(p.symbol, p.direction, p.strategy_scores.get("strategy"))
                  for p in M.portfolio.get_open_positions() if p.symbol == sym]
        kayit["mevcut_pozisyon"] = ";".join(f"{st}:{'long' if d == 1 else 'short'}"
                                            for _, d, st in mevcut)
        self.aktif_risk = pct
        try:
            res = await M.executor.execute_signal(sig, kayit["atr_q"])
        finally:
            self.aktif_risk = None
        if res.success and res.position is not None:
            p = res.position
            self.aday_ids.add(p.id)
            kayit.update(sonuc="dolum", pos_id=p.id, E_fill=p.entry_price, miktar=p.quantity,
                         risk_pct=pct, giris_zamani=p.entry_time.isoformat())
        else:
            kayit.update(sonuc="engellendi", neden_kodu=neden_kodu(res.error, mevcut, yon),
                         hata=(res.error or "")[:120])
        self.sinyaller.append(kayit)

    def ozsermaye_kaydet(self, kapanis_ms):
        ex = self.M.exchange
        bak = float(ex._balance)
        marj = unr = risk = 0.0
        acik = aday_acik = 0
        for p in ex.get_open_positions():
            px = float(ex._price_for(p.symbol))
            d = 1.0 if p.side == "long" else -1.0
            marj += p.margin_used
            unr += d * (px - p.entry_price) * p.quantity
            risk += max(0.0, d * (px - p.sl_price)) * p.quantity if p.sl_price > 0 else 0.0
            acik += 1
            aday_acik += p.id in self.aday_ids
        self.ozsermaye.append((kapanis_ms, bak + marj + unr, bak, marj, unr, risk, acik, aday_acik))

    def bar_acilis(self, sym):
        s = self.feed._s(sym, "1h")
        k = int(np.searchsorted(s.kapanis_ns, self.feed._simdi_ns(), side="right"))
        return float(s.o[k - 1]) if k > 0 else None

    # ── kancaları tak ──────────────────────────────────────────────────────
    def tak(self):
        import data as D
        import exchange as EX
        import risk as RK
        import portfolio as PF
        K = self

        orj_fire = D.DataManager._fire_callbacks

        async def fire(dm, tf, candle):
            await orj_fire(dm, tf, candle)
            if tf != "1h":
                return
            ts = int(candle.timestamp)
            if K._son_ts is not None and ts != K._son_ts and K.kuyruk:
                for r in K.kuyruk:                       # olmamalı; olursa görünür
                    r["sonuc"] = "damga_sonu_kacti"
                    K.sinyaller.append(r)
                K.kuyruk = []
            K._son_ts = ts
            K.aday_guncelle(dm._symbol, ts)
            if K.son_sembol.get(ts) == dm._symbol:
                await K.ts_sonu(ts)
        D.DataManager._fire_callbacks = fire

        orj_setup = RK.RiskManager.build_trade_setup_from_levels

        def setup(rm, *a, **k):
            if K.aktif_risk is not None:
                k["risk_pct_override"] = K.aktif_risk
                if K.mod == "S":
                    k["balance"] = S_SABIT_BAKIYE
            return orj_setup(rm, *a, **k)
        RK.RiskManager.build_trade_setup_from_levels = setup

        orj_create = PF.Portfolio.create_position

        def create(pf, *a, **k):
            sc = k.get("strategy_scores")
            if isinstance(sc, dict) and sc.get("strategy") == F.STRATEJI:
                sc["max_hold"] = F.MAX_TUTUS
            return orj_create(pf, *a, **k)
        PF.Portfolio.create_position = create

        orj_check = EX.PaperExchange.check_sl_tp

        async def check(ex, high, low, symbol=None):
            if symbol is not None and K.aday_ids:
                o = None
                for pos in list(ex.get_open_positions()):
                    if pos.symbol != symbol or pos.id not in K.aday_ids or pos.sl_price <= 0:
                        continue
                    if o is None:
                        o = K.bar_acilis(symbol)
                    if o is None:
                        continue
                    if (pos.side == "long" and o <= pos.sl_price) or \
                       (pos.side == "short" and o >= pos.sl_price):
                        K.bosluk_ids.add(pos.id)
                        await ex._close_paper_position(pos, o, "sl_gap")
            return await orj_check(ex, high, low, symbol)
        EX.PaperExchange.check_sl_tp = check

        if ADAY_CIKIS is not None:
            orj_close = EX.PaperExchange._close_paper_position
            bp = float(ADAY_CIKIS)

            async def close(ex, pos, exit_price, reason):
                if pos.id in K.aday_ids:
                    ex.SLIP_CIKIS_BP = bp
                    try:
                        return await orj_close(ex, pos, exit_price, reason)
                    finally:
                        del ex.SLIP_CIKIS_BP
                return await orj_close(ex, pos, exit_price, reason)
            EX.PaperExchange._close_paper_position = close

        if self.mod == "S":
            from execution import ExecutionResult
            orj_exec = self.M.executor.execute_signal

            async def yalniz_aday(sig, atr):
                if sig.dominant_strategy != F.STRATEJI:
                    return ExecutionResult(False, error="S: bot kolu kapali")
                return await orj_exec(sig, atr)
            self.M.executor.execute_signal = yalniz_aday


async def ana():
    from ikiz.kos import kur, sur
    from ikiz import db_yolu
    t0 = time.time()
    M, saat, feed = await kur("2023-04-06", source="local")
    import exchange as EX
    if FIX_FUNDING:
        EX._simdi_ts = lambda: saat.simdi.timestamp()
        funding_onbellek_duzelt()
    harita = risk_haritasi()
    K = Kancalar(M, saat, feed, MOD, harita)
    K.tak()
    r = M.config.risk
    ayar = dict(AD=AD, MOD=MOD, SLIP_KAT=KAT, FIX_FUNDING=FIX_FUNDING, ADAY_CIKIS_SLIP_BP=ADAY_CIKIS,
                slip_giris=EX.PaperExchange.SLIP_GIRIS_BP, slip_cikis=EX.PaperExchange.SLIP_CIKIS_BP,
                fee=EX.PaperExchange.FEE_RATE, funding_acik=EX.PaperExchange.FUNDING_ACIK,
                risk_scale=r.risk_scale, donchian_risk_pct=r.donchian_risk_pct,
                squeeze_risk_pct=r.squeeze_risk_pct, max_risk_per_trade=r.max_risk_per_trade,
                cap=getattr(r, "position_cap_fraction", None), max_positions=r.max_positions,
                leverage=M.config.exchange.leverage, one_per_symbol=getattr(r, "one_per_symbol", None),
                baslangic_bakiye=M.config.paper_initial_balance, bitis=BITIS,
                aday_harita=harita if MOD in ("B", "S") else None,
                semboller=list(M.symbol_ctxs))
    print("AYAR", json.dumps(ayar, default=str), flush=True)
    n = await sur(M, saat, feed, bitis=BITIS, ilerleme_her=40000)
    await asyncio.sleep(0)
    print(f"{n} mum · {(time.time() - t0) / 60:.1f} dk", flush=True)

    import sqlite3
    import pandas as pd
    c = sqlite3.connect(f"file:{db_yolu()}?mode=ro", uri=True)
    d = pd.read_sql("SELECT id,symbol,side,entry_price,exit_price,sl_price,tp_price,quantity,entry_time,"
                    "exit_time,pnl_usdt,exit_reason,strategy_scores,fees_usdt FROM trades "
                    "WHERE exit_time IS NOT NULL", c)
    acik = pd.read_sql("SELECT COUNT(*) n FROM trades WHERE exit_time IS NULL", c)["n"].iloc[0]
    d["aday"] = d["id"].isin(K.aday_ids)
    d["sl_gap"] = d["id"].isin(K.bosluk_ids)
    d.to_csv(os.path.join(CIKTI, f"{AD}_islemler.csv"), index=False)
    pd.DataFrame(K.sinyaller).to_csv(os.path.join(CIKTI, f"{AD}_aday_sinyaller.csv"), index=False)
    pd.DataFrame(K.olaylar).to_csv(os.path.join(CIKTI, f"{AD}_aday_olaylar.csv.gz"), index=False)
    with gzip.open(os.path.join(CIKTI, f"{AD}_ozsermaye.csv.gz"), "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kapanis_ms", "ozsermaye", "serbest", "marjin", "gerceklesmemis",
                    "acik_risk_stopa", "acik_poz", "aday_acik"])
        w.writerows(K.ozsermaye)
    bitis_ozs = K.ozsermaye[-1][1] if K.ozsermaye else None
    with open(os.path.join(CIKTI, f"{AD}_ozet.json"), "w") as f:
        json.dump(dict(ayar=ayar, kapanmis=len(d), acik_kalan=int(acik), aday_kapanmis=int(d["aday"].sum()),
                       sinyal=len(K.sinyaller), son_ozsermaye=bitis_ozs,
                       dk=(time.time() - t0) / 60), f, default=str, indent=1)
    print("BITTI", AD, len(d), "islem; aday", int(d["aday"].sum()), flush=True)


if __name__ == "__main__":
    asyncio.run(ana())
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
