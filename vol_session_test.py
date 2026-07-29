"""
vol_session_test.py — HACİM ve SEANS filtreleri, GÜNCEL deploy konfigürasyonunda yeniden.

NEDEN TEKRAR (tekrar değil, eksik kalmış doğrulama):
Hacim filtresi ledger'da RED (satır 341-346): taban PF1.48 $1115 → +hacim PF1.58 ama $806 (−$309).
AMA o test ESKİ konfigürasyonda: rr2.0, ICP/BNB yok, CAP 1.0, occ/MTF düzeltmelerinden önce.
Lookahead düzeltmesinden sonra DÖRT ret yeniden doğrulandı (cooldown, piramitleme, stop yerleşimi,
ML) — hacim ve seans BUNLARIN ARASINDA DEĞİLDİ.
Lookahead ortak-mod hataydı (baseline'a da varyanta da eşit) → sıralamayı bozmuyordu.
Ama **rr 2.0→2.5 ortak-mod DEĞİL**: kazananın ödemesini büyütür, kaybedeni değiştirmez. Bir
filtrenin "kazananı da eler" dengesi bu yüzden rr'ye duyarlıdır → verdict FLIP EDEBİLİR.
Bu yüzden güncel tabanda (rr2.5, 11 coin, CAP1.25, occ+MTF düzeltilmiş) yeniden ölçülüyor.

CANLI-DOĞRU: filtre SİNYAL ANINDA uygulanır. Elenen sinyal pozisyon açmaz → occ İLERLEMEZ →
koltuğu meşgul etmez → sonraki sinyal girebilir. (Post-hoc eleme yanlış olurdu: canlıda filtre
bir sinyali atarsa slot boş kalır.)

FİLTRELER:
  HACİM  : kırılım barının hacmi > X × (önceki 20 barın ortalaması). shift(1) → lookahead YOK.
           X ∈ {1.0, 1.25, 1.5, 2.0}. "Gerçek kırılım hacimle gelir" klasik TA iddiası.
  SEANS  : sinyal barının kapanış SAATİ (UTC). Asya 00-08, Avrupa 08-16, ABD 16-24.
           Hem "sadece şu seans" hem "şu seans HARİÇ" denenir (biri işe yararsa diğeri simetrik
           bozulmalı — bozulmuyorsa gürültüdür, bu tutarlılık kontrolü kasten var).
  BİRLEŞİK: hacim+seans en iyi ikilisi (yalnız ikisi de tek başına geçerse).

KABUL BARI: toplam ARTACAK **ve** HER YIL artacak. PF'in artması TEK BAŞINA YETMEZ — hacim
filtresi zaten PF'i artırıp doları düşürüyordu; PF bir oran, biz dolar kazanıyoruz.

Kullanım:  py vol_session_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.25; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
VOL_WIN = 20

SESSIONS = {"asya": (0, 8), "avrupa": (8, 16), "abd": (16, 24)}
VARIANTS = ([("taban", None, None)]
            + [(f"hacim>{x:.2f}x", x, None) for x in (1.0, 1.25, 1.5, 2.0)]
            + [(f"sadece {s}", None, ("only", s)) for s in SESSIONS]
            + [(f"{s} HARİÇ", None, ("skip", s)) for s in SESSIONS])


def gen(sleeve, m, vol_mult, sess):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    # hacim ortalaması: ÖNCEKİ 20 bar (mevcut bar HARİÇ) → lookahead yok
    vol = d["volume"].values
    vol_ma = d["volume"].rolling(VOL_WIN).mean().shift(1).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    hours = idx.hour.values
    out = []; occ = -1; skipped = 0
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue

        # ── FİLTRELER: sinyal anında, elenen occ'u İLERLETMEZ (canlı-birebir) ──
        if vol_mult is not None:
            vm = vol_ma[i]
            if not np.isfinite(vm) or vm <= 0 or vol[i] < vol_mult * vm:
                skipped += 1; continue
        if sess is not None:
            mode, name = sess
            lo_h, hi_h = SESSIONS[name]
            inside = lo_h <= hours[i] < hi_h
            if (mode == "only" and not inside) or (mode == "skip" and inside):
                skipped += 1; continue

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
        out.append((idx[i], idx[j], R, sld / e)); occ = j
    return out, skipped


def seat_select(trades):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry, exit_ts, R, slp in ev:
        while openh and openh[0][0] <= entry: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R, slp))
    return taken


def summarize(taken):
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    ya = np.array([pd.Timestamp(t[0]).year for t in taken])
    pnl = r * np.minimum(RISKF, CAP * slp) * BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=pnl.sum(),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ms = {c: fast_bt.load(c, source=source) for c in set(DONCH + SQZ)}
    print(f"\n{'='*112}\n=== HACİM ve SEANS FİLTRELERİ — GÜNCEL tabanda (rr2.5, 11 coin, CAP1.25) ===")
    print(f"  filtre sinyal anında uygulanır; elenen sinyal koltuğu MEŞGUL ETMEZ (canlı-birebir)")
    print(f"\n  {'varyant':>14s} {'n':>5s} {'elenen':>7s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} "
          f"{'Δ$':>8s}  yıl-yıl                                    karar")
    base = None
    for label, vmult, sess in VARIANTS:
        trades = []; skipped = 0
        for c in DONCH:
            t, sk = gen("donchian", ms[c], vmult, sess); trades += t; skipped += sk
        for c in SQZ:
            t, sk = gen("squeeze", ms[c], vmult, sess); trades += t; skipped += sk
        s = summarize(seat_select(trades))
        if base is None:
            base = s; delta = ""; verdict = "◄ referans"
        else:
            delta = f"{s['tot']-base['tot']:+8.0f}"
            dy = {y: s["yrs"].get(y, 0.0) - base["yrs"].get(y, 0.0) for y in base["yrs"]}
            every = all(v > 0 for v in dy.values())
            if s["tot"] > base["tot"] and every: verdict = "★ KABUL"
            elif s["tot"] > base["tot"]: verdict = "toplam+ ama yıl BOZUK → RET"
            elif s["pf"] > base["pf"]: verdict = "PF+ ama $ DÜŞTÜ → RET"
            else: verdict = "RET"
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        print(f"  {label:>14s} {s['n']:>5d} {skipped:>7d} {s['wr']:>3.0f}% {s['pf']:>5.2f} "
              f"{s['tot']:>+9.0f} {delta:>8s}  {ys}  {verdict}")

    print(f"\n  TUTARLILIK KONTROLÜ: 'sadece X' işe yarıyorsa 'X HARİÇ' simetrik BOZULMALI.")
    print(f"  İkisi de iyileşiyor/ikisi de bozuluyorsa → seans sinyal değil GÜRÜLTÜ.")
    print(f"  PF'in tek başına artması KABUL DEĞİL: hacim filtresi eskiden PF'i 1.48→1.58 çıkarıp")
    print(f"  doları $1115→$806 düşürmüştü. PF bir oran; biz dolar kazanıyoruz.")


if __name__ == "__main__":
    main()
