"""
sleeve_audit.py — "Hangi kol bizi bitiriyor?" sorusunun DOĞRU sorulmuş hali.

YANLIŞ SORU: "bu sleeve tek başına ne kazandı?" — çünkü koltuklar paylaşılıyor. Bir kolu
çıkarınca onun kullandığı koltuklar BOŞALIR ve başka sinyaller girer. Tek-başına rakamı,
o ikinci mertebeden etkiyi görmez.

DOĞRU SORU: "bu kolu ÇIKARSAK kitap ne yapar?" (leave-one-out). Kol gerçekten zarar veriyorsa
çıkarınca toplam ARTAR. Bu, canlıda alınacak kararla birebir aynı soru (env'den kapatmak).

Aynı analiz COIN bazında da yapılır: belki sorun bir sleeve değil, o sleeve içindeki tek bir coin.

KABUL BARI (kapatma kararı için): çıkarınca toplam ARTACAK **ve** HER YIL artacak.
Tek yıl iyileşmesi yetmez — bu oturumda beş fikir tam o tuzağa düştü.

Taban = deployed_backtest.py'nin ÜRETTİĞİ tam canlı config (BB/LTC hafta sonu DAHİL).

Kullanım:  py sleeve_audit.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB


def tagged_trades(source):
    """Her işlemi (sleeve, coin) etiketiyle üret."""
    out = []
    for c in DB.DONCH:
        for t in DB.gen("donchian", fast_bt.load(c, source=source)):
            out.append((t[0], t[1], t[2], t[3], "donchian", c))
    for c in DB.SQZ:
        for t in DB.gen("squeeze", fast_bt.load(c, source=source)):
            out.append((t[0], t[1], t[2], t[3], "squeeze", c))
    for c in DB.BB_COINS:
        for t in DB.gen_bb(fast_bt.load(c, source=source)):
            out.append((t[0], t[1], t[2], t[3], "bb", c))
    return out


def seat_select(trades):
    """deployed_backtest.seat_select ile aynı mantık, etiketleri koruyarak."""
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, sv, cn in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, sv, cn))
    return taken


def stats(taken):
    if not taken:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, yrs={})
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    ya = np.array([pd.Timestamp(t[0]).year for t in taken])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * slp) * DB.BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), pf=gp / max(gl, 1e-9),
                wr=(r > 0).mean() * 100,
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    all_tr = tagged_trades(source)
    base = stats(seat_select(all_tr))
    ys = " ".join(f"{y}:${v:+.0f}" for y, v in base["yrs"].items())
    print(f"\n{'='*104}\n=== SLEEVE/COIN DENETİMİ — 'çıkarsak ne olur?' (leave-one-out) ===")
    print(f"  TABAN (tam canlı config): n={base['n']} PF {base['pf']:.2f} "
          f"WR %{base['wr']:.0f} ${base['tot']:+.0f}   {ys}")

    # ── tek başına katkı (kıyas için, KARAR VERDİRMEZ) ──
    print(f"\n  --- A) TEK BAŞINA (koltuk rekabeti YOK — yanıltıcı, sadece kıyas) ---")
    print(f"  {'kol':<10s} {'n':>5s} {'PF':>5s} {'WR':>4s} {'toplam$':>9s}   yıl-yıl")
    for sv in ("donchian", "squeeze", "bb"):
        s = stats(seat_select([t for t in all_tr if t[4] == sv]))
        y = " ".join(f"{k}:${v:+.0f}" for k, v in s["yrs"].items())
        print(f"  {sv:<10s} {s['n']:>5d} {s['pf']:>5.2f} {s['wr']:>3.0f}% {s['tot']:>+9.0f}   {y}")

    # ── leave-one-out: KARAR VERDİREN ölçü ──
    print(f"\n  --- B) ÇIKARINCA NE OLUR (leave-one-out) — KARAR BU SATIRLARDAN ÇIKAR ---")
    print(f"  {'çıkarılan':<12s} {'n':>5s} {'toplam$':>9s} {'Δ':>8s}  yıl-yıl Δ                                 karar")
    for sv in ("donchian", "squeeze", "bb"):
        s = stats(seat_select([t for t in all_tr if t[4] != sv]))
        d = s["tot"] - base["tot"]
        dy = {y: s["yrs"].get(y, 0.0) - base["yrs"].get(y, 0.0) for y in base["yrs"]}
        every = all(v > 0 for v in dy.values())
        verdict = ("★ KAPATILMALI" if (d > 0 and every)
                   else "zarar ediyor ama yıl-yıl DEĞİL" if d > 0 else "KATKI SAĞLIYOR (tut)")
        y = " ".join(f"{k}:{v:+.0f}" for k, v in dy.items())
        print(f"  {sv:<12s} {s['n']:>5d} {s['tot']:>+9.0f} {d:>+8.0f}  {y}  {verdict}")

    # ── coin bazında leave-one-out ──
    print(f"\n  --- C) COIN BAZINDA ÇIKARINCA (sorun bir sleeve değil tek coin olabilir) ---")
    print(f"  {'çıkarılan':<8s} {'sleeve':<10s} {'Δtoplam':>9s}  yıl-yıl Δ                                  karar")
    rows = []
    for cn in sorted({t[5] for t in all_tr}):
        sv = next(t[4] for t in all_tr if t[5] == cn)
        s = stats(seat_select([t for t in all_tr if t[5] != cn]))
        d = s["tot"] - base["tot"]
        dy = {y: s["yrs"].get(y, 0.0) - base["yrs"].get(y, 0.0) for y in base["yrs"]}
        rows.append((d, cn, sv, dy, all(v > 0 for v in dy.values())))
    for d, cn, sv, dy, every in sorted(rows, reverse=True):
        verdict = ("★ ÇIKARILMALI" if (d > 0 and every)
                   else "zararlı ama yıl-yıl değil" if d > 0 else "katkı sağlıyor")
        y = " ".join(f"{k}:{v:+.0f}" for k, v in dy.items())
        print(f"  {cn:<8s} {sv:<10s} {d:>+9.0f}  {y}  {verdict}")

    print(f"\n  OKUMA: Δ POZİTİF = çıkarınca kitap İYİLEŞİYOR = o kol/coin zarar veriyor.")
    print(f"  Ama kapatma kararı için HER YIL da iyileşmeli — tek yıl iyileşmesi gürültüdür.")
    print(f"  A ile B çelişebilir: tek başına zararlı bir kol, boşalttığı koltuk yüzünden")
    print(f"  portföyde faydalı olabilir (ya da tersi). B doğru olan.")


if __name__ == "__main__":
    main()
