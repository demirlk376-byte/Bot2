"""
trail_tara.py — TAKİP EDEN ÇIKIŞ (trailing), donchian, 3 yıllık veri.

NEDEN: 5a'da ölçüldü — ortalama R, çıkışlar TP'den max_hold'a kaydıkça
YÜKSELİYOR (+0.238 → +0.300). Yani **2.5R'lik TP kazananları erken kesiyor.**
Ama TP'yi kaldırmak (rr=5) en kötü ayı −21.0'dan −29.7'ye çıkarıyor.
Trailing hipotezi: koşuyu bırak, geri verişi koru.

⚠⚠ GÜÇLÜ TERS ÖN-BEKLENTİ VAR, GÖRMEZDEN GELİNMİYOR.
main.py:1078-1082 kayıtlı: sr_breakout'ta (o da bir KIRILIM stratejisi)
trailing sistemi PERİŞAN etti — sabit PF 1.80 / +23.4R vs trailing PF 1.39 /
+7.1R, drawdown da kötüleşti. Not aynen: "Sabit stoplar 3R'lik kazananın
koşmasına izin veriyor." Donchian da kırılım. Yani beklenen sonuç RET.
Yine de ölçülüyor çünkü o kanıt 12 AYLIK tek rejimden ve docstring'in kendisi
"2023/24 verisi olunca daha uzun veriyle yeniden doğrula" diyor (main.py:1088).

⚠ ÇÖZÜNÜRLÜK: 4h barlarında bar-İÇİ sıra görünmez. KÖTÜMSER KONVANSİYON:
  her barda ÖNCE bir önceki barın trail seviyesiyle stop kontrolü yapılır,
  SONRA bu barın ucuyla trail güncellenir. Böylece "bar yeni zirve yaptı,
  trail yükseldi, oradan çıktık" gibi bir lookahead İMKÂNSIZ.

⚠ ÖN-KAYIT (sonuç görülmeden yazıldı, gevşetilmeyecek):
  Aday ancak DÖRDÜNÜ birden sağlarsa önerilir:
    (1) walk-forward OOS'ta mevcut ayarı yenmeli   ← ASIL HAKEM (5a dersi)
    (2) Δ$ ≥ +28  (duran ön-kayıtlı baraj)
    (3) en kötü ay kötüleşmemeli (≥ −21.0)
    (4) maxDD 2 puandan fazla bozulmamalı (≤ 26.4)
  Havuzlanmış en yüksek hücre KARAR DEĞİLDİR — 5a'da havuzlanmış marjinal
  yanılttı, yıl bazında çöktü.

Kullanım:  python3 trail_tara.py local
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
import cikis_tara as CT

BAL = 190.0
TP_YOK = 99.0            # "TP kaldırıldı" — pratikte hiç vurulmaz


def kol_trail(d, sig, sl_a, rr, mh, mod, p):
    """mod: 'sabit' | 'be' | 'atr' | 'geri'
       p: be→R eşiği · atr→k (ATR katı) · geri→zirveden geri veriş (R)
       ATR giriş anındaki değer — canlı _update_trailing_stops da öyle yapıyor
       (strategy_scores['atr'], main.py:1071)."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i, yon, a in sig:
        if i <= occ:
            continue
        e = cl[i]; sld = sl_a * a
        stop = e - yon * sld
        tp = e + yon * rr * sld
        zirve_R = 0.0
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            # ── 1) STOP KONTROLÜ — BİR ÖNCEKİ barın trail seviyesiyle (lookahead yok)
            if yon == 1:
                if lo[j] <= stop: ep = stop; break
                if hi[j] >= tp:   ep = tp;   break
            else:
                if hi[j] >= stop: ep = stop; break
                if lo[j] <= tp:   ep = tp;   break
            # ── 2) TRAIL GÜNCELLE — bu barın ucuyla, SONRAKİ bar için
            uc = hi[j] if yon == 1 else lo[j]
            R_uc = yon * (uc - e) / sld
            zirve_R = max(zirve_R, R_uc)
            if mod == "be":
                if zirve_R >= p:
                    yeni = e
                    stop = max(stop, yeni) if yon == 1 else min(stop, yeni)
            elif mod == "atr":
                yeni = uc - yon * p * a
                stop = max(stop, yeni) if yon == 1 else min(stop, yeni)
            elif mod == "geri":
                if zirve_R > 0:
                    yeni = e + yon * (zirve_R - p) * sld
                    stop = max(stop, yeni) if yon == 1 else min(stop, yeni)
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = yon * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e))
        occ = j
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("trail_tara.py — takip eden çıkış, donchian, 3 yıl\n")
    print("  ⚠ TERS ÖN-BEKLENTİ: main.py:1078 sr_breakout'ta trailing'in sistemi")
    print("    perişan ettiğini kaydediyor (PF 1.80→1.39). Donchian da kırılım.")
    print("    Beklenen sonuç RET; yine de ölçülüyor (o kanıt 12 aylık tek rejim).\n")
    sla, _rr, mh = CT.MEVCUT
    coin_sig = {c: CT.sinyal_cek(c, source) for c in A.DONCH}
    sabit = []
    for c in A.SQZ:
        sabit += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        sabit += A.gen_bb(fast_bt.load(c, source=source))

    def calistir(rr, mod, p):
        ham = []
        for c in A.DONCH:
            d, sig = coin_sig[c]
            ham += kol_trail(d, sig, sla, rr, mh, mod, p)
        ham += sabit
        return CT.olc(A.seat_select(ham))

    t_kar, t_dd, t_ay, t_n, t_yil = calistir(_rr, "sabit", 0)
    ok = (t_n == 1579) and abs(t_kar - 1420.66) < 0.5
    print(f"  MAKİNE DOĞRULAMASI (trailing KAPALI): {t_n} işlem / ${t_kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")
    print(f"  taban: maxDD {t_dd:.1f} · en kötü ay {t_ay:.1f}\n")

    adaylar = [("BE@1R (canlı-doğrulanmış model, TP DURUYOR)", _rr, "be", 1.0)]
    for k in (1.5, 2.0, 3.0):
        adaylar.append((f"ATR trail {k}× (TP duruyor)", _rr, "atr", k))
    for k in (1.5, 2.0, 3.0):
        adaylar.append((f"ATR trail {k}× (TP YOK)", TP_YOK, "atr", k))
    for g in (0.5, 1.0, 1.5):
        adaylar.append((f"zirveden {g}R geri veriş (TP YOK)", TP_YOK, "geri", g))

    print(f"{'='*94}")
    print(f"  {'aday':<42s}{'işlem':>6s} {'kâr$':>8s} {'Δ$':>7s} {'maxDD':>7s} "
          f"{'kötü ay':>8s}  BAR")
    print(f"  {'TABAN (sabit SL/TP)':<42s}{t_n:>6d} {t_kar:>+8.0f} {0:>7.0f} "
          f"{t_dd:>7.1f} {t_ay:>8.1f}")
    sonuc = {}
    for ad, rr, mod, p in adaylar:
        kar, dd, ay, n, yil = calistir(rr, mod, p)
        sonuc[ad] = (kar, dd, ay, n, yil)
        neden = []
        if kar - t_kar < 28: neden.append("Δ$")
        if ay < t_ay - 0.05: neden.append("ay↓")
        if dd > t_dd + 2.0: neden.append("DD↑")
        bar = "✓ ön-eleme" if not neden else "✗ " + "+".join(neden)
        print(f"  {ad:<42s}{n:>6d} {kar:>+8.0f} {kar-t_kar:>+7.0f} {dd:>7.1f} "
              f"{ay:>8.1f}  {bar}")

    # ── WALK-FORWARD OOS — ASIL HAKEM (5a dersi) ─────────────────────────────
    print(f"\n{'='*94}\nWALK-FORWARD OOS — asıl hakem\n{'='*94}")
    yillar = sorted(t_yil)
    adlar = list(sonuc) + ["TABAN"]
    yil_tab = {a: sonuc[a][4] for a in sonuc}
    yil_tab["TABAN"] = t_yil
    oa = om = 0.0
    print(f"  {'yıl':>6s} {'diğer yıllarda en iyi aday':>44s} {'OOS $':>8s} "
          f"{'taban $':>9s} {'fark':>7s}")
    for Y in yillar:
        skor = {a: sum(v for y, v in yil_tab[a].items() if y != Y) for a in adlar}
        sec = max(skor, key=skor.get)
        aa = yil_tab[sec].get(Y, 0.0); mm = t_yil.get(Y, 0.0)
        oa += aa; om += mm
        print(f"  {Y:>6d} {sec[:44]:>44s} {aa:>+8.0f} {mm:>+9.0f} {aa-mm:>+7.0f}")
    print(f"  {'TOPLAM':>6s} {'':>44s} {oa:>+8.0f} {om:>+9.0f} {oa-om:>+7.0f}")

    print(f"\n{'='*94}\nHÜKÜM\n{'='*94}")
    if oa - om <= 0:
        print(f"  ✗ OOS'ta hiçbir trailing varyantı tabanı yenemedi (${oa-om:+.0f}).")
        print(f"    sr_breakout'taki bulgu donchian'da da doğrulandı: SABİT STOPLAR")
        print(f"    KAZANANIN KOŞMASINA İZİN VERİYOR. 'TP kazananı kesiyor' ölçümü")
        print(f"    GERÇEK ama çaresi trailing DEĞİL — trailing daha erken kesiyor.")
    else:
        print(f"  ⚠ OOS'ta ${oa-om:+.0f} önde. Ön-kaydın diğer üç şartına da bak:")
        print(f"    yukarıdaki tabloda '✓ ön-eleme' olan var mı? Yoksa RET.")


if __name__ == "__main__":
    main()
