"""
pairs_collide.py — PAIRS'İ ALT HESAP OLMADAN, AYNI HESAPTA KOŞMAK: ne kadarı hayatta kalır?

SORU (kullanıcı): "başka türlü halledemiyor muyuz?" — alt hesap açmadan pairs'i çalıştırmanın
yolu var mı?

ENGEL: MEXC netted mod — bir hesapta, bir sembolde TEK net pozisyon. Bot ADA'da LONG taşırken
pairs ADA'yı SHORT'larsa emirler birbirini NETLER. Ve pairs edge'i tam da vazgeçemeyeceğimiz
coinlerde yaşıyor (ADA/DOT, XLM/XRP, ADA/ALGO, ADA/ATOM; ADA en iyi donchian coinimiz PF1.78).

TEST EDİLEN POLİTİKA — "ÇAKIŞANI ATLA": pairs sinyali geldiğinde, iki bacaktan HERHANGİ BİRİNİN
sembolünde bot'un AÇIK pozisyonu varsa o çift işlemi ALINMAZ. Alt hesap YOK, kod riski minimal,
bota SIFIR dokunuş (pairs ayrı bir süreç olarak aynı hesapta koşar, sadece kendi sinyalini eler).

ÖLÇÜLEN: tam setin +$532'sinin yüzde kaçı hayatta kalıyor? Ve hayatta kalan kısım hâlâ
HER YIL pozitif mi (pairs'in orijinal barı buydu)?

İKİNCİ POLİTİKA — "PAIRS ÖNCELİKLİ": bot'un o sembole girmesini engellemek. ÖLÇÜLMÜYOR çünkü
bota dokunmayı gerektirir ve bot'un kaybı pairs'in kazancından büyük olabilir; ayrıca bu artık
"alt hesap gerekmez" değil "bot'u boz" demektir. Kapsam dışı olduğu AÇIKÇA belirtiliyor.

DOĞRULAMA: kısıtsız (çakışma filtresi kapalı) sonuç, ledger'ın 8-çiftlik setiyle uyuşmalı
(+$532 civarı, 4/4 yıl pozitif). Uyuşmuyorsa araç bozuktur ve tablo basılmaz.

Kullanım:  py pairs_collide.py local
"""
import sys
import bisect

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
import pairs_verify as P


def bot_occupancy(source):
    """Bot'un GERÇEKTEN aldığı işlemlerin sembol bazında meşguliyet aralıkları.

    A.seat_select sembolü taşımıyor; burada sembol etiketlenerek aynı sıralama kuralıyla
    (kararlı sort, DONCH→SQZ→BB) yeniden koşuluyor. Koltuk bulamayan sinyal pozisyon AÇMAZ,
    dolayısıyla sembolü de MEŞGUL ETMEZ — bu yüzden filtre ham sinyale değil, seat_select'ten
    GEÇEN işlemlere göre kurulmalı."""
    import heapq
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)): tagged.append((c,) + t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)): tagged.append((c,) + t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)): tagged.append((c,) + t)
    ev = sorted(tagged, key=lambda t: t[1])
    openh = []; ctr = 0; taken = []
    for sym, entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((sym, entry_ns, exit_ts.value, R, slp))
    occ = {}
    for sym, s, e, _R, _sp in taken:
        occ.setdefault(sym, []).append((s, e))
    for sym in occ:
        occ[sym].sort()
    tot = sum(len(v) for v in occ.values())
    return occ, tot, taken


def busy(occ, sym, t0, t1):
    """[t0,t1] aralığında sym meşgul mü? (aralık kesişimi, binary search)"""
    iv = occ.get(sym)
    if not iv: return False
    i = bisect.bisect_right([s for s, _ in iv], t1)
    for s, e in iv[max(0, i - 40):i]:
        if s <= t1 and e >= t0:
            return True
    return False


def run_pair_col(px, a, b, z_in, z_out, z_stop, occ=None):
    """P.run_pair ile AYNI mantık; occ verilirse çakışan işlem ATLANIR.
    Filtre ÜRETİM SIRASINDA uygulanıyor (post-hoc değil): atlanan işlem bir sonraki
    aramanın başlangıcını da etkiler — canlıda da öyle olurdu."""
    lg = np.log(px[[a, b]].dropna())
    sp = lg[a] - lg[b]
    mu = sp.rolling(P.ZWIN).mean(); sd = sp.rolling(P.ZWIN).std()
    z = ((sp - mu) / sd).values
    idx = sp.index; ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
    n = len(z)
    out = []; skipped = 0
    i = P.ZWIN + 1
    while i < n - 1:
        if not np.isfinite(z[i]) or abs(z[i]) < z_in:
            i += 1; continue
        d_ = -1 if z[i] > 0 else +1
        ex = None
        for j in range(i + 1, min(i + 1 + P.MAXBARS, n)):
            if not np.isfinite(z[j]): continue
            if abs(z[j]) < z_out or abs(z[j]) > z_stop: ex = j; break
        if ex is None: ex = min(i + P.MAXBARS, n - 1)
        if occ is not None:
            t0 = idx[i].value; t1 = idx[ex].value
            if busy(occ, a, t0, t1) or busy(occ, b, t0, t1):
                skipped += 1
                i += 1              # işlem AÇILMADI → bir sonraki bardan aramaya devam
                continue
        r_a = d_ * (ra[ex] - ra[i]) / ra[i]
        r_b = -d_ * (rb[ex] - rb[i]) / rb[i]
        out.append({"ret": (r_a + r_b) / 2 - 4 * P.FEE, "ts": idx[ex]})
        i = ex + 1
    return out, skipped


def show(tag, r, base=None):
    if r is None:
        print(f"  {tag:<28s} (işlem yok)"); return
    ys = " ".join(f"{r['yrs'].get(y, 0.0):>+7.0f}" for y in (2023, 2024, 2025, 2026))
    allpos = all(r["yrs"].get(y, 0) > 0 for y in (2023, 2024, 2025, 2026))
    pct = "" if base is None else f" {r['tot']/base['tot']*100:>5.0f}%"
    print(f"  {tag:<28s} {r['n']:>5d} {r['tot']:>+8.0f}{pct} {r['pf']:>6.2f} "
          f"{r['train']:>+8.0f} {r['test']:>+8.0f} | {ys}  {'✓ 4/4 yıl+' if allpos else '✗'}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = P.load_px(source)
    pairs, _ = P.pick_pairs(px, P.NPAIRS)
    Z = (2.0, 0.5, 3.5)     # ledger'ın seçtiği konfig
    print(f"\n{'=' * 112}")
    print("=== PAIRS'İ ALT HESAP OLMADAN KOŞMAK — 'çakışanı atla' politikası ===")
    print(f"  çiftler (TRAIN'den seçildi): {pairs}")
    print(f"  z konfigi: giriş {Z[0]} / çıkış {Z[1]} / stop {Z[2]}")

    print("\n  bot meşguliyet haritası çıkarılıyor (seat_select'ten GEÇEN işlemler)...")
    occ, ntak, taken = bot_occupancy(source)
    print(f"  bot {ntak} pozisyon açmış; sembol bazında meşguliyet:")
    for s in sorted(occ, key=lambda k: -len(occ[k])):
        span = sum(e - st for st, e in occ[s]) / 1e9 / 86400
        print(f"     {s:>5s}  {len(occ[s]):>4d} pozisyon, toplam {span:>6.0f} gün meşgul")

    hdr = (f"  {'senaryo':<28s} {'işlem':>5s} {'toplam$':>8s} {'  %':>6s} {'PF':>6s} "
           f"{'TRAIN':>8s} {'TEST':>8s} | {'2023':>7s} {'2024':>7s} {'2025':>7s} {'2026':>7s}")

    # ── kısıtsız (doğrulama) ──
    free_tr = []
    for a, b in pairs:
        t, _ = run_pair_col(px, a, b, *Z, occ=None)
        free_tr += t
    free = P.agg(free_tr)
    print(f"\n{hdr}")
    show("ALT HESAP (kısıtsız)", free, free)
    ok = free is not None and 450 <= free["tot"] <= 620
    print(f"\n  DOĞRULAMA: ledger +$532 diyor → ölçülen ${free['tot']:+.0f}  "
          f"{'✓ uyuşuyor' if ok else '✗ SAPMA — araç şüpheli, aşağısı okunmamalı'}")
    if not ok:
        return

    # ── aynı hesap, çakışanı atla ──
    col_tr = []; nskip = 0
    for a, b in pairs:
        t, sk = run_pair_col(px, a, b, *Z, occ=occ)
        col_tr += t; nskip += sk
    col = P.agg(col_tr)
    print(f"\n{hdr}")
    show("ALT HESAP (kısıtsız)", free, free)
    show("AYNI HESAP (çakışanı atla)", col, free)
    print(f"\n  çakışma yüzünden atlanan çift işlemi: {nskip}")

    # ── çift bazında kırılım: hangi çiftler kurtulabiliyor ──
    print(f"\n  --- ÇİFT BAZINDA (hangi çiftler alt hesap olmadan yaşıyor) ---")
    print(f"  {'çift':<14s} {'kısıtsız$':>10s} {'aynı hesap$':>12s} {'atlanan':>8s} {'kalan%':>7s}")
    for a, b in pairs:
        t0, _ = run_pair_col(px, a, b, *Z, occ=None)
        t1, sk = run_pair_col(px, a, b, *Z, occ=occ)
        r0 = P.agg(t0); r1 = P.agg(t1)
        v0 = r0["tot"] if r0 else 0.0
        v1 = r1["tot"] if r1 else 0.0
        pc = (v1 / v0 * 100) if abs(v0) > 1e-9 else 0.0
        mark = "  ← bot'ta YOK" if (a not in occ and b not in occ) else ""
        print(f"  {a + '/' + b:<14s} {v0:>+10.0f} {v1:>+12.0f} {sk:>8d} {pc:>6.0f}%{mark}")

    print(f"\n{'=' * 112}")
    print("=== HÜKÜM ===")
    if col is None:
        print("  Aynı hesapta hiç işlem kalmıyor → alt hesap ZORUNLU."); return
    keep = col["tot"] / free["tot"] * 100
    allpos = all(col["yrs"].get(y, 0) > 0 for y in (2023, 2024, 2025, 2026))
    print(f"  Kısıtsız $+{free['tot']:.0f} → aynı hesapta $+{col['tot']:.0f}  (%{keep:.0f} hayatta)")
    print(f"  Her yıl pozitif: {'EVET' if allpos else 'HAYIR'}  |  TEST dönemi ${col['test']:+.0f}")
    print(f"\n  Bar (pairs'in orijinal barı): her yıl pozitif VE TEST pozitif VE büyüklük anlamlı")
    if allpos and col["test"] > 0 and col["tot"] > 100:
        print("  ★ ALT HESAP GEREKMEYEBİLİR — aynı hesapta anlamlı kısım yaşıyor.")
        print("    (yine de: bu bir ADAY, deploy değil. Kod yazmadan önce bağımsız çürütme şart.)")
    else:
        print("  ✗ Aynı hesapta kalan kısım barı geçmiyor → alt hesap gerçekten gerekli.")


if __name__ == "__main__":
    main()
