"""
breadth_test.py — "Daha çok kazanmak" için tek açık yön GENİŞLİK mi? Önce DARBOĞAZI bul.

DURUM: sinyal kalitesi yolu kapalı (~20 fikir reddedildi, girişte kazanan/kaybeden ayrılamıyor,
OOS AUC 0.502). 22-coinlik veri evreni de tarandı (coin_expand → ICP+BNB eklendi, gerisi elendi).
Profesyonel CTA'lar aynı %38-48 isabetle çalışıyor ama 80-150 PİYASADA. Yani teorik yön: GENİŞLİK.

AMA genişlik ancak DARBOĞAZ oradaysa işe yarar. İki aday darboğaz var ve HANGİSİ olduğu ölçülmedi:
  A) KOLTUK (MAX_POSITIONS=7): koltuklar zaten sürekli doluysa, coin eklemek sadece aynı 7
     koltuk için REKABETİ artırır → yeni coin eski coinin işlemini KOVAR, net kazanç ~0.
  B) SİNYAL: koltuklar çoğu zaman boşsa, coin eklemek doğrudan yeni işlem = doğrudan kâr.

Bu araç ikisini ayırt eder:
  1. Eşzamanlılık dağılımı: zamanın yüzde kaçında kaç pozisyon açık? 7 koltuk gerçekten doluyor mu?
  2. Koltuk tavanının REDDETTİĞİ sinyal sayısı ve bunların gerçek $ değeri (fırsat maliyeti).
  3. MAX_POSITIONS taraması: her EK koltuğun marjinal $ katkısı (nerede düzleşiyor?).
  4. MARJİN GERÇEĞİ: N koltuk $190'lık hesapta fiziksel olarak mümkün mü? Pozisyon başına
     nominal = min(risk%/SL%, CAP)×bakiye; marjin = nominal/kaldıraç. Koltuk artırmanın
     sermaye tavanı var — "daha çok koltuk" bedava değil.

Kullanım:  py breadth_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.25; LEV = 10
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
DEPLOYED_MAXPOS = 7


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
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
        out.append((idx[i], idx[j], R, sld / e)); occ = j
    return out


def seat_run(trades, maxpos):
    """Koltuk seçimi + REDDEDİLENLERİ de döndür (fırsat maliyeti için)."""
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; rejected = []; ctr = 0
    for entry, exit_ts, R, slp in ev:
        while openh and openh[0][0] <= entry: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((entry, exit_ts, R, slp))
        else:
            rejected.append((entry, exit_ts, R, slp))
    return taken, rejected


def dollars(rows):
    if not rows: return 0.0
    r = np.array([t[2] for t in rows]); slp = np.array([t[3] for t in rows])
    return float((r * np.minimum(RISKF, CAP * slp) * BAL0).sum())


def occupancy(taken):
    """Zaman-ağırlıklı eşzamanlılık: her anda kaç pozisyon açıktı?"""
    ev = []
    for entry, exit_ts, _, _ in taken:
        ev.append((entry, +1)); ev.append((exit_ts, -1))
    ev.sort()
    cur = 0; prev = None; dur = {}
    for ts, delta in ev:
        if prev is not None and ts > prev:
            dur[cur] = dur.get(cur, 0.0) + (ts - prev).total_seconds()
        cur += delta; prev = ts
    tot = sum(dur.values())
    return {k: v / tot * 100 for k, v in sorted(dur.items())}, tot


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    trades = []
    for c in DONCH: trades += gen("donchian", fast_bt.load(c, source=source))
    for c in SQZ: trades += gen("squeeze", fast_bt.load(c, source=source))
    print(f"\n{'='*100}\n=== DARBOĞAZ TEŞHİSİ: koltuk mu, sinyal mi? ({len(trades)} ham sinyal, 11 coin) ===")

    # ── 1) Mevcut deploy'da eşzamanlılık ──
    taken, rejected = seat_run(trades, DEPLOYED_MAXPOS)
    occ, tot_s = occupancy(taken)
    print(f"\n  ─── 1) EŞZAMANLILIK (MAX_POSITIONS={DEPLOYED_MAXPOS}) ───")
    print(f"  Zamanın yüzde kaçında kaç pozisyon açıktı:")
    for k in sorted(occ):
        bar = "█" * int(occ[k] / 2)
        print(f"    {k:>2d} pozisyon: {occ[k]:>5.1f}%  {bar}")
    full = occ.get(DEPLOYED_MAXPOS, 0.0)
    idle = occ.get(0, 0.0)
    print(f"\n    → koltuklar DOLU: %{full:.1f} | HİÇ pozisyon yok: %{idle:.1f} | "
          f"ort açık pozisyon: {sum(k*v for k,v in occ.items())/100:.2f}")

    # ── 2) Koltuk tavanının reddettikleri ──
    print(f"\n  ─── 2) KOLTUK TAVANININ REDDETTİĞİ SİNYALLER ───")
    if rejected:
        rr_ = np.array([t[2] for t in rejected])
        print(f"    {len(rejected)} sinyal reddedildi (ham sinyalin %{len(rejected)/len(trades)*100:.1f}'i)")
        print(f"    gerçekte: ort {rr_.mean():+.3f}R | WR %{(rr_>0).mean()*100:.0f} | "
              f"kaçırılan ${dollars(rejected):+.0f}")
    else:
        print(f"    HİÇBİRİ reddedilmedi → koltuk tavanı ŞU AN BAĞLAMIYOR.")

    # ── 3) MAX_POSITIONS taraması: her ek koltuğun marjinal değeri ──
    print(f"\n  ─── 3) HER EK KOLTUĞUN MARJİNAL KATKISI ───")
    print(f"  {'koltuk':>7s} {'n':>5s} {'toplam$':>9s} {'marjinal$':>10s} {'gereken marjin$':>16s} "
          f"{'bakiyenin %':>12s}")
    prev = None
    for mp in (3, 4, 5, 6, 7, 8, 10, 12, 20):
        tk, _ = seat_run(trades, mp)
        tot = dollars(tk)
        marj = "" if prev is None else f"{tot - prev:+10.0f}"
        # en kötü durum marjin: mp pozisyon aynı anda, her biri nominal tavanında
        worst_margin = mp * CAP * BAL0 / LEV
        pct = worst_margin / BAL0 * 100
        warn = "  ⚠ MARJİN YETMEZ" if pct > 90 else ""
        print(f"  {mp:>7d} {len(tk):>5d} {tot:>+9.0f} {marj:>10s} {worst_margin:>16.0f} "
              f"{pct:>11.0f}%{warn}")
        prev = tot

    # ── 4) Karar ──
    print(f"\n  ─── 4) TEŞHİS ───")
    if full < 5.0 and len(rejected) < len(trades) * 0.02:
        print(f"    DARBOĞAZ = SİNYAL, koltuk DEĞİL. Koltuklar zamanın yalnız %{full:.1f}'inde dolu,")
        print(f"    reddedilen sinyal ~yok. → Coin eklemek mevcut coinlerin işlemini KOVMAZ,")
        print(f"    doğrudan YENİ işlem ekler. GENİŞLİK gerçek ve açık bir yön.")
        print(f"    Sınır: sermaye (eşzamanlı pozisyon marjini) + veri (yeni coin indirmek gerek).")
    else:
        print(f"    DARBOĞAZ = KOLTUK. Koltuklar zamanın %{full:.1f}'inde dolu, {len(rejected)} sinyal")
        print(f"    reddedilmiş (${dollars(rejected):+.0f}). → Önce MAX_POSITIONS/sermaye, sonra coin.")


if __name__ == "__main__":
    main()
