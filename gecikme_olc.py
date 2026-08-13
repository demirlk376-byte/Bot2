"""
gecikme_olc.py — 13.4bp KAYMA NEREDEN GELİYOR? Spread mi, GECİKME mi?

NEDEN ÖNEMLİ: ankor_denetim.py giriş kaymasının ankordan $251 götürdüğünü ölçtü
(yılda ~$70) — bugün denenen 14 filtrenin hepsinden büyük. Ama "kayma" tek bir şey
değil; en az iki bileşeni var ve İKİSİNİN ÇARESİ FARKLI:

  (a) SPREAD + ETKİ — emri verdiğin anda alış/satış farkı. $200'lık bir emirde
      likit perp'te bu ~1bp'dir. ÇARESİ: maker limit (maker_giris.py).
  (b) GECİKME SÜRÜKLENMESİ — bar kapandı, bot bunu FARK EDENE kadar geçen sürede
      fiyat kırılım yönünde kaçtı. ÇARESİ: daha erken fark etmek. ÜCRETSİZ.

KODDA BULUNAN SOMUT ŞÜPHE (data.py:88):
      REST_POLL_INTERVAL = 30   # seconds
  Mum kapanışı WEBSOCKET'ten değil, 30 SANİYEDE BİR REST anketinden yakalanıyor
  (data.py:220 _rest_poll_loop → _poll_once → _fire_callbacks). Anket bar sınırına
  HİZALI DEĞİL — bot ne zaman başladıysa o faz. Yani ortalama ~15sn, en kötü 30sn
  fark edilmiyor. Üstüne on_candle_close içindeki fetch/indikatör işi ve
  sembol başına bekleme geliyor.

  4 saatlik bir barda ATR ~%1.5 ise, T saniyelik sürüklenme ≈ %1.5×√(T/14400).
      15sn → ~4.8bp · 30sn → ~6.8bp · 60sn → ~9.7bp · 120sn → ~13.7bp
  Yani 13.4bp'nin BÜYÜK KISMI gecikme olabilir. Olabilir ≠ öyledir: ÖLÇÜLÜR.

BU ARAÇ NE YAPIYOR: gerçek donchian(4h)/squeeze(1h) sinyallerinde, bar KAPANDIKTAN
sonraki 1..30 dakikada fiyatın SİNYAL YÖNÜNDE ne kadar kaçtığını ölçer. Eğri
13.4bp'yi nerede kesiyorsa, botun gerçek gecikmesi ORADADIR.

HÜKÜM NASIL OKUNUR:
  • 1dk'da sürüklenme 13.4bp'ye YAKINSA → kayma ~tamamen GECİKME. Anketi bar
    sınırına hizalamak (ücretsiz, tek satır) $251'in çoğunu geri verir.
  • 1dk'da çok KÜÇÜKSE (~1-3bp) → kayma spread/etki kaynaklı. O zaman tek çare
    maker limit; hizalama boşa iş.

⚠ VEKİL: yalnız yerel 1dk CSV'ler (BTC=Binance venue, canlı değil; ETH=canlı
donchian listesinde VAR). Kesin ölçüm defterde: her işlemin sinyal zamanı ile
gerçek dolum zamanı arasındaki fark. VPS'te 'py live_verify.py' o farkı görüyor.

Kullanım:  py gecikme_olc.py
"""
import numpy as np
import pandas as pd

import deployed_backtest as A
from maker_giris import sinyal_cek, yerel_1m, _tf_delta

KAYMA_BP = 13.4          # live_verify.py:44 — ölçülmüş toplam giriş kayması
DK = [1, 2, 3, 5, 10, 15, 30]


def surukle_olc(d1m, d_tf, sig, tf, sl_a, rr, mh):
    """Her sinyal için bar kapanışından sonraki t dakikada YÖNE GÖRE sürüklenme (bp).
    Pozitif = aleyhe (long'da fiyat yukarı kaçmış → daha pahalıya giriyoruz)."""
    hi = d_tf["high"].values; lo = d_tf["low"].values; cl = d_tf["close"].values
    idx = d_tf.index; n = len(cl)
    dt = _tf_delta(tf)
    c1 = d1m["close"].values
    t1 = d1m.index
    rows = []
    for i, d_, a in sig:
        kapanis = idx[i] + dt
        p0 = t1.searchsorted(kapanis, side="left")
        if p0 >= len(t1) or abs((t1[p0] - kapanis).total_seconds()) > 90:
            continue
        L = cl[i]
        sld = sl_a * a
        slp = L - d_ * sld; tp = L + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        r = {"R": d_ * (ep - L) / sld, "atr_bp": sld / L * 10000.0 / sl_a}
        for t in DK:
            p = p0 + t - 1                      # t. dakikanın KAPANIŞI
            r[t] = d_ * (c1[p] - L) / L * 10000.0 if p < len(c1) else np.nan
        rows.append(r)
    return rows


def rapor(rows, ad):
    if len(rows) < 30:
        print(f"\n  --- {ad}: n={len(rows)} — çok az, hüküm verilmez ---")
        return
    print(f"\n  --- {ad} (n={len(rows)}) ---")
    print(f"  {'dk':>4s} {'ort bp':>8s} {'%95 aralık':>18s} {'medyan':>8s} "
          f"{'aleyhe%':>8s} {'13.4bp payı':>12s}")
    for t in DK:
        v = np.array([r[t] for r in rows if np.isfinite(r.get(t, np.nan))])
        if len(v) < 30:
            continue
        se = v.std(ddof=1) / np.sqrt(len(v))
        pay = v.mean() / KAYMA_BP * 100
        print(f"  {t:>4d} {v.mean():>+8.2f} [{v.mean()-1.96*se:>+7.2f},{v.mean()+1.96*se:>+7.2f}] "
              f"{np.median(v):>+8.2f} {(v > 0).mean()*100:>7.1f}% {pay:>11.0f}%")
    # kazanan/kaybeden ayrımı: sürüklenme momentumun kendisi mi?
    R = np.array([r["R"] for r in rows])
    for t in (1, 5):
        v = np.array([r[t] for r in rows])
        m = np.isfinite(v)
        if m.sum() < 40:
            continue
        vw = v[m & (R > 0)]; vl = v[m & (R <= 0)]
        if len(vw) > 10 and len(vl) > 10:
            print(f"    t={t}dk · KAZANAN işlemlerde {vw.mean():+.2f}bp · "
                  f"KAYBEDENlerde {vl.mean():+.2f}bp")


def main():
    print(f"\n{'=' * 110}")
    print("=== GECİKME ÖLÇÜMÜ: 13.4bp kaymanın ne kadarı 'geç fark etme'? ===")
    print("  data.py:88 REST_POLL_INTERVAL = 30sn, bar sınırına HİZALI DEĞİL.")
    print("  Bar kapandıktan sonra fiyat sinyal yönünde ne kadar kaçıyor?")

    src = yerel_1m()
    if not src:
        print("\n  ✗ Yerel 1dk CSV yok — ölçüm yapılamaz.")
        return
    print(f"\n  ⚠ VEKİL kaynaklar: {list(src)} (Binance 1dk). ETH canlı donchian'da VAR.")

    for kol in ("donchian", "squeeze"):
        tf, win, sl_a, rr, mh = A.CFG[kol]
        rows = []
        for c, m1 in src.items():
            d_tf, sig = sinyal_cek(kol, m1)
            r = surukle_olc(m1, d_tf, sig, tf, sl_a, rr, mh)
            rows += r
            print(f"    {c:4s} {kol:9s}: {len(sig):4d} sinyal → {len(r):4d} ölçülebildi")
        rapor(rows, f"{kol.upper()} — bar kapanışı sonrası ALEYHE sürüklenme")
        globals()[f"_rows_{kol}"] = rows

    print(f"\n{'=' * 110}\n=== HÜKÜM ===")
    rd = globals().get("_rows_donchian", [])
    if len(rd) >= 30:
        v1 = np.array([r[1] for r in rd if np.isfinite(r.get(1, np.nan))])
        v5 = np.array([r[5] for r in rd if np.isfinite(r.get(5, np.nan))])
        print(f"\n  donchian: 1dk sonra {v1.mean():+.2f}bp · 5dk sonra {v5.mean():+.2f}bp "
              f"(toplam ölçülen kayma {KAYMA_BP}bp)")
        if v1.mean() >= KAYMA_BP * 0.5:
            print(f"    ✓ KAYMANIN ÇOĞU GECİKME. Bot barı ~1dk geç görüyorsa 13.4bp'nin")
            print(f"      %{v1.mean()/KAYMA_BP*100:.0f}'i sırf bekleyişten geliyor.")
            print(f"      ÇARE ÜCRETSİZ: REST anketini bar sınırına HİZALA (data.py).")
            print(f"      Sonraki 4h/1h kapanışına kadar uyu, +2sn ile uyan. Sinyal DEĞİŞMEZ.")
        elif v1.mean() >= KAYMA_BP * 0.2:
            print(f"    ~ Kaymanın ~%{v1.mean()/KAYMA_BP*100:.0f}'i gecikme. Hizalama işe yarar")
            print(f"      ama tek başına yetmez; kalanı spread/etki → maker limit gerekir.")
        else:
            print(f"    ✗ Gecikme KÜÇÜK ({v1.mean():+.2f}bp). 13.4bp'nin kaynağı başka:")
            print(f"      spread/etki, ya da botun gecikmesi 1dk'dan ÇOK daha uzun.")
            print(f"      → hizalama boşa iş; maker limit (maker_giris.py) tek yol.")
        print(f"\n  ⚠ Bu eğri botun GERÇEK gecikmesini bilmiyor — onu yalnız defter bilir.")
        print(f"    VPS'te ölç: her işlemin sinyal barı kapanışı ile entry_time farkı.")
        print(f"    Eğri o gecikmede hangi bp'yi veriyorsa, geri kazanılabilir tutar odur.")


if __name__ == "__main__":
    main()
