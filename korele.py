"""
korele.py — EŞZAMANLI MARUZİYET: fazla aylık yayılma gerçekten korele
pozisyonlardan mı geliyor?

NEDEN BU EKSEN: 2026-09-09 taramasında ay-etiketi karıştırma null'unu geçen
TEK istatistik aylık PnL standart sapmasıydı (31.45 vs null 24.32, p=0.006).
Kötü aylar öngörülemiyor, ama aylık dağılımın fazla yayılması GERÇEK.
Hipotez: aynı ay içinde aynı yönde, aynı anda açılan pozisyonlar birlikte
kazanıp birlikte kaybediyor.

⚠ BU BİR GİRİŞ FİLTRESİ SORUSU DEĞİL. Giriş özelliklerinde iz yok (OOS r=+0.031).
   Bu bir PORTFÖY İNŞASI sorusu: kaç pozisyon, hangi yönde, aynı anda.

⚠ SİLMEK ≠ KÜÇÜLTMEK. Ledger: "ne silinirse silinsin silmek negatif
   beklentidir" (290 deneme). Aynı-yön cap K=4 daha önce denendi, dolar-negatif
   çıktı — çünkü cap SİLER. Burada asıl aday SİLMEYEN sürüm: kalabalık anda
   açılan pozisyonları KÜÇÜLT, tenha anda açılanları BÜYÜT, toplam riski sabit
   tut. Hiçbir işlem kaybolmaz.

Kullanım:  py korele.py
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

VERI = "data/ay_analiz.csv"
TOHUM = 20260909


def yukle():
    df = pd.read_csv(VERI)
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["giris_ts"] = pd.to_datetime(df["giris"])
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["ay"] = df["cikis_ts"].dt.tz_localize(None).dt.to_period("M")
    return df.sort_values("giris_ts").reset_index(drop=True)


def esZamanli(df):
    """Her işlem için: AÇILDIĞI ANDA kaç pozisyon açıktı, kaçı AYNI YÖNDE.

    ⚠ NEDENSELLİK: yalnız o ana kadar AÇILMIŞ ve HENÜZ KAPANMAMIŞ pozisyonlar
    sayılıyor. Gelecekte açılacaklar sayılmıyor — canlıda da bilinemezdi.
    """
    g = df["giris_ts"].values; c = df["cikis_ts"].values; y = df["yon"].values
    n = len(df)
    top = np.zeros(n, dtype=int); ayni = np.zeros(n, dtype=int)
    for i in range(n):
        # j < i  (daha önce açılmış)  ve  cikis[j] > giris[i]  (hâlâ açık)
        acik = (g[:i] <= g[i]) & (c[:i] > g[i])
        top[i] = acik.sum()
        ayni[i] = (acik & (y[:i] == y[i])).sum()
    df["es_top"] = top + 1          # kendisi dâhil
    df["es_ayni"] = ayni + 1        # kendisi dâhil
    return df


def aylik(df, eff):
    return pd.Series(df["R"].values * eff * 100.0,
                     index=df["ay"].values).groupby(level=0).sum()


def main():
    df = esZamanli(yukle())
    rng = np.random.default_rng(TOHUM)
    e = df["eff"].values
    ay_g = aylik(df, e)

    print(f"\n{'=' * 96}")
    print(f"=== EŞZAMANLI MARUZİYET TEŞHİSİ ===")
    print(f"  taban: aylık ort %{ay_g.mean():+.2f} · std %{ay_g.std():.2f} · "
          f"en kötü %{ay_g.min():.2f}\n")

    print(f"  [1] EŞZAMANLILIK PROFİLİ (açılış anında, kendisi dâhil)")
    print(f"      {'n':>3s} {'işlem':>6s} {'pay':>6s} {'ort R':>8s} {'$/işlem':>9s}")
    for n in range(1, 8):
        s = df[df["es_top"] == n]
        if not len(s): continue
        print(f"      {n:>3d} {len(s):>6d} {len(s)/len(df)*100:>5.1f}% "
              f"{s['R'].mean():>+8.3f} {(s['R']*s['eff']*A.BAL0).mean():>+9.3f}")
    print(f"      → ort eşzamanlı {df['es_top'].mean():.2f} · "
          f"MAX {df['es_top'].max()} (MAXPOS={A.MAXPOS})")

    print(f"\n  [2] AYNI YÖNDE KALABALIK — asıl şüpheli")
    print(f"      {'aynı yön':>8s} {'işlem':>6s} {'pay':>6s} {'ort R':>8s} {'WR':>6s} {'$/işlem':>9s}")
    for n in range(1, 8):
        s = df[df["es_ayni"] == n]
        if not len(s): continue
        print(f"      {n:>8d} {len(s):>6d} {len(s)/len(df)*100:>5.1f}% "
              f"{s['R'].mean():>+8.3f} {(s['R']>0).mean()*100:>5.1f}% "
              f"{(s['R']*s['eff']*A.BAL0).mean():>+9.3f}")
    print(f"      ⚠ ort R kalabalıkla DÜŞÜYORSA bu bir edge sinyalidir;")
    print(f"        DÜŞMÜYORSA sorun beklenti değil YALNIZ VARYANS'tır.")

    print(f"\n  [3] FAZLA YAYILMA EŞZAMANLILIKTAN MI? — R'leri kol içinde karıştır")
    print(f"      (zamanlar ve boyutlar aynı kalır; yalnız hangi işlemin hangi")
    print(f"       sonucu aldığı karışır → örtüşen işlemler arası ORTAK HAREKET kırılır)")
    R = df["R"].values.copy()
    kol = df["kol"].values
    null_std = []
    for _ in range(4000):
        Rk = R.copy()
        for k in np.unique(kol):
            m = kol == k
            Rk[m] = rng.permutation(Rk[m])
        null_std.append(pd.Series(Rk * e * 100.0,
                                  index=df["ay"].values).groupby(level=0).sum().std())
    null_std = np.array(null_std)
    p = (null_std >= ay_g.std()).mean()
    print(f"      gözlenen aylık std %{ay_g.std():.2f}")
    print(f"      karıştırılmış null  ort %{null_std.mean():.2f} · "
          f"%95 dilim %{np.percentile(null_std, 95):.2f}")
    print(f"      p = {p:.4f}  → {'✓ ORTAK HAREKET GERÇEK' if p < 0.05 else '✗ ortak hareket kanıtlanamadı'}")

    print(f"\n  [4] ORTAK HAREKETİN KAYNAĞI — örtüşen çiftlerin R korelasyonu")
    g = df["giris_ts"].values; c = df["cikis_ts"].values
    yon = df["yon"].values
    ciftler = {"aynı yön": [], "ters yön": []}
    for i in range(len(df)):
        j = np.where((g[i+1:] < c[i]))[0] + i + 1      # i ile örtüşenler
        for k in j[:40]:                                # ilk 40 örtüşme yeter
            ciftler["aynı yön" if yon[i] == yon[k] else "ters yön"].append((R[i], R[k]))
    for ad, v in ciftler.items():
        if len(v) < 50: continue
        a = np.array(v)
        print(f"      {ad}: {len(a):5d} çift · korelasyon {np.corrcoef(a[:,0], a[:,1])[0,1]:+.4f}")
    print(f"      → aynı yön korelasyonu ters yönden BELİRGİN YÜKSEKSE, aynı-yön")
    print(f"        maruziyeti gerçek risk kaynağıdır ve tavan MANTIKLIDIR.")
    print(f"{'=' * 96}\n")


if __name__ == "__main__":
    main()
