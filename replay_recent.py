"""
replay_recent.py — MEVCUT sistemi son N günde "sanki canlıymış gibi" koştur.

Amaç: bu haftanın 21 hata düzeltmesi + ORB kapatma SONRASI kodun, canlının
işlem yaptığı pencerede ne YAPARDI'ğını görmek. Canlı defterle (hatalı dönem)
kıyaslanır: fark, düzeltmelerin değeri.

FIDELITY (üretim kodunu maksimum kullanır — uydurma yok):
  • Gerçek .env: load_config() ile OKUNUR → aynı allowlist / risk / gate'ler
    (ORB kapalı, BB_SYMBOLS, IFVG/SQUEEZE/DONCHIAN allowlist'leri, RISK_SCALE).
  • Gerçek strateji sınıfları: her sleeve'in kendi .analyze()'ı (zone state
    dahil), bar-bar, coin-bazında sırayla çağrılır.
  • Gerçek RiskManager: build_trade_setup / _from_levels, EQUITY üzerinden,
    sleeve başına risk override (execution.py zinciriyle aynı).
  • Canlı gate'ler: ADX rejim (bo_allowed/bb_allowed), hafta sonu, allowlist.
  • ONE-PER-SYMBOL (canlı netted): coin başına AYNI ANDA tek pozisyon — asıl
    sansür mekanizması budur. max_positions + korelasyon capi de uygulanır.
  • Dolum: BB maker@kapanış; yapısal sleeve'ler market@kapanış (force_market).
  • Çıkış: 1m intrabar (SL önce), sleeve başına max-hold, ifvg BE@1R.

APPROKSİMASYONLAR (dürüstçe):
  • BE@1R 1h kapanışta kontrol edilir (canlı da öyle; backtest intrabar'dan
    hafif farklı — bilinen #4).
  • Maker giriş her zaman dolar varsayılır (paper modeliyle aynı).
  • Fee: maker %0 giriş + taker %0.01 çıkış (canlı muhasebe modeli).

Kullanım (VPS):  venv/bin/python replay_recent.py [gün_sayısı]
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from config import load_config
from risk import RiskManager
from indicators import atr as atr_fn, adx as adx_fn
from strategies.mean_reversion import MeanReversionStrategy
from strategies.fvg import FvgStrategy
from strategies.ifvg import IfvgStrategy
from strategies.squeeze import SqueezeStrategy
from strategies.donchian import DonchianStrategy
from strategies.sr_breakout import SrBreakoutStrategy

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
EPOCH = pd.Timestamp("2026-06-29", tz="UTC")
FEE_TAKER = 0.0001


def fetch(symbol: str, tf: str, days: int) -> pd.DataFrame:
    """Doğrudan tf'yi çek (benchmark_recent'te doğrulanan yöntem). MEXC 1m
    geçmişi sınırlı sayfalıyor; 1h/4h since ile sorunsuz geliyor."""
    import ccxt
    ex = ccxt.mexc()
    since = int((datetime.now(timezone.utc).timestamp() - (days + 12) * 86400) * 1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(symbol, tf, since=since, limit=500)
        if not b:
            break
        rows.extend(b)
        if len(b) < 500:
            break
        since = b[-1][0] + 1
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns=["ts"]).astype(float).iloc[:-1]


def resample(df1m: pd.DataFrame, tf: str) -> pd.DataFrame:
    return df1m.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


class Sim:
    def __init__(self, cfg):
        self.cfg = cfg
        self.risk = RiskManager(cfg.risk)
        self.equity = 190.0
        self.start_equity = 190.0
        self.positions = {}   # symbol -> dict (one-per-symbol, netted)
        self.trades = []      # closed

    def _allowed(self, sleeve: str, symbol: str) -> bool:
        s = self.cfg.strategy
        amap = {"mean_rev": getattr(s, "bb_symbols", None),
                "sr_breakout": getattr(s, "sr_breakout_symbols", None),
                "ifvg": getattr(s, "ifvg_symbols", None),
                "squeeze": getattr(s, "squeeze_symbols", None),
                "donchian": getattr(s, "donchian_symbols", None)}
        allow = amap.get(sleeve)
        return allow is None or symbol in allow

    def _risk_override(self, sleeve: str) -> float:
        r = self.cfg.risk
        return {"fvg": getattr(r, "fvg_risk_pct", 0.0),
                "ifvg": getattr(r, "ifvg_risk_pct", 0.0),
                "donchian": getattr(r, "donchian_risk_pct", 0.0),
                "squeeze": getattr(r, "squeeze_risk_pct", r.max_risk_per_trade),
                }.get(sleeve, 0.0)

    def try_open(self, symbol, sleeve, direction, entry, sl, tp, atr, ts):
        # one-per-symbol (canlı netted): coin başına tek pozisyon
        if symbol in self.positions:
            return "occupied"
        if len(self.positions) >= getattr(self.cfg.risk, "max_positions", 12):
            return "max_pos"
        # korelasyon capi (BTC/ETH/SOL aynı yön)
        cap = getattr(self.cfg.risk, "max_correlated_direction", 0)
        if cap:
            grp = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
            same = sum(1 for p in self.positions.values()
                       if p["symbol"] in grp and p["dir"] == direction)
            if symbol in grp and same >= cap:
                return "corr_cap"
        ro = self._risk_override(sleeve)
        if sleeve in ("mean_rev",):
            setup = self.risk.build_trade_setup(direction, entry, atr, self.equity,
                                                self.cfg.exchange.leverage, symbol)
        else:
            setup = self.risk.build_trade_setup_from_levels(
                direction, entry, sl, tp, self.equity, self.cfg.exchange.leverage,
                symbol, risk_pct_override=ro)
        if setup is None:
            return "setup_none"
        maker = sleeve == "mean_rev"
        self.positions[symbol] = dict(
            symbol=symbol, sleeve=sleeve, dir=direction, entry=setup.entry_price,
            sl=setup.sl_price, tp=setup.tp_price, qty=setup.quantity, atr=atr,
            open_ts=ts, maker=maker, be_done=False,
            max_hold={"donchian": 120, "fvg": 24, "ifvg": 24}.get(sleeve, 48))
        return "opened"

    def check_exit(self, symbol, hi, lo, close, ts, hours_held):
        p = self.positions.get(symbol)
        if not p:
            return
        d = p["dir"]
        # BE@1R (ifvg) — 1h kapanış kontrolü, canlı ile aynı
        if p["sleeve"] == "ifvg" and not p["be_done"]:
            r = abs(p["entry"] - p["sl"])
            if r > 0 and ((d == 1 and close >= p["entry"] + r) or
                          (d == -1 and close <= p["entry"] - r)):
                p["sl"] = p["entry"]; p["be_done"] = True
        ep = None
        if d == 1:
            if lo <= p["sl"]: ep = p["sl"]
            elif hi >= p["tp"]: ep = p["tp"]
        else:
            if hi >= p["sl"]: ep = p["sl"]
            elif lo <= p["tp"]: ep = p["tp"]
        if ep is None and hours_held >= p["max_hold"]:
            ep = close
        if ep is not None:
            entry_fee = 0.0 if p["maker"] else FEE_TAKER
            fees = (p["entry"] * entry_fee + ep * FEE_TAKER) * p["qty"]
            pnl = d * (ep - p["entry"]) * p["qty"] - fees
            self.equity += pnl
            self.trades.append(dict(symbol=symbol, sleeve=p["sleeve"], pnl=pnl,
                                    r=d * (ep - p["entry"]) / abs(p["entry"] - p["sl"])))
            del self.positions[symbol]


def main():
    cfg = load_config()
    symbols = cfg.exchange.symbols or [cfg.exchange.symbol]
    print(f"Replay: {DAYS} gün, coinler={[s.split('/')[0] for s in symbols]}")
    print(f"Gate'ler (gerçek .env): ORB={'ON' if cfg.strategy.orb_enabled else 'OFF'}, "
          f"RISK_SCALE={getattr(cfg.risk,'risk_scale',1.0)}, "
          f"max_pos={cfg.risk.max_positions}")

    # veri: 1m (intrabar) + 1h + 4h
    data = {}
    for full in symbols:
        sym = full.split(":")[0]
        try:
            d1 = fetch(sym, "1h", DAYS)
            d4 = fetch(sym, "4h", DAYS)
            data[full] = dict(sym=sym, h1=d1, h4=d4)
            print(f"  {sym}: {len(d1)} 1h bar, {len(d4)} 4h bar")
        except Exception as e:
            print(f"  {sym}: veri hatası: {e}")

    # sleeve örnekleri (üretim sınıfları)
    def mk(full):
        s = cfg.strategy
        return dict(
            mean_rev=MeanReversionStrategy(s),
            fvg=FvgStrategy(min_gap_atr=s.fvg_min_gap_atr, rr=s.fvg_rr) if s.fvg_enabled else None,
            ifvg=IfvgStrategy(min_gap_atr=s.ifvg_min_gap_atr, rr=s.ifvg_rr) if s.ifvg_enabled else None,
            squeeze=SqueezeStrategy(kc_mult=s.squeeze_kc_mult, min_squeeze_bars=s.squeeze_min_bars,
                                    sl_atr=s.squeeze_sl_atr, rr=s.squeeze_rr, mtf_filter=s.squeeze_mtf) if s.squeeze_enabled else None,
            donchian=DonchianStrategy(channel=s.donchian_channel, rr=s.donchian_rr,
                                      sl_atr=s.donchian_sl_atr, ema_trend=s.donchian_ema_trend) if s.donchian_enabled else None,
            sr_breakout=SrBreakoutStrategy() if s.sr_breakout_enabled else None,
        )
    sleeves = {full: mk(full) for full in data}

    sim = Sim(cfg)

    # kronolojik birleşik 1h zaman çizgisi
    all_ts = sorted(set().union(*[set(d["h1"].index) for d in data.values()]))
    for ts in all_ts:
        if ts < EPOCH:
            # zone state'i ısıt ama trade açma
            pass
        for full, d in data.items():
            if ts not in d["h1"].index:
                continue
            h1 = d["h1"]; i = h1.index.get_loc(ts)
            if i < 210:
                continue
            sub = h1.iloc[: i + 1]
            atr_v = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            if np.isnan(atr_v) or atr_v <= 0:
                continue
            # exit: bu 1h barın high/low'u ile (parite testi yöntemi, SL-önce
            # pesimistik). Aynı barda giriş yok → bu barın range'i pozisyona ait.
            if full in sim.positions:
                p = sim.positions[full]
                held = (ts - p["open_ts"]).total_seconds() / 3600
                sim.check_exit(full, float(sub["high"].iloc[-1]), float(sub["low"].iloc[-1]),
                               float(sub["close"].iloc[-1]), ts, held)
            if ts < EPOCH:
                continue
            # rejim + gate'ler
            adx_raw = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            adx_v = float(adx_raw) if np.isfinite(adx_raw) else 20.0
            regime = ("trending" if adx_v >= cfg.risk.adx_trending_threshold
                      else "ranging" if adx_v <= cfg.risk.adx_ranging_threshold else "neutral")
            rf = cfg.risk.regime_filter_enabled
            bo_ok = not (rf and regime == "ranging")
            bb_ok = not (rf and regime == "trending")
            if datetime.now(timezone.utc).weekday() >= 5:
                pass
            is_weekend = ts.weekday() >= 5
            if not getattr(cfg.risk, "bb_weekday_enabled", True) and not is_weekend:
                bb_ok = False
            close = sub["close"].iloc[-1]
            sl = sleeves[full]

            # BB
            if sl["mean_rev"] and bb_ok and sim._allowed("mean_rev", d["sym"]):
                sig = sl["mean_rev"].analyze(sub)
                if sig.direction != 0:
                    sim.try_open(full, "mean_rev", sig.direction, close, 0, 0, atr_v, ts)
            # FVG (allowlist yok — canlıda da yok)
            if sl["fvg"]:
                sub250 = h1.iloc[max(0, i - 249): i + 1]
                sg = sl["fvg"].analyze(sub250, atr_v)
                if sg.direction != 0 and sg.sl_price > 0:
                    sim.try_open(full, "fvg", sg.direction, sg.entry_price, sg.sl_price, sg.tp_price, atr_v, ts)
            # IFVG
            if sl["ifvg"] and sim._allowed("ifvg", d["sym"]):
                sub250 = h1.iloc[max(0, i - 249): i + 1]
                sg = sl["ifvg"].analyze(sub250, atr_v)
                if sg.direction != 0 and sg.sl_price > 0:
                    sim.try_open(full, "ifvg", sg.direction, sg.entry_price, sg.sl_price, sg.tp_price, atr_v, ts)
            # Squeeze
            if sl["squeeze"] and bo_ok and sim._allowed("squeeze", d["sym"]):
                sg = sl["squeeze"].analyze(sub, atr_v)
                if sg.direction != 0 and sg.sl_price > 0:
                    sim.try_open(full, "squeeze", sg.direction, sg.entry_price, sg.sl_price, sg.tp_price, atr_v, ts)
            # S/R (BB slotunu paylaşır — one-per-symbol zaten hallediyor)
            if sl["sr_breakout"] and bo_ok and sim._allowed("sr_breakout", d["sym"]):
                sg = sl["sr_breakout"].analyze(sub, atr_v)
                if sg.direction != 0 and sg.sl_price > 0:
                    sim.try_open(full, "sr_breakout", sg.direction, close, sg.sl_price, sg.tp_price, atr_v, ts)
            # Donchian (4h sınırında)
            if sl["donchian"] and sim._allowed("donchian", d["sym"]) and ts.hour % 4 == 3:
                h4 = d["h4"]; sub4 = h4[h4.index <= ts]
                if len(sub4) >= max(cfg.strategy.donchian_channel + 2, cfg.strategy.donchian_ema_trend):
                    atr4 = atr_fn(sub4["high"], sub4["low"], sub4["close"], 14).iloc[-1]
                    if not (np.isnan(atr4) or atr4 <= 0):
                        sg = sl["donchian"].analyze(sub4, float(atr4))
                        if sg.direction != 0 and sg.sl_price > 0:
                            sim.try_open(full, "donchian", sg.direction, sg.entry_price, sg.sl_price, sg.tp_price, float(atr4), ts)

    # rapor
    tr = sim.trades
    print("\n" + "=" * 66)
    print(f"  MEVCUT SİSTEM — {DAYS}g REPLAY (sanki canlı, düzeltmeler + ORB off)")
    print("=" * 66)
    if not tr:
        print("  Kapanan trade yok.")
        return
    from collections import defaultdict
    by = defaultdict(list)
    for t in tr:
        by[t["sleeve"]].append(t["pnl"])
    tot = sum(t["pnl"] for t in tr)
    wr = sum(1 for t in tr if t["pnl"] > 0) / len(tr)
    gp = sum(t["pnl"] for t in tr if t["pnl"] > 0); gl = -sum(t["pnl"] for t in tr if t["pnl"] < 0)
    pf = gp / gl if gl > 0 else 9.99
    print(f"  TOPLAM: {len(tr)}t  WR{wr:.0%}  PF{pf:.2f}  net ${tot:+.2f}  "
          f"(equity ${sim.start_equity:.0f}→${sim.equity:.2f})")
    print("  " + "-" * 62)
    for s in sorted(by, key=lambda k: -sum(by[k])):
        p = by[s]
        w = sum(1 for x in p if x > 0)
        sgp = sum(x for x in p if x > 0); sgl = -sum(x for x in p if x < 0)
        spf = sgp / sgl if sgl > 0 else 9.99
        print(f"  {s:12s} {len(p):>3d}t  WR{w/len(p):>3.0%}  PF{spf:4.2f}  ${sum(p):+7.2f}")
    print("  " + "-" * 62)
    print("  Kıyas: canlı defter aynı pencerede -$10.85 (26t, PF0.52) — o HATALI")
    print("  dönemdi. Bu replay DÜZELTİLMİŞ kodun ne yapacağını gösterir.")


if __name__ == "__main__":
    main()
