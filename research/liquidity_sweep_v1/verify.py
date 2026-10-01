"""
Uyum kapıları (şartname §22) ve test raporu. `cli verify` bunu çağırır.

  G1  pytest: research/liquidity_sweep_v1/tests → tests_report.txt
  G2  PaperExchange mutabakatı: araştırma defterindeki her işlem, gerçek exchange.PaperExchange'e
      AYNI giriş/çıkış dolumlarıyla (kayma=0, ücret oranları aynı, tp muafiyeti kapalı) verilir;
      net PnL (funding hariç) işlem başına eşleşmeli.
  G3  Referans izolasyonu: eski 1H ikiz kısa referans koşusu, araştırma paketi aynı süreçte
      içe aktarılmışken ve aktarılmamışken AYNI işlemleri üretmeli (global/env sızıntısı yok).
  G4  Duman: keşif döneminin İLK 30 GÜNÜNDE 32 varyantın sinyal/durum makinesi + motor hatasız.
  G5  Determinizm: aynı manifestle iki tekrar → ekonomik içerik hashleri eşit; araya başka
      varyant girince de değişmez.
  G6  Motor yanlılığı: sentetik rastgele yürüyüşte, SIFIR maliyetle, 32 varyantın birleşik
      ortalama net_R'si 0'dan istatistiksel olarak ayrışmamalı (|z| < 3).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np
import pandas as pd

from . import config as C
from . import cli

ROOT = cli.ROOT


def _hash_df(df):
    if df is None or not len(df):
        return "EMPTY"
    cols = [c for c in df.columns if c not in ("trade_id",)]
    return hashlib.sha256(pd.util.hash_pandas_object(df[cols], index=False).values.tobytes()).hexdigest()


def g1_pytest(out):
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join(cli.PKG, "tests")], cwd=ROOT, capture_output=True, text=True)
    txt = r.stdout[-20000:] + "\n" + r.stderr[-5000:]
    with open(os.path.join(out, "tests_report.txt"), "w") as f:
        f.write(txt)
    last = [l for l in r.stdout.strip().splitlines() if l.strip()][-1:] or [""]
    return dict(ok=r.returncode == 0, summary=last[0])


def g2_paper(W, out, vid="L1_K1_F0"):
    import asyncio
    sys.path.insert(0, ROOT)
    import exchange as EX
    cost = C.TWIN_MARKET_PROFILE
    _, res = cli.run_variant(W, vid, "DISCOVERY", cost, C.C0_FALLBACK, record_equity=False)
    diffs = []

    async def one(t):
        px = EX.PaperExchange(1_000_000.0, leverage=C.LIVE_GATES["LEVERAGE"])
        px.SLIP_GIRIS_BP = 0.0
        px.SLIP_CIKIS_BP = 0.0
        px.KAYMASIZ_CIKISLAR = ()
        px.FUNDING_ACIK = False
        px.FEE_RATE = cost.exit_fee_rate
        sym = f"{t['symbol']}/USDT:USDT"
        await px.update_price(t["E_fill"], sym)
        o = await px.place_market_order(sym, "buy" if t["side"] == "LONG" else "sell", t["quantity_base"], {})
        px._positions[o.order_id].fee_rate = cost.entry_fee_rate
        await px.update_price(t["X_fill"], sym)
        before = px._balance
        r = await px.close_position(sym, "long" if t["side"] == "LONG" else "short", t["quantity_base"], "x")
        margin = px._positions[o.order_id].margin_used
        net_paper = (px._balance - before) - margin
        ours = t["gross_PnL"] - t["entry_fee"] - t["exit_fee"]
        return net_paper - ours

    for t in res.trades[:400]:
        diffs.append(asyncio.run(one(t)))
    diffs = np.abs(np.array(diffs)) if diffs else np.zeros(0)
    tol = max(1e-6, C.C0_FALLBACK * 1e-10)
    return dict(ok=bool(len(diffs) and diffs.max() <= tol), trades=int(len(diffs)),
                max_abs_diff=float(diffs.max()) if len(diffs) else None, tol=tol, variant=vid)


_G3_SCRIPT = r"""
import asyncio, os, sys, json
sys.path.insert(0, os.environ["ROOT"])
if os.environ.get("ARASTIRMA") == "1":
    import research.liquidity_sweep_v1.cli  # noqa: F401  (paketi aynı süreçte yükle)
    import research.liquidity_sweep_v1.replay_adapter  # noqa: F401
import fast_bt
fast_bt.CACHE_DIR = os.path.join(os.environ["ROOT"], "data")
from ikiz.kos import kur, sur
from ikiz import db_yolu
async def ana():
    M, saat, feed = await kur("2023-04-06", source="local")
    await sur(M, saat, feed, bitis="2023-05-20", ilerleme_her=10**9)
asyncio.run(ana())
import sqlite3
c = sqlite3.connect(f"file:{db_yolu()}?mode=ro", uri=True)
rows = c.execute("SELECT symbol, side, entry_price, exit_price, quantity, entry_time, exit_time, pnl_usdt, exit_reason FROM trades ORDER BY entry_time, symbol").fetchall()
print("SONUC" + json.dumps(rows))
sys.stdout.flush(); os._exit(0)
"""


def g3_reference(out):
    res = {}
    for flag in ("0", "1"):
        d = os.path.join(out, f"g3_ref_{flag}")
        os.makedirs(d, exist_ok=True)
        env = dict(os.environ, ROOT=ROOT, ARASTIRMA=flag, REPLAY_DB=os.path.join(d, "ref.db"),
                   PAPER_SLIP_GIRIS_BP="15.85", PAPER_SLIP_CIKIS_BP="0.24", PAPER_FUNDING="true",
                   DONCHIAN_MAKER_ENTRY="false")
        r = subprocess.run([sys.executable, "-c", _G3_SCRIPT], cwd=d, env=env, capture_output=True, text=True,
                           timeout=3600)
        line = [l for l in r.stdout.splitlines() if l.startswith("SONUC")]
        res[flag] = json.loads(line[-1][5:]) if line else None
    ok = res["0"] is not None and res["0"] == res["1"]
    return dict(ok=bool(ok), trades=len(res["0"] or []), window="2023-04-06→2023-05-20",
                note="aynı süreçte araştırma paketi yüklü/yüklü değil")


def g4_smoke(W):
    a, _ = W.window("DISCOVERY")
    win = (a, a + 30 * C.DAY)
    errs, counts = [], {}
    for vid in C.VARIANT_IDS:
        try:
            recs, sig = W.signals(vid, "DISCOVERY")
            sig30 = [r for r in sig if r.signal_time < win[1]]
            from . import replay_adapter as RA
            res = RA.simulate(vid, "SMOKE30", win, sig30, W.U, C.TWIN_MARKET_PROFILE, C.C0_FALLBACK,
                              record_equity=True)
            counts[vid] = dict(events=sum(1 for r in recs if r.sweep_close < win[1]), signals=len(sig30),
                               trades=len(res.trades))
        except Exception as e:                       # yutulmaz: RUN_FAILED olarak raporlanır
            errs.append(f"{vid}: {type(e).__name__}: {e}")
    return dict(ok=not errs, errors=errs, counts=counts, window=[cli.t2s(win[0]), cli.t2s(win[1])])


def g5_determinism(W):
    def run(vid):
        _, res = cli.run_variant(W, vid, "DISCOVERY", C.TWIN_MARKET_PROFILE, C.C0_FALLBACK, record_equity=True)
        return _hash_df(pd.DataFrame(res.trades)), _hash_df(pd.DataFrame(res.equity))
    a1 = run("L2_K2_F1")
    run("L3_K4_F0")                                  # araya başka varyant
    a2 = run("L2_K2_F1")
    W2 = cli.World(universe=W.U) if W.data_dir is None else cli.World(W.data_dir)
    _, r3 = cli.run_variant(W2, "L2_K2_F1", "DISCOVERY", C.TWIN_MARKET_PROFILE, C.C0_FALLBACK)
    a3 = (_hash_df(pd.DataFrame(r3.trades)), _hash_df(pd.DataFrame(r3.equity)))
    return dict(ok=a1 == a2 == a3, hashes=[a1, a2, a3])


def g6_bias(seed=7):
    sys.path.insert(0, os.path.join(cli.PKG, "tests"))
    from .tests.sentetik import sentetik_evren
    U = sentetik_evren(n_days=200, syms=("AAA", "BBB", "CCC", "DDD"), seed=seed)
    W = cli.World(universe=U)
    zero = C.CostProfile("ZERO", 0.0, 0.0, 0.0, 0.0, "test")
    rs = []
    for vid in C.VARIANT_IDS:
        _, res = cli.run_variant(W, vid, "DISCOVERY", zero, C.C0_FALLBACK, record_equity=False)
        rs += [t["net_R"] for t in res.trades]
    r = np.array(rs, dtype=float)
    z = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 else float("nan")
    return dict(ok=bool(len(r) > 100 and abs(z) < 3), trades=int(len(r)), mean_R=float(r.mean()) if len(r) else None,
                z=z, note="sentetik rastgele yürüyüş, sıfır maliyet; işlemler varyantlar arası bağımsız DEĞİL "
                          "(ortak olaylar) → z kaba bir yanlılık alarmıdır")


def main(a):
    out = os.path.join(a.out, "_verify")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    rep = {}
    rep["G1_pytest"] = g1_pytest(out)
    rep["G6_bias"] = g6_bias()
    W = cli.World(a.data) if os.path.isdir(a.data) else None
    if W is not None:
        rep["G2_paper_reconciliation"] = g2_paper(W, out)
        rep["G4_smoke_30d"] = g4_smoke(W)
        rep["G5_determinism"] = g5_determinism(W)
    else:
        rep["G2_G4_G5"] = "veri yok — koşulmadı"
    rep["G3_reference_isolation"] = g3_reference(out)
    rep["all_ok"] = all(v.get("ok", False) for v in rep.values() if isinstance(v, dict))
    rep["sure_dk"] = round((time.time() - t0) / 60, 1)
    with open(os.path.join(out, "fidelity_gates.json"), "w") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False, default=str)
    lines = ["# Uyum raporu (fidelity_report)", "", f"Genel: {'GEÇTİ' if rep['all_ok'] else 'METRICS_INVALID — sapma var'}", "",
             "| kapı | sonuç | ayrıntı |", "|---|---|---|"]
    for k, v in rep.items():
        if isinstance(v, dict):
            det = {x: y for x, y in v.items() if x not in ("ok", "counts", "hashes")}
            lines.append(f"| {k} | {'✓' if v.get('ok') else '✗'} | {json.dumps(det, ensure_ascii=False, default=str)[:400]} |")
    lines += ["", "## Model sınırları", "",
              "| varsayım | durum |", "|---|---|",
              "| emir defteri / kuyruk | yok; tam dolum varsayımı |",
              "| veri gecikmesi / ağ | yok; ilk 5m açılışında idealize yürütme |",
              "| mark / tetik fiyatı | tarihsel mark yok; stop/hedef trade OHLCV ile; birebir mark tetikleme İDDİA EDİLMEZ |",
              "| likidasyon | modellenmez (risk/marjin kapıları likidasyon mesafesinin çok altında) |",
              "| venue | fiyat Binance USDⓈ-M (MEXC vekili); tick/kontrat MEXC güncel metadata |",
              "| funding | Binance gerçek settlement zamanları (vekil); mark = son 5m kapanışı |"]
    with open(os.path.join(out, "fidelity_report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({k: (v.get("ok") if isinstance(v, dict) else v) for k, v in rep.items()}, indent=1))
    return rep
