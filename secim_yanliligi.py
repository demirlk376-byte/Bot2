"""
secim_yanliligi.py — "neden hiçbir şey işe yaramıyor?" sorusunun ölçülebilir hâli.

ŞÜPHE: taban ANKOR, bu verinin ÜZERİNDE seçildi.
  · coinler geçmiş performansa göre (donchian 7'si, 21 coin içinde ort sıra 4.6)
  · kanal 40, altı seçenek (20/30/40/60/80/120) arasından en iyisi olduğu için
  · RR 2.5, taramayla
Yani her yeni fikri, KENDİSİ DE AYNI VERİYE UYDURULMUŞ bir sayıyla kıyaslıyoruz.
Bu doğruysa, yeni fikirlerin düşmesi onların kötü olmasından değil, tabanın
ŞİŞKİN olmasından kaynaklanır — ve bu, "her şey düşüyor" deseninin açıklaması olur.

ÖLÇÜM: zamanı ikiye böl. İLK yarıda en iyi kanalı seç. İKİNCİ yarıda o seçimin
hâlâ ortalamayı yenip yenmediğine bak.
  · yeniyorsa → kanal 40 gerçek bir optimum, taban dürüst
  · yenmiyorsa → tabanın üstünlüğü SEÇİM YANLILIĞI, ve her kıyas o kadar şişkin

Kullanım:  py secim_yanliligi.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from pro_donchian import uret, portfoy, olc

KANALLAR = [20, 30, 40, 60, 80, 120]


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    veri = {c: fast_bt.load(c, source=src) for c in A.DONCH}
    print(f"\n{'=' * 92}\n=== TABAN ŞİŞKİN Mİ? — kanal seçiminin yanlılığı ===\n")

    tum = {}
    for k in KANALLAR:
        ham = []
        for c in A.DONCH: ham += uret(c, veri[c], kanal=k)
        tum[k] = portfoy(ham)

    # zaman ekseninde ikiye böl (çıkış tarihine göre)
    hepsi = sorted({x for tk in tum.values() for x, _, _ in tk})
    kesim = hepsi[len(hepsi) // 2]

    def parca(tk, ilk):
        return [t for t in tk if (t[0] < kesim if ilk else t[0] >= kesim)]

    print(f"  bölme noktası: {pd.Timestamp(kesim).date()}\n")
    print(f"  {'kanal':>6s} {'TÜM kâr':>10s} {'1.yarı':>10s} {'2.yarı':>10s} {'2.yarı n':>9s}")
    y1, y2 = {}, {}
    for k in KANALLAR:
        a = olc(parca(tum[k], True)); b = olc(parca(tum[k], False))
        t = olc(tum[k])
        y1[k], y2[k] = a["kar"], b["kar"]
        print(f"  {k:>6d} {t['kar']:>+10.2f} {a['kar']:>+10.2f} {b['kar']:>+10.2f} {b['n']:>9d}")

    en_iyi_1 = max(y1, key=y1.get)
    ort_2 = np.mean(list(y2.values()))
    print(f"\n  1. yarının EN İYİSİ: kanal {en_iyi_1} (${y1[en_iyi_1]:+.2f})")
    print(f"  o kanalın 2. yarıdaki kârı        : ${y2[en_iyi_1]:+.2f}")
    print(f"  altı kanalın 2. yarıdaki ORTALAMASI: ${ort_2:+.2f}")
    fark = y2[en_iyi_1] - ort_2
    print(f"  fark: ${fark:+.2f}")
    print(f"  → {'✓ seçim İLERİYE TAŞINIYOR, taban dürüst' if fark > 0 else '✗ seçim TAŞINMIYOR — tabanın üstünlüğü YANLILIK'}")

    print(f"\n  TÜM VERİDE kanal 40'ın altı kanal ortalamasına üstünlüğü:")
    ort_tum = np.mean([olc(tum[k])["kar"] for k in KANALLAR])
    k40 = olc(tum[40])["kar"]
    print(f"    kanal 40 ${k40:+.2f} · ortalama ${ort_tum:+.2f} · üstünlük ${k40-ort_tum:+.2f} "
          f"(%{(k40/ort_tum-1)*100:+.1f})")
    print(f"    2. yarıda AYNI üstünlük: ${y2[40]-ort_2:+.2f} "
          f"(%{(y2[40]/ort_2-1)*100:+.1f})")
    print(f"\n  ⓘ Tüm veride görünen üstünlük, 2. yarıda ne kadar KORUNUYOR?")
    print(f"    Büyük ölçüde kayboluyorsa, tabanla yapılan HER kıyas o oranda")
    print(f"    yeni fikirlerin aleyhinedir.")
    print(f"{'=' * 92}\n")


if __name__ == "__main__":
    main()
