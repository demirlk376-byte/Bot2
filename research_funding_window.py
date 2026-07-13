"""
research_funding_window.py — Funding-penceresi sapması ailesi. Sprint #4 (son).

NEDEN BU AİLE: perp funding ödemesi 00/08/16 UTC'de kesilir. Hipotez
(literatürde belgeli, kontraryan taşıma): funding AŞIRI pozitifken longlar
kalabalık ve ödemeye sıkışmıştır → kesinti penceresi etrafında fiyat aşağı
sapar (short lehine); aşırı negatifte ayna. Bu, SPOT veride görünmez —
perp kline + tarihsel funding oranı gerekir (ikisi de binance vision'da).

MEKANİK (ön-kayıtlı, kontraryan):
  funding >= +P persentil (son 90 günün dağılımında) → kesintiden 4h önce SHORT
  funding <= -P persentil                            → kesintiden 4h önce LONG
  Çıkış: kesinti anında (H=0) ya da +4h sonrasında (H=4). Fee 2 taker bacağı.
  Grid: P ∈ {80, 90, 95} × H ∈ {0, 4}  → 6 hücre. BTC karar, ETH doğrulama.

ÖN-KAYITLI KABUL ÇITASI:
  BTC'de TRAIN(2023-24) PF >= 1.2 VE TEST(2025-26) PF >= 1.2 VE n >= 50,
  >= 2 KOMŞU hücrede; VE bunların yarısı ETH'de iki dönem PF >= 1.0.
  Geçerse paper-forward; geçmezse AİLE (ve sprint) MÜHÜRLENİR.

Kullanım (VPS):  venv/bin/python research_funding_window.py
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import requests

YEARS = [2023, 2024, 2025, 2026]
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
FEE_LEG = 0.0001
BASE = "https://data.binance.vision/data/futures/um/monthly"

GRID_P = [80, 90, 95]
GRID_H = [0, 4]          # çıkış: kesinti anı / +4h
PRE_H  = 4               # giriş: kesintiden 4h önce


def _fetch_zip_csv(url: str, names: list[str] | None) -> pd.DataFrame | None:
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(r.content)) as z, z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, header=None, names=names) if names else pd.read_csv(f)
    except Exception:
        return None


def load_klines(sym: str) -> pd.DataFrame:
    fr = []
    for y in YEARS:
        for m in range(1, 13):
            d = _fetch_zip_csv(
                f"{BASE}/klines/{sym}/1h/{sym}-1h-{y}-{m:02d}.zip",
                ["ts", "open", "high", "low", "close", "volume",
                 "ct", "qv", "n", "a", "b", "c"])
            if d is None:
                continue
            d = d[pd.to_numeric(d["ts"], errors="coerce").notna()].copy()
            d["ts"] = pd.to_numeric(d["ts"])
            unit = "us" if d["ts"].iloc[0] > 1e15 else "ms"
            d.index = pd.to_datetime(d["ts"], unit=unit, utc=True)
            fr.append(d[["open", "high", "low", "close"]].astype(float))
    if not fr:
        raise RuntimeError(f"kline yok: {sym}")
    return pd.concat(fr).sort_index()


def load_funding(sym: str) -> pd.Series:
    fr = []
    for y in YEARS:
        for m in range(1, 13):
            d = _fetch_zip_csv(f"{BASE}/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip",
                               None)
            if d is None:
                continue
            # kolon adları sürüme göre değişebiliyor — savunmacı tespit:
            cols = {c.lower(): c for c in d.columns}
            tcol = next((cols[k] for k in cols if "time" in k), d.columns[0])
            rcol = next((cols[k] for k in cols if "rate" in k), d.columns[-1])
            d = d[[tcol, rcol]].copy()
            d.columns = ["ts", "rate"]
            d = d[pd.to_numeric(d["ts"], errors="coerce").notna()]
            d["ts"] = pd.to_numeric(d["ts"])
            unit = "us" if d["ts"].iloc[0] > 1e15 else "ms"
            d.index = pd.to_datetime(d["ts"], unit=unit, utc=True)
            fr.append(d["rate"].astype(float))
    if not fr:
        raise RuntimeError(f"funding yok: {sym}")
    s = pd.concat(fr).sort_index()
    return s[~s.index.duplicated()]


def run(kl: pd.DataFrame, fund: pd.Series, pctl: int, exit_h: int) -> list[dict]:
    close = kl["close"]
    trades: list[dict] = []
    # persentil eşiği: son 90 günün |funding| dağılımı (bakış-öncesi, rolling)
    abs_roll = fund.abs().rolling(90 * 3, min_periods=60).quantile(pctl / 100.0)
    for ts, rate in fund.items():
        thr = abs_roll.get(ts, np.nan)
        if np.isnan(thr) or thr <= 0 or abs(rate) < thr:
            continue
        d = -1 if rate > 0 else 1          # kontraryan: kalabalığın tersine
        t_in = ts - pd.Timedelta(hours=PRE_H)
        t_out = ts + pd.Timedelta(hours=exit_h)
        try:
            p_in = close.asof(t_in)
            p_out = close.asof(t_out)
        except Exception:
            continue
        if p_in is None or p_out is None or np.isnan(p_in) or np.isnan(p_out) or p_in <= 0:
            continue
        pnl = d * (p_out / p_in - 1.0) - 2 * FEE_LEG
        trades.append({"pnl": pnl, "ts": ts})
    return trades


def stats(tr):
    if not tr:
        return {"n": 0, "pf": 0.0, "tot": 0.0}
    p = [t["pnl"] for t in tr]
    gp = sum(x for x in p if x > 0); gl = -sum(x for x in p if x < 0)
    return {"n": len(p), "pf": (gp / gl) if gl > 0 else 9.99, "tot": sum(p)}


def main() -> None:
    print("Perp kline + funding geçmişi indiriliyor (BTC, ETH — 2023-2026)...")
    kb, fb = load_klines("BTCUSDT"), load_funding("BTCUSDT")
    ke, fe = load_klines("ETHUSDT"), load_funding("ETHUSDT")
    print(f"BTC: {len(kb)} bar, {len(fb)} funding | ETH: {len(ke)} bar, {len(fe)} funding")

    print("\n" + "=" * 84)
    print("  FUNDING-PENCERESİ KONTRARYAN (#4) — BTC karar / ETH doğrulama (pnl: %)")
    print("=" * 84)
    print(f"  {'P':>3} {'H':>2} | {'BTC-TR n':>8} {'PF':>5} {'tot%':>7} | "
          f"{'BTC-TE n':>8} {'PF':>5} {'tot%':>7} | {'ETH TR/TE PF':>13} | karar")
    print("  " + "-" * 80)
    passed = 0
    for p_ in GRID_P:
        for h_ in GRID_H:
            trb = run(kb, fb, p_, h_)
            a = stats([x for x in trb if x["ts"] < SPLIT])
            z = stats([x for x in trb if x["ts"] >= SPLIT])
            tre = run(ke, fe, p_, h_)
            ea = stats([x for x in tre if x["ts"] < SPLIT])
            ez = stats([x for x in tre if x["ts"] >= SPLIT])
            ok = (a["pf"] >= 1.2 and z["pf"] >= 1.2 and (a["n"] + z["n"]) >= 50)
            passed += ok
            print(f"  {p_:>3} {h_:>2} | {a['n']:>8} {a['pf']:>5.2f} {a['tot']*100:>+6.1f}% | "
                  f"{z['n']:>8} {z['pf']:>5.2f} {z['tot']*100:>+6.1f}% | "
                  f"{ea['pf']:>5.2f}/{ez['pf']:<5.2f} | {'PASS' if ok else 'no'}")

    print("\n  ÖN-KAYITLI KARAR: BTC'de >=2 KOMŞU PASS + yarısı ETH'de iki dönem")
    print("  PF>=1.0 → paper-forward. Aksi halde AİLE (ve sprint) MÜHÜRLENİR.")
    print(f"  Sonuç: {passed}/6 BTC-PASS")


if __name__ == "__main__":
    main()
