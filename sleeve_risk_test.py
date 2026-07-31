"""
sleeve_risk_test.py — Bir sleeve'e DAHA FAZLA RİSK vermek mantıklı mı?

TETİKLEYEN SORU (kullanıcı): "BB canlıda iyi gidiyor, riskini artıralım mı?"
Canlı gerekçe GEÇERSİZ: n=10, bootstrap'a göre bu örneklemde hiçbir yön iddiası yapılamaz,
üstelik 'üç koldan iyi gideni seç' sonradan-seçimdir ve aylık PnL ortalamaya döner (-0.345).
Ama BACKTEST gerekçesi meşru olabilir: 1579 işlemde bir kol katkısına göre az pay alıyorsa,
bu performans kovalamak değil PORTFÖY İNŞASIdır. BB'nin kitapla korelasyonu -0.368.

KRİTİK TUZAK — KALDIRAÇ vs TAHSİS:
Bir sleeve'in riskini artırmak TOPLAM dağıtılan riski de artırır. O zaman kazanç "daha iyi
tahsis"ten değil sadece "daha çok kaldıraç"tan gelebilir. Vol-hedefleme testinde tam bu oldu:
12 "kazanan" varyantın hepsi gizli kaldıraçtı. Bu yüzden İKİ ölçüm yapılır:
  A) HAM     : sadece hedef sleeve'in riski çarpılır (toplam risk ARTAR — kaldıraç karışık)
  B) BÜTÇE-NÖTR: hedef artırılır, DİĞERLERİ düşürülür → ortalama dağıtılan risk TABANLA AYNI.
     Kazanç B'de de duruyorsa TAHSİS gerçekten daha iyidir. Durmuyorsa kazanç kaldıraçtı.

KABUL BARI: toplam ARTACAK **ve** HER YIL artacak **ve** B (bütçe-nötr) formunda da geçecek.

Kullanım:  py sleeve_risk_test.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from sleeve_audit import tagged_trades, seat_select

SLEEVES = ("donchian", "squeeze", "bb")


def evaluate(taken, mults):
    """mults: {sleeve: risk çarpanı}. eff = min(RISKF*mult, CAP*sl_pct) — tavan HER ZAMAN geçerli."""
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    sv = np.array([t[3] for t in taken])
    ya = np.array([pd.Timestamp(t[0]).year for t in taken])
    risk = np.array([DB.RISKF * mults.get(s, 1.0) for s in sv])
    eff = np.minimum(risk, DB.CAP * slp)
    pnl = r * eff * DB.BAL0
    eq = np.concatenate([[DB.BAL0], DB.BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    mon = pd.Series(pnl, index=[pd.Timestamp(t[0]).tz_localize(None).to_period("M")
                                for t in taken]).groupby(level=0).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(tot=float(pnl.sum()), pf=gp / max(gl, 1e-9),
                dd=float(((peak - eq) / peak).max() * 100),
                worst=float(mon.min()), avg_risk=float(eff.mean()),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def budget_neutral(taken, target, mult, base_avg, tol=1e-4):
    """Hedef/diğer ORANINI koru, ama TÜM vektörü ortak bir g ile ölçekleyerek ortalama
    dağıtılan riski tabana eşitle.

    ÖNCEKİ (HATALI) SÜRÜM: sadece 'diğerleri'ni kısıyordu ve alt sınırı 0.05'ti. Donchian
    işlemlerin %63'ü olduğundan 2x/3x'te diğerlerini sıfıra yaklaştırmak bile yetmiyor,
    arama hedefe ULAŞAMADAN duruyor ve fonksiyon yine de bir sonuç döndürüyordu → ort risk
    %2.73/%3.47 (taban %2.13) olduğu halde "bütçe-nötr" etiketiyle raporlanıyordu. Yani test,
    yakalamak için yazıldığı KALDIRAÇ tuzağına kendisi düşüyordu (2 sahte '★ KABUL').

    Bu sürüm global bir g arar: g istediği kadar küçülebildiği için kısıt HER ZAMAN sağlanır.
    Sağlanamazsa None döner — sessizce yanlış etiket basmaz."""
    lo, hi = 1e-3, 1.0
    if evaluate(taken, {s: (mult if s == target else 1.0) for s in SLEEVES})["avg_risk"] < base_avg:
        hi = 50.0                                        # tahsis riski DÜŞÜRÜYORSA yukarı ara
    for _ in range(60):
        g = (lo + hi) / 2
        m = {s: g * (mult if s == target else 1.0) for s in SLEEVES}
        if evaluate(taken, m)["avg_risk"] > base_avg: hi = g
        else: lo = g
    g = (lo + hi) / 2
    m = {s: g * (mult if s == target else 1.0) for s in SLEEVES}
    got = evaluate(taken, m)["avg_risk"]
    return m if abs(got - base_avg) / base_avg < tol else None


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    taken = seat_select(tagged_trades(source))
    base = evaluate(taken, {})
    ys = " ".join(f"{y}:${v:+.0f}" for y, v in base["yrs"].items())
    print(f"\n{'='*108}\n=== SLEEVE BAZINDA RİSK TAHSİSİ — 'iyi giden kola daha çok verelim mi?' ===")
    print(f"  TABAN: ${base['tot']:+.0f} | PF {base['pf']:.2f} | maxDD %{base['dd']:.1f} | "
          f"en kötü ay ${base['worst']:+.0f} | ort risk %{base['avg_risk']*100:.2f}")
    print(f"         {ys}")

    for target in SLEEVES:
        print(f"\n  {'─'*104}\n  ### {target.upper()} riski çarpılırsa")
        print(f"  {'form':<12s} {'çarpan':>7s} {'toplam$':>9s} {'Δ':>7s} {'maxDD%':>7s} "
              f"{'kötü ay$':>9s} {'ort risk':>9s}  yıl-yıl Δ                          karar")
        for mult in (1.25, 1.5, 2.0, 3.0):
            # A) HAM — toplam risk artar
            s = evaluate(taken, {target: mult})
            dy = {y: s["yrs"].get(y, 0.0) - base["yrs"].get(y, 0.0) for y in base["yrs"]}
            ev = all(v > 0 for v in dy.values())
            y = " ".join(f"{k}:{v:+.0f}" for k, v in dy.items())
            lev = s["avg_risk"] / base["avg_risk"]
            print(f"  {'A) ham':<12s} {mult:>7.2f} {s['tot']:>+9.0f} {s['tot']-base['tot']:>+7.0f} "
                  f"{s['dd']:>7.1f} {s['worst']:>+9.0f} {s['avg_risk']*100:>8.2f}%  {y}  "
                  f"{'(risk x' + format(lev, '.3f') + ')'}")
            # B) BÜTÇE-NÖTR — toplam risk sabit
            m = budget_neutral(taken, target, mult, base["avg_risk"])
            if m is None:
                print(f"  {'B) bütçe-nötr':<12s} {mult:>7.2f}   —  bütçe kısıtı SAĞLANAMADI, "
                      f"satır GEÇERSİZ (sessizce kaldıraç raporlamamak için atlandı)")
                continue
            s2 = evaluate(taken, m)
            dy2 = {y_: s2["yrs"].get(y_, 0.0) - base["yrs"].get(y_, 0.0) for y_ in base["yrs"]}
            ev2 = all(v > 0 for v in dy2.values())
            y2 = " ".join(f"{k}:{v:+.0f}" for k, v in dy2.items())
            verdict = ("★ KABUL" if (s2["tot"] > base["tot"] and ev2)
                       else "toplam+ ama yıl bozuk" if s2["tot"] > base["tot"] else "RET")
            print(f"  {'B) bütçe-nötr':<12s} {mult:>7.2f} {s2['tot']:>+9.0f} "
                  f"{s2['tot']-base['tot']:>+7.0f} {s2['dd']:>7.1f} {s2['worst']:>+9.0f} "
                  f"{s2['avg_risk']*100:>8.2f}%  {y2}  {verdict}")

    print(f"\n  OKUMA: A) formunda kazanç görülürse önce 'risk x..' sütununa bak — 1.00'ın")
    print(f"  üstündeyse kazanç KALDIRAÇTAN geliyor olabilir. B) formunda toplam risk TABANLA")
    print(f"  AYNI; kazanç orada da duruyorsa tahsis gerçekten daha iyi demektir.")
    print(f"  Vol-hedefleme testinde 12 'kazanan' varyantın hepsi A'da iyi, B'de yok olmuştu.")


if __name__ == "__main__":
    main()
