"""
canli_ikiz_uyum.py — CANLI işlemler, aynı dönemin İKİZ koşusuyla karşılaştırılır.

Soru: "Canlı bot, ikizin (gerçek main.on_candle_close replay'i) bu dönem için
öngördüğünü mü yapıyor?" Sayım, eşleşme, giriş fiyatı, çıkış nedeni ve R.

GÜVENLİK (VPS'te koşar):
  • Canlı veritabanı yalnız `mode=ro` ile açılır; hiçbir şey yazılmaz.
  • Canlı .env yalnız bu sürecin ortamına OKUNUR (ayar sadakati için); kopyalanmaz,
    yazdırılmaz. Ekrana/dosyaya yalnız GİZLİ OLMAYAN beyaz listedeki ayarlar çıkar.
  • İkiz kağıt modda, ağ kapalı (ccxt.pro sahte modülle değiştirilir), telegram/ntfy/
    web/orderflow/funding/whale izleyicileri zorla kapalı. Emir gönderemez.
  • Mum verisi ÇIKTI klasörüne indirilir; repodaki data/ klasörüne DOKUNULMAZ.
  • İkiz, `nice` ile düşük öncelikte koşturulmalı (komut aşağıda).

Kullanım (VPS):
  cd /opt/bot2
  nice -n 19 venv/bin/python arastirma/canli_ikiz_uyum/canli_ikiz_uyum.py hepsi \\
      --bot-dizini /opt/bot2 --cikti /tmp/canli_ikiz
Adımlar tek tek: indir | kos | karsilastir  (hepsi = üçü sırayla)

Sınır: ikiz koşusu BUGÜNKÜ kod ve BUGÜNKÜ .env ile yapılır. Canlı dönemde ayar/kod
değiştiyse (bilinen tarihler aşağıda) o tarihten önceki farkların bir kısmı buradan gelir;
rapor dönemleri ayrı gösterir.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time

BURA = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(BURA))

# Bilinen canlı ayar değişiklikleri (ikiz/kos.py CANLI_ENV notlarından)
AYAR_DEGISIKLIKLERI = {
    "2026-07-21": "DONCHIAN_RR 2.5",
    "2026-09-14": "donchian piyasa girişi (DONCHIAN_MAKER_ENTRY=false)",
    "2026-09-22": "RISK_SCALE 1.75 / SQUEEZE_SYMBOLS XRP,DOGE,XLM (TRX çıktı)",
    "2026-09-26": "POSITION_CAP_FRACTION 2.5",
}
GOSTER = ("SYMBOLS", "DONCHIAN_SYMBOLS", "SQUEEZE_SYMBOLS", "BB_SYMBOLS", "BB_WEEKDAY_ENABLED",
          "MAX_POSITIONS", "POSITION_CAP_FRACTION", "MAX_RISK_PCT", "RISK_SCALE",
          "DONCHIAN_RISK_PCT", "SQUEEZE_RISK_PCT", "DAILY_MAX_LOSS_PCT", "LEVERAGE",
          "CONSECUTIVE_LOSS_LIMIT", "COOLDOWN_MINUTES", "DONCHIAN_MTF", "DONCHIAN_RR",
          "DONCHIAN_VOL_MULT", "DONCHIAN_MAKER_ENTRY", "MAKER_ENTRY", "SQUEEZE_MAKER_ENTRY",
          "ATR_SL_MULT", "RR_RATIO", "MAX_HOLD_CANDLES", "VOL_FILTER_ENABLED", "FUNDING_ENABLED",
          "FUNDING_MODE", "DONCHIAN_MOD", "STOP_MOVE_ENABLED", "ONE_PER_SYMBOL")
ESLESME_PENCERE_DK = 90


def env_yukle(bot_dizini):
    """Canlı .env → os.environ (setdefault). Değerler YAZDIRILMAZ."""
    y = os.path.join(bot_dizini, ".env")
    if not os.path.exists(y):
        sys.exit(f".env bulunamadı: {y}")
    with open(y, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if not satir or satir.startswith("#") or "=" not in satir:
                continue
            k, v = satir.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def db_yolu(bot_dizini):
    aday = [os.environ.get("DB_PATH"), "trades.db", "data/trades.db"]
    for a in aday:
        if not a:
            continue
        y = a if os.path.isabs(a) else os.path.join(bot_dizini, a)
        if os.path.exists(y):
            return y
    sys.exit("canlı trades.db bulunamadı (DB_PATH, trades.db, data/trades.db denendi)")


def canli_islemler(bot_dizini):
    import pandas as pd
    y = db_yolu(bot_dizini)
    c = sqlite3.connect(f"file:{y}?mode=ro", uri=True)
    d = pd.read_sql("SELECT * FROM trades WHERE is_paper = 0", c)
    c.close()
    return d


# ───────────────────────────── 1) indir ──────────────────────────────────────
def indir(a):
    import pandas as pd
    import requests
    env_yukle(a.bot_dizini)
    canli = canli_islemler(a.bot_dizini)
    if canli.empty:
        sys.exit("canlı işlem yok")
    t0 = pd.to_datetime(canli["entry_time"], utc=True, format="mixed").min()
    bas = (t0 - pd.Timedelta(days=80)).floor("D")
    semboller = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
    vdir = os.path.join(a.cikti, "veri")
    os.makedirs(vdir, exist_ok=True)
    ses = requests.Session()
    ses.headers.update({"User-Agent": "bot2-uyum/1.0"})
    simdi = int(time.time())
    for coin in semboller:
        coin = coin.split("/")[0]
        cur, parca = int(bas.timestamp()), []
        while cur < simdi:
            son = min(cur + 1900 * 3600, simdi)
            for deneme in range(4):
                try:
                    r = ses.get(f"https://contract.mexc.com/api/v1/contract/kline/{coin}_USDT",
                                params={"interval": "Min60", "start": cur, "end": son}, timeout=45)
                    r.raise_for_status()
                    k = r.json()["data"]
                    break
                except Exception as e:
                    if deneme == 3:
                        sys.exit(f"{coin}: indirme hatası {e}")
                    time.sleep(2 ** deneme)
            t = k.get("time") or []
            if t:
                parca.append(pd.DataFrame({"ts": t, "open": k["open"], "high": k["high"],
                                           "low": k["low"], "close": k["close"], "volume": k["vol"]}))
                cur = int(t[-1]) + 3600
            else:
                cur = son
            time.sleep(0.15)
        d = pd.concat(parca).drop_duplicates("ts").sort_values("ts")
        d["ts"] = pd.to_datetime(d["ts"].astype("int64"), unit="s", utc=True)
        d = d.set_index("ts").astype(float)
        d = d[d.index + pd.Timedelta(hours=1) <= pd.Timestamp.now(tz="UTC")]   # oluşan mumu at
        d.to_csv(os.path.join(vdir, f"{coin}_fut_1h.csv"))
        eksik = int((d.index.to_series().diff() > pd.Timedelta(hours=1)).sum())
        print(f"  {coin}: {len(d)} mum {d.index[0]} → {d.index[-1]} (boşluk {eksik})", flush=True)
    with open(os.path.join(a.cikti, "donem.json"), "w") as f:
        json.dump(dict(ilk_canli_giris=str(t0), veri_bas=str(bas)), f)


# ───────────────────────────── 2) ikiz koşusu ────────────────────────────────
def kos(a):
    import asyncio
    env_yukle(a.bot_dizini)
    live_funding = (os.environ.get("FUNDING_ENABLED", "false"), os.environ.get("FUNDING_MODE", "monitor"))
    # ağa dokunan / dışarı mesaj atan her şey kapalı; maliyet 936 referansıyla aynı
    os.environ.update({
        "ORDERFLOW_ENABLED": "false", "WHALE_ENABLED": "false", "FUNDING_ENABLED": "false",
        "TELEGRAM_ENABLED": "false", "NTFY_ENABLED": "false", "WEB_DASHBOARD_ENABLED": "false",
        "PAPER_SLIP_GIRIS_BP": "15.85", "PAPER_SLIP_CIKIS_BP": "0.24", "PAPER_FUNDING": "false",
        "REPLAY_DB": os.path.join(a.cikti, "ikiz.db"),
    })
    os.makedirs(a.cikti, exist_ok=True)
    os.chdir(a.cikti)                      # signals_log.csv canlı klasöre DEĞİL buraya yazılır
    sys.path.insert(0, KOK)
    import pandas as pd
    import fast_bt
    fast_bt.CACHE_DIR = os.path.join(a.cikti, "veri")
    with open(os.path.join(a.cikti, "donem.json")) as f:
        donem = json.load(f)
    bas = (pd.Timestamp(donem["veri_bas"]) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    ayar = {k: os.environ.get(k, "(yok→kod varsayılanı)") for k in GOSTER}
    ayar["_canli_FUNDING"] = f"{live_funding[0]}/{live_funding[1]}"
    try:
        ayar["_commit"] = subprocess.check_output(["git", "-C", KOK, "rev-parse", "--short", "HEAD"],
                                                  text=True).strip()
    except Exception:
        ayar["_commit"] = "?"
    print("AYAR", json.dumps(ayar, ensure_ascii=False), flush=True)

    async def ana():
        from ikiz.kos import kur, sur
        M, saat, feed = await kur(bas, source="local")
        await sur(M, saat, feed, bitis=None, ilerleme_her=40000)
    asyncio.run(ana())
    c = sqlite3.connect(f"file:{os.path.join(a.cikti, 'ikiz.db')}?mode=ro", uri=True)
    pd.read_sql("SELECT * FROM trades", c).to_csv(os.path.join(a.cikti, "ikiz_islemler.csv"), index=False)
    with open(os.path.join(a.cikti, "ikiz_ayar.json"), "w") as f:
        json.dump(dict(ayar=ayar, ikiz_bas=bas), f, ensure_ascii=False, indent=1)
    print("ikiz bitti", flush=True)
    sys.stdout.flush()
    os._exit(0)


# ───────────────────────────── 3) karşılaştır ────────────────────────────────
def _hazirla(d, kaynak):
    import pandas as pd
    d = d.copy()
    d["kaynak"] = kaynak
    d["giris"] = pd.to_datetime(d["entry_time"], utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d["exit_time"], utc=True, format="mixed", errors="coerce")
    sc = d["strategy_scores"].apply(lambda s: json.loads(s) if isinstance(s, str) and s else {})
    d["kol"] = sc.apply(lambda x: x.get("strategy", "mean_rev"))
    d["sl0"] = [float(x.get("sl0") or s) for x, s in zip(sc, d["sl_price"])]
    d["niyet"] = [float(x.get("intended_entry") or e) for x, e in zip(sc, d["entry_price"])]
    yon = d["side"].map({"long": 1, "short": -1})
    risk = (d["entry_price"] - d["sl0"]).abs() * d["quantity"]
    d["R_net"] = d["pnl_usdt"] / risk.where(risk > 0)
    d["R_brut"] = yon * (d["exit_price"] - d["entry_price"]) / (d["entry_price"] - d["sl0"]).abs()
    d["giris_kayma_bp"] = yon * (d["entry_price"] / d["niyet"] - 1) * 1e4
    d["kapali"] = d["cikis"].notna()
    return d


def _boot(x, n=5000, seed=20260930):
    import numpy as np
    x = np.asarray([v for v in x if v == v])
    if len(x) < 3:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    m = rng.choice(x, (n, len(x))).mean(1)
    return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))


def karsilastir(a):
    import pandas as pd
    import numpy as np
    env_yukle(a.bot_dizini)
    canli = _hazirla(canli_islemler(a.bot_dizini), "canli")
    ikiz = _hazirla(pd.read_csv(os.path.join(a.cikti, "ikiz_islemler.csv")), "ikiz")
    with open(os.path.join(a.cikti, "donem.json")) as f:
        donem = json.load(f)
    bas = pd.Timestamp(a.bas, tz="UTC") if a.bas else pd.Timestamp(donem["ilk_canli_giris"]).floor("D")
    veri_son = ikiz["giris"].max()
    son = pd.Timestamp.now(tz="UTC")
    canli = canli[canli["giris"] >= bas]
    ikiz = ikiz[ikiz["giris"] >= bas]

    # eşleşme: aynı sembol + yön + kol, giriş farkı ≤ 90 dk, en yakın, bire bir
    eslesen, kullanildi = [], set()
    for i, r in canli.sort_values("giris").iterrows():
        adaylar = ikiz[(ikiz["symbol"] == r["symbol"]) & (ikiz["side"] == r["side"]) &
                       (ikiz["kol"] == r["kol"]) & (~ikiz.index.isin(kullanildi))]
        if adaylar.empty:
            continue
        fark = (adaylar["giris"] - r["giris"]).abs()
        j = fark.idxmin()
        if fark[j] <= pd.Timedelta(minutes=ESLESME_PENCERE_DK):
            kullanildi.add(j)
            eslesen.append((i, j))
    ci = {i for i, _ in eslesen}
    yalniz_canli = canli[~canli.index.isin(ci)]
    yalniz_ikiz = ikiz[~ikiz.index.isin(kullanildi)]

    rows = []
    for i, j in eslesen:
        c, k = canli.loc[i], ikiz.loc[j]
        yon = 1 if c["side"] == "long" else -1
        rows.append(dict(
            sembol=c["symbol"], yon=c["side"], kol=c["kol"], canli_giris=c["giris"], ikiz_giris=k["giris"],
            giris_farki_dk=(c["giris"] - k["giris"]).total_seconds() / 60,
            canli_giris_fiyat=c["entry_price"], ikiz_giris_fiyat=k["entry_price"],
            giris_fiyat_farki_bp=yon * (c["entry_price"] / k["entry_price"] - 1) * 1e4,   # + = canlı daha kötü
            canli_kayma_bp=c["giris_kayma_bp"],
            canli_cikis_nedeni=c["exit_reason"], ikiz_cikis_nedeni=k["exit_reason"],
            ayni_cikis_nedeni=c["exit_reason"] == k["exit_reason"],
            canli_cikis=c["cikis"], ikiz_cikis=k["cikis"],
            canli_R_net=c["R_net"], ikiz_R_net=k["R_net"], canli_R_brut=c["R_brut"], ikiz_R_brut=k["R_brut"],
            canli_kapali=c["kapali"], ikiz_kapali=k["kapali"]))
    es = pd.DataFrame(rows)

    # canlı sinyal günlüğü: ikizde olup canlıda olmayan işlemlerin olası nedeni
    sl_y = os.path.join(a.bot_dizini, "signals_log.csv")
    if os.path.exists(sl_y) and len(yalniz_ikiz):
        sl = pd.read_csv(sl_y)
        sl["ts"] = pd.to_datetime(sl["ts"], utc=True, format="mixed", errors="coerce")
        neden = []
        for _, r in yalniz_ikiz.iterrows():
            yak = sl[(sl["symbol"] == r["symbol"]) & (sl["strategy"] == r["kol"]) &
                     ((sl["ts"] - r["giris"]).abs() <= pd.Timedelta(minutes=ESLESME_PENCERE_DK))]
            neden.append("; ".join(sorted(set(yak["reason"].fillna("").astype(str)))) if len(yak)
                         else "canlı günlükte sinyal yok")
        yalniz_ikiz = yalniz_ikiz.assign(canli_gunluk=neden)

    def ozet_kol(g_c, g_i, g_e):
        kap_c, kap_i = g_c[g_c["kapali"]], g_i[g_i["kapali"]]
        o = dict(canli_islem=len(g_c), ikiz_islem=len(g_i), eslesen=len(g_e),
                 kapsama_ikizin_yuzde=round(100 * len(g_e) / len(g_i), 1) if len(g_i) else None,
                 canli_toplam_R=round(float(kap_c["R_net"].sum()), 2),
                 ikiz_toplam_R=round(float(kap_i["R_net"].sum()), 2),
                 canli_ort_R=round(float(kap_c["R_net"].mean()), 3) if len(kap_c) else None,
                 ikiz_ort_R=round(float(kap_i["R_net"].mean()), 3) if len(kap_i) else None)
        if len(g_e):
            kk = g_e[g_e["canli_kapali"] & g_e["ikiz_kapali"]]
            fark = (kk["canli_R_net"] - kk["ikiz_R_net"]).to_numpy()
            o.update(eslesen_kapali=len(kk),
                     ayni_cikis_nedeni_yuzde=round(100 * float(kk["ayni_cikis_nedeni"].mean()), 1) if len(kk) else None,
                     R_farki_ort=round(float(np.nanmean(fark)), 3) if len(kk) else None,
                     R_farki_GA95=[round(x, 3) for x in _boot(fark)],
                     giris_fiyat_farki_bp_ort=round(float(g_e["giris_fiyat_farki_bp"].mean()), 2),
                     canli_giris_kayma_bp_ort=round(float(g_e["canli_kayma_bp"].mean()), 2))
        return o

    ozet = dict(karsilastirma_bas=str(bas), ikiz_son_giris=str(veri_son), rapor_zamani=str(son),
                eslesme_penceresi_dk=ESLESME_PENCERE_DK, ayar_degisiklikleri=AYAR_DEGISIKLIKLERI,
                TOPLAM=ozet_kol(canli, ikiz, es))
    for kol in sorted(set(canli["kol"]) | set(ikiz["kol"])):
        ozet[f"kol_{kol}"] = ozet_kol(canli[canli["kol"] == kol], ikiz[ikiz["kol"] == kol],
                                      es[es["kol"] == kol] if len(es) else es)
    sinirlar = [bas] + [pd.Timestamp(t, tz="UTC") for t in sorted(AYAR_DEGISIKLIKLERI)
                        if pd.Timestamp(t, tz="UTC") > bas] + [son]
    for x, y in zip(sinirlar[:-1], sinirlar[1:]):
        f = lambda d, c="giris": d[(d[c] >= x) & (d[c] < y)]
        ozet[f"donem_{x.date()}_{y.date()}"] = ozet_kol(f(canli), f(ikiz),
                                                        f(es, "canli_giris") if len(es) else es)
    ozet["yalniz_ikiz_canli_gunluk_nedenleri"] = (
        yalniz_ikiz["canli_gunluk"].value_counts().head(15).to_dict() if "canli_gunluk" in yalniz_ikiz else {})
    ozet["yalniz_canli_cikis_nedenleri"] = yalniz_canli["exit_reason"].fillna("acik").value_counts().to_dict()

    kol_c = ["symbol", "side", "kol", "giris", "cikis", "entry_price", "exit_price", "sl0", "exit_reason",
             "R_net", "R_brut"]
    es.to_csv(os.path.join(a.cikti, "eslesen.csv"), index=False)
    yalniz_canli[kol_c].to_csv(os.path.join(a.cikti, "yalniz_canli.csv"), index=False)
    yalniz_ikiz[kol_c + (["canli_gunluk"] if "canli_gunluk" in yalniz_ikiz else [])].to_csv(
        os.path.join(a.cikti, "yalniz_ikiz.csv"), index=False)
    with open(os.path.join(a.cikti, "uyum_ozet.json"), "w") as f:
        json.dump(ozet, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(ozet, ensure_ascii=False, indent=1, default=str))
    print(f"\nDosyalar: {a.cikti}/ uyum_ozet.json eslesen.csv yalniz_canli.csv yalniz_ikiz.csv")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("adim", choices=["indir", "kos", "karsilastir", "hepsi"])
    p.add_argument("--bot-dizini", default="/opt/bot2")
    p.add_argument("--cikti", default="/tmp/canli_ikiz")
    p.add_argument("--bas", default=None, help="karşılaştırma başlangıcı (YYYY-MM-DD); yoksa ilk canlı giriş günü")
    a = p.parse_args()
    a.cikti = os.path.abspath(a.cikti)
    os.makedirs(a.cikti, exist_ok=True)
    if a.adim == "hepsi":
        py = sys.executable
        for adim in ("indir", "kos", "karsilastir"):
            arg = [py, os.path.abspath(__file__), adim, "--bot-dizini", a.bot_dizini, "--cikti", a.cikti]
            if a.bas:
                arg += ["--bas", a.bas]
            r = subprocess.run(arg)
            if r.returncode != 0:
                sys.exit(f"{adim} adımı başarısız ({r.returncode})")
        return
    {"indir": indir, "kos": kos, "karsilastir": karsilastir}[a.adim](a)


if __name__ == "__main__":
    main()
