"""
replay_recent.py — MEVCUT sistemi son N günde "sanki canlıymış gibi" koştur.

Üç soruya cevap verir:
  1. Düzeltilmiş sistem (21 hata + ORB off) canlı defterin -$10.85'ine karşı ne yapar?
  2. ORB açılırsa ne değişir?  (--orb)
  3. Çakışma (one-per-symbol) olmasaydı — her strateji KENDİ YOLUNDA — ne olurdu? (--lanes)

FIDELITY (üretim kodunu maksimum kullanır):
  • Gerçek .env (load_config) → aynı allowlist / risk / gate'ler.
  • Üretim strateji sınıfları (.analyze, zone state dahil).
  • Üretim RiskManager, EQUITY üzerinden, sleeve başına risk override.
  • GERÇEKÇİ DOLUM: limit-retest sleeve'leri (FVG/IFVG/ORB) HEMEN dolmaz —
    seviyeye ancak WINDOW bar içinde fiyat DÖNERSE dolar, dönmezse iptal
    (canlıdaki 'market fallback yok' davranışı). Market sleeve'leri (BB
    fallback'li, squeeze/sr/donchian force_market) kapanışta dolar.
  • Çıkış: 1h bar high/low (SL önce, parite yöntemi), sleeve max-hold, ifvg BE@1R.

MODLAR:
  varsayılan : netted (coin başına tek slot — CANLI gerçeği, one-per-symbol)
  --lanes    : her sleeve KENDİ slotunda (sub-account dünyası — çakışma YOK)
  --orb      : ORB'yi de dahil et (limit-retrace, gerçekçi dolum)

Kullanım (VPS):  venv/bin/python replay_recent.py 21 [--orb] [--lanes]
"""
from __future__ import annotations

import sys
from collections import defaultdict
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
from strategies.orb import OrbStrategy

DAYS = int([a for a in sys.argv[1:] if a.isdigit()][0]) if any(a.isdigit() for a in sys.argv[1:]) else 21
WITH_ORB = "--orb" in sys.argv
LANES = "--lanes" in sys.argv
# Uzun pencerede (>=180g) TÜM veriyi trade et (yıl-yıl edge testi); kısa
# pencerede canlı temiz-epoch'a kilitle (son-dönem kıyası).
EPOCH = pd.Timestamp("2000-01-01", tz="UTC") if DAYS >= 180 else pd.Timestamp("2026-06-29", tz="UTC")
FEE_TAKER = 0.0001
FILL_WINDOW = 2          # limit-retest sleeve'leri kaç bar içinde dolmalı
MARKET = {"mean_rev", "squeeze", "sr_breakout", "donchian"}   # kapanışta dolar
LIMIT = {"fvg", "ifvg", "orb"}                                # retest gerekir
MAXHOLD = {"donchian": 120, "fvg": 24, "ifvg": 24, "orb": 6}


def fetch(symbol: str, tf: str, days: int) -> pd.DataFrame:
    import ccxt
    ex = ccxt.mexc()
    since = int((datetime.now(timezone.utc).timestamp() - (days + 14) * 86400) * 1000)
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


class Sim:
    def __init__(self, cfg):
        self.cfg = cfg
        self.risk = RiskManager(cfg.risk)
        self.equity = 190.0
        self.start_equity = 190.0
        self.positions = {}   # slot -> pos dict
        self.pending = []     # bekleyen limit emirleri
        self.trades = []
        self.blocked = defaultdict(int)   # sleeve -> çakışma yüzünden bloklanan sinyal

    def slot(self, symbol, sleeve):
        return f"{symbol}:{sleeve}" if LANES else symbol

    def _allowed(self, sleeve, symbol):
        s = self.cfg.strategy
        amap = {"mean_rev": s.bb_symbols, "sr_breakout": s.sr_breakout_symbols,
                "ifvg": s.ifvg_symbols, "squeeze": s.squeeze_symbols,
                "donchian": s.donchian_symbols}
        allow = amap.get(sleeve)
        return allow is None or symbol in allow

    def _risk(self, sleeve):
        r = self.cfg.risk
        return {"fvg": r.fvg_risk_pct, "ifvg": r.ifvg_risk_pct,
                "donchian": r.donchian_risk_pct,
                "squeeze": getattr(r, "squeeze_risk_pct", r.max_risk_per_trade),
                "orb": getattr(r, "orb_risk_pct", 0.05)}.get(sleeve, 0.0)

    def _can_place(self, slot, symbol, direction):
        if slot in self.positions:
            return False
        if any(p["slot"] == slot for p in self.pending):
            return False
        if len(self.positions) >= self.cfg.risk.max_positions:
            return False
        cap = getattr(self.cfg.risk, "max_correlated_direction", 0)
        if cap:
            grp = {"BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"}
            same = sum(1 for p in self.positions.values()
                       if p["symbol"] in grp and p["dir"] == direction)
            if symbol in grp and same >= cap:
                return False
        return True

    def signal(self, symbol, sleeve, direction, entry, sl, tp, atr, ts):
        slot = self.slot(symbol, sleeve)
        if not self._can_place(slot, symbol, direction):
            self.blocked[sleeve] += 1
            return
        if sleeve in MARKET:
            self._open(slot, symbol, sleeve, direction, entry, sl, tp, atr, ts, maker=(sleeve == "mean_rev"))
        else:  # limit-retest: bekleyen emir
            self.pending.append(dict(slot=slot, symbol=symbol, sleeve=sleeve, dir=direction,
                                     entry=entry, sl=sl, tp=tp, atr=atr, ts=ts, bars=0))

    def _open(self, slot, symbol, sleeve, direction, entry, sl, tp, atr, ts, maker):
        ro = self._risk(sleeve)
        if sleeve == "mean_rev":
            setup = self.risk.build_trade_setup(direction, entry, atr, self.equity,
                                                self.cfg.exchange.leverage, symbol)
        else:
            setup = self.risk.build_trade_setup_from_levels(
                direction, entry, sl, tp, self.equity, self.cfg.exchange.leverage,
                symbol, risk_pct_override=ro)
        if setup is None:
            return
        self.positions[slot] = dict(
            slot=slot, symbol=symbol, sleeve=sleeve, dir=direction, entry=setup.entry_price,
            sl=setup.sl_price, tp=setup.tp_price, qty=setup.quantity, open_ts=ts,
            maker=maker, be_done=False, risk0=abs(setup.entry_price - setup.sl_price))

    def process_pending(self, symbol, hi, lo, ts):
        """Bekleyen limit-retest emirleri: fiyat seviyeye DÖNERSE dolar, WINDOW
        bar içinde dönmezse iptal (canlı: market fallback yok)."""
        still = []
        for o in self.pending:
            if o["symbol"] != symbol:
                still.append(o)
                continue
            o["bars"] += 1
            if lo <= o["entry"] <= hi:   # seviyeye dönüldü → dolar
                if self._can_place(o["slot"], symbol, o["dir"]):
                    self._open(o["slot"], symbol, o["sleeve"], o["dir"], o["entry"],
                               o["sl"], o["tp"], o["atr"], ts, maker=False)
                    # AYNI BARDA SL/TP kontrolü (audit v_bt #2): dolum barının
                    # kalan hareketi stop'u vurabilir — validated model 'aynı bar
                    # SL = kayıp' der. SL önce (pesimistik).
                    pos = self.positions.get(o["slot"])
                    if pos is not None:
                        dd = pos["dir"]
                        ep2 = None
                        if dd == 1:
                            if lo <= pos["sl"]: ep2 = pos["sl"]
                            elif hi >= pos["tp"]: ep2 = pos["tp"]
                        else:
                            if hi >= pos["sl"]: ep2 = pos["sl"]
                            elif lo <= pos["tp"]: ep2 = pos["tp"]
                        if ep2 is not None:
                            self._book(o["slot"], pos, ep2, ts)
                continue  # dolduysa ya da yer yoksa: emir düşer
            if o["bars"] < FILL_WINDOW:
                still.append(o)   # hâlâ bekliyor
            # else: süre doldu, iptal
        self.pending = still

    def check_exit(self, slot, hi, lo, close, ts):
        p = self.positions.get(slot)
        if not p:
            return
        d = p["dir"]
        held = (ts - p["open_ts"]).total_seconds() / 3600
        # 1) ÖNCE mevcut sl/tp ile çıkış (SL önce, pesimistik). BE bu bardan
        #    önce kurulduysa zaten p["sl"] güncel; bu bar kapanışında kurulacak
        #    BE ise yalnız SONRAKİ barları etkiler (look-ahead yok — audit v_bt #1).
        ep = None
        if d == 1:
            if lo <= p["sl"]: ep = p["sl"]
            elif hi >= p["tp"]: ep = p["tp"]
        else:
            if hi >= p["sl"]: ep = p["sl"]
            elif lo <= p["tp"]: ep = p["tp"]
        if ep is None and held >= MAXHOLD.get(p["sleeve"], 48):
            ep = close
        if ep is not None:
            self._book(slot, p, ep, ts)
            return
        # 2) Çıkış olmadıysa: ifvg BE'yi bu barın KAPANIŞINDAN kur (gelecekte etkiler)
        if p["sleeve"] == "ifvg" and not p["be_done"]:
            r = p["risk0"]
            if r > 0 and ((d == 1 and close >= p["entry"] + r) or
                          (d == -1 and close <= p["entry"] - r)):
                p["sl"] = p["entry"]; p["be_done"] = True

    def _book(self, slot, p, ep, ts):
        d = p["dir"]
        entry_fee = 0.0 if p["maker"] else FEE_TAKER
        fees = (p["entry"] * entry_fee + ep * FEE_TAKER) * p["qty"]
        pnl = d * (ep - p["entry"]) * p["qty"] - fees
        self.equity += pnl
        r0 = p["risk0"] if p["risk0"] > 0 else 1.0
        self.trades.append(dict(symbol=p["symbol"], sleeve=p["sleeve"], pnl=pnl,
                                year=ts.year, r=d * (ep - p["entry"]) / r0))
        del self.positions[slot]


def mk(cfg):
    s = cfg.strategy
    d = dict(
        mean_rev=MeanReversionStrategy(s),
        fvg=FvgStrategy(min_gap_atr=s.fvg_min_gap_atr, rr=s.fvg_rr) if s.fvg_enabled else None,
        ifvg=IfvgStrategy(min_gap_atr=s.ifvg_min_gap_atr, rr=s.ifvg_rr) if s.ifvg_enabled else None,
        squeeze=SqueezeStrategy(kc_mult=s.squeeze_kc_mult, min_squeeze_bars=s.squeeze_min_bars,
                                sl_atr=s.squeeze_sl_atr, rr=s.squeeze_rr, mtf_filter=s.squeeze_mtf) if s.squeeze_enabled else None,
        donchian=DonchianStrategy(channel=s.donchian_channel, rr=s.donchian_rr,
                                  sl_atr=s.donchian_sl_atr, ema_trend=s.donchian_ema_trend) if s.donchian_enabled else None,
        sr_breakout=SrBreakoutStrategy() if s.sr_breakout_enabled else None,
        orb=OrbStrategy() if WITH_ORB else None,
    )
    return d


def main():
    cfg = load_config()
    symbols = cfg.exchange.symbols or [cfg.exchange.symbol]
    mode = ("LANES (her sleeve kendi slotu — çakışma YOK)" if LANES
            else "NETTED (coin başına tek slot — CANLI gerçeği)")
    print(f"Replay {DAYS}g | mod: {mode} | ORB: {'AÇIK' if WITH_ORB else 'kapalı'}")
    print(f"  gerçek .env: RISK_SCALE={cfg.risk.risk_scale} max_pos={cfg.risk.max_positions}")

    data = {}
    for full in symbols:
        sym = full.split(":")[0]
        try:
            data[full] = dict(sym=sym, h1=fetch(sym, "1h", DAYS), h4=fetch(sym, "4h", DAYS))
            print(f"  {sym}: {len(data[full]['h1'])} 1h, {len(data[full]['h4'])} 4h")
        except Exception as e:
            print(f"  {sym}: veri hatası: {e}")

    sleeves = {full: mk(cfg) for full in data}
    sim = Sim(cfg)
    r = cfg.risk

    all_ts = sorted(set().union(*[set(d["h1"].index) for d in data.values()]))
    for ts in all_ts:
        for full, d in data.items():
            if ts not in d["h1"].index:
                continue
            h1 = d["h1"]; i = h1.index.get_loc(ts)
            if i < 260:
                continue
            # CANLI pencere boyutu: bot BB/squeeze/sr'ye 120 bar besliyor
            # (get_candles(120)). Tam geçmiş beslemek hem O(n^2) hem canlıdan
            # sapma; 120 bara sınırla (tüm göstergeler <=64 bar geriye bakar,
            # ATR/ADX seed etkisi 120 barda ihmal edilebilir → birebir aynı).
            sub = h1.iloc[max(0, i - 119): i + 1]
            atr_v = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            if np.isnan(atr_v) or atr_v <= 0:
                continue
            hi = float(sub["high"].iloc[-1]); lo = float(sub["low"].iloc[-1]); close = float(sub["close"].iloc[-1])
            # 1) çıkışlar
            for slot in [s for s in list(sim.positions) if sim.positions[s]["symbol"] == full]:
                sim.check_exit(slot, hi, lo, close, ts)
            # 2) bekleyen limitler (retest dolumu / iptal)
            sim.process_pending(full, hi, lo, ts)
            if ts < EPOCH:
                continue
            # gate'ler
            adx_raw = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            adx_v = float(adx_raw) if np.isfinite(adx_raw) else 20.0
            regime = ("trending" if adx_v >= r.adx_trending_threshold
                      else "ranging" if adx_v <= r.adx_ranging_threshold else "neutral")
            rf = r.regime_filter_enabled
            bo_ok = not (rf and regime == "ranging")
            bb_ok = not (rf and regime == "trending")
            sym = d["sym"]; sl = sleeves[full]

            if sl["mean_rev"] and bb_ok and sim._allowed("mean_rev", full):
                g = sl["mean_rev"].analyze(sub)
                if g.direction != 0:
                    sim.signal(full, "mean_rev", g.direction, close, 0, 0, atr_v, ts)
            if WITH_ORB and sl["orb"] and bo_ok:
                g = sl["orb"].analyze(sub)
                if g.direction != 0 and g.sl_price > 0:
                    orb_entry = g.orb_high if g.direction == 1 else g.orb_low
                    sim.signal(full, "orb", g.direction, orb_entry, g.sl_price, g.tp_price, atr_v, ts)
            for name, gate in (("fvg", True), ("ifvg", True), ("squeeze", bo_ok), ("sr_breakout", bo_ok)):
                st = sl[name]
                if not st or not gate or not sim._allowed(name, full):
                    continue
                sub2 = h1.iloc[max(0, i - 249): i + 1] if name in ("fvg", "ifvg") else sub
                g = st.analyze(sub2, atr_v)
                if g.direction != 0 and g.sl_price > 0:
                    entry = close if name == "sr_breakout" else g.entry_price
                    sim.signal(full, name, g.direction, entry, g.sl_price, g.tp_price, atr_v, ts)
            if sl["donchian"] and sim._allowed("donchian", full) and ts.hour % 4 == 3:
                h4 = d["h4"]; sub4 = h4[h4.index <= ts].tail(260)
                need = max(cfg.strategy.donchian_channel + 2, cfg.strategy.donchian_ema_trend)
                if len(sub4) >= need:
                    a4 = atr_fn(sub4["high"], sub4["low"], sub4["close"], 14).iloc[-1]
                    if not (np.isnan(a4) or a4 <= 0):
                        g = sl["donchian"].analyze(sub4, float(a4))
                        if g.direction != 0 and g.sl_price > 0:
                            sim.signal(full, "donchian", g.direction, g.entry_price, g.sl_price, g.tp_price, float(a4), ts)

    tr = sim.trades
    print("\n" + "=" * 68)
    print(f"  REPLAY SONUÇ — {mode.split('(')[0].strip()}{' +ORB' if WITH_ORB else ''}")
    print("=" * 68)
    if not tr:
        print("  Kapanan trade yok.")
        return
    by = defaultdict(list)
    byyear = defaultdict(list)
    for t in tr:
        by[t["sleeve"]].append(t["pnl"])
        byyear[t.get("year", "?")].append(t["pnl"])
    tot = sum(t["pnl"] for t in tr)
    wr = sum(1 for t in tr if t["pnl"] > 0) / len(tr)
    gp = sum(t["pnl"] for t in tr if t["pnl"] > 0); gl = -sum(t["pnl"] for t in tr if t["pnl"] < 0)
    pf = gp / gl if gl > 0 else 9.99
    print(f"  TOPLAM: {len(tr)}t  WR{wr:.0%}  PF{pf:.2f}  net ${tot:+.2f}  "
          f"(${sim.start_equity:.0f}→${sim.equity:.2f})")
    print("  " + "-" * 64)
    for s in sorted(by, key=lambda k: -sum(by[k])):
        p = by[s]; w = sum(1 for x in p if x > 0)
        sgp = sum(x for x in p if x > 0); sgl = -sum(x for x in p if x < 0)
        spf = sgp / sgl if sgl > 0 else 9.99
        blk = sim.blocked.get(s, 0)
        print(f"  {s:12s} {len(p):>3d}t WR{w/len(p):>3.0%} PF{spf:4.2f} ${sum(p):+7.2f}"
              f"   (çakışma-blok: {blk})")
    print("  " + "-" * 64)
    print("  YIL-YIL (botun sıra sıra kendini test etmesi):")
    for yr in sorted(byyear):
        p = byyear[yr]; w = sum(1 for x in p if x > 0)
        ygp = sum(x for x in p if x > 0); ygl = -sum(x for x in p if x < 0)
        ypf = ygp / ygl if ygl > 0 else 9.99
        print(f"    {yr}  {len(p):>3d}t WR{w/len(p):>3.0%} PF{ypf:4.2f} ${sum(p):+8.2f}")
    print("  " + "-" * 64)
    bycoin = defaultdict(list)
    for t in tr:
        bycoin[t["symbol"].split("/")[0]].append((t["sleeve"], t["pnl"]))
    print("  COIN kırılımı:")
    for cn in sorted(bycoin, key=lambda k: -sum(x[1] for x in bycoin[k])):
        rows = bycoin[cn]
        sl_str = " ".join(f"{sv}:{sum(x[1] for x in rows if x[0]==sv):+.1f}"
                          for sv in sorted(set(x[0] for x in rows)))
        print(f"    {cn:5s} {len(rows):>2d}t ${sum(x[1] for x in rows):+7.2f}  {sl_str}")
    print("  " + "-" * 64)
    print("  Kıyas: canlı defter -$10.85 (26t) — HATALI dönem.")
    print("  'çakışma-blok' = one-per-symbol yüzünden alınamayan sinyal sayısı.")
    if not LANES:
        print("  --lanes ile koş: her strateji kendi yolunda ne yapardı gör.")


if __name__ == "__main__":
    main()
