"""
uyum_testi.py — "CANLI, BACKTEST'İN DEDİĞİNİ Mİ YAPIYOR?" — uçtan uca uyum.

KULLANICININ FİKRİ, ve doğru fikir: bu dönemin verisini backtest'e sok, aynı
dönemin GERÇEK işlem geçmişiyle karşılaştır.

NEDEN ŞU AN EN DEĞERLİ İŞ BU: 34 eksen boyunca her şey ANKORA KARŞI ölçüldü.
Ama ankorun canlıyla örtüştüğü uçtan uca hiç doğrulanmadı. Canlı bot
backtest'in dediğini yapmıyorsa, o 34 ölçümün hepsi yanlış zemine oturuyor —
ve riski büyütmek de dayanaksız kalır.

⚠ saglik_kaniti.py sinyalin OLUŞUP OLUŞMADIĞINI karşılaştırıyordu. Bu araç
  SONUCU karşılaştırıyor: backtest'in öngördüğü giriş/çıkış/R ile canlının
  gerçekte aldığı giriş/çıkış/R.

ÜÇ SORU:
  [1] SAYIM   — backtest kaç işlem bekliyordu, canlı kaç tane açtı?
  [2] EŞLEŞME — her canlı işlem, backtest'in bir işlemine karşılık geliyor mu?
  [3] SONUÇ   — eşleşenlerde R aynı mı? Sistematik sapma var mı, hangi yönde?

⚠ ANKOR VERİSİNE DOKUNMAZ: taze veri AYRI dosyaya yazılır
  (`data/{COIN}_uyum_1h.csv`), `_fut_` dosyalarına elini sürmez.
⚠ HÜKÜM KURALLARI: kapsama <%70 ise sistematik sapma hükmü VERİLMEZ.
  Açık pozisyonlar hariç tutulur (sonuçları belli değil).

Kullanım (VPS'te):  venv/bin/python uyum_testi.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

import deployed_backtest as A          # noqa: E402
import fast_bt                          # noqa: E402
from config import load_config          # noqa: E402
from indicators import atr as atr_fn, adx as adx_fn   # noqa: E402

UYUM = "data/{coin}_uyum_1h.csv"


def taze_cek(coin, gun=200):
    """MEXC 1h — AYRI dosyaya. fast_bt._save_cache yoluna GİRMEZ."""
    p = UYUM.format(coin=coin)
    if os.path.exists(p):
        m = pd.read_csv(p, index_col=0, parse_dates=True)
        print(f"    {coin}: {p} var ({len(m)} bar), yeniden çekilmedi")
        return m
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    since = int((time.time() - gun * 86400) * 1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(f"{coin}/USDT:USDT", "1h", since=since, limit=500)
        if not b:
            break
        rows += b
        if len(b) < 500:
            break
        since = b[-1][0] + 1
    if not rows:
        raise RuntimeError(f"{coin}: veri çekilemedi")
    m = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop_duplicates("ts").drop(columns=["ts"]).astype(float).iloc[:-1]
    os.makedirs("data", exist_ok=True)
    m.to_csv(p)
    print(f"    {coin}: {len(m)} bar → {p}")
    return m


def _kol(js):
    try:
        d = json.loads(js or "{}")
        return str(d.get("strategy") or d.get("sleeve") or "?")
    except Exception:
        return "?"


def main():
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")
    db_path = cfg.db_path
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    cut = con.execute("SELECT value FROM meta WHERE key='temiz_cut'").fetchone()
    con.close()
    if not cut:
        raise SystemExit("⛔ Çıpa yok — önce temiz_donem.py --yaz")
    cut = str(cut[0])
    bas = datetime.strptime(cut, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print("=" * 78)
    print(f"UYUM TESTİ — canlı, backtest'in dediğini mi yapıyor? ({cut} sonrası)")
    print("=" * 78)
    print("\n  taze veri çekiliyor (ANKOR dosyalarına DOKUNULMUYOR)...")
    veri = {}
    for c in A.DONCH + A.SQZ + A.BB_COINS:
        try:
            veri[c] = taze_cek(c)
        except Exception as e:
            print(f"    ⛔ {c}: {e}")
    eksik = [c for c in A.DONCH + A.SQZ + A.BB_COINS if c not in veri]
    if eksik:
        print(f"\n  ⛔ {eksik} çekilemedi. Eksik veriyle uyum hükmü VERİLMEZ.")
        raise SystemExit(2)

    # ── BACKTEST'İN BU DÖNEM İÇİN BEKLEDİĞİ İŞLEMLER ────────────────────────
    # ⚠⚠ ZAMAN DAMGASI KONVANSİYONU — İLK SÜRÜMÜN HATASI BURADAYDI.
    # A.gen `idx[i]` yazıyor = pandas resample bin etiketi = BARIN BAŞLANGICI.
    # Canlı bot ise bar KAPANINCA giriyor. Donchian 4h → aradaki fark TAM 4 SAAT,
    # squeeze/bb 1h → 1 saat. ±2 saatlik eşleştirme penceresiyle donchian ASLA
    # eşleşemezdi; ilk koşuda %22 çıktı ve bu botun değil ARACIN hatasıydı.
    # (Aynı konvansiyonu veri_pencere.py ve sabirli_maker.py'de doğru yazmıştım,
    #  burada unuttum — o yüzden artık kol başına AÇIKÇA ekleniyor.)
    KAPANIS = {"donchian": pd.Timedelta(hours=4),
               "squeeze": pd.Timedelta(hours=1),
               "bb": pd.Timedelta(hours=1)}
    bek = []
    for kol_ad, coinler, uret in (("donchian", A.DONCH, lambda c: A.gen("donchian", veri[c])),
                                  ("squeeze", A.SQZ, lambda c: A.gen("squeeze", veri[c])),
                                  ("bb", A.BB_COINS, lambda c: A.gen_bb(veri[c]))):
        for c in coinler:
            for t in uret(c):
                bek.append({"coin": c, "kol": kol_ad,
                            # bar başlangıcı + tf = canlının GERÇEKTEN girdiği an
                            "e": pd.Timestamp(t[0], tz="UTC") + KAPANIS[kol_ad],
                            "x": pd.Timestamp(t[1]), "R": t[2], "slp": t[3]})
    bek = [b for b in bek if b["e"] >= bas]
    bek.sort(key=lambda b: b["e"])

    # ── CANLININ GERÇEKTE AÇTIĞI İŞLEMLER ───────────────────────────────────
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    canli = [dict(r) for r in con.execute(
        "SELECT symbol,side,entry_price,exit_price,sl_price,quantity,pnl_usdt,"
        "entry_time,exit_time,exit_reason,strategy_scores FROM trades "
        "WHERE is_paper=0 AND entry_time>=? ORDER BY entry_time", (cut,))]
    con.close()
    kapali = [r for r in canli if r["exit_time"]]

    print(f"\n{'='*78}\n[1] SAYIM\n{'='*78}")
    print(f"  backtest'in beklediği (koltuk ÖNCESİ ham): {len(bek)}")
    print(f"  canlının açtığı                          : {len(canli)} "
          f"({len(kapali)} kapanmış, {len(canli)-len(kapali)} açık)")
    print(f"  ⚠ Ham sayı EŞİT OLMAK ZORUNDA DEĞİL: canlıda MAX_POSITIONS,")
    print(f"    cooldown ve coin-kilidi var; backtest'in seat_select'i de eler.")
    print(f"    Anlamlı olan aşağıdaki EŞLEŞME oranı.")

    # ── EŞLEŞTİRME: coin + kol + giriş zamanı (±2 saat) ─────────────────────
    print(f"\n{'='*78}\n[2] EŞLEŞME — her canlı işlem backtest'te var mı?\n{'='*78}")
    eslesen = []; eslesmeyen = []
    for r in kapali:
        c = r["symbol"].split("/")[0]; k = _kol(r["strategy_scores"])
        et = pd.Timestamp(r["entry_time"])
        if et.tzinfo is None:
            et = et.tz_localize("UTC")
        aday = [b for b in bek if b["coin"] == c and b["kol"] == k
                and abs((b["e"] - et).total_seconds()) <= 2 * 3600]
        if aday:
            eslesen.append((r, min(aday, key=lambda b: abs((b["e"] - et).total_seconds()))))
        else:
            eslesmeyen.append(r)
    kaps = len(eslesen) / max(len(kapali), 1)
    print(f"  eşleşen {len(eslesen)}/{len(kapali)} (%{kaps*100:.0f}) · "
          f"eşleşmeyen {len(eslesmeyen)}")
    for r in eslesmeyen[:6]:
        print(f"    ⚠ backtest'te YOK: {str(r['entry_time'])[:16]} "
              f"{r['symbol'].split('/')[0]} {_kol(r['strategy_scores'])}")
    if eslesmeyen:
        print(f"  → Eşleşmeyen işlem, canlının backtest'in ÜRETMEDİĞİ bir sinyalle")
        print(f"    işlem açtığı anlamına gelir. Az sayıda ise zamanlama/veri")
        print(f"    kayması, çok ise GERÇEK bir ayrışmadır.")

    if kaps < 0.70:
        print(f"\n  ⛔ Kapsama %70'in ALTINDA — sistematik sapma hükmü VERİLMEZ.")
        print(f"     Önce eşleşmeme sebebi bulunmalı.")
        # Düşük eşleşmenin EN OLASI sebebi aracın kendi hatasıdır, botun değil.
        # Toplam sayılar tutuyorsa (backtest ~= canlı) sorun EŞLEŞTİRMEDEDİR.
        if abs(len(bek) - len(canli)) <= max(5, 0.15 * len(canli)):
            print(f"\n  ⚠ AMA TOPLAM SAYILAR TUTUYOR ({len(bek)} vs {len(canli)}).")
            print(f"    Bu, botun farklı işlem açtığını DEĞİL, EŞLEŞTİRMENİN")
            print(f"    bozuk olduğunu gösterir. Önce aracı şüphelen:")
            print(f"      • zaman damgası konvansiyonu (bar başlangıcı vs kapanışı)")
            print(f"      • kol etiketi (strategy_scores['strategy']) farklı yazım")
            print(f"      • veri penceresi (taze veri ankorla aynı dönemi kapsıyor mu)")
        return

    # ── SONUÇ KARŞILAŞTIRMASI ───────────────────────────────────────────────
    print(f"\n{'='*78}\n[3] SONUÇ — eşleşenlerde R aynı mı?\n{'='*78}")
    fark = []
    for r, b in eslesen:
        e = float(r["entry_price"] or 0); x = float(r["exit_price"] or 0)
        sl = float(r["sl_price"] or 0)
        if e <= 0 or x <= 0 or sl <= 0:
            continue
        yon = 1 if str(r["side"]).lower() == "long" else -1
        sld = abs(e - sl)
        if sld <= 0:
            continue
        R_canli = yon * (x - e) / sld
        fark.append((R_canli, b["R"], r, b))
    if not fark:
        print("  ⛔ R hesaplanabilen eşleşme yok.")
        return
    rc = np.array([f[0] for f in fark]); rb = np.array([f[1] for f in fark])
    d = rc - rb
    se = d.std(ddof=1) / np.sqrt(len(d))
    print(f"  n={len(d)} eşleşmiş işlem")
    print(f"  canlı ort R    {rc.mean():+.4f}")
    print(f"  backtest ort R {rb.mean():+.4f}")
    print(f"  FARK           {d.mean():+.4f}  ± {1.96*se:.4f} (%95)  "
          f"z={d.mean()/se if se > 0 else 0:+.2f}")
    if abs(d.mean()) < 1.96 * se:
        print(f"\n  ✓ SİSTEMATİK SAPMA YOK. Canlı, backtest'in dediğini yapıyor.")
        print(f"    Ankorun 34 eksende kullanılan zemini DOĞRULANDI.")
    else:
        yon = "DÜŞÜK" if d.mean() < 0 else "YÜKSEK"
        print(f"\n  ⛔ SİSTEMATİK SAPMA VAR: canlı, backtest'ten {yon} R üretiyor.")
        print(f"    Ankor tabanlı her karar bu kadar kaymış demektir.")
        print(f"    En olası adaylar: giriş kayması (ölçülen 15.32bp), çıkışların")
        print(f"    seviye fiyatından kaydedilmesi, ücret farkı.")
    en = sorted(fark, key=lambda f: abs(f[0] - f[1]), reverse=True)[:5]
    print(f"\n  EN BÜYÜK 5 SAPMA:")
    for rc_, rb_, r, b in en:
        print(f"    {str(r['entry_time'])[:16]} {r['symbol'].split('/')[0]:<5s} "
              f"{_kol(r['strategy_scores']):<8s} canlı {rc_:+.2f}R vs "
              f"backtest {rb_:+.2f}R  ({r['exit_reason']})")


if __name__ == "__main__":
    main()
