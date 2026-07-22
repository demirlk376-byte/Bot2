"""
worst_month.py — En kötü ayları NEDEN kötü olduklarına göre parçala (canlı-doğru, MP=7).

"Kötü aylar var" yetmez; sürücüyü bul. Her kötü ay için: sleeve kırılımı (donchian/squeeze),
YÖN kırılımı (long/short), en çok kaybettiren coinler, işlem sayısı/WR, ve BTC'nin o ayki
getirisi (kripto-geneli çöküş müydü?). Sürücü belliyse belki koruyucu kol (regime/yön filtresi);
değilse "korelasyonlu kuyruk, tasarım gereği" deriz — ama kanıtla.

Deploy: donchian 7 + squeeze 4, MP=7, %2.25/işlem. BTC bağlam için ayrıca yüklenir.

Kullanım:  py worst_month.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
MAXPOS = 7
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}


def gen(sleeve, coin, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    dd = fast_bt.resample(m, "1d"); dema = ema_fn(dd["close"], 20)
    up = (dd["close"] > dema).reindex(d.index, method="ffill").values
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"entry_ns": idx[i].value, "exit": idx[j], "R": R,
                    "coin": coin, "sleeve": sleeve, "dir": d_}); occ = j   # occ=coin başına tek-pozisyon
    return out


def btc_monthly():
    try:
        d = fast_bt.resample(fast_bt.load("BTC", source="local"), "1d")
        return (d["close"].resample("ME").last().pct_change() * 100)
    except Exception:
        return None


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trades = []
    for c in DONCH:
        try: trades += gen("donchian", c, fast_bt.load(c, source=source))
        except Exception as e: print(f"  d {c}: {e}")
    for c in SQZ:
        try: trades += gen("squeeze", c, fast_bt.load(c, source=source))
        except Exception as e: print(f"  s {c}: {e}")
    # koltuk-kısıtlı seçim (MP=7)
    ev = sorted(trades, key=lambda t: t["entry_ns"]); openh = []; taken = []; ctr = 0
    for t in ev:
        while openh and openh[0][0].value <= t["entry_ns"]:
            heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (t["exit"], ctr, t)); taken.append(t)
    df = pd.DataFrame([{**t, "pnl": t["R"] * RISKF * BAL0, "m": pd.Timestamp(t["exit"]).to_period("M")} for t in taken])
    monthly = df.groupby("m")["pnl"].sum().sort_values()
    btc = btc_monthly()
    print(f"\n{'='*72}\n=== EN KÖTÜ 6 AY — NEDEN? (MP={MAXPOS}, %2.25/işlem, taban ${BAL0:.0f}) ===")
    for m in monthly.index[:6]:
        sub = df[df["m"] == m]
        tot = sub["pnl"].sum(); pct = tot / BAL0 * 100
        dn = sub[sub["sleeve"] == "donchian"]["pnl"].sum(); sq = sub[sub["sleeve"] == "squeeze"]["pnl"].sum()
        lo = sub[sub["dir"] == 1]["pnl"].sum(); sh = sub[sub["dir"] == -1]["pnl"].sum()
        nl = (sub["dir"] == 1).sum(); ns = (sub["dir"] == -1).sum()
        wr = (sub["R"] > 0).mean() * 100
        btcm = ""
        if btc is not None:
            try: btcm = f"BTC {btc.loc[pd.Timestamp(m.start_time).replace(day=28)]:+.0f}%" if False else f"BTC {btc[btc.index.to_period('M')==m].iloc[0]:+.0f}%"
            except Exception: btcm = "BTC ?"
        # en çok kaybettiren 3 coin
        byc = sub.groupby("coin")["pnl"].sum().sort_values()
        worst3 = ", ".join(f"{c}${v:+.0f}" for c, v in byc.head(3).items())
        print(f"\n  {m}  ${tot:+7.2f} ({pct:+5.1f}%)  {btcm}  n={len(sub)} WR{wr:.0f}%")
        print(f"     sleeve: donchian${dn:+.0f} | squeeze${sq:+.0f}")
        print(f"     yön:    LONG${lo:+.0f}(n{nl}) | SHORT${sh:+.0f}(n{ns})")
        print(f"     en kötü coinler: {worst3}")
    # genel: kötü aylarda long mu short mu daha çok kaybediyor + BTC ilişkisi
    print(f"\n{'='*72}\n=== GENEL DESEN (tüm aylar) ===")
    if btc is not None:
        mm = df.groupby("m")["pnl"].sum()
        aligned = pd.DataFrame({"pnl": mm})
        aligned["btc"] = [btc[btc.index.to_period("M") == m].iloc[0] if (btc.index.to_period("M") == m).any() else np.nan for m in mm.index]
        aligned = aligned.dropna()
        corr = aligned["pnl"].corr(aligned["btc"])
        neg = aligned[aligned["pnl"] < 0]
        print(f"  Aylık PnL ↔ BTC aylık getiri korelasyonu: {corr:+.2f}")
        print(f"  Kayıp aylarında BTC ort: {neg['btc'].mean():+.1f}%  (kazanç aylarında {aligned[aligned['pnl']>0]['btc'].mean():+.1f}%)")
    ld = df[df["dir"] == 1]; sd = df[df["dir"] == -1]
    print(f"  LONG toplam: ${ld['pnl'].sum():+.0f} (WR{(ld['R']>0).mean()*100:.0f}%, n{len(ld)}) | "
          f"SHORT toplam: ${sd['pnl'].sum():+.0f} (WR{(sd['R']>0).mean()*100:.0f}%, n{len(sd)})")
    print("\n  Kötü aylar BTC-çöküşünde + long-ağırlıklı ise → regime/yön koruması test edilebilir.")
    print("  Dağınık/rastgele ise → korelasyonlu kuyruk, tasarım gereği (kabul et, boyutla yönet).")


if __name__ == "__main__":
    main()
