"""
pw_bb_margin.py — BB HİZALAMA + CAP=1.5 paketinin ÖLÜM TESTİ: marjin fiziksel olarak yetiyor mu?

pw_cap_margin.py CAP=3'ü öldürmüştü (tepe marjin $203.6 > $190 bakiye → o kâr fantezi).
AMA o betik BB kolunu da RISKF(%2.25) ile modelledi — bugün bulundu ki CANLIDA BB %9 hedefle
gidiyor ve nominali neredeyse HER ZAMAN CAP'e dayanıyor. Yani pw_cap_margin BUGÜNKÜ marjini
OLDUĞUNDAN AZ göstermiş olabilir.

Bu betik üç yapılandırmayı aynı ölçekte karşılaştırır:
  1) BUGÜN            BB %9,    CAP 1.25   ← canlıda şu an olan
  2) SADECE CAP       BB %9,    CAP 1.50   ← ön-kayıtlı bardan (en kötü ay) DÜŞTÜ
  3) HİZALI + CAP     BB %2.25, CAP 1.50   ← önerilen paket
  4) SADECE HİZALI    BB %2.25, CAP 1.25

Soru: (3) bakiyeyi aşıyor mu, ve (1)'e göre daha mı güvenli?

Kullanım:  py pw_bb_margin.py local
"""
import sys

import fast_bt
import deployed_backtest as A

LEV = 10.0
BAL = 190.0
MAXR_LIVE = 0.08 * 1.125     # canlı .env: BB'nin gerçek hedef riski


def pozisyonlar(source):
    """Ankorun ALDIĞI işlemler; kol etiketi + giriş/çıkış + sl_pct."""
    import heapq
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            tagged.append(("trend",) + t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            tagged.append(("trend",) + t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            tagged.append(("bb",) + t)
    ev = sorted(tagged, key=lambda t: t[1])
    openh = []; ctr = 0; out = []
    for kol, entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            out.append((kol, entry_ns, exit_ts.value, slp))
    return out


def profil(poz, cap, bb_risk):
    """Olay-bazlı eşzamanlı marjin. (tepe, süre-ağırlıklı ort, bakiyeyi aşma %zaman, %80 aşma)."""
    ev = []
    for kol, s, e, slp in poz:
        hedef = bb_risk if kol == "bb" else A.RISKF
        nom = min(hedef * BAL / slp, cap * BAL)
        ev.append((s, +nom / LEV)); ev.append((e, -nom / LEV))
    ev.sort()
    cur = 0.0; segs = []; prev = ev[0][0]
    for ts, d in ev:
        if ts > prev: segs.append((prev, ts, cur))
        cur += d; prev = ts
    tot = sum(e - s for s, e, _ in segs) or 1
    ort = sum(m * (e - s) for s, e, m in segs) / tot
    tepe = max(m for _, _, m in segs)
    a100 = sum(e - s for s, e, m in segs if m > BAL) / tot * 100
    a80 = sum(e - s for s, e, m in segs if m > BAL * 0.8) / tot * 100
    return tepe, ort, a100, a80


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    poz = pozisyonlar(source)
    nbb = sum(1 for p in poz if p[0] == "bb")
    print(f"\n{'=' * 104}")
    print("=== BB HİZALAMA + CAP=1.5 — MARJİN ÖLÜM TESTİ ===")
    print(f"  {len(poz)} pozisyon ({nbb} BB) · bakiye ${BAL:.0f} · kaldıraç {LEV:.0f}x")
    print(f"  DOĞRULAMA: {len(poz)} == 1579 → {'✓' if len(poz) == 1579 else '✗ SAPMA'}")
    if len(poz) != 1579:
        return

    senaryolar = [
        ("1) BUGÜN         BB %9    CAP 1.25", 1.25, MAXR_LIVE),
        ("2) SADECE CAP    BB %9    CAP 1.50", 1.50, MAXR_LIVE),
        ("3) HİZALI+CAP    BB %2.25 CAP 1.50", 1.50, A.RISKF),
        ("4) SADECE HİZALI BB %2.25 CAP 1.25", 1.25, A.RISKF),
    ]
    print(f"\n  {'yapılandırma':<36s} {'ort marjin$':>12s} {'TEPE marjin$':>13s} "
          f"{'tepe/bakiye':>12s} {'>bakiye %zmn':>13s} {'>%80 %zmn':>11s}")
    res = {}
    for ad, cap, br in senaryolar:
        tepe, ort, a100, a80 = profil(poz, cap, br)
        res[ad[0]] = (tepe, ort, a100, a80)
        uyari = "  ⛔ UYGULANAMAZ" if a100 > 0.5 else ("  ⚠ sınırda" if a80 > 5 else "  ✓")
        print(f"  {ad:<36s} ${ort:>11.1f} ${tepe:>12.1f} {tepe/BAL:>11.0%} "
              f"{a100:>12.1f}% {a80:>10.1f}%{uyari}")

    t1, o1 = res["1"][0], res["1"][1]
    t3, o3 = res["3"][0], res["3"][1]
    print(f"\n{'=' * 104}\n=== HÜKÜM ===")
    print(f"  Önerilen paket (3) vs bugün (1):")
    print(f"    tepe marjin  ${t1:.1f} → ${t3:.1f}  ({t3-t1:+.1f}$)")
    print(f"    ort marjin   ${o1:.1f} → ${o3:.1f}  ({o3-o1:+.1f}$)")
    if res["3"][2] > 0.5:
        print(f"    ⛔ Paket bakiyeyi aşıyor — CAP=1.5 UYGULANAMAZ, kâr rakamı fantezi.")
    elif t3 <= t1:
        print(f"    ✓ Paket bugünden DAHA AZ marjin kullanıyor. Fiziksel engel yok.")
    else:
        print(f"    ✓ Marjin bakiyeyi aşmıyor (tepe %{t3/BAL*100:.0f}), ama bugünden "
              f"${t3-t1:.1f} fazla — tampon {BAL-t3:.0f}$.")


if __name__ == "__main__":
    main()
