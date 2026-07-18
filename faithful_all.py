"""
faithful_all.py — TÜM sleeve'ler CANLI-BİREBİR, MEXC VADELİ veride, çok-coin sweep.

Amaç: test harness'ine güvendiğimize göre (test==canlı, doğru veri kanıtlı), tüm
stratejileri aynı güvenilir zeminde karşılaştırıp en sağlam çakışmasız config'i
seçmek. Üretim strateji SINIFLARINI kullanır (canlı ile aynı), canlının pencere/
tf/kapı/risk'iyle bar-bar koşar.

DÜRÜST GÜVEN AYRIMI (fill modeli):
  • MARKET giriş (force_market / market-fallback) → BYTE-BİREBİR:
      squeeze, donchian, sr_breakout, BB/mean_rev. Fill = sinyal barı close.
  • LİMİT giriş (retest, fallback yok) → MODELLENİR (kesin değil, işaretli):
      orb, fvg, ifvg. Fill = sinyalden sonra fiyat entry seviyesine değerse.
      Canlı emir-yaşamdöngüsü (yeni sinyalde iptal) tam modellenmez. Karar
      market sleeve'ler + faithful_bt ile alınır; limitler yol gösterici.

Canlı davranış (main.py'den, byte-exact spec):
  sleeve   | tf/N       | atr        | fill   | SL/TP            | max_hold | BE  | risk | kapı
  squeeze  | 1h/120→4h  | 1h atr14   | market | 2xATR / rr2.5    | 48       | -   | .02  | ranging blok
  donchian | 4h/260     | 4h atr14   | market | 2xATR / rr2.0    | 30(4h)   | -   | .02  | yok(EMA200)
  sr_break | 1h/120     | 1h atr14   | market | 3xATR / rr3.0    | 48       | -   | .02  | ranging blok
  BB       | 1h/120     | 1h atr14   | market*| 3xATR / rr1.667  | 48       | -   | .02  | trending blok
  orb      | 1h/120     | -          | LİMİT  | range / +2xrange | 6        | 1R  | .05  | ranging blok
  fvg      | 1h/250     | 1h atr14   | LİMİT  | zone / rr2.5      | 24       | -   | .02  | yok
  ifvg     | 1h/250     | 1h atr14   | LİMİT  | zone / rr2.0      | 24       | 1R  | .02  | yok

Kullanım:
  python faithful_all.py BTC                 # tüm sleeve'ler tek coin (MEXC vadeli)
  python faithful_all.py BTC,ETH,SOL,BNB     # coin sweep
  python faithful_all.py BTC binance_csv     # yerel BTC CSV (hızlı, venue farklı!)
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.squeeze import SqueezeStrategy
from strategies.donchian import DonchianStrategy
from strategies.sr_breakout import SrBreakoutStrategy
from strategies.fvg import FvgStrategy
from strategies.ifvg import IfvgStrategy
from strategies.orb import OrbStrategy

BAL = 190.0
FEE = 0.0001


def watr(sub, p=14):
    v = atr_fn(sub["high"], sub["low"], sub["close"], p).iloc[-1]
    return float(v) if np.isfinite(v) else 0.0


def wadx(sub, p=14):
    v = adx_fn(sub["high"], sub["low"], sub["close"], p).iloc[-1]
    return float(v) if np.isfinite(v) else 20.0   # düz piyasa → nötr 20 (canlı ile aynı)


def prep1h(m):
    """HIZ: 120-bar pencere-yerel ADX+ATR'yi coin başına BİR KEZ hesapla (her
    sleeve tekrar hesaplamasın). Canlıyla aynı: get_candles(120) + .iloc[-1]."""
    d = fast_bt.resample(m, "1h"); n = len(d)
    H, L, C = d["high"], d["low"], d["close"]
    adx = np.full(n, 20.0); at = np.zeros(n)
    for i in range(119, n):
        sh, sl, sc = H.iloc[i - 119:i + 1], L.iloc[i - 119:i + 1], C.iloc[i - 119:i + 1]
        av = atr_fn(sh, sl, sc, 14).iloc[-1]; xv = adx_fn(sh, sl, sc, 14).iloc[-1]
        at[i] = float(av) if np.isfinite(av) else 0.0
        adx[i] = float(xv) if np.isfinite(xv) else 20.0
    return d, adx, at


def prep4h(m):
    d = fast_bt.resample(m, "4h"); n = len(d)
    H, L, C = d["high"], d["low"], d["close"]
    at = np.zeros(n)
    for i in range(259, n):
        av = atr_fn(H.iloc[i - 259:i + 1], L.iloc[i - 259:i + 1], C.iloc[i - 259:i + 1], 14).iloc[-1]
        at[i] = float(av) if np.isfinite(av) else 0.0
    return d, at


CD_DELTA = pd.Timedelta(minutes=240)   # canlı cooldown_minutes (config default 240)


def simulate(df, orders, risk_pct, cooldown=False):
    """orders: dict(i, dir, entry, sl, tp, max_hold, fill, be, expiry). Canlı exit:
    sabit SL/TP + max-hold; BE (orb/ifvg) +1R'de SL→entry, SONRAKİ bara etkir
    (main.py: taşınmış SL bu barın SL kontrolünü etkilemez). SL-önce-TP = kötümser.
    cooldown=True → canlı execution.py: 2 ARDIŞIK KAYIP sonrası bu sleeve@coin
    240 dk yeni giriş almaz (kazanç streak'i sıfırlar)."""
    hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    idx = df.index; n = len(cl)
    tr = []; occ = -1; streak = 0; cd_until = None
    for od in sorted(orders, key=lambda o: o["i"]):
        i = od["i"]
        if i <= occ or i >= n - 1:
            continue
        if cooldown and cd_until is not None and idx[i] < cd_until:
            continue   # canlı: cooldown aktif → yeni giriş yok
        d = od["dir"]; SL = od["sl"]; TP = od["tp"]; mh = od["max_hold"]; be = od.get("be", False)
        # ── giriş fill ──
        if od["fill"] == "market":
            fi = i; fe = cl[i]                      # force_market/fallback → close'da
        else:                                       # LİMİT retest: entry seviyesine değme
            E = od["entry"]; exp = od.get("expiry", mh); fi = None
            for j in range(i + 1, min(i + 1 + exp, n)):
                if lo[j] <= E <= hi[j]:
                    fi = j; break
            if fi is None:
                occ = min(i + exp, n - 1)           # dolmayan limit slotu meşgul tutar
                continue
            fe = E
        r0 = abs(fe - SL)
        if r0 <= 0:
            continue
        sl = SL; be_done = False; ep = None; j = fi
        for j in range(fi + 1, min(fi + 1 + mh, n)):
            if d == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= TP: ep = TP; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= TP: ep = TP; break
            if be and not be_done:                  # BE: bu bar exit OLMADIYSA taşı → j+1'e etkir
                if d == 1 and hi[j] >= fe + r0: sl = max(sl, fe); be_done = True
                elif d == -1 and lo[j] <= fe - r0: sl = min(sl, fe); be_done = True
        if ep is None:
            j = min(fi + mh, n - 1); ep = cl[j]
        R = d * (ep - fe) / r0 - 2 * FEE * fe / r0
        tr.append({"r": R, "year": idx[fi].year}); occ = j
        if cooldown:                               # canlı ardışık-zarar cooldown'u
            if R < 0:
                streak += 1
                if streak >= 2:
                    cd_until = idx[j] + CD_DELTA
            else:
                streak = 0; cd_until = None
    return tr, risk_pct


# ── Sinyal üreticiler — üretim sınıfı, canlı pencere/tf/kapı; ADX/ATR ÖN-HESAPLI ──
def sig_squeeze(ctx):
    d, adx, at = ctx["d1"], ctx["adx"], ctx["at"]
    s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0 or adx[i] <= 20.0:           # ranging blok (bo_allowed)
            continue
        sg = s.analyze(d.iloc[max(0, i - 119):i + 1], at[i])
        if sg.direction != 0:
            out.append(dict(i=i, dir=sg.direction, entry=sg.entry_price, sl=sg.sl_price,
                            tp=sg.tp_price, max_hold=48, fill="market", be=False))
    return d, out, 0.02


def sig_donchian(ctx):
    d, at = ctx["d4"], ctx["at4"]
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0:
            continue
        sg = s.analyze(d.iloc[max(0, i - 259):i + 1], at[i])
        if sg.direction != 0:
            out.append(dict(i=i, dir=sg.direction, entry=sg.entry_price, sl=sg.sl_price,
                            tp=sg.tp_price, max_hold=30, fill="market", be=False))
    return d, out, 0.02


def sig_sr(ctx):
    d, adx, at = ctx["d1"], ctx["adx"], ctx["at"]
    s = SrBreakoutStrategy()   # lookback80, min_touches3, sl_atr3, rr3
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0 or adx[i] <= 20.0:           # ranging blok
            continue
        sub = d.iloc[max(0, i - 119):i + 1]
        sg = s.analyze(sub, at[i])
        if sg.direction != 0:
            out.append(dict(i=i, dir=sg.direction, entry=float(sub["close"].iloc[-1]),
                            sl=sg.sl_price, tp=sg.tp_price, max_hold=48, fill="market", be=False))
    return d, out, 0.02


def sig_bb(ctx):
    if MeanRev is None:
        print("  BB atlandı (MeanReversionStrategy import edilemedi)"); return None
    try:
        from config import load_config
        s = MeanRev(load_config().strategy)
    except Exception as e:
        print(f"  BB atlandı (config yüklenemedi: {e})"); return None
    d, adx, at = ctx["d1"], ctx["adx"], ctx["at"]
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0 or adx[i] >= 28.0:           # trending blok (bb_allowed)
            continue
        sub = d.iloc[max(0, i - 119):i + 1]
        sg = s.analyze(sub)
        if sg.direction != 0:
            E = float(sub["close"].iloc[-1]); sld = 3.0 * at[i]   # RiskManager SL 3xATR, TP rr1.667
            out.append(dict(i=i, dir=sg.direction, entry=E, sl=E - sg.direction * sld,
                            tp=E + sg.direction * 1.667 * sld, max_hold=48, fill="market", be=False))
    return d, out, 0.02


def sig_orb(ctx):
    d, adx, at = ctx["d1"], ctx["adx"], ctx["at"]
    s = OrbStrategy()   # rr2.0, ORB_HOUR=14
    out = []
    for i in range(260, len(d)):
        if adx[i] <= 20.0:                         # ranging blok
            continue
        sg = s.analyze(d.iloc[max(0, i - 119):i + 1])
        if sg.direction != 0:
            entry = sg.orb_high if sg.direction == 1 else sg.orb_low   # limit trigger
            out.append(dict(i=i, dir=sg.direction, entry=entry, sl=sg.sl_price, tp=sg.tp_price,
                            max_hold=6, fill="limit", be=True, expiry=6))   # BE@1R
    return d, out, 0.05


def sig_fvg(ctx):
    d, at = ctx["d1"], ctx["at"]
    s = FvgStrategy(min_gap_atr=0.5, rr=2.5)
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0:
            continue
        sg = s.analyze(d.iloc[max(0, i - 249):i + 1], at[i])   # 250 bar (EMA200), 120-ATR
        if sg.direction != 0:
            out.append(dict(i=i, dir=sg.direction, entry=sg.entry_price, sl=sg.sl_price,
                            tp=sg.tp_price, max_hold=24, fill="limit", be=False, expiry=24))
    return d, out, 0.02


def sig_ifvg(ctx):
    d, at = ctx["d1"], ctx["at"]
    s = IfvgStrategy(min_gap_atr=0.75, rr=2.0)
    out = []
    for i in range(260, len(d)):
        if at[i] <= 0:
            continue
        sg = s.analyze(d.iloc[max(0, i - 249):i + 1], at[i])
        if sg.direction != 0:
            out.append(dict(i=i, dir=sg.direction, entry=sg.entry_price, sl=sg.sl_price,
                            tp=sg.tp_price, max_hold=24, fill="limit", be=True, expiry=24))   # BE@1R
    return d, out, 0.02


# MeanReversionStrategy adını geç-import et (config bağımlılığı sig_bb içinde)
try:
    from strategies.mean_reversion import MeanReversionStrategy as MeanRev
except Exception:
    MeanRev = None

SLEEVES = {
    "squeeze":  (sig_squeeze, "market"),
    "donchian": (sig_donchian, "market"),
    "sr_break": (sig_sr,       "market"),
    "BB":       (sig_bb,       "market"),
    "orb":      (sig_orb,      "LİMİT"),
    "fvg":      (sig_fvg,      "LİMİT"),
    "ifvg":     (sig_ifvg,     "LİMİT"),
}


def _stats(tr, rp):
    r = np.array([t["r"] for t in tr]) if tr else np.array([])
    if len(r) == 0:
        return 0, 0.0, 0.0, 0.0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    return len(r), (r > 0).mean(), pf, r.sum() * BAL * rp


def rep(name, kind, res):
    if res is None:
        return None
    df_i, orders, risk = res
    tr_off, _ = simulate(df_i, orders, risk, cooldown=False)   # backtest: hepsini al
    tr_on, _ = simulate(df_i, orders, risk, cooldown=True)     # canlı: 2-kayıp→4h dur
    if not tr_off:
        print(f"  {name:9s} [{kind:6s}] sinyal/işlem yok", flush=True); return None
    n0, wr0, pf0, u0 = _stats(tr_off, risk)
    n1, wr1, pf1, u1 = _stats(tr_on, risk)
    tag = "BİREBİR" if kind == "market" else "MODEL"
    delta = u1 - u0
    print(f"  {name:9s} [{kind:6s}] ({tag})", flush=True)
    print(f"      cooldown YOK : n={n0:>3d} WR{wr0:>3.0%} PF{pf0:4.2f} ${u0:+7.2f}", flush=True)
    print(f"      cooldown VAR : n={n1:>3d} WR{wr1:>3.0%} PF{pf1:4.2f} ${u1:+7.2f}  (CANLI) "
          f"→ cooldown etkisi ${delta:+6.2f}", flush=True)
    return dict(name=name, kind=kind, u_off=u0, u_on=u1, delta=delta, n_off=n0, n_on=n1)


def main():
    coins = (sys.argv[1] if len(sys.argv) > 1 else "BTC").split(",")
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    summary = []
    for coin in coins:
        coin = coin.strip().upper()
        print(f"\n{'='*64}\n=== {coin} — TÜM SLEEVE'LER (canlı-birebir) ===", flush=True)
        try:
            m = fast_bt.load(coin, source=source)
            print("  ADX/ATR ön-hesaplanıyor (1x)...", flush=True)
            d1, adx, at = prep1h(m)
            d4, at4 = prep4h(m)
            ctx = dict(d1=d1, adx=adx, at=at, d4=d4, at4=at4)
        except Exception as e:
            print(f"  {coin} veri/hazırlık hatası: {e}", flush=True); continue
        for name, (fn, kind) in SLEEVES.items():
            try:
                row = rep(name, kind, fn(ctx))
                if row:
                    row["coin"] = coin; summary.append(row)
            except Exception as e:
                print(f"  {name:9s} [{kind:6s}] HATA: {e}", flush=True)
    # ── ÖZET: COOLDOWN ETKİSİ ──
    print(f"\n{'='*64}\n=== ÖZET — COOLDOWN + KATKI SAĞLIYOR MU? (market sleeve'ler) ===", flush=True)
    mkt = [r for r in summary if r["kind"] == "market"]
    for row in sorted(mkt, key=lambda x: -x["u_off"]):
        print(f"  {row['name']:9s}@{row['coin']:5s}  YOK ${row['u_off']:+7.2f} (n{row['n_off']}) "
              f"→ VAR ${row['u_on']:+7.2f} (n{row['n_on']})   Δ${row['delta']:+6.2f}", flush=True)
    tot_off = sum(r["u_off"] for r in mkt); tot_on = sum(r["u_on"] for r in mkt)
    print(f"\n  TOPLAM (market): cooldown YOK ${tot_off:+.2f}  →  VAR ${tot_on:+.2f}   "
          f"Δ${tot_on - tot_off:+.2f}", flush=True)
    if tot_on > tot_off:
        print("  → COOLDOWN + KATKI: canlıda TUT + backtest'e dahil et (test=canlı).", flush=True)
    else:
        print("  → COOLDOWN zararlı/nötr: canlıda KAPAT → backtest zaten hepsini alır (test=canlı).", flush=True)
    lim = [r for r in summary if r["kind"] != "market"]
    if lim:
        print("\n  LİMİT (model — ipucu): " + ", ".join(
            f"{r['name']}@{r['coin']} YOK${r['u_off']:+.0f}/VAR${r['u_on']:+.0f}" for r in lim), flush=True)


if __name__ == "__main__":
    main()
