"""
pw_risk_scale.py — "RİSKİ ARTIRALIM MI?" sorusunun fiziksel sınırı.

Sabit-oran modelinde riski artırmak kârı da düşüşü de AYNI oranda büyütür. Yani
"daha çok kâr" tek başına bir bulgu değil; bedeli maxDD ve en kötü ay sütunlarında.
Bu betik o takası gösterir — AMA asıl işi başka:

⚠️ BACKTEST'İN GÖRMEDİĞİ DUVAR: MARJİN.
Risk arttıkça pozisyon nominali büyür, nominal büyüyünce eşzamanlı marjin talebi büyür.
Talep bakiyeyi aştığı anda o işlemler CANLIDA AÇILAMAZ (execution.py'deki ön-kontrol
`margin_required > balance*0.95` ise işlemi ATLAR). Backtest onları almış sayar →
o satırdaki kâr FANTEZİDİR. pw_cap_margin CAP=3'ü tam olarak böyle öldürmüştü.

CAP=1.5'te tepe marjin zaten bakiyenin %82'si. Yani tampon $34. Riski artırmak bu
tamponu yer. Betik her RISK_SCALE için tepe marjini ve bakiyeyi aşma süresini verir.

Yapılandırma: BB HİZALI (paket sonrası hâl) + CAP=1.5.

Kullanım:  py pw_risk_scale.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

LEV = 10.0
CAP_YENI = 1.50


def pozisyonlar(source):
    """Ankorun ALDIĞI işlemler: (giriş_ns, çıkış_ns, R, sl_pct)."""
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)): tagged.append(t)
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)): tagged.append(t)
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)): tagged.append(t)
    ev = sorted(tagged, key=lambda t: t[0])
    openh = []; ctr = 0; out = []
    for entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            out.append((entry_ns, exit_ts, R, slp))
    return out


def olc(poz, riskf, cap, bal):
    r = np.array([p[2] for p in poz]); sp = np.array([p[3] for p in poz])
    eff = np.minimum(riskf, cap * sp)
    pnl = r * eff * bal
    eq = bal + np.cumsum(pnl)
    ex = [pd.Timestamp(p[1]) for p in poz]
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / bal * 100
    # marjin: olay-bazlı eşzamanlı talep
    nom = np.minimum(riskf * bal / sp, cap * bal)
    ev = []
    for i, p in enumerate(poz):
        ev.append((p[0], +nom[i] / LEV)); ev.append((p[1].value, -nom[i] / LEV))
    ev.sort()
    cur = 0.0; segs = []; prev = ev[0][0]
    for ts, d in ev:
        if ts > prev: segs.append((prev, ts, cur))
        cur += d; prev = ts
    tot = sum(e - s for s, e, _ in segs) or 1
    tepe = max(m for _, _, m in segs)
    asan = sum(e - s for s, e, m in segs if m > bal * 0.95) / tot * 100
    return dict(tot=float(pnl.sum()), dd=float(A.maxdd(np.concatenate([[bal], eq]))),
                worst=float(mon.min()), tepe=float(tepe), asan=float(asan),
                ort_risk=float(eff.mean() * 100))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bal = float(sys.argv[2]) if len(sys.argv) > 2 else A.BAL0
    poz = pozisyonlar(source)
    print(f"\n{'=' * 112}")
    print("=== RİSKİ ARTIRMALI MI? — kâr/düşüş takası ve MARJİN DUVARI ===")
    print(f"  {len(poz)} işlem · bakiye ${bal:.0f} · kaldıraç {LEV:.0f}x · CAP={CAP_YENI} (paket sonrası)")
    print(f"  DOĞRULAMA: {len(poz)} == 1579 → {'✓' if len(poz) == 1579 else '✗ SAPMA'}")
    if len(poz) != 1579:
        return

    taban = olc(poz, A.RISKF, CAP_YENI, bal)
    print(f"\n  {'RISK_SCALE':>11s} {'risk/işlem':>11s} {'toplam$':>9s} {'Δ%':>7s} {'maxDD%':>7s} "
          f"{'en kötü ay%':>12s} {'ay $kaybı':>10s} {'TEPE marjin$':>13s} {'tepe/bak':>9s} "
          f"{'>bakiye':>8s}")
    for rs in (0.875, 1.000, 1.125, 1.250, 1.500, 1.750, 2.000):
        riskf = 0.02 * rs
        v = olc(poz, riskf, CAP_YENI, bal)
        mark = "  ← ŞU AN" if abs(rs - 1.125) < 1e-9 else ""
        if v["asan"] > 0.5:
            mark += "  ⛔ FANTEZİ (marjin yetmiyor)"
        elif v["tepe"] > bal * 0.9:
            mark += "  ⚠ tampon yok"
        print(f"  {rs:>11.3f} {riskf*100:>10.2f}% {v['tot']:>+9.0f} "
              f"{(v['tot']/taban['tot']-1)*100:>+6.0f}% {v['dd']:>7.1f} {v['worst']:>+12.1f} "
              f"{v['worst']/100*bal:>+10.0f} {v['tepe']:>13.1f} {v['tepe']/bal:>8.0%} "
              f"{v['asan']:>7.1f}%{mark}")

    print(f"\n{'=' * 112}\n=== NASIL OKUNUR ===")
    print(f"  · 'Δ%' ile 'maxDD%' NEREDEYSE AYNI oranda büyür — sabit-oran modelinde risk")
    print(f"    artışı bedava kâr değil, ölçek değişimidir. Seçim getiri değil, DAYANMA seçimidir.")
    print(f"  · 'ay $kaybı' = en kötü ayda bu bakiyeyle cebinden çıkacak para.")
    print(f"  · '>bakiye' > %0 olan satır UYGULANAMAZ: o işlemler canlıda açılamaz")
    print(f"    (execution.py marjin ön-kontrolü atlar), backtest kârı gerçekleşmez.")


if __name__ == "__main__":
    main()
