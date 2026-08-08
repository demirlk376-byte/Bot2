"""
pairs_robust.py — PAIRS'E "GEREK VAR MI" SORUSUNUN SON ÜÇ TESTİ.

Maliyet ölüm testi GEÇİLDİ (pairs_cost.py): ölçülen 13.4 bp/dolum sürtünmede +$419,
PF 1.47, TRAIN+262/TEST+157, 4/4 yıl pozitif. Edge >30 bp'ye kadar ölmüyor.

AMA maliyet, bulguyu öldürebilecek TEK şey değil. Kullanıcı haftalarca sürecek bir kod
işine girmeden önce "emin ol" dedi. Geriye ÜÇ klasik overfit vektörü kaldı ve üçü de
bu depoda pairs için HİÇ sorulmadı:

 T1 — ÇOKLU TEST (z konfigi): 2.0/0.5/3.5 üçlüsü kaç aday arasından seçildi? Eğer edge
      yalnız o hücrede varsa seçim yanlılığıdır. Gerçek bir ortalamaya-dönüş etkisi
      KOMŞU hücrelerde de görünmeli. Tüm ızgara raporlanıyor — kiraz toplama yok.

 T2 — ÇİFT SAYISI (NPAIRS): 8 sayısı nereden geldi? Edge yalnız 8'de varsa gürültüdür.
      4/6/8/10/12/16 taranıyor; korelasyon sıralaması TRAIN'den, TEST'e bakılmadan.

 T3 — YOĞUNLAŞMA: kârın kaçı en iyi birkaç işlemde? Bu oturumda trailing bulgusu tam
      bunun için düşmüştü (kârın %73'ü 24 işlemde). En iyi 1/3/5/10 işlem çıkarılınca
      ne kalıyor — ve 4/4 yıl kuralı hâlâ geçiyor mu?

HEPSİ ÖLÇÜLEN MALİYETLE (13.4 bp/dolum) koşuluyor — artık 4bp'lik fantezi yok.

Kullanım:  py pairs_robust.py local
"""
import sys
import itertools

import numpy as np
import pandas as pd

import pairs_verify as P
from pairs_cost import run_pair_cost, agg

BP = 13.4          # ölçülen sürtünme, dolum başına


def build(px, pairs, z, bp=BP):
    trs = []
    for a, b in pairs:
        trs += run_pair_cost(px, a, b, *z, bp_per_fill=bp)
    return trs


def line(r, tag, mark=""):
    if r is None:
        print(f"  {tag:<22s} (işlem yok)"); return
    y = r["yrs"]
    print(f"  {tag:<22s} {r['n']:>4d} {r['tot']:>+8.0f} {r['pf']:>6.2f} "
          f"{r['train']:>+8.0f} {r['test']:>+8.0f} " +
          " ".join(f"{y.get(k, 0.0):>+7.0f}" for k in (2023, 2024, 2025, 2026)) +
          f"  {'✓' if r['allpos'] else '✗':>3s}" + mark)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = P.load_px(source)
    pairs8, ncand = P.pick_pairs(px, 8)
    Z0 = (2.0, 0.5, 3.5)

    print(f"\n{'=' * 104}")
    print(f"=== PAIRS SAĞLAMLIK — üç overfit vektörü, HEPSİ {BP} bp/dolum gerçek maliyetle ===")
    print(f"  aday çift havuzu: {ncand} · seçilen 8: {pairs8}")
    hdr = (f"  {'':<22s} {'n':>4s} {'toplam$':>8s} {'PF':>6s} {'TRAIN$':>8s} {'TEST$':>8s} "
           f"{'2023':>7s} {'2024':>7s} {'2025':>7s} {'2026':>7s}  {'4/4':>3s}")

    # ── T1: z ızgarası ──
    print(f"\n--- T1) ÇOKLU TEST: z konfigi ızgarası (edge sadece seçilen hücrede mi?) ---")
    print(hdr)
    grid = []
    for zi in (1.5, 1.75, 2.0, 2.25, 2.5):
        for zo in (0.25, 0.5, 0.75):
            for zs in (3.0, 3.5, 4.0):
                r = agg(build(px, pairs8, (zi, zo, zs)))
                grid.append(((zi, zo, zs), r))
    for cfg, r in grid:
        if r is None: continue
        mark = "  ← LEDGER" if cfg == Z0 else ""
        if cfg == Z0 or cfg[1] == 0.5 and cfg[2] == 3.5:
            line(r, f"z {cfg[0]}/{cfg[1]}/{cfg[2]}", mark)
    poz = sum(1 for _, r in grid if r and r["tot"] > 0)
    allpos = sum(1 for _, r in grid if r and r["allpos"])
    tots = [r["tot"] for _, r in grid if r]
    print(f"\n  IZGARA ÖZETİ: {len(tots)} hücre · {poz} tanesi KÂRLI (%{poz/len(tots)*100:.0f}) · "
          f"{allpos} tanesi 4/4 yıl+ (%{allpos/len(tots)*100:.0f})")
    print(f"  medyan ${np.median(tots):+.0f} · en kötü ${min(tots):+.0f} · en iyi ${max(tots):+.0f}")
    print(f"  ledger'ın seçtiği hücre ${[r['tot'] for c, r in grid if c == Z0][0]:+.0f} → "
          f"ızgaranın {sum(1 for t in tots if t < [r['tot'] for c, r in grid if c == Z0][0])/len(tots)*100:.0f}. yüzdeliği")
    print(f"  OKUMA: kârlı hücre oranı yüksekse edge YAPISAL; sadece birkaç hücre kârlıysa SEÇİM.")

    # ── T2: çift sayısı ──
    print(f"\n--- T2) ÇİFT SAYISI: 8 sayısı seçilmiş mi? ---")
    print(hdr)
    for k in (4, 6, 8, 10, 12, 16):
        pk, _ = P.pick_pairs(px, k)
        line(agg(build(px, pk, Z0)), f"NPAIRS={k}", "  ← LEDGER" if k == 8 else "")

    # ── T3: yoğunlaşma ──
    print(f"\n--- T3) YOĞUNLAŞMA: kâr birkaç işlemde mi toplanmış? ---")
    trs = build(px, pairs8, Z0)
    d = np.array([t["ret"] * P.BAL0 for t in trs])
    ts = [pd.Timestamp(t["ts"]) for t in trs]
    order = np.argsort(-d)
    print(hdr)
    line(agg(trs), "hepsi")
    for drop in (1, 3, 5, 10, 20):
        keep = [trs[i] for i in range(len(trs)) if i not in set(order[:drop].tolist())]
        line(agg(keep), f"en iyi {drop} çıkarıldı")
    top5 = d[order[:5]].sum()
    print(f"\n  en iyi 5 işlem toplam ${top5:+.0f} = tüm kârın %{top5/d.sum()*100:.0f}'i")
    print(f"  (kıyas: bu oturumda trailing bulgusu 'kârın %73'ü 24 işlemde' diye düşmüştü)")

    print(f"\n{'=' * 104}")
    print("HÜKÜM NASIL OKUNUR — üçü birden geçmeli:")
    print("  T1: ızgaranın BÜYÜK ÇOĞUNLUĞU kârlı olmalı (edge yapısal, hücreye özel değil)")
    print("  T2: farklı çift sayılarında da kârlı olmalı (8 sihirli bir sayı olmamalı)")
    print("  T3: en iyi 5 işlem çıkınca kâr ve 4/4 yıl kuralı AYAKTA kalmalı")


if __name__ == "__main__":
    main()
