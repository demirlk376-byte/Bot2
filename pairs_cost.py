"""
pairs_cost.py — PAIRS BULGUSUNUN ÖLÜM TESTİ: gerçek işlem maliyeti altında hayatta kalıyor mu?

BULUNAN BOŞLUK (bu oturuma kadar hiç sorulmadı):
`pairs_verify.py:105` bir tur işlem için `4 * FEE` = **toplam 4 baz puan** masraf yazıyor.
Ama bir ÇİFT işlemi DÖRT AYRI DOLUM demektir: A-bacağı giriş, B-bacağı giriş, A çıkış, B çıkış.
Ve ankorda ÖLÇÜLEN gerçek donchian giriş kayması **tek dolumda +13.4 bp** (ledger:1225-1230).
MEXC taker ücreti buna ek ~2 bp.

Yani gerçekçi dolum başına maliyet ≈ 13 bp, dört dolum ≈ **52 bp** — backtest'in yazdığı
4 bp'nin **13 KATI**. Pairs işlem başına ortalama getirisi $532/260 = $2.05 (nominal $190
üzerinden %1.08). 48 bp'lik eksik masraf işlem başına $0.91 demek → 260 işlemde **$237**.
Bu, +$532'nin neredeyse yarısı.

BU TEST NEDEN ŞİMDİ: kullanıcı "pairs'e gerek var mı, emin ol, ona göre çalışmalara
başlayacağız" dedi. Haftalarca sürecek bir kod işine girmeden önce bulgunun gerçek
sürtünme altında ayakta kalıp kalmadığını bilmek ZORUNDAYIZ. Bu, "biraz azalır mı" sorusu
değil — "bulgu tamamen kaybolur mu" sorusu.

YÖNTEM: dolum başına maliyeti 1 bp'den 30 bp'ye taradık ve HER seviyede
  · toplam kâr        · PF        · TRAIN/TEST ayrımı        · DÖRT YILIN HEPSİ pozitif mi
raporlanıyor. Ölüm noktası (kârın sıfırlandığı maliyet) ve 4/4-yıl kuralının kırıldığı
nokta AYRI AYRI bulunuyor — çünkü ledger'ın pairs'i kabul etme gerekçesi "her yıl pozitif"ti.

DOĞRULAMA: 1 bp'de (yani 4*FEE=4bp) sonuç pairs_verify ile BİREBİR çıkmalı ($+532).

Kullanım:  py pairs_cost.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import pairs_verify as P

BAL0 = P.BAL0
TRAIN_END = P.TRAIN_END


def run_pair_cost(px, a, b, z_in, z_out, z_stop, bp_per_fill):
    """P.run_pair ile AYNI sinyal mantığı; SADECE maliyet modeli değişiyor.

    Maliyet: dolum başına bp_per_fill baz puan × 4 dolum (A giriş, B giriş, A çıkış, B çıkış).
    Getiri iki bacağın ortalaması olduğu için maliyet de aynı ölçekte uygulanır:
    her bacak 2 dolum yapar → bacak başına 2×bp, ortalamada yine 2×bp... ama toplam nominal
    iki bacağa BÖLÜNDÜĞÜ için işlem başına efektif maliyet = 2 × bp_per_fill.
    (Ayrıntı: ret = (r_a + r_b)/2 olduğundan her bacağın 2×bp maliyeti ortalamada 2×bp kalır.)"""
    lg = np.log(px[[a, b]].dropna())
    sp = lg[a] - lg[b]
    mu = sp.rolling(P.ZWIN).mean(); sd = sp.rolling(P.ZWIN).std()
    z = ((sp - mu) / sd).values
    idx = sp.index; ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
    n = len(z)
    cost = 2.0 * bp_per_fill * 1e-4          # işlem başına efektif (yukarıdaki türetme)
    out = []
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
        r_a = d_ * (ra[ex] - ra[i]) / ra[i]
        r_b = -d_ * (rb[ex] - rb[i]) / rb[i]
        out.append({"ret": (r_a + r_b) / 2 - cost, "ts": idx[ex]})
        i = ex + 1
    return out


def agg(trs):
    if not trs: return None
    d = np.array([t["ret"] * BAL0 for t in trs])
    ts = [pd.Timestamp(t["ts"]) for t in trs]
    ya = np.array([t.year for t in ts])
    gp = d[d > 0].sum(); gl = -d[d < 0].sum()
    tr = np.array([t < TRAIN_END for t in ts])
    yrs = {int(y): float(d[ya == y].sum()) for y in sorted(set(ya.tolist()))}
    return dict(n=len(d), pf=gp / max(gl, 1e-9), tot=float(d.sum()),
                train=float(d[tr].sum()), test=float(d[~tr].sum()), yrs=yrs,
                allpos=all(v > 0 for v in yrs.values()))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = P.load_px(source)
    pairs, _ = P.pick_pairs(px, P.NPAIRS)
    Z = (2.0, 0.5, 3.5)

    print(f"\n{'=' * 100}")
    print("=== PAIRS ÖLÜM TESTİ — gerçek işlem maliyeti altında ayakta mı? ===")
    print(f"  çiftler: {pairs}")
    print(f"  Bir çift işlemi = 4 DOLUM (A giriş, B giriş, A çıkış, B çıkış)")
    print(f"  backtest'in varsaydığı: toplam 4 bp   ·   ÖLÇÜLEN donchian kayması: dolum başına 13.4 bp")

    rows = []
    for bp in (1, 2, 3, 5, 7, 10, 13.4, 15, 20, 25, 30):
        trs = []
        for a, b in pairs:
            trs += run_pair_cost(px, a, b, *Z, bp_per_fill=bp)
        r = agg(trs)
        rows.append((bp, r))

    # DOĞRULAMA: 1bp ≈ pairs_verify'ın 4*FEE'si
    base = rows[0][1]
    print(f"\n  DOĞRULAMA (1 bp/dolum ≈ backtest'in 4bp toplamı): ${base['tot']:+.0f} "
          f"— ledger +$532 diyor → {'✓ uyumlu' if 450 <= base['tot'] <= 620 else '✗ SAPMA'}")
    if not (450 <= base["tot"] <= 620):
        return

    print(f"\n  {'bp/dolum':>9s} {'toplam$':>9s} {'PF':>6s} {'TRAIN$':>8s} {'TEST$':>8s} "
          f"{'2023':>7s} {'2024':>7s} {'2025':>7s} {'2026':>7s}  {'4/4 yıl+':>9s}")
    print("  " + "-" * 96)
    olum_bp = None; yil_kirilma = None
    for bp, r in rows:
        y = r["yrs"]
        mark = ""
        if abs(bp - 13.4) < 1e-9: mark = "  ← ÖLÇÜLEN"
        print(f"  {bp:>9.1f} {r['tot']:>+9.0f} {r['pf']:>6.2f} {r['train']:>+8.0f} "
              f"{r['test']:>+8.0f} " +
              " ".join(f"{y.get(k, 0.0):>+7.0f}" for k in (2023, 2024, 2025, 2026)) +
              f"  {'✓' if r['allpos'] else '✗':>9s}" + mark)
        if olum_bp is None and r["tot"] <= 0: olum_bp = bp
        if yil_kirilma is None and not r["allpos"]: yil_kirilma = bp

    print(f"\n  --- HÜKÜM ---")
    print(f"  Kâr sıfırlanma noktası     : {olum_bp if olum_bp else '>30'} bp/dolum")
    print(f"  4/4-yıl kuralının kırılması: {yil_kirilma if yil_kirilma else '>30'} bp/dolum")
    olcum = [r for bp, r in rows if abs(bp - 13.4) < 1e-9][0]
    print(f"\n  ÖLÇÜLEN maliyette (13.4 bp/dolum):")
    print(f"    toplam ${olcum['tot']:+.0f}  (backtest'in iddia ettiği +$532'nin "
          f"%{olcum['tot']/base['tot']*100:.0f}'i)")
    print(f"    PF {olcum['pf']:.2f} · TRAIN ${olcum['train']:+.0f} · TEST ${olcum['test']:+.0f}")
    print(f"    4/4 yıl pozitif: {'EVET' if olcum['allpos'] else 'HAYIR'}")
    yil = olcum["tot"] / 3.3
    print(f"\n    → yıllık ${yil:+.0f} · k=0.70 ölçeğinde ${yil*0.7:+.0f}/yıl")
    print(f"    (botun ~$431/yıl'ının %{yil*0.7/431*100:.0f}'i)")
    print(f"\n  NOT: 13.4 bp donchian'ın 4h piyasa emirlerinden ÖLÇÜLDÜ. Pairs GÜNLÜK barlarda")
    print(f"  ve daha küçük coinlerde (ALGO/ATOM/VET) işlem yapıyor — kayma DAHA YÜKSEK olabilir.")
    print(f"  Bu yüzden 20-25 bp satırları da ciddiye alınmalı.")


if __name__ == "__main__":
    main()
