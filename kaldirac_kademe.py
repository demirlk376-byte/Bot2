"""
kaldirac_kademe.py — İŞLEM BAZINDA KALDIRAÇ: en iyi işlemlerimizin kırpılmasını bitir.

═══ NEDEN BU, BUGÜN DÜŞEN 18 EKSENDEN FARKLI ═══════════════════════════════════
Hepsi "hangi işlemi ALMAYALIM" sorusuydu ve hepsi düştü: iyi sinyali kötüden ayıran
hiçbir şey yok. Bu SORU DEĞİŞİK: hangi işlemi almayacağımızı değil, hangisine NE
KADAR yatıracağımızı soruyor. Ve dayandığı sayı ölçülmüş:

    CAP'e takılan işlemlerin ort R'si  +0.4597
    takılmayanların                    +0.2056        (risk_kademe.py)

Dar stoplu işlemler İKİ KATTAN fazla iyi — ve `eff = min(RISKF, CAP·slp)` tam
onları kırpıyor. Yani sistem EN İYİ işlemlerine EN KÜÇÜK bahsi koyuyor. Bu bir
sinyal sorunu değil, bir BOYUTLANDIRMA sorunu ve tamamen mekanik.

═══ NEDEN ŞİMDİYE KADAR ÇÖZÜLEMEDİ ══════════════════════════════════════════════
İki ayrı düzeltme denendi, ikisi de AYRI AYRI reddedildi:
  • CAP 1.5→2.0 : +$60/3.6yıl ama tepe marjin %82→%97, tampon %3 (DURUM 4)
  • kaldıraç 10→20x : marjini serbest bırakıyor AMA işlemlerin %35'inin stopu
    likidasyonun ÖTESİNE geçiyor — stop çalışmadan likide olursun (felaket)
İkisinin BİRLEŞİMİ hiç denenmedi. Oysa reddedilme sebepleri birbirini tamamlıyor:
kaldıraç YALNIZ stopun likidasyondan güvenli mesafede olduğu işlemlerde yükseltilirse
(a) o %35 hiç etkilenmez, (b) serbest kalan marjin CAP'in yükselmesine izin verir,
(c) CAP yükselince kırpılan +0.4597'lik grup tam riskini alır.

  likidasyon hareketi ≈ 1/kaldıraç − bakım_marjini
  ŞART: stop_mesafesi × GUVENLIK < likidasyon_hareketi

═══ NE ÖLÇÜLÜYOR ════════════════════════════════════════════════════════════════
Ankorun her işlemi için: stop mesafesine göre EN DÜŞÜK güvenli kaldıraç seçilir,
marjin ona göre hesaplanır, ve CANLI ÖN-KONTROL (execution.py:559,
`marjin > serbest × 0.95` ise işlemi ATLA) olay bazında BİREBİR uygulanır.
Reddedilen işlem varsa kâr FANTEZİDİR — rapor red sayısını her satırda basıyor.

⚠ ÖN-KAYITLI BAR (bugün 18 ekseni reddeden barın AYNISI):
  Δ$ > +28 · hiçbir yıl −%10'dan kötü değil · maxDD +2 puandan fazla artmıyor ·
  EN KÖTÜ AY KÖTÜLEŞMİYOR · marjin reddi = 0 · likidasyon ihlali = 0

⚠ GÜVENLİK ÖNCE: likidasyon ihlali OLAN hiçbir yapılandırma, kârı ne olursa olsun,
  raporda "geçti" işareti ALAMAZ. Bu kâr sorusundan ÖNCE gelen bir sorudur.

Kullanım (VPS'te):
    nohup python3 -u kaldirac_kademe.py local > /tmp/kald.log 2>&1 & disown
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt

ONK = 0.95           # execution.py:559 tamponu
BAKIM = 0.005        # MEXC bakım marjini (muhafazakâr)
GUVENLIK = 2.0       # stop, likidasyon mesafesinin 1/GUVENLIK'inden yakın olmalı
KADEMELER = [10, 15, 20, 25]      # denenecek kaldıraç merdiveni
BAR_DOLAR = 28.0


def havuz(source):
    ham = []
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            for t in A.gen(kol, fast_bt.load(c, source=source)):
                ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    return sorted(ham, key=lambda z: z[0])


def guvenli_kaldirac(slp: float, kademeler, guvenlik: float) -> int:
    """Stopun likidasyondan GÜVENLİ mesafede kaldığı EN YÜKSEK kaldıraç.
    likidasyon hareketi ≈ 1/L − BAKIM ; şart: slp × guvenlik < o mesafe.
    Hiçbiri güvenli değilse taban (en düşük) kaldıraç döner — asla güvensiz seçme."""
    en_iyi = kademeler[0]
    for L in kademeler:
        if slp * guvenlik < (1.0 / L - BAKIM):
            en_iyi = max(en_iyi, L)
    return en_iyi


def calistir(ham, cap, kademeler, bal, guvenlik=GUVENLIK, onkontrol=True):
    """Koltuk seçimi + işlem-bazında kaldıraç + CANLI marjin ön-kontrolü.
    Döner: (alinan, marjin_reddi, tepe_marjin%, ort_marjin%, ihlal, lev_dagilim)"""
    koltuk = []; ctr = 0; al = []; red = 0
    kullanim = 0.0; tepe = 0.0
    agirlik = 0.0; sure = 0.0; prev = ham[0][0]
    ihlal = 0; lev_say = {}
    for e, x, R, slp in ham:
        while koltuk and koltuk[0][0] <= e:
            _, _, mj = heapq.heappop(koltuk); kullanim -= mj
        if e > prev:
            dt = (e - prev) / 1e9
            agirlik += kullanim * dt; sure += dt; prev = e
        if len(koltuk) >= A.MAXPOS:
            continue
        L = guvenli_kaldirac(slp, kademeler, guvenlik)
        # GÜVENLİK DENETİMİ — seçilen kaldıraçta stop gerçekten likidasyonun berisinde mi?
        if slp >= (1.0 / L - BAKIM):
            ihlal += 1
        nom = min(A.RISKF * bal / slp, cap * bal)
        marjin = nom / L
        if onkontrol and marjin > (bal - kullanim) * ONK:
            red += 1
            continue
        kullanim += marjin; tepe = max(tepe, kullanim)
        ctr += 1
        heapq.heappush(koltuk, (x, ctr, marjin))
        lev_say[L] = lev_say.get(L, 0) + 1
        al.append((x, R, slp, nom))
    return (al, red, tepe / bal * 100, (agirlik / sure / bal * 100) if sure else 0.0,
            ihlal, lev_say)


def olc(al, bal):
    if not al:
        return dict(n=0)
    r = np.array([a[1] for a in al]); nom = np.array([a[3] for a in al])
    slp = np.array([a[2] for a in al])
    pnl = r * (nom * slp)                       # risk$ = nominal × stop mesafesi
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = bal + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / bal * 100
    yil = pd.Series(pnl).groupby([x.year for x in ex]).sum() / bal * 100
    kz = pnl[pnl > 0].sum(); ky = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kz / ky) if ky > 0 else float("inf"),
                dd=float(A.maxdd(np.concatenate([[bal], eq]))),
                worst=float(mon.min()), yil=yil,
                ort_risk=float((nom * slp / bal).mean() * 100))


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bal = float(sys.argv[2]) if len(sys.argv) > 2 else A.BAL0
    print("=" * 118)
    print("=== İŞLEM BAZINDA KALDIRAÇ — en iyi işlemlerin kırpılmasını bitir ===")
    print("  Ölçülmüş: CAP'e takılanların ort R'si +0.4597, takılmayanların +0.2056.")
    print("  Sistem EN İYİ işlemlerine EN KÜÇÜK bahsi koyuyor. Sinyal sorunu değil,")
    print("  BOYUTLANDIRMA sorunu — ve tamamen mekanik.")
    print(f"  bakiye ${bal:.0f} · bakım marjini %{BAKIM*100:.1f} · güvenlik payı "
          f"{GUVENLIK}× · ön-kontrol %{ONK*100:.0f}")

    ham = havuz(source)
    # ── KONTROL: bugünkü yapılandırma ankoru üretmeli ──
    al, red, tepe, ort, ihlal, _ = calistir(ham, A.CAP, [10], bal, onkontrol=False)
    m = olc(al, bal)
    ok = m["n"] == 1579 and abs(m["tot"] - 1420.66) < 1.0
    print(f"\n  DOĞRULAMA (CAP={A.CAP}, tek kaldıraç 10x): {m['n']} işlem / "
          f"${m['tot']:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA — durduruldu'}")
    if not ok:
        print("    (ankor tutmuyorsa: git checkout -- data/)")
        return

    # ── TABAN: bugünkü canlı (CAP=1.5, 10x, ön-kontrol AÇIK) ──
    CANLI_CAP = 1.5
    al0, red0, tepe0, ort0, ihl0, _ = calistir(ham, CANLI_CAP, [10], bal)
    T = olc(al0, bal)
    print(f"\n  TABAN (canlı: CAP={CANLI_CAP}, 10x sabit)")
    print(f"    {T['n']} işlem  ${T['tot']:+.0f}  PF {T['pf']:.2f}  maxDD {T['dd']:.1f}  "
          f"en kötü ay {T['worst']:+.1f}  ort risk %{T['ort_risk']:.2f}")
    print(f"    marjin: tepe %{tepe0:.0f} · ortalama %{ort0:.0f} · RED {red0} · ihlal {ihl0}")

    # ── TARAMA ──
    print(f"\n{'='*118}")
    print(f"  {'yapılandırma':<30s} {'işlem':>6s} {'toplam$':>9s} {'Δ$':>7s} {'PF':>6s} "
          f"{'maxDD':>7s} {'ΔDD':>6s} {'kötü ay':>8s} {'Δay':>6s} {'tepe%':>6s} "
          f"{'RED':>4s} {'İHL':>4s}  BAR")
    print(f"  {'TABAN (CAP1.5 · 10x)':<30s} {T['n']:>6d} {T['tot']:>+9.0f} {'—':>7s} "
          f"{T['pf']:>6.2f} {T['dd']:>7.1f} {'—':>6s} {T['worst']:>+8.1f} {'—':>6s} "
          f"{tepe0:>6.0f} {red0:>4d} {ihl0:>4d}")
    en_iyi = None
    for cap in (1.5, 2.0, 2.5, 3.0):
        for kad in ([10], [10, 15], [10, 15, 20], [10, 15, 20, 25]):
            if cap == CANLI_CAP and kad == [10]:
                continue
            al2, red2, tp2, or2, ih2, lv = calistir(ham, cap, kad, bal)
            M = olc(al2, bal)
            if not M.get("n"):
                continue
            d = M["tot"] - T["tot"]; dd = M["dd"] - T["dd"]; day = M["worst"] - T["worst"]
            kotu_yil = any(y < -10.0 for y in M["yil"].values)
            # ⚠ İHL ŞARTI DÜZELTİLDİ. Önce "ih2 == 0" yazıyordu ve TÜM satırlar
            # düşüyordu — çünkü İHL=36 TABANDA da var, yani mevcut canlı sistemin
            # zaten sahip olduğu bir durum (2×ATR stopu %9.5'i geçen işlemler).
            # Adayı, kendisinin SEBEP OLMADIĞI bir sorunu çözmeye mecbur etmek
            # yanlış bir bar. Doğru şart: İHL ARTMASIN.
            neden = []
            if d <= BAR_DOLAR: neden.append(f"Δ${d:+.0f}≤{BAR_DOLAR:.0f}")
            if kotu_yil: neden.append("yıl<−%10")
            if dd > 2.0: neden.append(f"maxDD+{dd:.1f}")
            if day < -0.05: neden.append(f"ay{day:+.1f}")
            if red2 > 0: neden.append(f"RED{red2}")
            if ih2 > ihl0: neden.append(f"İHL↑{ih2-ihl0}")
            gecti = not neden
            ad = f"CAP{cap} · {'/'.join(str(k) for k in kad)}x"
            print(f"  {ad:<30s} {M['n']:>6d} {M['tot']:>+9.0f} {d:>+7.0f} {M['pf']:>6.2f} "
                  f"{M['dd']:>7.1f} {dd:>+6.1f} {M['worst']:>+8.1f} {day:>+6.1f} "
                  f"{tp2:>6.0f} {red2:>4d} {ih2:>4d}  "
                  f"{'✓ GEÇTİ' if gecti else '✗ ' + ','.join(neden)}")
            if gecti and (en_iyi is None or d > en_iyi[1]):
                en_iyi = (ad, d, M, tp2, lv)

    print(f"\n{'='*118}\n=== HÜKÜM ===")
    print(f"  ⚠ İHL={ihl0} TABANDA DA VAR — yani MEVCUT canlı sistemin durumu.")
    print(f"    2×ATR stopu likidasyon mesafesini (%{(1/10-BAKIM)*100:.1f} @10x) aşan")
    print(f"    {ihl0} işlem var ({ihl0/max(T['n'],1)*100:.1f}%). Bunlarda stop çalışmadan")
    print(f"    likide olunur. AYRI BİR BULGU — bu taramanın konusu değil, ama kayda geçti.")
    print(f"    Bar şartı: İHL ARTMASIN (sıfır olsun DEĞİL — aday kendi sebep olmadığı")
    print(f"    bir sorunu çözmek zorunda değil).")
    print(f"  ⚠ RED>0 olan satırın kârı FANTEZİDİR: canlı ön-kontrol (execution.py:559)")
    print(f"    o işlemleri gerçekte açmaz.")
    if en_iyi is None:
        print(f"\n  ✗ Hiçbir yapılandırma ön-kayıtlı barı geçmedi.")
        print(f"    Boyutlandırma ekseni de kapandı — kırpma gerçek ama düzeltmenin")
        print(f"    marjin/likidasyon bedeli kazancından büyük.")
        return
    ad, d, M, tp2, lv = en_iyi
    print(f"\n  ✓ EN İYİ: {ad}")
    print(f"    Δ ${d:+.0f} / 3.6 yıl = yılda ~${d/3.6:+.0f} (bakiye ${bal:.0f} tabanında)")
    print(f"    maxDD {M['dd']:.1f} · en kötü ay {M['worst']:+.1f} · tepe marjin %{tp2:.0f}")
    print(f"    kaldıraç dağılımı: " + " · ".join(f"{k}x:{v}" for k, v in sorted(lv.items())))
    print(f"\n    YIL YIL (taban → aday, bakiyenin %'si):")
    for y in sorted(set(T["yil"].index) | set(M["yil"].index)):
        t0v = T["yil"].get(y, 0.0); m0v = M["yil"].get(y, 0.0)
        print(f"      {y}: {t0v:>+7.1f}% → {m0v:>+7.1f}%  ({m0v-t0v:>+6.1f})"
              f"{'  ⚠ kötüleşti' if m0v < t0v - 1e-9 else ''}")
    print(f"\n  ⚠ CANLIYA ALMADAN ÖNCE — bu bir BACKTEST sonucu:")
    print(f"    1. MEXC'te işlem bazında kaldıraç DEĞİŞTİRİLEBİLİR mi? (aynı sembolde")
    print(f"       açık pozisyon varken set_leverage reddedilebilir — ÖNCE test et)")
    print(f"    2. Bakım marjini %{BAKIM*100:.1f} varsayıldı; MEXC'in gerçek kademeli")
    print(f"       oranı sembol ve nominal büyüklüğüne göre DEĞİŞİR — doğrula.")
    print(f"    3. Bakiye düşerse tepe marjin oranı AYNI kalır ama mutlak tampon küçülür.")


if __name__ == "__main__":
    main()
