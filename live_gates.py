"""
live_gates.py — Canlı botun backtest'te MODELLENMEYEN giriş kapıları ne kadar tutuyor?

SORUN: deployed_backtest.py "canlı config" diyor ama execution.py'deki giriş kapılarının
bir kısmını hiç modellemiyor. Yani ilan ettiğimiz $ rakamı, canlının ATLAYACAĞI işlemleri
de sayıyor olabilir. Bir ay başında kimse yokken bu farkı bilmemek kabul edilemez.

execution.py:334-412'deki kapıların envanteri ve durumu:
  1. halt (günlük zarar)        — nadir, modellenmiyor (ayrı ölçüldü)
  2. COOLDOWN                   — ✗ BACKTEST'TE YOK  ← bu aracın konusu
  3. MAX_POSITIONS              — ✓ modelleniyor (koltuk seçimi)
  4. korelasyon tavanı          — grup {BTC,ETH,SOL}, tavan 2. Deploy'da BTC YOK →
                                  grubun yalnız 2 üyesi var → same_dir hiçbir zaman
                                  2'yi AŞAMAZ → kapı ASLA tetiklenmez. Etkisi sıfır.
  5. tek-pozisyon/sembol        — ✓ modelleniyor (occ)
  6. slot dolu                  — ✓ occ ile aynı (sleeve başına tek slot)

COOLDOWN (execution.py:249-280 + 338-347), üretimdeki HALİYLE:
  anahtar = "{sleeve}:{coin}". Kapanan işlem ZARARDAYSA streak++, streak >= 2 ise
  o anahtar KAPANIŞ ANINDAN itibaren COOLDOWN dk boyunca kapalı. Kâr streak'i sıfırlar.
  Streak, cooldown tetiklendiğinde SIFIRLANMAZ → 2. kayıptan sonra HER kayıp yeniden
  4 saat kapatır. Atlanan sinyal pozisyon açmaz → occ İLERLEMEZ (canlı-birebir).

Ayrıca CAP düzeltmesi: deployed_backtest.py CAP=1.0 kullanıyordu; canlı .env
POSITION_CAP_FRACTION=1.25. Burada ikisi de raporlanır.

Kullanım:  py live_gates.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
LOSS_LIMIT = 2          # CONSECUTIVE_LOSS_LIMIT
COOLDOWN_MIN = 240      # COOLDOWN_MINUTES


def gen(sleeve, m, cooldown_min):
    """cooldown_min=0 → kapı kapalı (mevcut backtest). >0 → üretimdeki zaman-tabanlı kapı.

    Atlanan sinyalin gerçek sonucu da hesaplanır (fırsat maliyeti): cooldown
    KAZANDIRIYOR mu KAYBETTİRİYOR mu, ancak bu ölçülünce bilinir."""
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BİREBİR MTF (lookahead YOK)
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    cd_delta = pd.Timedelta(minutes=cooldown_min)
    out = []; blocked = []; occ = -1; consec = 0; cd_until = None

    def resolve(i, d_, a):
        """Bar i'de açılsa nasıl biterdi — hem alınan hem ATLANAN sinyal için aynı motor."""
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        return d_ * (ep - e) / sld - 2 * FEE * e / sld, j, sld / e

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

        # ── COOLDOWN kapısı (üretimde: giriş anında kontrol; atlanan sinyal occ'u
        #    ilerletMEZ, çünkü pozisyon açılmıyor) ──
        if cd_until is not None and idx[i] < cd_until:
            R_lost, _, slp_lost = resolve(i, d_, a)
            blocked.append((idx[i], R_lost, slp_lost))
            continue

        R, j, slpct = resolve(i, d_, a)
        out.append((idx[i].value, idx[j], R, slpct)); occ = j
        # ── kapanışta sonuç kaydı (execution._record_trade_outcome ile birebir) ──
        if R < 0:
            consec += 1
            if cooldown_min > 0 and consec >= LOSS_LIMIT:
                cd_until = idx[j] + cd_delta      # streak SIFIRLANMAZ (üretimde de öyle)
        else:
            consec = 0
    return out, blocked


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[0])


def report(taken, cap):
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    exits = [pd.Timestamp(x) for x, _, _ in taken]
    eff = np.minimum(RISKF, cap * slp)
    pnl = r * eff * BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    ya = np.array([x.year for x in exits])
    # tz_localize(None): to_period tz'yi zaten düşürüyor, uyarıyı susturmak için açıkça.
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in exits]).groupby(level=0).sum()
    eq = np.concatenate([[BAL0], BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=pnl.sum(),
                yrs={y: pnl[ya == y].sum() for y in sorted(set(ya))},
                worst=mon.min(), dd=((peak - eq) / peak).max() * 100,
                capped=(eff < RISKF - 1e-12).mean() * 100)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    ms = {c: fast_bt.load(c, source=source) for c in set(DONCH + SQZ)}

    variants = {}
    for label, cdm in (("cooldown YOK (mevcut backtest)", 0), (f"cooldown VAR (canlı, {COOLDOWN_MIN}dk)", COOLDOWN_MIN)):
        trades = []; blocked = []
        for c in DONCH:
            t, b = gen("donchian", ms[c], cdm); trades += t; blocked += b
        for c in SQZ:
            t, b = gen("squeeze", ms[c], cdm); trades += t; blocked += b
        variants[label] = (seat_select(trades), blocked)

    print(f"\n{'='*104}")
    print(f"=== CANLI GİRİŞ KAPILARININ BACKTEST'E ETKİSİ (MP={MAXPOS}, %{RISKF*100:.2f}/işlem) ===")
    for cap in (1.0, 1.25):
        print(f"\n  ─── POSITION_CAP_FRACTION = {cap} "
              f"{'(deployed_backtest.py varsayımı)' if cap == 1.0 else '(canlı .env — GERÇEK)'} ───")
        print(f"  {'senaryo':34s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} {'maxDD%':>7s} "
              f"{'en kötü ay$':>11s}  yıl-yıl")
        base = None
        for label, (taken, _) in variants.items():
            s = report(taken, cap)
            if base is None: base = s
            ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
            print(f"  {label:34s} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['tot']:>+9.0f} "
                  f"{s['dd']:>7.1f} {s['worst']:>+11.0f}  {ys}")
        s_cd = report(variants[f"cooldown VAR (canlı, {COOLDOWN_MIN}dk)"][0], cap)
        d = s_cd["tot"] - base["tot"]
        print(f"  {'→ COOLDOWN ETKİSİ':34s} {s_cd['n']-base['n']:>+5d} işlem  "
              f"${d:>+7.0f} ({d/abs(base['tot'])*100:+.1f}%)  "
              f"en kötü ay {s_cd['worst']-base['worst']:+.0f}$  maxDD {s_cd['dd']-base['dd']:+.1f}p")

    # Atlanan işlemlerin gerçek sonucu = cooldown'ın fırsat maliyeti/kazancı
    blocked = variants[f"cooldown VAR (canlı, {COOLDOWN_MIN}dk)"][1]
    if blocked:
        br = np.array([R for _, R, _ in blocked]); bs = np.array([s for _, _, s in blocked])
        for cap in (1.25,):
            bp = br * np.minimum(RISKF, cap * bs) * BAL0
            ya = np.array([t.year for t, _, _ in blocked])
            print(f"\n  ─── COOLDOWN'IN ATLADIĞI {len(br)} SİNYAL gerçekte ne yapardı? (cap={cap}) ───")
            print(f"    ort {br.mean():+.3f}R | WR %{(br > 0).mean()*100:.0f} | "
                  f"toplam ${bp.sum():+.0f}  (POZİTİFSE cooldown para KAYBETTİRİYOR)")
            print("    yıl-yıl: " + " ".join(f"{y}:${bp[ya == y].sum():+.0f}" for y in sorted(set(ya))))
            print(f"    NOT: koltuk çakışması yüzünden bunların hepsi alınamazdı; üst sınır.")

    print(f"\n  KARAR ÇERÇEVESİ: cooldown canlıda AÇIK ama backtest'te YOK.")
    print(f"    • Etki ~0 ise: ilan ettiğimiz rakam dürüst, dokunma.")
    print(f"    • Cooldown KAYBETTİRİYORSA: ya .env'de kapat, ya backtest rakamını düzelt.")
    print(f"    • Cooldown KAZANDIRIYORSA: backtest canlıyı OLDUĞUNDAN KÖTÜ gösteriyor (iyi haber).")


if __name__ == "__main__":
    main()
