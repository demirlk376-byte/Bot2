"""
coklu_pozisyon.py — "DAHA FAZLA AL" ekseni. 32 kapanan eksende HİÇ denenmedi.

GÖZLEM: kapanan 32 eksenin HEPSİ ÇIKARMAK ya da KORUMAK üzerineydi —
filtre, rejim kapısı, yön sınırı, boyut kısma, kâr kilidi, trailing.
Hiçbiri EKLEMEK değildi. Bu yapısal bir kör nokta.

VE ÖLÇÜLMÜŞ BİR AÇIK VAR (sessizlik.py): donchian coinleri zamanın %32.2'sinde
açık pozisyonla KİLİTLİ. Yani rastgele bir donchian sinyalinin ~1/3'ü
"bu coinde zaten pozisyon var" diye eleniyor (canlıda: "already holds a
position, one-per-symbol in netted mode"; ankorda: `occ`).

5a şunu gösterdi: kâr birkaç BÜYÜK KOŞUDAN geliyor (ort R, çıkışlar TP'den
max_hold'a kaydıkça +0.238→+0.300 yükseliyor). Eğer öyleyse, bir koşu
sinyalinin VASAT bir pozisyon yüzünden engellenmesi GERÇEK bir kayıptır.

⚠ AMA BEDAVA DEĞİL: aynı coinde iki pozisyon = o coine iki kat risk, ve
   MAX_POSITIONS=7 koltuğu daha çok bağlar. Ağustos'ta 6 korelasyonlu long
   birlikte stoplandı; bu kural onu ÇOĞALTABİLİR. Ölçüm bunu yakalamalı:
   en kötü ay ve maxDD şartları tam bu yüzden ön-kayıtta.

⚠ ÖN-KAYIT (sonuç görülmeden, gevşetilmeyecek):
   (1) walk-forward OOS'ta tabanı yenmeli   ← ASIL HAKEM
   (2) Δ$ ≥ +28
   (3) en kötü ay kötüleşmemeli
   (4) maxDD 2 puandan fazla bozulmamalı
   Havuzlanmış en yüksek KARAR DEĞİLDİR (5a dersi).

Kullanım:  python3 coklu_pozisyon.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
import cikis_tara as CT


def kol_coklu(d, sig, sl_a, rr, mh, coin_limit):
    """coin_limit: aynı coinde EŞ ZAMANLI izin verilen pozisyon sayısı.
    1 = mevcut davranış (occ). Büyükse aynı coinde üst üste binebilir."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []
    acik = []                     # o coinde açık pozisyonların çıkış barları
    for i, yon, a in sig:
        # ⚠ SINIR KOŞULU: ankor `if i <= occ: continue` diyor, yani ÇIKIŞ
        # BARININ KENDİSİ de DOLU sayılır (aynı barda çık-gir yok). İlk sürümde
        # `x > i` yazmıştım = o barı boş saymak → 119 FAZLA işlem (1698 vs 1579)
        # ve $40 sapma. Makine doğrulaması yakaladı. Doğrusu `x >= i`.
        acik = [x for x in acik if x >= i]     # kapananları düş (çıkış barı DAHİL dolu)
        if len(acik) >= coin_limit:
            continue
        e = cl[i]; sld = sl_a * a
        slp = e - yon * sld; tp = e + yon * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if yon == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = yon * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e))
        acik.append(j)
    return out


def marjin_tepe(taken):
    """Eş zamanlı kullanılan marjinin ZİRVESİ (bakiyenin %'si) — 'daha fazla al'
    kuralının gizli maliyeti burada görünür."""
    olay = []
    for x, R, slp in taken:
        pass
    return None


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("coklu_pozisyon.py — 'daha fazla al' ekseni (32 eksende hiç denenmedi)\n")
    sla, rr, mh = CT.MEVCUT
    coin_sig = {c: CT.sinyal_cek(c, source) for c in A.DONCH}
    sabit = []
    for c in A.SQZ:
        sabit += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        sabit += A.gen_bb(fast_bt.load(c, source=source))

    def calistir(limit):
        ham = []
        for c in A.DONCH:
            d, sig = coin_sig[c]
            ham += kol_coklu(d, sig, sla, rr, mh, limit)
        ham += sabit
        return CT.olc(A.seat_select(ham))

    t_kar, t_dd, t_ay, t_n, t_yil = calistir(1)
    ok = (t_n == 1579) and abs(t_kar - 1420.66) < 0.5
    print(f"  MAKİNE DOĞRULAMASI (coin başına 1 = mevcut): {t_n} işlem / "
          f"${t_kar:+.2f} → {'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")
    print(f"  taban: maxDD {t_dd:.1f} · en kötü ay {t_ay:.1f}\n")

    print(f"{'='*84}")
    print(f"  {'coin başına eş zamanlı':<26s}{'işlem':>7s} {'kâr$':>8s} {'Δ$':>7s} "
          f"{'maxDD':>7s} {'kötü ay':>8s}  BAR")
    print(f"  {'1 (MEVCUT)':<26s}{t_n:>7d} {t_kar:>+8.0f} {0:>7.0f} {t_dd:>7.1f} "
          f"{t_ay:>8.1f}")
    tab = {"1 (MEVCUT)": (t_kar, t_dd, t_ay, t_n, t_yil)}
    for lim in (2, 3, 99):
        kar, dd, ay, n, yil = calistir(lim)
        ad = f"{lim}" if lim < 99 else "SINIRSIZ"
        tab[ad] = (kar, dd, ay, n, yil)
        neden = []
        if kar - t_kar < 28: neden.append("Δ$")
        if ay < t_ay - 0.05: neden.append("ay↓")
        if dd > t_dd + 2.0: neden.append("DD↑")
        bar = "✓ ön-eleme" if not neden else "✗ " + "+".join(neden)
        print(f"  {ad:<26s}{n:>7d} {kar:>+8.0f} {kar-t_kar:>+7.0f} {dd:>7.1f} "
              f"{ay:>8.1f}  {bar}")

    print(f"\n{'='*84}\nWALK-FORWARD OOS — asıl hakem\n{'='*84}")
    yillar = sorted(t_yil)
    oa = om = 0.0
    print(f"  {'yıl':>6s} {'diğer yıllarda en iyi':>24s} {'OOS $':>8s} "
          f"{'taban $':>9s} {'fark':>7s}")
    for Y in yillar:
        skor = {a: sum(v for y, v in tab[a][4].items() if y != Y) for a in tab}
        sec = max(skor, key=skor.get)
        aa = tab[sec][4].get(Y, 0.0); mm = t_yil.get(Y, 0.0)
        oa += aa; om += mm
        print(f"  {Y:>6d} {sec:>24s} {aa:>+8.0f} {mm:>+9.0f} {aa-mm:>+7.0f}")
    print(f"  {'TOPLAM':>6s} {'':>24s} {oa:>+8.0f} {om:>+9.0f} {oa-om:>+7.0f}")

    print(f"\n{'='*84}\nHÜKÜM\n{'='*84}")
    if oa - om <= 0:
        print(f"  ✗ OOS'ta 'daha fazla al' da tabanı yenemedi (${oa-om:+.0f}).")
        print(f"    Bu, kör noktanın da kapandığı anlamına gelir: sistem ne")
        print(f"    kesilerek ne de çoğaltılarak iyileşiyor.")
    else:
        print(f"  ⚠ OOS'ta ${oa-om:+.0f} önde — ön-kaydın diğer üç şartına bak.")
        print(f"    Geçse bile CANLI KISIT var: aynı coinde ikinci pozisyon")
        print(f"    MEXC netted modda AYRI pozisyon DEĞİL, mevcut pozisyonu")
        print(f"    BÜYÜTÜR. Yani bu kural canlıda 'iki işlem' değil 'tek büyük")
        print(f"    işlem' olur ve SL/TP tek seviyeye düşer. Uygulanabilirlik")
        print(f"    AYRICA doğrulanmalı (exchange.py netted mod).")


if __name__ == "__main__":
    main()
