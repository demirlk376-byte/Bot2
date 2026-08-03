"""
pw_coins.py — COIN EVRENİ: bugünkü koltuk bulgusunun YENİDEN AÇTIĞI eksen.

NEDEN YENİDEN AÇILIYOR (gerekçe, keyfi değil):
  Ledger 2026-07-22'de DOT/AVAX/VET'i şu sebeple REDDETTİ: "+hepsi(10): marjinal para,
  PF düşer, DD şişer (MP=8 DD%73)". Yani ret gerekçesi KOLTUK ÇEKİŞMESİ idi.
  Bugün (2026-08-03) pw_seat.py o mekanizmayı ölçtü: koltuklar zamanın yalnızca %3.25'inde
  tamamen dolu, tüm 2023-2026'da gerçek seçim anı 6 tane, geleceği bilen tahsis bile
  yalnızca +$26 kazandırıyor. **Ret gerekçesinin dayandığı mekanizma bizde yok.**
  Ayrıca o test İZOLE donchian alt-portföyünde (MP=8) yapılmıştı; ankorda squeeze+BB de
  aynı koltukları paylaşıyor ve gerçek eşzamanlılık çok daha düşük.

⚠️ ASIL TEHLİKE BURADA SEÇİM YANLILIĞI. 22 coinden en iyi görüneni seçmek, geçmişe
bakarak kazananı işaret etmektir. Bu yüzden ÜÇ AYRI TEST, en dürüstünden en zayıfına:

  T1 — SEÇİMSİZ ("hepsini ekle"): 10 kullanılmayan coin'in TAMAMI donchian'a eklenir.
       SIFIR seçim kararı → sıfır seçim yanlılığı. Bu geçerse sonuç TARTIŞMASIZDIR.
       Bu, elimizdeki en temiz tek testtir.

  T2 — TRAIN'DE SEÇ, TEST'TE ÖLÇ: aday sıralaması YALNIZCA 2023-2024 verisiyle yapılır
       (kural önceden sabit: her TRAIN yılı pozitif VE PF>1.10), sonra seçilen küme
       2025-2026'da ölçülür. Bu, "coin seçme prosedürünün" gerçek örneklem-dışı testidir
       ve bu depoda HİÇ yapılmadı. Ledger'daki seçim tüm tarihe bakarak (in-sample) yapıldı
       — kendi notu da bunu kabul ediyor: "(2) in-sample seçim (2023-26), gerçek OOS ileriye."

  T3 — DOZ-YANIT: K=0..10 coin ekleyerek eğri. Gerçek bir etki düzgün olmalı; tek bir K'da
       zıplayıp sönüyorsa gürültüdür.

ÖN-KAYITLI BAR (değiştirilmedi — bugün üç ekseni reddeden barın AYNISI):
  Δ$ > +28 (ankorun %2'si) · hiçbir yıl >%10 kötüleşmeyecek · maxDD +2 puandan fazla
  artmayacak · en kötü ay kötüleşmeyecek.

DÜRÜSTLÜK NOTU: coin eklemek "yeni bir fikir" değil, mevcut edge'i daha geniş uygulamaktır.
Bu bir zayıflık değil AVANTAJDIR — yeni parametre uydurmuyoruz, aynı kuralı daha çok yere
uyguluyoruz. Ve deploy'u env-var'dır (DONCHIAN_SYMBOLS), kod değişikliği YOK, geri alınabilir.

Kullanım:  py pw_coins.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
# Canlıda donchian kolunda OLMAYAN coinler. squeeze/BB coinleri de aday: donchian ve
# squeeze farklı sinyaller üretir, aynı coin ikisinde birden olabilir (canlıda ICP zaten öyle).
CAND = [c for c in ALL22 if c not in A.DONCH]


def portfolio(donch_syms, raw):
    """Ankoru verilen donchian coin listesiyle koştur. Diğer HER ŞEY aynı.
    SLEEVE SIRASI KRİTİK: seat_select'in sıralaması kararlı → ankorla birebir aynı sıra
    (DONCH → SQZ → BB), yoksa eş-zamanlı sinyallerde koltuk sahibi değişir."""
    trades = []
    for c in donch_syms: trades += A.gen("donchian", raw[c])
    for c in A.SQZ: trades += A.gen("squeeze", raw[c])
    for c in A.BB_COINS: trades += A.gen_bb(raw[c])
    taken = A.seat_select(trades)
    r = np.array([R for _, R, _ in taken])
    slp = np.array([sp for _, _, sp in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    eff = np.minimum(A.RISKF, A.CAP * slp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), pf=float(gp / gl) if gl > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()}, pnl=pnl, ex=ex)


def verdict(v, b, years):
    """Ön-kayıtlı bar. Bugün üç ekseni reddeden barın AYNISI."""
    why = []
    if v["tot"] - b["tot"] <= 28: why.append(f"kâr yetersiz ({v['tot']-b['tot']:+.0f}$)")
    bad = [y for y in years
           if abs(b["yr"].get(y, 0)) > 1e-9
           and (v["yr"].get(y, 0) - b["yr"].get(y, 0)) / abs(b["yr"].get(y, 0)) < -0.10]
    if bad: why.append("yıl kötüleşti " + ",".join(
        f"{y}:{(v['yr'].get(y,0)-b['yr'].get(y,0))/abs(b['yr'].get(y,0))*100:.0f}%" for y in bad))
    if v["dd"] > b["dd"] + 2: why.append(f"maxDD {b['dd']:.1f}→{v['dd']:.1f}")
    if v["worst"] < b["worst"] - 0.05: why.append(f"en kötü ay {b['worst']:.1f}→{v['worst']:.1f}")
    return why


def train_score(coin, raw):
    """Adayı YALNIZCA TRAIN (2023-2024) verisiyle puanla. Kural ÖNCEDEN sabit:
    her TRAIN yılı pozitif VE PF > 1.10. TEST verisine BAKILMAZ."""
    tr = A.gen("donchian", raw[coin])
    if not tr: return None
    ex = [pd.Timestamp(t[1]) for t in tr]
    r = np.array([t[2] for t in tr])
    slp = np.array([t[3] for t in tr])
    msk = np.array([x < TRAIN_END for x in ex])
    if msk.sum() < 15: return None
    r = r[msk]; slp = slp[msk]; ex = [x for x, k in zip(ex, msk) if k]
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * A.BAL0
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else float("inf")
    return dict(coin=coin, n=int(msk.sum()), pf=float(pf), tot=float(pnl.sum()),
                allpos=bool((yr > 0).all()) and len(yr) >= 2,
                yrs={int(k): float(v) for k, v in yr.items()})


def show(tag, v, b, years, extra=""):
    d = v["tot"] - b["tot"]
    print(f"  {tag:<26s} {v['n']:>5d} {v['tot']:>+8.0f} {d:>+7.0f} {v['pf']:>5.2f} "
          f"{v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>8.0f} | " +
          " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + extra)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in ALL22:
        try: raw[c] = fast_bt.load(c, source=source)
        except SystemExit: pass
    have = [c for c in CAND if c in raw]

    print(f"\n{'=' * 118}")
    print("=== COIN EVRENİ GENİŞLETME — koltuk bulgusunun yeniden açtığı eksen ===")
    print(f"  canlı donchian: {A.DONCH}")
    print(f"  aday havuzu ({len(have)}): {have}")

    base = portfolio(A.DONCH, raw)
    years = sorted(base["yr"])
    print(f"\n  DOĞRULAMA: taban {base['n']} işlem / ${base['tot']:+.2f}  "
          f"(ankor 1579 / $+1420.66 olmalı) → "
          f"{'✓ BİREBİR' if base['n'] == 1579 and abs(base['tot'] - 1420.66) < 0.01 else '✗ SAPMA — sonuçlar geçersiz'}")
    if base["n"] != 1579 or abs(base["tot"] - 1420.66) > 0.01:
        return

    hdr = (f"  {'küme':<26s} {'işlem':>5s} {'toplam$':>8s} {'Δ$':>7s} {'PF':>5s} {'maxDD%':>7s} "
           f"{'kötü ay%':>9s} {'poz-ay%':>8s} | " + " ".join(f"{y:>7d}" for y in years))

    # ── T1: SEÇİMSİZ ─────────────────────────────────────────────────────────
    print(f"\n{'=' * 118}\n=== T1 — SEÇİMSİZ: 10 adayın TAMAMI eklenir (sıfır seçim yanlılığı) ===")
    print("  Bu en temiz testtir: hiçbir coin seçilmedi, dolayısıyla geçmişe bakma imkânı YOK.")
    print(hdr)
    show("TABAN (canlı 7)", base, base, years, "  ← CANLI")
    allv = portfolio(A.DONCH + have, raw)
    show(f"+HEPSİ ({len(have)} coin)", allv, base, years)
    w = verdict(allv, base, years)
    print(f"\n  T1 HÜKÜM: {'★ GEÇTİ — seçim yanlılığı İMKÂNSIZ' if not w else '✗ ' + '; '.join(w)}")

    # ── T2: TRAIN'de seç, TEST'te ölç ────────────────────────────────────────
    print(f"\n{'=' * 118}\n=== T2 — TRAIN'DE SEÇ (2023-24), TEST'TE ÖLÇ (2025-26) ===")
    print("  Kural ÖNCEDEN sabit: her TRAIN yılı pozitif VE PF>1.10. TEST verisine BAKILMAZ.")
    sc = [s for s in (train_score(c, raw) for c in have) if s]
    sc.sort(key=lambda s: -s["pf"])
    print(f"\n  {'coin':>6s} {'TRAIN n':>8s} {'TRAIN PF':>9s} {'TRAIN $':>9s} {'her yıl+':>9s}  seçildi")
    picked = []
    for s in sc:
        ok = s["allpos"] and s["pf"] > 1.10
        if ok: picked.append(s["coin"])
        print(f"  {s['coin']:>6s} {s['n']:>8d} {s['pf']:>9.2f} {s['tot']:>+9.0f} "
              f"{str(s['allpos']):>9s}  {'✓ SEÇİLDİ' if ok else '—'}")
    print(f"\n  TRAIN'in seçtiği ({len(picked)}): {picked if picked else 'HİÇBİRİ'}")
    if picked:
        selv = portfolio(A.DONCH + picked, raw)
        print(f"\n{hdr}")
        show("TABAN (canlı 7)", base, base, years, "  ← CANLI")
        show(f"+TRAIN seçimi ({len(picked)})", selv, base, years)
        # asıl soru: TEST döneminde ne oldu?
        for lbl, ys in (("TRAIN 2023-24", [y for y in years if y < 2025]),
                        ("TEST  2025-26", [y for y in years if y >= 2025])):
            db = sum(base["yr"].get(y, 0) for y in ys)
            dv = sum(selv["yr"].get(y, 0) for y in ys)
            print(f"      {lbl}: taban ${db:+.0f} → seçim ${dv:+.0f}  ({dv - db:+.0f}$)"
                  + ("   ← ASIL SORU: TRAIN'de seçilenler TEST'te de kazandı mı?" if "TEST" in lbl else ""))
        w2 = verdict(selv, base, years)
        print(f"\n  T2 HÜKÜM: {'★ GEÇTİ' if not w2 else '✗ ' + '; '.join(w2)}")

    # ── T3: DOZ-YANIT ────────────────────────────────────────────────────────
    print(f"\n{'=' * 118}\n=== T3 — DOZ-YANIT: TRAIN-PF sırasına göre K coin ekle ===")
    print("  Gerçek etki DÜZGÜN olmalı. Tek K'da zıplayıp sönüyorsa gürültüdür.")
    print(f"  (sıra TRAIN'e göre sabit, TEST'e bakılmadan: {[s['coin'] for s in sc]})")
    print(hdr)
    show("K=0 TABAN", base, base, years, "  ← CANLI")
    for K in range(1, len(sc) + 1):
        add = [s["coin"] for s in sc[:K]]
        v = portfolio(A.DONCH + add, raw)
        ok = not verdict(v, base, years)
        show(f"K={K} +{add[-1]}", v, base, years, "  ★" if ok else "")

    print(f"\n  OKUMA: T1 (seçimsiz) geçerse bu tartışmasız bir bulgudur — geçmişe bakarak")
    print(f"  coin seçme imkânı yoktur. T2, seçim PROSEDÜRÜNÜN örneklem-dışı testidir.")
    print(f"  T3 düzgün değilse (zıplama/sönme) T1/T2 geçse bile şüpheyle bakılmalıdır.")


if __name__ == "__main__":
    main()
