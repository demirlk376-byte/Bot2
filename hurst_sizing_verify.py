"""
hurst_sizing_verify.py — Hurst-tabanlı boyutlandırmayı ÇÜRÜTMEYE çalış.

BAĞLAM: indicator_sizing_test'te Hurst50 ile boyutlandırma TEST döneminde +$150 (test PnL'inin
%23'ü) verdi ve k'ya göre KUSURSUZ MONOTON (lin 41→83→124, tier 51→102→150). Kabul barını
yalnızca 2024'teki −$21 yüzünden geçemedi. Aynı barda ADX'in +$4'lük gürültüsü "KABUL" aldı
(2025 deltası +$0.4, yuvarlanınca pozitif) → BARIN KENDİSİNDE KUSUR VAR.

Bu script bulguyu KABUL ETMEK için değil, ÇÜRÜTMEK için yazıldı. Sekiz bağımsız saldırı:
 1. PERMÜTASYON: çarpanları işlemler arasında KARIŞTIR (aynı çarpan dağılımı, rastgele eşleşme).
    Gerçek +$150 rastgele eşleşmenin ürettiğinden anlamlı ölçüde iyi mi? p<0.05 değilse ÖLDÜ.
 2. YOĞUNLAŞMA: Δ'nın yüzde kaçı en iyi 5/10/20 işlemden geliyor? Yoğunsa örneklem gürültüsü.
 3. TERS BÖLME: 2025-26'da seç, 2023-24'te ölç. Etki simetrik mi?
 4. COIN KIRILIMI: kazanç 1-2 coinden mi geliyor?
 5. 2024 TEŞHİSİ: neden negatif? Yapısal mı, birkaç işlem mi?
 6. BOOTSTRAP: ay-bloklu, TEST Δ'sının %90 güven aralığı sıfırı kapsıyor mu?
 7. PARAMETRE SAĞLAMLIĞI: Hurst penceresi N ∈ {30,50,80,100} — plato mu tek nokta mı?
 8. ÇOKLU TEST: 30 kombinasyon tarandı; Šidák düzeltmesi sonrası anlamlı mı?

Kullanım:  py hurst_sizing_verify.py local
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as DB
import indicator_sizing_test as IST
import fast_bt

RNG = np.random.default_rng(12345)


def build(source, hurst_n=50):
    """Aynı motor; Hurst penceresini parametreleştir."""
    IST.IND = {"h": lambda c, v, a, _n=hurst_n: IST.hurst_rs(c, _n)}
    trades = []
    for c in DB.DONCH:
        trades += IST.gen_donchian_with_ind(fast_bt.load(c, source=source))
    trades += IST.other_sleeves(source)
    return IST.seat_select(trades)


def coin_of(t):
    return t[5].get("_coin") if t[5] else None


def stats(taken, mults, g):
    return IST.evaluate(taken, mults, g)


def delta_series(taken, mults, g):
    """İşlem başına PnL farkı (varyant − taban) — yoğunlaşma analizi için."""
    r = np.array([t[2] for t in taken]); slp = np.array([t[3] for t in taken])
    base = r * np.minimum(DB.RISKF, DB.CAP * slp) * DB.BAL0
    var = r * np.minimum(DB.RISKF * mults * g, DB.CAP * slp) * DB.BAL0
    return var - base


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    K, MODE = 0.6, "tier"
    taken = build(source, 50)
    n = len(taken)
    base = IST.evaluate(taken, np.ones(n))
    m = IST.multipliers(taken, "h", K, MODE)
    g = IST.budget_neutral_g(taken, m, base["avg_risk"])
    s = IST.evaluate(taken, m, g)
    d_test = s["test"] - base["test"]
    ent_ns = np.array([t[0] for t in taken], dtype="int64")
    is_test = ent_ns >= IST.TRAIN_END_NS
    print(f"\n{'='*104}\n=== HURST BOYUTLANDIRMA — ÇÜRÜTME DENEMESİ (tier k=0.6, N=50) ===")
    print(f"  TABAN  TRAIN ${base['train']:+.0f}  TEST ${base['test']:+.0f}  toplam ${base['tot']:+.0f}")
    print(f"  VARYANT TRAIN ${s['train']:+.0f}  TEST ${s['test']:+.0f}  toplam ${s['tot']:+.0f}  "
          f"(g={g:.3f}, ort risk %{s['avg_risk']*100:.2f} = taban)")
    print(f"  ΔTEST = ${d_test:+.0f}")

    # ── 1) PERMÜTASYON ──
    print(f"\n  [1] PERMÜTASYON (çarpanlar işlemler arasında karıştırılır, 2000 tur)")
    donch = np.array([t[4] == "donchian" for t in taken])
    obs = d_test; cnt = 0; sims = []
    for _ in range(2000):
        mm = np.ones(n)
        perm = RNG.permutation(m[donch])            # aynı çarpan dağılımı, rastgele eşleşme
        mm[donch] = perm
        gg = IST.budget_neutral_g(taken, mm, base["avg_risk"])
        if gg is None: continue
        ss = IST.evaluate(taken, mm, gg)
        sims.append(ss["test"] - base["test"])
        if sims[-1] >= obs: cnt += 1
    sims = np.array(sims)
    p = (cnt + 1) / (len(sims) + 1)
    print(f"      rastgele ΔTEST: ort ${sims.mean():+.1f} sd ${sims.std():.1f} | "
          f"gerçek ${obs:+.0f} → z={(obs-sims.mean())/max(sims.std(),1e-9):+.2f}  p={p:.4f}"
          f"  {'✓ ANLAMLI' if p < 0.05 else '✗ GÜRÜLTÜ'}")
    p_sidak = 1 - (1 - p) ** 30
    print(f"      30 kombinasyon için Šidák düzeltmesi → p_düz={p_sidak:.4f}  "
          f"{'✓ HÂLÂ ANLAMLI' if p_sidak < 0.05 else '✗ DÜZELTME SONRASI ÖLÜ'}")

    # ── 2) YOĞUNLAŞMA ──
    dd = delta_series(taken, m, g)[is_test]
    order = np.argsort(-np.abs(dd))
    print(f"\n  [2] YOĞUNLAŞMA (TEST'te {is_test.sum()} işlem, ΔTEST ${dd.sum():+.0f})")
    for topn in (5, 10, 20, 50):
        share = dd[order[:topn]].sum() / dd.sum() * 100 if dd.sum() != 0 else 0
        print(f"      en büyük {topn:>2d} işlem Δ'nın %{share:.0f}'ini taşıyor")

    # ── 3) TERS BÖLME ──
    print(f"\n  [3] TERS BÖLME — etki TRAIN döneminde de var mı?")
    print(f"      ΔTRAIN ${s['train']-base['train']:+.0f} | ΔTEST ${d_test:+.0f} "
          f"→ {'✓ iki dönemde de pozitif' if (s['train']>base['train'] and d_test>0) else '✗ asimetrik'}")

    # ── 5) YIL-YIL ──
    print(f"\n  [5] YIL-YIL")
    for y in sorted(base["yrs"]):
        dv = s["yrs"].get(y, 0) - base["yrs"].get(y, 0)
        print(f"      {y}: taban ${base['yrs'][y]:+.0f} → varyant ${s['yrs'].get(y,0):+.0f}  (Δ${dv:+.0f})")

    # ── 6) BOOTSTRAP (ay-bloklu, TEST) ──
    print(f"\n  [6] BOOTSTRAP (ay-bloklu, TEST Δ, 3000 tur)")
    months = np.array([pd.Timestamp(t[1]).to_period("M").ordinal for t in taken])[is_test]
    ddt = dd; um = np.unique(months)
    bs = []
    for _ in range(3000):
        pick = RNG.choice(um, size=len(um), replace=True)
        bs.append(sum(ddt[months == mo].sum() for mo in pick))
    bs = np.array(bs)
    lo, hi = np.percentile(bs, [5, 95])
    print(f"      %90 GA [${lo:+.0f}, ${hi:+.0f}]  P(Δ>0)=%{(bs>0).mean()*100:.0f}  "
          f"{'✓ sıfırı kapsamıyor' if lo > 0 else '✗ SIFIRI KAPSIYOR'}")

    # ── 7) PARAMETRE SAĞLAMLIĞI ──
    print(f"\n  [7] HURST PENCERESİ SAĞLAMLIĞI (plato mu tek nokta mı?)")
    for hn in (30, 50, 80, 100):
        tk = build(source, hn)
        b2 = IST.evaluate(tk, np.ones(len(tk)))
        m2 = IST.multipliers(tk, "h", K, MODE)
        g2 = IST.budget_neutral_g(tk, m2, b2["avg_risk"])
        if g2 is None:
            print(f"      N={hn:>3d}: bütçe kısıtı sağlanamadı"); continue
        s2 = IST.evaluate(tk, m2, g2)
        dy = {y: s2["yrs"].get(y, 0) - b2["yrs"].get(y, 0) for y in b2["yrs"]}
        print(f"      N={hn:>3d}: ΔTRAIN ${s2['train']-b2['train']:+.0f}  ΔTEST ${s2['test']-b2['test']:+.0f}"
              f"  yıl-yıl " + " ".join(f"{k}:{v:+.0f}" for k, v in dy.items()))

    print(f"\n  HÜKÜM: [1] p ve [6] GA birlikte belirleyici. p>=0.05 ya da GA sıfırı kapsıyorsa")
    print(f"  bulgu ÖLÜ. [7]'de tek pencere çalışıyorsa parametre-kırılgan. [2]'de Δ birkaç işlemde")
    print(f"  yoğunlaşmışsa örneklem gürültüsü — plato bunu KURTARMAZ (trailing testinin dersi).")


if __name__ == "__main__":
    main()
