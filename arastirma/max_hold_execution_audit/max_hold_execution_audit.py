"""
max_hold_execution_audit.py — canlı max_hold MARKET çıkışlarının gerçek execution maliyeti. SALT OKUR.

KOD YOLU (doğrulandı, bkz. MAX_HOLD_EXECUTION_RAPORU.md):
  main.py:219-222  her 1h mum KAPANIŞI işleyicisinde → _enforce_max_hold(symbol, current_price)
  main.py:193      current_price = ctx.data_mgr.get_current_price()  ← ANLIK TICKER, mum değil
  main.py:1513-34  age = now − entry_time ≥ max_hold × 3600 (PRIMARY_TF=1h) → executor.close_position
  execution.py     close_position → exchange.close_position (reduce-only MARKET) → exit_price = dolum
  exchange.py      dolum fiyatı 0 ise fetch_order/dealAvgPrice, en son MARK fiyatı (yalnız WARNING
                   log: "Close fill price unavailable"; DB'de işaret YOK)
  execution.py     _close_position_internal: çıkış ücreti SABİT 0.0001 (taker 1bp), exit_time = now

REFERANS: karar anındaki ticker fiyatı DB'ye yazılmıyor → birebir kurulamaz. Vekil: karar
işleyicisini tetikleyen 1h mumun KAPANIŞI (ccxt ts = mum AÇILIŞI; kapanış = açılış + 1h).
Vekil hatası = mum kapanışı ile karar anı arasındaki birkaç saniyelik fiyat oynaması (sıfır ortalamalı).

Önceden sabit kurallar ve hüküm: MAX_HOLD_EXECUTION_RAPORU.md.

VPS:  cd /opt/bot2 && git pull && venv/bin/python arastirma/max_hold_execution_audit/max_hold_execution_audit.py
Mumları MEXC HALKA AÇIK OHLCV'den okur (emir/hesap erişimi yok). Tahmini dolumları yakalamak için
`journalctl -u btc-bot` çıktısını OKUR. .env okumaz, bota dokunmaz, DB mode=ro.
İşlem düzeyi CSV /tmp/max_hold_execution_audit/ altına yazılır.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOK)
import erken_uyari as EU  # noqa: E402  (kol_adi, _skor; yalnız stdlib)

TF_SN = 3600                 # PRIMARY_TF=1h (config.py:232/529; canlı .env'de değiştirilmedi)
MAX_HOLD_VARSAYILAN = 48     # config.risk.max_hold_candles (MAX_HOLD_CANDLES=48)
GECIKME_MAX = 300            # karar mumu kapanışı → exit_time en fazla 300 sn (önceden sabit)
REC_PASS_ORAN = 0.80         # adayların ≥%80'i tutarlı kurulmalı
TAKER_BP = 1.0               # execution.py _close_position_internal: exit × 0.0001
MAKER_BP = 0.0               # execution.py:910 yorum: maker = %0
N_BOOT = 5000
TOHUM = 20260928
SL_ATR = {"donchian": 2.0, "squeeze": 2.0}   # yedek stop doğrulaması (yalnız bu iki kol)
ATR_TOL = 0.02
ANLAMSIZ_PCT = 0.5           # üst sınır < canlı net kârın %0.5'i → "anlamsız küçük"
KAYDA_DEGER_PCT = 2.0        # üst sınır ≥ canlı net kârın %2'si → "kayda değer"
R_ANLAMSIZ, R_KAYDA_DEGER = 0.005, 0.02   # net kâr ≤ 0 ise R/işlem ölçütü


def _utc(x):
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# ─────────────────────────── veri ───────────────────────────
def defter(db):
    con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, symbol, side, entry_price, exit_price, quantity, sl_price, entry_time, "
        "exit_time, pnl_usdt, fees_usdt, exit_reason, strategy_scores FROM trades "
        "WHERE is_paper=0 ORDER BY entry_time")]
    con.close()
    return rows


def journal_tahmini(bas, bit):
    """'Close fill price unavailable' uyarılarının zamanları (UTC). None = journal okunamadı."""
    temel = ["journalctl", "-u", "btc-bot", "--since", bas.strftime("%Y-%m-%d %H:%M:%S"),
             "--until", bit.strftime("%Y-%m-%d %H:%M:%S"), "--no-pager", "-o",
             "short-iso-precise", "--utc"]
    satirlar = None
    for ek in (["--grep", "Close fill price unavailable"], []):   # eski systemd: --grep yok
        try:
            cik = subprocess.run(temel + ek, capture_output=True, text=True, timeout=300)
        except Exception:
            continue
        if cik.returncode in (0, 1):
            satirlar = [x for x in cik.stdout.splitlines() if "Close fill price unavailable" in x]
            break
    if satirlar is None:
        return None
    out = []
    for s in satirlar:
        try:
            out.append(_utc(s.split()[0]))
        except Exception:
            pass
    return out


def mum_cek_ccxt(coin, bas, bit):
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}})
    since = int(bas.timestamp() * 1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(f"{coin}/USDT:USDT", "1h", since=since, limit=500)
        if not b:
            break
        rows += b
        if len(b) < 500 or b[-1][0] >= int(bit.timestamp() * 1000):
            break
        since = b[-1][0] + 1
    d = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    d["ts"] = pd.to_datetime(d["ts"], unit="ms", utc=True)
    return d.drop_duplicates("ts").set_index("ts").sort_index()


def mum_cek_yerel(klasor, coin):
    d = pd.read_csv(os.path.join(klasor, f"{coin}_fut_1h.csv"))
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    return d.drop_duplicates("ts").set_index("ts").sort_index()


# ─────────────────────────── kurulum ───────────────────────────
def stop0(t, kol):
    ss = EU._skor(t)
    try:
        if ss.get("sl0"):
            return float(ss["sl0"]), "sl0"
    except (TypeError, ValueError):
        pass
    if kol in SL_ATR:
        try:
            atr, sp = float(ss.get("atr")), float(t["sl_price"])
            niyet = float(ss.get("intended_entry") or t["entry_price"])
            if atr > 0 and abs(abs(niyet - sp) / (SL_ATR[kol] * atr) - 1) <= ATR_TOL:
                return sp, "sl_price(ATR doğrulandı)"
        except (TypeError, ValueError):
            pass
    return float("nan"), "yok"


def kur(adaylar, mumlar, tahmini):
    """Her aday için karar mumu, referans, kayma. (geçerli_df, elenen_sayim, tutarsız_n)"""
    sat, ele = [], {}
    tutarsiz = 0

    def say(k):
        ele[k] = ele.get(k, 0) + 1

    for t in adaylar:
        kol = EU.kol_adi(t.get("strategy_scores"))
        ss = EU._skor(t)
        coin = str(t["symbol"]).split("/")[0].upper()
        if ss.get("exit_price_estimated"):
            say("exit_price_estimated işaretli")
            continue
        et, xt = _utc(t["entry_time"]), _utc(t["exit_time"])
        mh = ss.get("max_hold")
        mh_kaynak = "strategy_scores" if mh is not None else "varsayılan 48"
        mh = int(mh if mh is not None else MAX_HOLD_VARSAYILAN)
        max_age = mh * TF_SN
        C = xt.floor("h")                         # karar işleyicisini tetikleyen mum KAPANIŞI
        gecikme = (xt - C).total_seconds()
        yas = (xt - et).total_seconds()
        # tutarlılık: (1) çıkış mum kapanışından ≤300 sn sonra, (2) yaş ≥ max_age,
        # (3) İLK uygun kapanışta tetiklenmiş (yaş − max_age < 1 saat + 300 sn)
        if not (0 <= gecikme <= GECIKME_MAX and yas >= max_age and yas - max_age < TF_SN + GECIKME_MAX):
            tutarsiz += 1
            say("zamanlama tutarsız (gecikme>300sn / erken / ilk uygun mumda değil — restart?)")
            continue
        if tahmini is not None and any(timedelta(0) <= xt - w <= timedelta(seconds=30) for w in tahmini):
            say("dolum TAHMİNİ (journal: 'Close fill price unavailable')")
            continue
        d = mumlar.get(coin)
        acilis = C - timedelta(hours=1)           # referans mum: [C−1h, C) ; ccxt ts = AÇILIŞ
        if d is None or acilis not in d.index:
            say("referans mum yok")
            continue
        ref = float(d.loc[acilis, "close"])
        fill = float(t["exit_price"])
        if not (ref > 0 and fill > 0):
            say("fiyat bozuk")
            continue
        yon = 1 if str(t["side"]).lower() in ("long", "buy") else -1
        bp = (ref - fill) / ref * 1e4 if yon == 1 else (fill - ref) / ref * 1e4
        sl, sk = stop0(t, kol)
        ep = float(t["entry_price"])
        stop_pct = abs(ep - sl) / ep if np.isfinite(sl) and sl > 0 else float("nan")
        nom = fill * float(t["quantity"])
        sat.append(dict(
            trade_id=t["id"], symbol=coin, kol=kol, side="long" if yon == 1 else "short",
            entry_time=et, max_hold=mh, max_hold_kaynak=mh_kaynak,
            max_age_saat=max_age / 3600, decision_time=C, ref_candle_open=acilis,
            ref_candle_close_time=C, reference_price=ref, exit_time=xt, actual_fill=fill,
            latency_s=gecikme, slippage_bp=bp, stop_kaynak=sk, initial_stop_pct=stop_pct,
            exit_slippage_R=(bp / 1e4) / stop_pct if stop_pct > 0 else float("nan"),
            fee_R=(TAKER_BP / 1e4) / stop_pct if stop_pct > 0 else float("nan"),
            notional_usdt=nom, pnl_usdt=t.get("pnl_usdt")))
    return pd.DataFrame(sat), ele, tutarsiz


def lookahead(m):
    if m.empty:
        return 0
    k1 = m["decision_time"] > m["exit_time"]
    k2 = (m["ref_candle_open"] + pd.Timedelta(hours=1)) > m["exit_time"]
    k3 = m["ref_candle_close_time"] > m["decision_time"]
    return int((k1 | k2 | k3).sum())


# ─────────────────────────── istatistik ───────────────────────────
def boot_ga(x):
    x = np.asarray(x, float)
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(TOHUM)
    o = rng.choice(x, (N_BOOT, len(x))).mean(1)
    return float(np.percentile(o, 2.5)), float(np.percentile(o, 97.5))


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan"), float("nan")
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(TOHUM)
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(N_BOOT)])
    return rho, float((np.abs(perm) >= abs(rho) - 1e-12).mean())


def orneklem(n):
    return "yalnız betimsel" if n < 10 else "zayıf örneklem" if n < 20 else "yorumlanabilir"


def main(argv=None):
    ap = argparse.ArgumentParser(description="canlı max_hold çıkış maliyeti (salt okur)")
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--cikti", default="/tmp/max_hold_execution_audit")
    ap.add_argument("--veri", default=None, help="MEXC yerine {COIN}_fut_1h.csv klasörü (test)")
    ap.add_argument("--journal-yok", action="store_true", help="journalctl okuma (test)")
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        sys.exit(f"DB yok: {a.db}")

    tum = defter(a.db)
    adaylar = [t for t in tum if str(t.get("exit_reason") or "").lower() == "max_hold"
               and t.get("exit_time") and t.get("exit_price")]
    print(f"max_hold_execution_audit · DB {a.db} (is_paper=0, salt okur) · canlı işlem {len(tum)}")
    print(f"  çıkış nedenleri: {pd.Series([t.get('exit_reason') for t in tum]).value_counts().to_dict()}")
    print(f"  max_hold aday: {len(adaylar)}")

    mumlar = {}
    if adaylar:
        xs = [_utc(t["exit_time"]) for t in adaylar]
        bas, bit = min(xs) - timedelta(hours=3), max(xs) + timedelta(hours=1)
        for coin in sorted({str(t["symbol"]).split("/")[0].upper() for t in adaylar}):
            try:
                mumlar[coin] = mum_cek_yerel(a.veri, coin) if a.veri else mum_cek_ccxt(coin, bas, bit)
            except Exception as e:
                print(f"  ⚠ {coin} mum okunamadı: {e}")
        tahmini = None if a.journal_yok else journal_tahmini(bas - timedelta(hours=1), bit)
    else:
        tahmini = None
    if a.journal_yok:
        print("  journal: OKUNMADI (--journal-yok) → tahmini dolum denetimi YAPILMADI")
    elif tahmini is None:
        print("  ⚠ journal okunamadı → tahmini dolum denetimi YAPILAMADI")
    else:
        print(f"  journal: 'Close fill price unavailable' uyarısı {len(tahmini)} (aday aralığında)")

    m, ele, tutarsiz = kur(adaylar, mumlar, tahmini)
    ihlal = lookahead(m)
    os.makedirs(a.cikti, exist_ok=True)
    csv_yol = os.path.join(a.cikti, "max_hold_trades.csv")
    m.to_csv(csv_yol, index=False)
    n_ad, n = len(adaylar), len(m)
    rec_ok = n_ad > 0 and (n_ad - tutarsiz) / n_ad >= REC_PASS_ORAN and ihlal == 0
    print(f"\n  geçerli {n} · elenen {n_ad - n}: {ele or '-'}")
    print(f"  zamanlama tutarlılığı: {n_ad - tutarsiz}/{n_ad} "
          f"(PASS eşiği %{REC_PASS_ORAN * 100:.0f}) · lookahead ihlali {ihlal}")
    print(f"  işlem düzeyi CSV: {csv_yol}")

    if not m.empty:
        print("\n== SELF-CHECK (ilk 8 geçerli işlem; referans = karar mumunun kapanışı)")
        cols = ["symbol", "side", "entry_time", "max_hold", "decision_time", "ref_candle_open",
                "reference_price", "exit_time", "actual_fill", "slippage_bp"]
        g = m[cols].head(8).copy()
        for c in ("entry_time", "decision_time", "ref_candle_open", "exit_time"):
            g[c] = g[c].dt.strftime("%m-%d %H:%M:%S")
        print(g.to_string(index=False, float_format=lambda v: f"{v:.6g}"))

    x = m["slippage_bp"].to_numpy(float) if n else np.array([])
    r = m["exit_slippage_R"].dropna().to_numpy(float) if n else np.array([])
    fr = m["fee_R"].dropna().to_numpy(float) if n else np.array([])
    lo, hi = boot_ga(x)
    if n:
        print("\n== ANA ÖLÇÜM (+ = aleyhe; ücret HARİÇ)")
        print(f"  n {n} · ort {x.mean():+.2f}bp · medyan {np.median(x):+.2f} · std {x.std(ddof=1) if n > 1 else 0:.2f} · "
              f"p25/p75 {np.percentile(x, 25):+.2f}/{np.percentile(x, 75):+.2f} · p90 {np.percentile(x, 90):+.2f} · "
              f"min/max {x.min():+.2f}/{x.max():+.2f} · %95 GA [{lo:+.2f}, {hi:+.2f}] ({orneklem(n)})")
        print(f"  kayma R (n={len(r)}; stop kaynağı {m['stop_kaynak'].value_counts().to_dict()}): "
              f"ort {r.mean() if len(r) else float('nan'):+.4f} · medyan {np.median(r) if len(r) else float('nan'):+.4f}")
        print(f"  gecikme (karar mumu kapanışı → exit_time): ort {m.latency_s.mean():.1f} sn · "
              f"medyan {m.latency_s.median():.1f} sn")
        print(f"  market çıkış ücreti {TAKER_BP:.2f}bp (taker; maker {MAKER_BP:.2f}bp) · "
              f"toplam çıkış maliyeti ort {x.mean() + TAKER_BP:+.2f}bp")
        print("\n== KOL BAZINDA (betimsel)")
        for k, g in m.groupby("kol"):
            print(f"  {k:<9s} n={len(g):>3d} ort {g.slippage_bp.mean():+.2f}bp medyan "
                  f"{g.slippage_bp.median():+.2f} ort R {g.exit_slippage_R.mean():+.4f} ({orneklem(len(g))})")

    # ── ekonomi ──
    kapali = [t for t in tum if t.get("exit_time") and t.get("pnl_usdt") is not None]
    net = float(sum(t["pnl_usdt"] for t in kapali))
    if kapali:
        span = (max(_utc(t["exit_time"]) for t in kapali) - min(_utc(t["entry_time"]) for t in kapali))
        gun = max(span.total_seconds() / 86400, 1.0)
    else:
        gun = float("nan")
    ust_usd = float(((m.slippage_bp + TAKER_BP - MAKER_BP) / 1e4 * m.notional_usdt).sum()) if n else float("nan")
    ust_R = float(np.nanmean(m.exit_slippage_R + m.fee_R)) if n and m.exit_slippage_R.notna().any() else float("nan")
    yillik = ust_usd / gun * 365 if n else float("nan")
    pct = ust_usd / net * 100 if n and net > 0 else float("nan")
    if n:
        print("\n== PERFECT_FILL_SAVING_UPPER_BOUND (kusursuz dolum varsayımı; gerçek limit getirisi DEĞİL)")
        print(f"  toplam ${ust_usd:+.2f} · işlem başı {ust_R:+.4f}R · yıllık ${yillik:+.2f} "
              f"(canlı dönem {gun:.0f} gün) · canlı net PnL ${net:+.2f} → "
              + (f"%{pct:.2f}" if np.isfinite(pct) else "yüzde tanımsız (net PnL ≤ 0)"))

    # ── nominal ──
    iliski_rho, iliski_p = float("nan"), float("nan")
    if n >= 20:
        iliski_rho, iliski_p = spearman(m.notional_usdt, m.slippage_bp)
        print(f"\n== NOMİNAL / KAYMA: Spearman rho {iliski_rho:+.3f} p {iliski_p:.3f}")
        q = pd.qcut(m.notional_usdt, 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for k, g in m.groupby(q, observed=True):
            print(f"  {k} n={len(g)} medyan nominal ${g.notional_usdt.median():,.0f} "
                  f"ort {g.slippage_bp.mean():+.2f}bp medyan {g.slippage_bp.median():+.2f}")
    else:
        print(f"\n== NOMİNAL / KAYMA: n={n} < 20 → INSUFFICIENT")

    # ── hüküm (önceden sabit) ──
    if ihlal:
        hukum = "TEST INVALID"
    elif not rec_ok or n < 15:
        hukum = "D"
    elif n < 30:
        hukum = "D"          # 15 ≤ n < 30: yalnız keşif
    else:
        if np.isfinite(pct):
            onemli, anlamsiz = pct >= KAYDA_DEGER_PCT, pct < ANLAMSIZ_PCT
        else:
            onemli, anlamsiz = ust_R >= R_KAYDA_DEGER, ust_R < R_ANLAMSIZ
        if lo > 0 and onemli:
            hukum = "A"
        elif anlamsiz and (x.mean() <= 0 or lo <= 0):
            hukum = "C"
        else:
            hukum = "B"

    def f(v, fmt):
        return format(v, fmt) if np.isfinite(v) else "-"

    print("\n" + "=" * 60)
    print(f"MAX_HOLD candidate n: {n_ad}")
    print(f"valid n: {n}")
    print(f"excluded n: {n_ad - n}")
    print()
    print(f"mean slippage bp: {f(x.mean() if n else np.nan, '+.2f')}")
    print(f"median slippage bp: {f(np.median(x) if n else np.nan, '+.2f')}")
    print(f"95% CI: [{f(lo, '+.2f')}, {f(hi, '+.2f')}]")
    print()
    print(f"mean slippage R: {f(r.mean() if len(r) else np.nan, '+.4f')}")
    print()
    print(f"mean/median execution latency: {f(m.latency_s.mean() if n else np.nan, '.1f')} / "
          f"{f(m.latency_s.median() if n else np.nan, '.1f')} sn")
    print()
    print(f"market fee bp: {TAKER_BP:.2f}")
    print()
    print("PERFECT_FILL_SAVING_UPPER_BOUND:")
    print(f"$: {f(ust_usd, '+.2f')}  (yıllık {f(yillik, '+.2f')})")
    print(f"R/trade: {f(ust_R, '+.4f')}")
    print(f"% of live net profit: {f(pct, '.2f') if np.isfinite(pct) else 'tanımsız (net PnL ≤ 0)'}")
    print()
    print("notional-slippage:")
    print(f"rho: {f(iliski_rho, '+.3f') if n >= 20 else 'INSUFFICIENT'}")
    print(f"p: {f(iliski_p, '.3f') if n >= 20 else 'INSUFFICIENT'}")
    print()
    print("RECONSTRUCTION:")
    print("PASS" if rec_ok else "FAIL")
    print()
    print("HÜKÜM:")
    ek = "  (15 ≤ n < 30: yalnız keşif)" if hukum == "D" and rec_ok and 15 <= n < 30 else ""
    print(hukum + ek)
    return hukum


if __name__ == "__main__":
    main()
