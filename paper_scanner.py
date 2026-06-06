"""
paper_scanner.py

Çok-coinli PAPER (kağıt) BB-fade fırsat tarayıcı.

Ne yapar:
  • Verilen coin listesini sürekli tarar (1h mum kapanışlarında).
  • Doğrulanmış BB-fade sinyalini (BB kırılımı + hacim filtresi) her coinde arar.
  • Sinyal bulunca GERÇEK PARA yerine "paper" pozisyon açar ve loglar.
  • Açık paper pozisyonları SL/TP/max-hold için izler, kapanınca PnL kaydeder.
  • Her coin için ayrı paper bakiye + WR + PnL tutar → hangi coinde edge VAR görürsün.

NEDEN: +28.2% edge sadece BTC'de doğrulandı. Bu araç, gerçek para riske atmadan
diğer coinlerde edge'in GERÇEKTEN olup olmadığını ileri (forward) veriyle test eder.
Bir coin 4-8 hafta paper'da pozitif + makul WR verirse, ANCAK O ZAMAN canlıya alınır.

GÜVENLİK: Hiçbir emir göndermez. Sadece OHLCV okur (fetch_ohlcv). API key gerekmez
(public veri). Borsa erişimi olan kendi makinende çalıştır.

Kurulum:
  pip install ccxt pandas numpy
Çalıştır:
  python paper_scanner.py
  python paper_scanner.py --coins BTC ETH SOL BNB XRP --exchange mexc
  python paper_scanner.py --once          # tek tarama (test için)
  python paper_scanner.py --interval 300  # 5 dakikada bir kontrol

State: paper_state.json (pozisyonlar+bakiye), paper_trades.csv (kapanan trade'ler),
       paper_signals.csv (her sinyal anı).
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

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

# ── Doğrulanmış parametreler (BTC'de +28.2% veren) ────────────────────────────
BB_PERIOD   = 20
BB_STD      = 2.0
ATR_PERIOD  = 14
SL_MULT     = 3.0
TP_MULT     = 5.0
MAX_HOLD_H  = 48
RISK_PCT    = 0.03
COST        = 0.0002        # maker round-trip tahmini
VOL_MA      = 20            # hacim filtresi penceresi
INIT_BAL    = 10_000.0      # coin başına paper bakiye

STATE_FILE   = Path("paper_state.json")
TRADES_CSV   = Path("paper_trades.csv")
SIGNALS_CSV  = Path("paper_signals.csv")

DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    print(f"[{now_utc():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ── Telegram push (opsiyonel — telefona bildirim) ─────────────────────────────

_TG_TOKEN = ""
_TG_CHAT  = ""


def init_telegram(token: str, chat: str) -> bool:
    """Token+chat verilirse Telegram push'u etkinleştir. requests gerekir."""
    global _TG_TOKEN, _TG_CHAT
    if not token or not chat:
        return False
    _TG_TOKEN, _TG_CHAT = token, chat
    notify("📡 Paper tarayıcı başladı — sinyaller telefonuna düşecek.")
    return True


def notify(text: str) -> None:
    """Telegram'a mesaj gönder (sessizce başarısız olur — tarama durmasın)."""
    if not _TG_TOKEN or not _TG_CHAT:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            data={"chat_id": _TG_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log(f"  ! Telegram push hatası: {str(e)[:60]}")


# ── State yönetimi ────────────────────────────────────────────────────────────

def load_state(coins: list[str]) -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    else:
        state = {"coins": {}}
    for c in coins:
        state["coins"].setdefault(c, {
            "balance": INIT_BAL,
            "position": None,        # açık paper pozisyon
            "n_trades": 0,
            "n_wins": 0,
            "total_pnl": 0.0,
        })
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def append_csv(path: Path, row: dict) -> None:
    exists = path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


# ── Exchange (sadece OHLCV okuma) ─────────────────────────────────────────────

def make_exchange(name: str):
    import ccxt
    ex_class = getattr(ccxt, name)
    ex = ex_class({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},   # USDT-M perpetual
    })
    return ex


def fetch_1h(ex, symbol: str, limit: int = 250) -> pd.DataFrame | None:
    """Son `limit` adet KAPANMIŞ 1h mumu getir."""
    try:
        raw = ex.fetch_ohlcv(symbol, timeframe="1h", limit=limit)
    except Exception as e:
        log(f"  ! {symbol} OHLCV hatası: {str(e)[:80]}")
        return None
    if not raw or len(raw) < BB_PERIOD + ATR_PERIOD:
        return None
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    # Son mum henüz kapanmamış olabilir → at
    return df.iloc[:-1]


def symbol_for(coin: str) -> str:
    return f"{coin}/USDT:USDT"


# ── Sinyal mantığı (doğrulanmış BB-fade) ──────────────────────────────────────

def check_signal(df: pd.DataFrame) -> dict | None:
    """
    En son KAPANMIŞ mumda BB-fade sinyali var mı?
    Dönüş: {direction, entry, atr} veya None.
    """
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
    if not (bb_pos < 0 or bb_pos > 1):       # BB dışına çıkış yok
        return None

    vol = df["volume"].iloc[i]; vma = vol_ma.iloc[i]
    if np.isnan(vma) or vol < vma:           # hacim filtresi
        return None

    direction = 1 if bb_pos < 0 else -1
    return {"direction": direction, "entry": float(close), "atr": float(a)}


# ── Açık pozisyon kontrolü (SL/TP/max-hold) ───────────────────────────────────

def manage_position(coin: str, cdata: dict, df: pd.DataFrame) -> dict | None:
    """Açık paper pozisyonu son mumla kontrol et. Kapanırsa kapanış kaydı döner."""
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
        return None     # hala açık

    pnl = d * (ep - entry) * qty - (entry + ep) * qty * COST
    cdata["balance"] += pnl
    cdata["n_trades"] += 1
    cdata["total_pnl"] += pnl
    if pnl > 0:
        cdata["n_wins"] += 1
    cdata["position"] = None

    rec = {
        "coin": coin, "entry_ts": pos["entry_ts"],
        "exit_ts": df.index[-1].isoformat(),
        "direction": "LONG" if d == 1 else "SHORT",
        "entry": round(entry, 4), "exit": round(ep, 4),
        "qty": qty, "pnl": round(pnl, 2), "reason": reason,
        "balance_after": round(cdata["balance"], 2),
    }
    return rec


# ── Tek tarama döngüsü ────────────────────────────────────────────────────────

def scan_once(ex, coins: list[str], state: dict) -> None:
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
            emoji = "🟢" if closed["pnl"] >= 0 else "🔴"
            notify(f"{emoji} <b>{coin} KAPANDI</b> ({closed['reason']})\n"
                   f"PnL: <code>${closed['pnl']:+.2f}</code>\n"
                   f"Bakiye: <code>${cdata['balance']:.0f}</code> | "
                   f"WR {wr:.0%} ({cdata['n_trades']}t)")

        # 2) Pozisyon yoksa yeni sinyal ara
        if cdata["position"] is None:
            sig = check_signal(df)
            if sig:
                d = sig["direction"]; entry = sig["entry"]; a = sig["atr"]
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
                    }
                    sig_row = {
                        "ts": df.index[-1].isoformat(), "coin": coin,
                        "direction": "LONG" if d == 1 else "SHORT",
                        "entry": round(entry, 4), "sl": round(sl, 4),
                        "tp": round(tp, 4), "atr": round(a, 4), "qty": qty,
                    }
                    append_csv(SIGNALS_CSV, sig_row)
                    log(f"  {coin}: ⚡ SİNYAL {'LONG' if d==1 else 'SHORT'} "
                        f"@ {entry:.4f}  SL {sl:.4f}  TP {tp:.4f}")
                    notify(f"⚡ <b>{coin} {'LONG' if d==1 else 'SHORT'}</b>\n"
                           f"Entry: <code>{entry:.4f}</code>\n"
                           f"SL: <code>{sl:.4f}</code>  TP: <code>{tp:.4f}</code>")
        else:
            pos = cdata["position"]
            log(f"  {coin}: pozisyon AÇIK "
                f"{'LONG' if pos['direction']==1 else 'SHORT'} @ {pos['entry']:.4f}")

    save_state(state)
    write_summary_md(state, coins)


def write_summary_md(state: dict, coins: list[str]) -> None:
    """Telefondan GitHub'da açıp okunabilen özet tablo (paper_summary.md).
    Telegram gerekmez — sadece bu dosyaya bakman yeterli."""
    lines = [
        "# 📊 Paper Demo Durumu",
        "",
        f"Son güncelleme: **{now_utc():%Y-%m-%d %H:%M} UTC**",
        "",
        "Gerçek para YOK — her coin $10,000 sanal bakiyeyle başlar. Amaç: hangi",
        "coinde edge GERÇEKTEN var, körlemesine değil veriyle görmek.",
        "",
        "| Coin | Bakiye | Getiri | Trade | Kazanma % | Açık pozisyon | Aday? |",
        "|------|--------|--------|-------|-----------|---------------|-------|",
    ]
    total_ret = 0.0
    for coin in coins:
        c = state["coins"][coin]
        ret = (c["balance"] - INIT_BAL) / INIT_BAL * 100
        total_ret += ret
        wr = c["n_wins"] / c["n_trades"] * 100 if c["n_trades"] else 0
        op = ("🟢 " + ("LONG" if c["position"]["direction"] == 1 else "SHORT")
              if c["position"] else "—")
        # Aday: pozitif getiri + WR>45 + en az birkaç trade
        aday = "✅" if (ret > 0 and wr > 45 and c["n_trades"] >= 3) else \
               ("⏳" if c["n_trades"] < 3 else "❌")
        lines.append(
            f"| {coin} | ${c['balance']:,.0f} | {ret:+.1f}% | "
            f"{c['n_trades']} | {wr:.0f}% | {op} | {aday} |"
        )
    lines += [
        "",
        "**Aday sütunu:** ✅ canlıya aday (pozitif + kazanma>%45) · "
        "⏳ yeterli veri yok · ❌ edge tutmadı",
        "",
        "> 4–8 hafta veri biriksin, sonra ✅ olan coinlerle $20 canlıya geçeriz.",
        "> Bu dosya her saat otomatik güncellenir.",
    ]
    Path("paper_summary.md").write_text("\n".join(lines), encoding="utf-8")


def print_summary(state: dict, coins: list[str]) -> None:
    print("\n" + "=" * 78)
    print(f"{'PAPER ÖZET':<14}{'Bakiye':>12}{'Getiri':>10}{'Trade':>7}{'WR':>6}{'Açık':>8}")
    print("-" * 78)
    for coin in coins:
        c = state["coins"][coin]
        ret = (c["balance"] - INIT_BAL) / INIT_BAL * 100
        wr = c["n_wins"] / c["n_trades"] * 100 if c["n_trades"] else 0
        op = "VAR" if c["position"] else "-"
        print(f"{coin:<14}${c['balance']:>10.0f}{ret:>+9.1f}%"
              f"{c['n_trades']:>7}{wr:>5.0f}%{op:>8}")
    print("=" * 78)
    print("Not: 4-8 hafta veri toplanınca hangi coinde edge GERÇEKTEN var görülür.")
    print("Pozitif + WR>%45 olan coinler canlıya aday. Diğerleri elenir.\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", nargs="*", default=DEFAULT_COINS)
    p.add_argument("--exchange", default="mexc",
                   help="ccxt borsa adı (mexc, binance, bybit, okx...)")
    p.add_argument("--interval", type=int, default=900,
                   help="Tarama aralığı saniye (varsayılan 900=15dk)")
    p.add_argument("--once", action="store_true", help="Tek tarama yap ve çık")
    p.add_argument("--tg-token", default=os.getenv("TELEGRAM_TOKEN", ""),
                   help="Telegram bot token (veya TELEGRAM_TOKEN env)")
    p.add_argument("--tg-chat", default=os.getenv("TELEGRAM_CHAT_ID", ""),
                   help="Telegram chat id (veya TELEGRAM_CHAT_ID env)")
    args = p.parse_args()

    coins = [c.upper() for c in args.coins]
    if init_telegram(args.tg_token, args.tg_chat):
        log("Telegram push AKTİF — sinyaller telefonuna gelecek")
    log(f"Paper tarayıcı başlıyor — borsa: {args.exchange}, coinler: {coins}")
    log(f"Parametreler: BB({BB_PERIOD},{BB_STD}) SL={SL_MULT}×ATR TP={TP_MULT}×ATR "
        f"risk={RISK_PCT:.0%} hacim-filtresi=AÇIK")
    log("GERÇEK PARA YOK — sadece fırsat loglar. Ctrl+C ile durdur.\n")

    ex = make_exchange(args.exchange)
    state = load_state(coins)

    if args.once:
        scan_once(ex, coins, state)
        print_summary(state, coins)
        return

    try:
        while True:
            log(f"── Tarama ({args.exchange}) ──")
            scan_once(ex, coins, state)
            print_summary(state, coins)
            log(f"Sonraki tarama {args.interval}s sonra...\n")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("Durduruldu. State kaydedildi.")
        print_summary(state, coins)


if __name__ == "__main__":
    main()
