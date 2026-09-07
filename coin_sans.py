"""
coin_sans.py — "mevcut 12 coin SEÇİLMİŞ mi, yoksa ŞANS mı?"

KULLANICININ SORUSU: mevcut coinlerden daha iyi çalışanlar bulabilir miyiz?

O eksen 2026-08-12'de KAPANDI (DURUM 4): coin eklemek en kötü ayı −21 → −58.8
yapıyor; "geçmişte iyi gideni seç" prosedürü walk-forward'da TRAIN'de muhteşem
TEST'te −$254. Yani "hangi coinleri ekleyelim" sorusunun cevabı yok.

⚠ AMA O BULGU RAHATSIZ EDİCİ BİR ŞEY İMA EDİYOR VE HİÇ KONTROL EDİLMEDİ:
   Eğer "geçmişte iyi gideni seç" TRANSFER ETMİYORSA, mevcut 12 coin de
   yıllar önce TAM O YÖNTEMLE seçildi. Bugünkü evren de bir aşırı-uydurma
   olabilir. Ankorun +$1420.66'sı stratejinin mi, yoksa şanslı bir coin
   listesinin mi eseri?

BU ARACIN SORDUĞU: elimizdeki 22 coinden RASTGELE 12 seçseydik ne olurdu?
  • Mevcut seçim dağılımın TEPESİNDEyse → seçimde beceri var (ama o beceri
    geçmişe bakarak elde edildi, yani ileriye taşınmayabilir).
  • Mevcut seçim ORTADAysa → coin seçimi hiçbir şey katmamış; edge
    STRATEJİDEN geliyor. Bu, "daha iyi coin arama" fikrini de kapatır ama
    ankoru GÜÇLENDİRİR: sonuç şanslı bir listeye bağlı değil.
  • Mevcut seçim ALTTAysa → kötü seçmişiz, bu ayrı bir bulgu olurdu.

⚠ Bu bir STRATEJİ DEĞİŞİKLİĞİ ÖNERMİYOR. Ankorun neye dayandığını ölçüyor.
  Çıkan sayı ne olursa olsun bugün hiçbir coin değişmeyecek — çünkü seçim
  prosedürünün kendisi zaten walk-forward'da düştü.

Kullanım:  python3 coin_sans.py local [deneme_sayisi]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt

BAL = 190.0
# Ankorun ölçüm penceresinde verisi olan tüm coinler
TUM = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "DOGE", "DOT",
       "ETC", "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET",
       "XLM", "XMR", "XRP"]
N_DONCH, N_SQZ, N_BB = len(A.DONCH), len(A.SQZ), len(A.BB_COINS)


def olc(taken):
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    o = np.argsort([x.value for x in ex]); p = pnl[o]
    e = np.concatenate([[BAL], BAL + np.cumsum(p)])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    mon = pd.Series(p, index=[ex[k].tz_localize(None).to_period("M")
                              for k in o]).groupby(level=0).sum() / BAL * 100
    return pnl.sum(), dd, mon.min(), len(taken)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    print("coin_sans.py — mevcut 12 coin seçilmiş mi, şans mı?\n")

    # ── her coin için HER KOLDA işlemleri BİR KEZ üret (pahalı kısım) ────────
    print(f"  {len(TUM)} coin × 3 kol için işlemler bir kez üretiliyor...")
    havuz = {"donchian": {}, "squeeze": {}, "bb": {}}
    for c in TUM:
        try:
            m = fast_bt.load(c, source=source)
        except SystemExit:
            print(f"    {c}: veri yok, ATLANDI")
            continue
        havuz["donchian"][c] = A.gen("donchian", m)
        havuz["squeeze"][c] = A.gen("squeeze", m)
        havuz["bb"][c] = A.gen_bb(m)
        print(f"    {c}: d{len(havuz['donchian'][c]):>3d} "
              f"s{len(havuz['squeeze'][c]):>3d} b{len(havuz['bb'][c]):>3d}", flush=True)
    uygun = [c for c in TUM if c in havuz["donchian"]]
    print(f"  kullanılabilir coin: {len(uygun)}")

    def portfoy(dch, sqz, bb):
        ham = []
        for c in dch: ham += havuz["donchian"][c]
        for c in sqz: ham += havuz["squeeze"][c]
        for c in bb:  ham += havuz["bb"][c]
        return olc(A.seat_select(ham))

    # ── MEVCUT SEÇİM — ankoru birebir üretmeli ──────────────────────────────
    m_kar, m_dd, m_ay, m_n = portfoy(A.DONCH, A.SQZ, A.BB_COINS)
    ok = (m_n == 1579) and abs(m_kar - 1420.66) < 0.5
    print(f"\n  MAKİNE DOĞRULAMASI (mevcut evren): {m_n} işlem / ${m_kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")
    print(f"  mevcut: maxDD {m_dd:.1f} · en kötü ay {m_ay:.1f}")

    # ── RASTGELE EVRENLER ───────────────────────────────────────────────────
    print(f"\n  {N} rastgele evren deneniyor "
          f"({N_DONCH} donchian + {N_SQZ} squeeze + {N_BB} bb)...", flush=True)
    rng = np.random.default_rng(12345)     # sabit tohum → tekrarlanabilir
    karlar = []; aylar = []; ddler = []
    for k in range(N):
        sec = list(rng.choice(uygun, N_DONCH + N_SQZ + N_BB, replace=False))
        kar, dd, ay, n = portfoy(sec[:N_DONCH],
                                 sec[N_DONCH:N_DONCH + N_SQZ],
                                 sec[N_DONCH + N_SQZ:])
        karlar.append(kar); aylar.append(ay); ddler.append(dd)
    karlar = np.array(karlar); aylar = np.array(aylar); ddler = np.array(ddler)

    yuzde = (karlar < m_kar).mean() * 100
    print(f"\n{'='*72}\nSONUÇ\n{'='*72}")
    print(f"  rastgele evrenlerin kârı:")
    print(f"    ortalama ${karlar.mean():+,.0f} · medyan ${np.median(karlar):+,.0f}")
    print(f"    p10 ${np.percentile(karlar,10):+,.0f} · "
          f"p90 ${np.percentile(karlar,90):+,.0f} · "
          f"en iyi ${karlar.max():+,.0f}")
    print(f"  MEVCUT evren: ${m_kar:+,.0f}")
    print(f"  → mevcut seçim, rastgelelerin **%{yuzde:.0f}**'inden iyi")
    print(f"\n  en kötü ay: mevcut {m_ay:.1f} · rastgele medyan {np.median(aylar):.1f}")
    print(f"  maxDD     : mevcut {m_dd:.1f} · rastgele medyan {np.median(ddler):.1f}")

    print(f"\n{'='*72}\nHÜKÜM\n{'='*72}")
    if yuzde >= 90:
        print(f"  ⚠ Mevcut evren rastgelelerin ÜST %{100-yuzde:.0f}'inde.")
        print(f"    Bu 'iyi seçmişiz' gibi görünür AMA seçim GEÇMİŞE BAKARAK")
        print(f"    yapıldı — aynı veriyle. Yani bu üstünlük İLERİYE taşınmayabilir;")
        print(f"    coin_expand'ın walk-forward'ı tam da bunun taşınmadığını gösterdi.")
        print(f"    Ankorun bir kısmı coin seçimine bağlı → ihtiyatlı ol.")
    elif yuzde >= 35:
        print(f"  ✓ Mevcut evren rastgelenin ORTASINDA (%{yuzde:.0f}).")
        print(f"    Coin seçimi kâra kayda değer bir şey KATMAMIŞ — yani ankorun")
        print(f"    +${m_kar:,.0f}'ı ŞANSLI BİR LİSTEYE DEĞİL, STRATEJİNİN KENDİSİNE")
        print(f"    dayanıyor. Bu ankoru GÜÇLENDİREN bir bulgudur.")
        print(f"    Ve 'daha iyi coin arayalım' fikrini de kapatır: rastgele bir")
        print(f"    liste de aynısını yapıyorsa, aramanın karşılığı yok.")
    else:
        print(f"  ⛔ Mevcut evren rastgelenin ALTINDA (%{yuzde:.0f}).")
        print(f"    Kötü seçilmiş olabilir — bu AYRI bir bulgu, incelenmeli.")


if __name__ == "__main__":
    main()
