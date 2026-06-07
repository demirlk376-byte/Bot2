"""
paper_scanner_v2.py — Teknik + Makro filtreli BB-fade paper bot.

V1 ile fark:
  Sinyal açılmadan önce 2 makro filtre kontrol edilir:
    1. Fear & Greed indeksi (Alternative.me, ücretsiz, API key yok)
    2. Funding rate (MEXC perpetual, public endpoint)

  Kural (mean-reversion mantığı):
    SHORT sinyali açılır EĞER: F&G > 55 (açgözlülük) VEYA funding > +0.01%
    LONG  sinyali açılır EĞER: F&G < 45 (korku)      VEYA funding < -0.01%
    İkisi de çelişiyorsa → sinyal ATLANDI

  Amaç: V1 (saf teknik) ile V2 (teknik+makro) yan yana koşar.
  4-8 hafta sonra hangisi daha iyi sonuç verdiği veriyle görülür.

Dosyalar (V1'den ayrı):
  paper_state_v2.json, paper_trades_v2.csv, paper_signals_v2.csv, paper_summary_v2.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

# ── Parametreler (V1 ile aynı) ─────────────────────────────────────────────────
BB_PERIOD   = 20
BB_STD      = 2.0
ATR_PERIOD  = 14
SL_MULT     = 3.0
TP_MULT     = 5.0
MAX_HOLD_H  = 48
RISK_PCT    = 0.03
COST        = 0.0002
VOL_MA      = 20
INIT_BAL    = 10_000.0

STATE_FILE  = Path("paper_state_v2.json")
TRADES_CSV  = Path("paper_trades_v2.csv")
SIGNALS_CSV = Path("paper_signals_v2.csv")

DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# Makro filtre eşikleri
FNG_SHORT_MIN  = 55    # F&G bu değerin üstündeyse SHORT onaylı (açgözlülük)
FNG_LONG_MAX   = 45    # F&G bu değerin altındaysa LONG onaylı (korku)
FUND_SHORT_MIN = 0.0001  # funding > +0.01% → SHORT onaylı
FUND_LONG_MAX  = -0.0001 # funding < -0.01% → LONG  onaylı


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{now_utc():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ── Makro veri ────────────────────────────────────────────────────────────────

def get_fear_greed() -> int | None:
    """0-100 Fear & Greed indeksi. 0=aşırı korku, 100=aşırı açgözlülük."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        r.raise_for_status()
        return int(r.json()["data"][0]["value"])
    except Exception as e:
        log(f"  ! F&G indeksi alınamadı: {e}")
        return None


def get_funding_rate(ex, symbol: str) -> float | None:
    """Anlık funding rate (örn. 0.0001 = +0.01%)."""
    try:
        info = ex.fetch_funding_rate(symbol)
        return float(info.get("fundingRate", 0) or 0)
    except Exception as e:
        log(f"  ! {symbol} funding alınamadı: {e}")
        return None


def macro_allows(direction: int, fng: int | None, funding: float | None) -> tuple[bool, str]:
    """
    Makro filtre: sinyale izin ver mi?
    direction: +1=LONG, -1=SHORT
    Döner: (izin_var_mı, neden)
    """
    confirmations = []
    conflicts = []

    if fng is not None:
        if direction == -1:  # SHORT
            if fng >= FNG_SHORT_MIN:
                confirmations.append(f"F&G={fng} (açgözlülük→short uygun)")
            elif fng <= FNG_LONG_MAX:
                conflicts.append(f"F&G={fng} (korku ortamında short riskli)")
        else:  # LONG
            if fng <= FNG_LONG_MAX:
                confirmations.append(f"F&G={fng} (korku→long uygun)")
            elif fng >= FNG_SHORT_MIN:
                conflicts.append(f"F&G={fng} (açgözlülük ortamında long riskli)")

    if funding is not None:
        pct = funding * 100
        if direction == -1:  # SHORT
            if funding >= FUND_SHORT_MIN:
                confirmations.append(f"funding={pct:+.4f}% (long ağırlıklı→short uygun)")
            elif funding <= FUND_LONG_MAX:
                conflicts.append(f"funding={pct:+.4f}% (short ağırlıklı→short riskli)")
        else:  # LONG
            if funding <= FUND_LONG_MAX:
                confirmations.append(f"funding={pct:+.4f}% (short ağırlıklı→long uygun)")
            elif funding >= FUND_SHORT_MIN:
                conflicts.append(f"funding={pct:+.4f}% (long ağırlıklı→long riskli)")

    # Hiç veri gelemediyse → izin ver (filtre yok gibi davran)
    if fng is None and funding is None:
        return True, "makro veri yok, filtre atlandı"

    # En az 1 onay yeterlı (çelişki yoksa)
    if confirmations and not conflicts:
        return True, " | ".join(confirmations)
    if conflicts and not confirmations:
        return False, "çelişki: " + " | ".join(conflicts)
    if confirmations and conflicts:
        # İkisi de var → onay sayısı fazlaysa geç
        return len(confirmations) >= len(conflicts), "karma: " + " | ".join(confirmations + conflicts)

    return True, "nötr makro, geç"


# ── State ─────────────────────────────────────────────────────────────────────

def load_state(coins: list[str]) -> dict:
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
        for c in coins:
            s["coins"].setdefault(c, {
                "balance": INIT_BAL, "position": None,
                "n_trades": 0, "n_wins": 0, "total_pnl": 0.0,
                "skipped": 0,
            })
        return s
    return {"coins": {c: {
        "balance": INIT_BAL, "position": None,
        "n_trades": 0, "n_wins": 0, "total_pnl": 0.0, "skipped": 0,
    } for c in coins}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def append_csv(path: Path, row: dict) -> None:
    exists = path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


# ── Exchange ──────────────────────────────────────────────────────────────────

def make_exchange(name: str):
    import ccxt
    ex_class = getattr(ccxt, name)
    return ex_class({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def fetch_1h(ex, symbol: str, limit: int = 250) -> pd.DataFrame | None:
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe="1h", limit=limit)
    except Exception as e:
        log(f"  ! {symbol} OHLCV hatası: {str(e)[:80]}")
        return None
    if not raw or len(raw) < BB_PERIOD + ATR_PERIOD:
        return None
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.iloc[:-1]


def symbol_for(coin: str) -> str:
    return f"{coin}/USDT:USDT"


# ── Sinyal (V1 ile aynı) ──────────────────────────────────────────────────────

def check_signal(df: pd.DataFrame) -> dict | None:
    upper, _, lower = bollinger_bands(df["close"], BB_PERIOD, BB_STD)
    atr_s  = atr(df["high"], df["low"], df["close"], ATR_PERIOD)
    vol_ma = df["volume"].rolling(VOL_MA).mean()

    i = len(df) - 1
    a = atr_s.iloc[i]
    if np.isnan(a) or a <= 0:
        return None

    close = df["close"].iloc[i]
    up, lo = upper.iloc[i], lower.iloc[i]
    if np.isnan(up) or np.isnan(lo) or up == lo:
        return None

    bb_pos = (close - lo) / (up - lo)
    if not (bb_pos < 0 or bb_pos > 1):
        return None

    vol = df["volume"].iloc[i]; vma = vol_ma.iloc[i]
    if np.isnan(vma) or vol < vma:
        return None

    direction = 1 if bb_pos < 0 else -1
    return {"direction": direction, "entry": float(close), "atr": float(a)}


# ── Pozisyon yönetimi (V1 ile aynı) ──────────────────────────────────────────

def manage_position(coin: str, cdata: dict, df: pd.DataFrame) -> dict | None:
    pos = cdata["position"]
    if pos is None:
        return None

    bar = df.iloc[-1]
    hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])
    d = pos["direction"]; entry = pos["entry"]
    sl = pos["sl"]; tp = pos["tp"]; qty = pos["qty"]

    entry_ts = pd.to_datetime(pos["entry_ts"])
    held_h = (df.index[-1] - entry_ts).total_seconds() / 3600.0

    ep = None; reason = None
    if d == 1:
        if lo <= sl: ep, reason = sl, "sl"
        elif hi >= tp: ep, reason = tp, "tp"
    else:
        if hi >= sl: ep, reason = sl, "sl"
        elif lo <= tp: ep, reason = tp, "tp"
    if ep is None and held_h >= MAX_HOLD_H:
        ep, reason = cl, "max_hold"

    if ep is None:
        return None

    pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
    cdata["balance"] += pnl
    cdata["n_trades"] += 1
    cdata["total_pnl"] += pnl
    if pnl > 0:
        cdata["n_wins"] += 1
    cdata["position"] = None

    return {
        "coin": coin, "entry_ts": pos["entry_ts"],
        "exit_ts": df.index[-1].isoformat(),
        "direction": "LONG" if d == 1 else "SHORT",
        "entry": round(entry, 4), "exit": round(ep, 4),
        "qty": qty, "pnl": round(pnl, 2), "reason": reason,
        "balance_after": round(cdata["balance"], 2),
    }


# ── Ana tarama ────────────────────────────────────────────────────────────────

def scan_once(ex, coins: list[str], state: dict) -> None:
    # Makro verileri bir kez çek (tüm coinler için aynı)
    fng = get_fear_greed()
    log(f"Makro: F&G={fng}")

    for coin in coins:
        sym = symbol_for(coin)
        df = fetch_1h(ex, sym)
        if df is None or len(df) < BB_PERIOD + ATR_PERIOD:
            log(f"  {coin}: veri yetersiz, atlandı")
            continue

        cdata = state["coins"][coin]

        # 1) Açık pozisyonu yönet
        closed = manage_position(coin, cdata, df)
        if closed:
            append_csv(TRADES_CSV, closed)
            wr = cdata["n_wins"] / cdata["n_trades"] if cdata["n_trades"] else 0
            log(f"  {coin}: KAPANDI {closed['reason']} "
                f"PnL ${closed['pnl']:+.2f} | bakiye ${cdata['balance']:.0f} "
                f"WR {wr:.0%} ({cdata['n_trades']}t)")

        # 2) Pozisyon yoksa sinyal + makro filtre
        if cdata["position"] is None:
            sig = check_signal(df)
            if sig:
                d = sig["direction"]; entry = sig["entry"]; a = sig["atr"]

                # Funding rate coin bazlı
                funding = get_funding_rate(ex, sym)
                allowed, reason_macro = macro_allows(d, fng, funding)

                if not allowed:
                    cdata["skipped"] = cdata.get("skipped", 0) + 1
                    log(f"  {coin}: sinyal VAR ama MAKRO FİLTRE ATTİ → {reason_macro}")
                    # Atlanan sinyali de kaydet
                    append_csv(SIGNALS_CSV, {
                        "ts": df.index[-1].isoformat(), "coin": coin,
                        "direction": "LONG" if d == 1 else "SHORT",
                        "entry": round(entry, 4), "atr": round(a, 4),
                        "fng": fng, "funding": funding,
                        "macro_ok": False, "macro_reason": reason_macro,
                    })
                    continue

                sl_d = SL_MULT * a
                sl = entry - d * sl_d
                tp = entry + d * TP_MULT * a
                qty = min(
                    round((cdata["balance"] * RISK_PCT) / (entry * (sl_d / entry)), 6),
                    cdata["balance"] * 0.5 / entry,
                )
                if qty > 0:
                    cdata["position"] = {
                        "direction": d, "entry": entry, "sl": sl, "tp": tp,
                        "qty": qty, "atr": a,
                        "entry_ts": df.index[-1].isoformat(),
                        "fng_at_entry": fng, "funding_at_entry": funding,
                    }
                    append_csv(SIGNALS_CSV, {
                        "ts": df.index[-1].isoformat(), "coin": coin,
                        "direction": "LONG" if d == 1 else "SHORT",
                        "entry": round(entry, 4), "sl": round(sl, 4),
                        "tp": round(tp, 4), "atr": round(a, 4),
                        "fng": fng, "funding": funding,
                        "macro_ok": True, "macro_reason": reason_macro,
                    })
                    log(f"  {coin}: ⚡ SİNYAL {'LONG' if d==1 else 'SHORT'} "
                        f"@ {entry:.4f}  [{reason_macro}]")
            else:
                pos = cdata.get("position")
                if pos:
                    log(f"  {coin}: pozisyon AÇIK "
                        f"{'LONG' if pos['direction']==1 else 'SHORT'} @ {pos['entry']:.4f}")

    save_state(state)
    write_summary_md(state, coins, fng)


def write_summary_md(state: dict, coins: list[str], fng: int | None) -> None:
    fng_str = f"{fng} ({'Açgözlülük' if fng and fng>55 else 'Korku' if fng and fng<45 else 'Nötr'})" if fng else "?"
    lines = [
        "# 📊 Paper Demo V2 — Teknik + Makro Filtre",
        "",
        f"Son güncelleme: **{now_utc():%Y-%m-%d %H:%M} UTC** · Fear & Greed: **{fng_str}**",
        "",
        "V1 (saf teknik) ile karşılaştırma: makro filtre sinyali ONAYLAMAK için gerekli.",
        "",
        "| Coin | Bakiye | Getiri | Trade | Kazanma % | Atlanan | Aday? |",
        "|------|--------|--------|-------|-----------|---------|-------|",
    ]
    for coin in coins:
        c = state["coins"][coin]
        ret = (c["balance"] - INIT_BAL) / INIT_BAL * 100
        wr = c["n_wins"] / c["n_trades"] * 100 if c["n_trades"] else 0
        skipped = c.get("skipped", 0)
        aday = "✅" if (ret > 0 and wr > 45 and c["n_trades"] >= 3) else \
               ("⏳" if c["n_trades"] < 3 else "❌")
        lines.append(
            f"| {coin} | ${c['balance']:,.0f} | {ret:+.1f}% | "
            f"{c['n_trades']} | {wr:.0f}% | {skipped} | {aday} |"
        )
    lines += [
        "",
        "**Atlanan:** makro filtre sinyali reddettiğinde artar. "
        "Eğer V2 daha az trade ama daha yüksek WR gösterirse filtre işe yarıyor.",
        "",
        "> V1 ile V2'yi 4-8 hafta karşılaştır. Hangisi kazanırsa o stratejiyle devam.",
    ]
    Path("paper_summary_v2.md").write_text("\n".join(lines), encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", nargs="+", default=DEFAULT_COINS)
    parser.add_argument("--exchange", default="mexc")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()

    ex    = make_exchange(args.exchange)
    state = load_state(args.coins)

    log(f"=== Paper V2 (Teknik+Makro) başlıyor — {args.coins} ===")
    scan_once(ex, args.coins, state)

    if not args.once:
        while True:
            time.sleep(args.interval)
            state = load_state(args.coins)
            scan_once(ex, args.coins, state)


if __name__ == "__main__":
    main()
