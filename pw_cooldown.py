"""
pw_cooldown.py — ANKORUN HİÇ MODELLEMEDİĞİ FREN: kayıp serisi cooldown'u.

BB sizing uyuşmazlığı bugün yeni bir eksen açtı: "ankor ile canlı kod arasındaki
MODELLENMEMİŞ farklar". Bunlar strateji arayışı değil — canlıyı ankora eşitleme işi.
Bulunan her fark ya bedava kâr ya da bedava risk azalması demek.

COOLDOWN o farkların en büyüğü (execution.py:263-285, 343-352):
    anahtar = f"{strateji}:{sembol}"
    kayıpta  → streak++ ; streak >= CONSECUTIVE_LOSS_LIMIT(2) ise
               o anahtar COOLDOWN_MINUTES(240) boyunca YENİ GİRİŞ ALAMAZ
    kazançta → streak = 0
Cooldown, kaybeden işlemin ÇIKIŞ anında başlar; girişleri sinyal anında bloke eder.

ANKOR (deployed_backtest.py) BU FRENİ HİÇ UYGULAMIYOR. Yani ankorun 1579 işleminin bir
kısmını canlı bot ASLA ALMADI. Bu, ankor ile canlı arasında sistematik bir sapma demek —
ve hangi yöne olduğu ÖLÇÜLMEMİŞ.

İKİ OLASILIK, İKİSİ DE İŞE YARAR:
 · Cooldown PARA KAYBETTİRİYORSA → gevşetmek (.env: limit 3, ya da süre 60dk) bedava kâr.
 · Cooldown PARA KAZANDIRIYORSA → ankor gerçek gücümüzü OLDUĞUNDAN AZ gösteriyor,
   ve sıkılaştırmak ayrı bir kazanç kapısı.

⚠ GERİ BESLEME: bir işlemi atlamak koltuğu boşaltır, o da SONRAKİ işlemleri değiştirir.
Bu yüzden cooldown, koltuk seçiminin SONRASINDA filtre olarak değil, koltuk döngüsünün
İÇİNDE simüle edilir. Kapanışlar da giriş zamanına göre değil ÇIKIŞ zamanına göre işlenir
(ayrı bir heap ile) — yoksa henüz kapanmamış bir işlemin sonucu geleceği etkilerdi.

KONTROL TESTİ: limit=∞ (fren kapalı) → 1579 işlem / $1420.66 BİREBİR çıkmalı.
Çıkmıyorsa betik bozuk demektir ve hiçbir satırı okunmaz.

ÖN-KAYITLI BAR (değişmedi): Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek ·
maxDD +2 puandan fazla artmayacak · EN KÖTÜ AY KÖTÜLEŞMEYECEK.

Kullanım:  py pw_cooldown.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

NS_DK = 60 * 1_000_000_000       # 1 dakika = ns


def olaylar(source):
    """(kol, coin, entry_ns, exit_ns, R, sl_pct) — giriş zamanına göre sıralı."""
    tagged = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            tagged.append(("donchian", c, t[0], t[1].value, t[2], t[3]))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            tagged.append(("squeeze", c, t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            tagged.append(("bb", c, t[0], t[1].value, t[2], t[3]))
    return sorted(tagged, key=lambda t: t[2])


def calistir(ev, limit, cooldown_dk):
    """Koltuk seçimi + cooldown, TEK geçişte. limit=None → fren kapalı (ankor)."""
    cd_ns = cooldown_dk * NS_DK
    koltuk = []          # (exit_ns, ctr) — MAXPOS için
    kapanis = []         # (exit_ns, ctr, key, R) — sonuçları çıkış sırasında işlemek için
    streak = {}
    cd_until = {}
    ctr = 0
    alinan = []
    bloke = 0
    for kol, coin, e_ns, x_ns, R, slp in ev:
        # 1) bu girişten ÖNCE kapanmış her işlemin sonucunu uygula (streak/cooldown)
        while kapanis and kapanis[0][0] <= e_ns:
            kapanis_ns, _, k, r = heapq.heappop(kapanis)
            if limit is None:
                continue
            if r < 0:
                streak[k] = streak.get(k, 0) + 1
                if streak[k] >= limit:
                    # cooldown KAYBIN ÇIKIŞ anından başlar (execution.py: _record_trade_result
                    # işlem kapanınca çalışır ve `now + cooldown_minutes` yazar).
                    cd_until[k] = kapanis_ns + cd_ns
            else:
                streak[k] = 0
        # 2) koltukları boşalt
        while koltuk and koltuk[0][0] <= e_ns:
            heapq.heappop(koltuk)
        # 3) cooldown kontrolü
        key = f"{kol}:{coin}"
        if limit is not None and cd_until.get(key, 0) > e_ns:
            bloke += 1
            continue
        # 4) koltuk varsa al
        if len(koltuk) < A.MAXPOS:
            ctr += 1
            heapq.heappush(koltuk, (x_ns, ctr))
            heapq.heappush(kapanis, (x_ns, ctr, key, R))
            alinan.append((kol, x_ns, R, slp))
    return alinan, bloke


def olc(taken):
    r = np.array([t[2] for t in taken]); sp = np.array([t[3] for t in taken])
    eff = np.minimum(A.RISKF, A.CAP * sp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ex = [pd.Timestamp(t[1]) for t in taken]
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    return dict(n=len(taken), tot=float(pnl.sum()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ev = olaylar(source)
    print(f"\n{'=' * 118}")
    print("=== MODELLENMEMİŞ FREN: kayıp serisi cooldown'u ===")
    print(f"  {len(ev)} aday sinyal · canlı .env: limit=2, süre=240dk")

    # ── KONTROL: fren kapalı → ankor ──
    base_t, _ = calistir(ev, None, 0)
    taban = olc(base_t)
    ok = taban["n"] == 1579 and abs(taban["tot"] - 1420.66) < 0.01
    print(f"\n  KONTROL (fren kapalı): {taban['n']} işlem / ${taban['tot']:+.2f} → "
          f"{'✓ BİREBİR — betik ankoru yeniden üretiyor' if ok else '✗ SAPMA — betik BOZUK, okuma'}")
    if not ok:
        return
    years = sorted(taban["yr"])

    print(f"\n  {'limit':>6s} {'süre dk':>8s} {'işlem':>6s} {'bloke':>6s} {'toplam$':>8s} "
          f"{'Δ$':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay':>7s} | " +
          " ".join(f"{y:>7d}" for y in years))
    print(f"  {'—':>6s} {'kapalı':>8s} {taban['n']:>6d} {0:>6d} {taban['tot']:>+8.0f} "
          f"{0:>+7.0f} {taban['dd']:>7.1f} {taban['worst']:>+9.1f} {taban['posm']:>7.0f} | " +
          " ".join(f"{taban['yr'].get(y, 0.0):>+7.0f}" for y in years) + "   ← ANKOR")

    sonuc = {}
    for limit in (2, 3, 4):
        for dk in (60, 240, 720):
            t, bl = calistir(ev, limit, dk)
            v = olc(t); sonuc[(limit, dk)] = v
            mark = "  ← CANLI" if (limit == 2 and dk == 240) else ""
            print(f"  {limit:>6d} {dk:>8d} {v['n']:>6d} {bl:>6d} {v['tot']:>+8.0f} "
                  f"{v['tot']-taban['tot']:>+7.0f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
                  f"{v['posm']:>7.0f} | " +
                  " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + mark)

    # ── HÜKÜM ──
    canli = sonuc[(2, 240)]
    print(f"\n{'=' * 118}\n=== HÜKÜM ===")
    d = canli["tot"] - taban["tot"]
    print(f"\n  1) COOLDOWN BUGÜN NE YAPIYOR? (canlı 2/240 vs fren kapalı)")
    print(f"     {taban['n']} → {canli['n']} işlem · kâr ${taban['tot']:+.0f} → ${canli['tot']:+.0f} "
          f"({d:+.0f}$)")
    print(f"     en kötü ay {taban['worst']:+.1f} → {canli['worst']:+.1f} · "
          f"maxDD {taban['dd']:.1f} → {canli['dd']:.1f}")
    if d < -28:
        print(f"     → COOLDOWN PARA KAYBETTİRİYOR. Ankor gerçek performansı FAZLA gösteriyor;")
        print(f"       canlı sonuçlarımız ankorun altında kalıyorsa sebeplerinden biri bu.")
    elif d > 28:
        print(f"     → COOLDOWN PARA KAZANDIRIYOR. Ankor gerçek gücümüzü AZ gösteriyor.")
    else:
        print(f"     → Etki ihmal edilebilir ({d:+.0f}$). Cooldown ne yardım ne zarar; "
              f"ucuz sigorta olarak kalabilir.")

    print(f"\n  2) ÖN-KAYITLI BAR — canlıya (2/240) göre daha iyi bir ayar var mı?")
    gecen = []
    for (limit, dk), v in sonuc.items():
        if (limit, dk) == (2, 240):
            continue
        w = []
        if v["tot"] - canli["tot"] <= 28: w.append(f"kâr {v['tot']-canli['tot']:+.0f}$")
        for y in years:
            b = canli["yr"].get(y, 0)
            if abs(b) > 1e-9 and (v["yr"].get(y, 0) - b) / abs(b) < -0.10:
                w.append(f"{y} kötü"); break
        if v["dd"] > canli["dd"] + 2: w.append(f"maxDD {v['dd']:.1f}")
        if v["worst"] < canli["worst"] - 0.05: w.append(f"en kötü ay {v['worst']:.1f}")
        if not w:
            gecen.append((limit, dk)); print(f"     ★ GEÇTİ  limit={limit} süre={dk}dk "
                                             f"({v['tot']-canli['tot']:+.0f}$)")
    if not gecen:
        print(f"     hiçbiri geçmedi — cooldown ayarı OLDUĞU GİBİ KALIR.")


if __name__ == "__main__":
    main()
