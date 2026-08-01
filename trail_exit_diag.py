"""
trail_exit_diag.py — trail_exit_test.py sonrası ÖZ-DENETİM + kuyruk analizi.

Üç soru:
 1) KUYRUK: trailing gerçekten "çok büyük kazanan" üretti mi? (maxR, R>5/R>10 sayısı, top-10 payı)
 2) ÖZ-DENETİM (kaldıraç/erken-çıkış tuzağı): donchian-trail KAYBEDENLERİ de kesiyor mu?
    Ort kaybeden R tabana göre küçüldüyse, bu "kazananı koştur" değil ÖRTÜK ERKEN ÇIKIŞ'tır
    (zaten reddedilmiş sınıf) — o zaman TRAIN kazancının kaynağı yanlış atfedilir.
 3) HİLE TESTİ: TEST'e bakarak seçseydik (yasak) HERHANGİ bir varyant 4/4 yıl tabanı geçer miydi?
    Geçmiyorsa "yanlış parametre seçtik" savunması da kapanır.

Kullanım:  py trail_exit_diag.py
"""
import numpy as np, pandas as pd
import trail_exit_test as T

P = T.build_cache("local")
base = T.stats(T.portfolio(P, {}), funding=False)
basef = T.stats(T.portfolio(P, {}), funding=True)

def tail(st):
    r = st["R"]
    top = np.sort(r)[-10:]
    return (f"maxR {r.max():+.1f} | R>5: {(r>5).sum():3d} | R>10: {(r>10).sum():2d} | "
            f"top10 toplam {top.sum():+.0f}R (${(np.sort(st['pnl'])[-10:]).sum():+.0f}) | "
            f"ort kazanan {r[r>0].mean():+.2f}R | ort KAYBEDEN {r[r<0].mean():+.2f}R | "
            f"kaybeden payı %{(r<0).mean()*100:.0f}")

print("=" * 110)
print("1+2) KUYRUK ve KAYBEDEN ANATOMİSİ (funding YOK, tüm dönem)")
print("=" * 110)
print(f"  {'TABAN':26s} {tail(base)}")
for spec, tag in [({"donchian": ("dontr", 20)}, "donchian dontr20 (TRAIN en iyi)"),
                  ({"donchian": ("dontr", 30)}, "donchian dontr30"),
                  ({"donchian": ("chand", 5.0)}, "donchian chand5.0"),
                  ({"donchian": ("chand", 4.0)}, "donchian chand4.0"),
                  ({"donchian": ("hchand", 4.0)}, "donchian hchand4.0"),
                  ({"donchian": ("hdontr", 20)}, "donchian hdontr20")]:
    st = T.stats(T.portfolio(P, spec), funding=False)
    print(f"  {tag:26s} {tail(st)}")

# sadece donchian bacaklarının kendi R'leri (portföy karışımı değil)
print("\n  -- yalnız DONCHIAN işlemleri (koltuk seçimi sonrası, sleeve izole) --")
for spec, tag in [({}, "TABAN"), ({"donchian": ("dontr", 20)}, "dontr20"),
                  ({"donchian": ("chand", 5.0)}, "chand5.0"),
                  ({"donchian": ("hchand", 4.0)}, "hchand4.0")]:
    st = T.stats(T.portfolio(P, spec), funding=False)
    m = st["slv"] == "donchian"; r = st["R"][m]
    print(f"  {tag:12s} n{m.sum():4d} ort {r.mean():+.3f}R | kazanan {r[r>0].mean():+.2f}R "
          f"(%{(r>0).mean()*100:.0f}) | KAYBEDEN {r[r<0].mean():+.3f}R | "
          f"tam-stop (<= -0.95R) payı %{(r <= -0.95).mean()*100:.0f} | maxR {r.max():+.1f}")

print("\n" + "=" * 110)
print("3) HİLE TESTİ — TEST'e bakarak seçseydik: 4/4 yıl tabanı geçen VAR MI? (66 kombinasyon)")
print("=" * 110)
KS = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]; NS = [5, 10, 15, 20, 30]
variants = ([("chand", k) for k in KS] + [("dontr", n) for n in NS] +
            [("hchand", k) for k in KS] + [("hdontr", n) for n in NS])
passers = []; test_beats = 0; tot = 0
rows = []
for slv in ("donchian", "squeeze", "bb"):
    for (mode, prm) in variants:
        st = T.stats(T.portfolio(P, {slv: (mode, prm)}), funding=True)
        tot += 1
        yok = all(st["by_year"].get(y, 0) > basef["by_year"].get(y, 0) for y in (2023, 2024, 2025, 2026))
        tb = st["test"] > basef["test"]
        test_beats += int(tb)
        rows.append((slv, mode, prm, st["train"], st["test"], yok, tb))
        if yok and tb: passers.append((slv, mode, prm, st["train"], st["test"]))
print(f"  TEST'te tabanı geçen: {test_beats}/{tot} kombinasyon (şansla beklenen ~{tot//2})")
print(f"  4/4 YIL tabanı geçen: {len(passers)}/{tot}")
for p in passers: print(f"    {p}")
print("\n  TRAIN'de tabanı geçenler ve onların TEST kaderi:")
tw = [r for r in rows if r[3] > basef["train"]]
print(f"    TRAIN'i geçen {len(tw)}/{tot}; bunlardan TEST'i de geçen: {sum(1 for r in tw if r[6])}")
for r in sorted(tw, key=lambda x: -x[3])[:12]:
    print(f"    {r[0]:9s} {r[1]:7s} {str(r[2]):5s} TRAIN ${r[3]:+7.0f} (taban ${basef['train']:+.0f}) "
          f"→ TEST ${r[4]:+7.0f} (taban ${basef['test']:+.0f}) {'GEÇ' if r[6] else 'KALDI'}")

print("\n" + "=" * 110)
print("4) TRAIN KAZANCI NEREDEN? donchian trail ailesi, yıl-yıl DELTA (taban=0), funding düşülmüş")
print("=" * 110)
print(f"  {'varyant':22s} {'2023':>8s} {'2024':>8s} {'2025':>8s} {'2026':>8s}   (TRAIN|TEST)")
for (mode, prm) in [("dontr", 10), ("dontr", 15), ("dontr", 20), ("dontr", 30),
                    ("chand", 4.0), ("chand", 5.0), ("hchand", 4.0), ("hchand", 5.0),
                    ("hdontr", 15), ("hdontr", 20), ("hdontr", 30)]:
    st = T.stats(T.portfolio(P, {"donchian": (mode, prm)}), funding=True)
    d = {y: st["by_year"].get(y, 0) - basef["by_year"].get(y, 0) for y in (2023, 2024, 2025, 2026)}
    print(f"  {mode+' '+str(prm):22s} {d[2023]:+8.0f} {d[2024]:+8.0f} {d[2025]:+8.0f} {d[2026]:+8.0f}   "
          f"({d[2023]+d[2024]:+.0f}|{d[2025]+d[2026]:+.0f})")
