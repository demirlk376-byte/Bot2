"""
pairs_margin.py — ASIL SORU: bot ve pairs $183'lük hesaba AYNI ANDA sığar mı?

min-notional sorusu KAPANDI (probe_hedge2, VPS): 16 bacağın toplam min notional'i $49.26,
10x ile $4.93 marjin → $183.63 ile fazlasıyla yeter. Yani "minimum emir büyüklüğü" engel DEĞİL.

AMA min-notional YANLIŞ SORU. Pairs'in +$532'yi üretmesi için gereken şey minimum boyut değil,
BACKTEST'TEKİ boyut: her çift işlemi ~$190 nominal (2 bacak × ~$95). Kâr boyutla DOĞRUSAL
ölçeklenir — yarı boyut, yarı kâr.

GERÇEK KISIT EŞZAMANLI MARJİN:
  · bot: 7 koltuk, her biri en fazla CAP×BAL0 = 1.25×$190 = $237 nominal → 10x'te $23.7 marjin
  · pairs: aynı anda kaç çift açık olur? "8'i birden" EN KÖTÜ durum, GERÇEK sayı değil.
Bu betik gerçek sayıyı ÖLÇER (varsaymaz) ve ikisinin TOPLAM marjin talebinin zaman içindeki
dağılımını çıkarır. Sorulan: $183.63 kaç kere yetmez, ve pairs'i hangi ölçekte koşabiliriz?

ÖLÇEK-KÂR İLİŞKİSİ: pairs kârı nominal ile doğrusaldır, dolayısıyla "sığdırma çarpanı" k
bulunursa beklenen kâr ≈ k × $532 olur. k'yı ölçüp gerçekçi kârı raporluyoruz — bu, "pairs
+$532 kazandırır" demekten çok daha dürüst bir ifade.

Kullanım:  py pairs_margin.py local
"""
import sys
import heapq

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
import pairs_verify as P

LEV = 10.0
BAL_LIVE = 183.63       # probe_hedge2'den GERÇEK serbest bakiye


def bot_positions(source):
    """Bot'un GERÇEKTEN açtığı pozisyonlar: (giriş_ns, çıkış_ns, nominal$).
    Nominal = risk/sl_pct, canlı risk.py tavanıyla (CAP×BAL0) sınırlı."""
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)): tagged.append((c,) + t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)): tagged.append((c,) + t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)): tagged.append((c,) + t)
    ev = sorted(tagged, key=lambda t: t[1])
    openh = []; ctr = 0; out = []
    for sym, entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            eff = min(A.RISKF, A.CAP * slp)          # gerçekleşen risk oranı
            notional = eff * A.BAL0 / slp            # risk$/sl% = nominal$
            out.append((entry_ns, exit_ts.value, notional))
    return out


def pairs_positions(source):
    """Pairs çift işlemleri: (giriş_ns, çıkış_ns, nominal$).
    Her çift işlemi 2 bacak; backtest ölçeği BAL0 nominal (bacak başına BAL0/2)."""
    px = P.load_px(source)
    pairs, _ = P.pick_pairs(px, P.NPAIRS)
    out = []
    for a, b in pairs:
        lg = np.log(px[[a, b]].dropna())
        sp = lg[a] - lg[b]
        mu = sp.rolling(P.ZWIN).mean(); sd = sp.rolling(P.ZWIN).std()
        z = ((sp - mu) / sd).values
        idx = sp.index; n = len(z)
        i = P.ZWIN + 1
        while i < n - 1:
            if not np.isfinite(z[i]) or abs(z[i]) < 2.0: i += 1; continue
            ex = None
            for j in range(i + 1, min(i + 1 + P.MAXBARS, n)):
                if not np.isfinite(z[j]): continue
                if abs(z[j]) < 0.5 or abs(z[j]) > 3.5: ex = j; break
            if ex is None: ex = min(i + P.MAXBARS, n - 1)
            out.append((idx[i].value, idx[ex].value, P.BAL0))   # 2 bacak toplamı = BAL0
            i = ex + 1
    return out, pairs


def margin_series(pos, lev=LEV):
    """Zaman içinde eşzamanlı marjin talebi. Olay tabanlı: her giriş +, her çıkış −."""
    ev = []
    for s, e, notional in pos:
        ev.append((s, +notional / lev))
        ev.append((e, -notional / lev))
    ev.sort()
    t = []; m = []; cur = 0.0
    for ts, d in ev:
        cur += d
        t.append(ts); m.append(cur)
    return np.array(t), np.array(m)


def combined(bot, prs, lev=LEV):
    """İki kümenin TOPLAM marjinini zamanda birleştir; süre-ağırlıklı istatistik."""
    ev = []
    for s, e, nt in bot: ev += [(s, +nt / lev), (e, -nt / lev)]
    for s, e, nt in prs: ev += [(s, +nt / lev), (e, -nt / lev)]
    ev.sort()
    cur = 0.0; segs = []
    prev = ev[0][0]
    for ts, d in ev:
        if ts > prev:
            segs.append((prev, ts, cur))
        cur += d; prev = ts
    return segs


def pct_time_over(segs, thresh):
    tot = sum(e - s for s, e, _ in segs)
    over = sum(e - s for s, e, m in segs if m > thresh)
    return over / tot * 100 if tot > 0 else 0.0


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 92}")
    print("=== BOT + PAIRS AYNI HESABA SIĞAR MI? (gerçek eşzamanlı marjin) ===")
    print(f"  canlı serbest bakiye ${BAL_LIVE:.2f} · kaldıraç {LEV:.0f}x")
    print(f"  min-notional sorusu KAPALI (VPS: 16 bacak $49.26 nominal = $4.93 marjin, YETER)")

    bot = bot_positions(source)
    prs, pairs = pairs_positions(source)
    print(f"\n  bot pozisyonu: {len(bot)} · pairs çift işlemi: {len(prs)}")
    print(f"  çiftler: {pairs}")

    tb, mb = margin_series(bot)
    tp, mp = margin_series(prs)
    print(f"\n  --- TEK BAŞINA marjin talebi ---")
    print(f"  {'kaynak':<10s} {'ortalama$':>10s} {'medyan$':>9s} {'%95$':>8s} {'tepe$':>8s}")
    print(f"  {'bot':<10s} {mb.mean():>10.1f} {np.median(mb):>9.1f} "
          f"{np.percentile(mb, 95):>8.1f} {mb.max():>8.1f}")
    print(f"  {'pairs':<10s} {mp.mean():>10.1f} {np.median(mp):>9.1f} "
          f"{np.percentile(mp, 95):>8.1f} {mp.max():>8.1f}")

    segs = combined(bot, prs)
    tot_t = sum(e - s for s, e, _ in segs)
    mm = np.array([m for _, _, m in segs])
    w = np.array([(e - s) / tot_t for s, e, _ in segs])
    mean_w = float((mm * w).sum())
    print(f"\n  --- BİRLEŞİK (bot + pairs, tam backtest ölçeğinde) ---")
    print(f"  süre-ağırlıklı ortalama marjin ${mean_w:.1f} · tepe ${mm.max():.1f}")
    for th in (BAL_LIVE, BAL_LIVE * 0.8, BAL_LIVE * 0.5):
        print(f"  ${th:.0f} aşılan zaman oranı: %{pct_time_over(segs, th):.1f}")

    # ── SIĞDIRMA ÇARPANI: pairs'i hangi ölçekte koşabiliriz? ──
    print(f"\n  --- SIĞDIRMA ÇARPANI k (pairs nominalini k ile çarp) ---")
    print(f"  Kural: birleşik marjin, zamanın %99'unda serbest bakiyenin %80'ini AŞMASIN.")
    print(f"  (%80 tampon: fonlama, ücret, uPnL dalgalanması ve likidasyon payı için)")
    limit = BAL_LIVE * 0.80
    best_k = 0.0
    for k in [round(x * 0.05, 2) for x in range(1, 41)]:
        scaled = [(s, e, nt * k) for s, e, nt in prs]
        sg = combined(bot, scaled)
        if pct_time_over(sg, limit) <= 1.0:
            best_k = k
        else:
            break
    print(f"  → k = {best_k:.2f}")
    print(f"  Pairs kârı nominalle DOĞRUSAL ölçeklenir:")
    print(f"     tam ölçek  +$532  (3.3 yıl) = ~${532/3.3:.0f}/yıl")
    print(f"     k={best_k:.2f} ölçek +${532*best_k:.0f}  (3.3 yıl) = ~${532*best_k/3.3:.0f}/yıl")
    print(f"\n  KIYAS: bot tek başına ~${1421/3.3:.0f}/yıl kazanıyor.")
    if best_k > 0:
        print(f"  pairs k={best_k:.2f} ile bunun ~%{532*best_k/1421*100:.0f}'i kadar EK getirir.")
    print(f"\n  UYARI: bu SADECE marjin sığdırma hesabı. Kod tarafı AYRI ve ÇÖZÜLMEMİŞ engel —")
    print(f"  exchange.py MEXC'e pozisyon yönü göndermiyor (probe_hedge2 [B]), yani hesap hedge")
    print(f"  modda olsa bile ters emrin ikinci pozisyon mu açacağı yoksa mevcut pozisyonu mu")
    print(f"  kapatacağı garanti DEĞİL. Marjin yetse bile kod değişikliği + paper test şart.")


if __name__ == "__main__":
    main()
