"""
pairs_mae.py — PAIRS POZİSYONLARI GÜNLER BOYU STOPSUZ DURUYOR. NE KADAR KÖTÜ OLABİLİR?

BACKTEST'TE GÖRÜNMEYEN BOŞLUK: pairs_verify çıkışı GÜNLÜK KAPANIŞTA kontrol eder
(|z|<0.5 → hedef, |z|>3.5 → stop, 20 gün → süre). Yani iki günlük kapanış ARASINDA
pozisyonda hiçbir koruma YOKTUR. Donchian kolunda her pozisyonun borsada duran bir
SL emri var; pairs'te yok — "stop" bir spread koşulu ve yalnız günde bir bakılıyor.

Kriptoda bir bacak saatler içinde %20 hareket edebilir. Backtest bunu GÖRMEZ çünkü
yalnız kapanıştan kapanışa bakar. Canlıda ise gerçek para o hareketin içinden geçer.

BU YÜZDEN ÖLÇÜLEN: MAE (maximum adverse excursion) — her çift işleminin ömrü boyunca
gördüğü EN KÖTÜ ara-dönem zararı. Ve o zararın ne kadarının kapanışta "geri geldiği".

ÜÇ SORU:
 1. Tipik ve en kötü MAE nedir? (nominal $190 üzerinden dolar)
 2. MAE'nin ne kadarı geri geliyor — yani stopsuz durmak GERÇEKTEN kazandırıyor mu,
    yoksa sadece şanslı mıydık?
 3. Sert bir bacak-stopu koysaydık (backtest'te YOKTU) kâr ne olurdu? Bu, "canlıda
    stop koymak zorundayız" ile "koyarsak edge ölür" arasındaki farkı gösterir.

VERİ: günlük kapanış yerine SAATLİK barlar kullanılıyor — ara-dönem hareketi ancak
daha ince çözünürlükle görülür. Giriş/çıkış günleri pairs_verify ile AYNI mantıkla
belirlenir; yalnızca ARADA ne olduğuna saatlik bakılır.

Kullanım:  py pairs_mae.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import pairs_verify as P

BP = 13.4          # ölçülen dolum başına sürtünme
BAL0 = P.BAL0


def hourly(coins, source):
    out = {}
    for c in coins:
        try:
            d = fast_bt.resample(fast_bt.load(c, source=source), "1h")
            out[c] = d["close"]
        except SystemExit:
            pass
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = P.load_px(source)                      # günlük — sinyal bunun üstünde
    pairs, _ = P.pick_pairs(px, P.NPAIRS)
    coins = sorted({c for p in pairs for c in p})
    hr = hourly(coins, source)                  # saatlik — ara-dönem bunun üstünde

    print(f"\n{'=' * 96}")
    print("=== PAIRS ARA-DÖNEM RİSKİ: pozisyonlar günler boyu STOPSUZ ===")
    print(f"  sinyal günlük kapanışta · ara-dönem saatlik barlarla ölçülüyor")
    print(f"  çiftler: {pairs}")

    rows = []
    for a, b in pairs:
        if a not in hr or b not in hr:
            continue
        lg = np.log(px[[a, b]].dropna())
        sp = lg[a] - lg[b]
        mu = sp.rolling(P.ZWIN).mean(); sd = sp.rolling(P.ZWIN).std()
        z = ((sp - mu) / sd).values
        idx = sp.index
        ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
        n = len(z)
        i = P.ZWIN + 1
        while i < n - 1:
            if not np.isfinite(z[i]) or abs(z[i]) < 2.0:
                i += 1; continue
            d_ = -1 if z[i] > 0 else +1
            ex = None
            for j in range(i + 1, min(i + 1 + P.MAXBARS, n)):
                if not np.isfinite(z[j]): continue
                if abs(z[j]) < 0.5 or abs(z[j]) > 3.5: ex = j; break
            if ex is None: ex = min(i + P.MAXBARS, n - 1)

            # ── ARA-DÖNEM: giriş ve çıkış günleri arasındaki SAATLİK yol ──
            t0, t1 = idx[i], idx[ex]
            ha = hr[a].loc[(hr[a].index > t0) & (hr[a].index <= t1)]
            hb = hr[b].loc[(hr[b].index > t0) & (hr[b].index <= t1)]
            if len(ha) < 2 or len(hb) < 2:
                i = ex + 1; continue
            j2 = ha.index.intersection(hb.index)
            if len(j2) < 2:
                i = ex + 1; continue
            pa0, pb0 = ra[i], rb[i]
            # her saatte çiftin toplam getirisi (iki bacak ortalaması, ücret hariç)
            yol = (d_ * (ha.reindex(j2).values - pa0) / pa0
                   - d_ * (hb.reindex(j2).values - pb0) / pb0) / 2.0
            mae = float(yol.min())              # en kötü ara-dönem
            son = float(yol[-1])                # kapanışta gerçekleşen
            rows.append(dict(cift=f"{a}/{b}", ts=t1, mae=mae, son=son,
                             sure=len(j2)))
            i = ex + 1

    if not rows:
        print("  ölçülemedi (saatlik veri eksik)"); return
    df = pd.DataFrame(rows)
    df["mae$"] = df.mae * BAL0
    df["son$"] = df.son * BAL0

    print(f"\n[1] MAE — ömür boyu görülen EN KÖTÜ ara-dönem zararı ({len(df)} işlem)")
    for q in (50, 75, 90, 95, 99):
        print(f"    %{q:>2d} yüzdelik: {np.percentile(df['mae$'], 100-q):>+8.2f} $")
    print(f"    EN KÖTÜ    : {df['mae$'].min():>+8.2f} $   "
          f"(nominal ${BAL0:.0f} üzerinden %{df['mae'].min()*100:.1f})")
    print(f"    ortalama   : {df['mae$'].mean():>+8.2f} $")

    print(f"\n[2] GERİ GELME — MAE'nin ne kadarı kapanışta telafi ediliyor?")
    kotu = df[df["mae$"] < -5]
    if len(kotu):
        toparlanan = (kotu["son$"] - kotu["mae$"])
        print(f"    MAE < -$5 olan {len(kotu)} işlemde:")
        print(f"      ortalama MAE {kotu['mae$'].mean():+.2f}$ → kapanış {kotu['son$'].mean():+.2f}$")
        print(f"      ortalama toparlanma {toparlanan.mean():+.2f}$")
        print(f"      bunların %{(kotu['son$']>0).mean()*100:.0f}'i ARTIDA kapanmış")
    print(f"    → Bu, 'stopsuz beklemek' stratejisinin ÇALIŞTIĞI anlamına gelir;")
    print(f"      ama aynı zamanda her işlemde bu dalgalanmaya KATLANMAK gerektiğini de.")

    print(f"\n[3] SERT BACAK-STOPU KOYSAYDIK (backtest'te YOKTU) kâr ne olurdu?")
    print(f"    {'stop':>10s} {'tetiklenen':>11s} {'toplam$':>9s} {'değişim':>9s}")
    taban = float((df["son$"]).sum()) - len(df) * 2 * BP * 1e-4 * BAL0
    print(f"    {'stop YOK':>10s} {'—':>11s} {taban:>+9.0f} {'—':>9s}")
    for s_pct in (0.03, 0.05, 0.08, 0.12, 0.20):
        pnl = np.where(df["mae"] <= -s_pct, -s_pct, df["son"]) * BAL0
        tot = float(pnl.sum()) - len(df) * 2 * BP * 1e-4 * BAL0
        tet = int((df["mae"] <= -s_pct).sum())
        print(f"    {s_pct*100:>9.0f}% {tet:>11d} {tot:>+9.0f} {tot-taban:>+9.0f}")
    print(f"\n    OKUMA: sert stop kârı DÜŞÜRÜYORSA, pairs'in edge'i tam da o")
    print(f"    dalgalanmaya katlanmaktan geliyor demektir — ve canlıda koruma")
    print(f"    koymak stratejiyi DEĞİŞTİRİR, backtest artık geçerli olmaz.")


if __name__ == "__main__":
    main()
