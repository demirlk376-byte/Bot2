"""
ikiz_coin_analiz.py — İKİZ'in işlem listesinde COİN BAZINDA kim kazandırıyor?

⚠ EN KLASİK TUZAK: "geçmişte zarar eden coinleri kapat" demek, SONUCA BAKARAK
SEÇMEKTİR. 12 coinin en kötüsü şans eseri de en kötü olabilir; onu atınca
geçmiş güzelleşir ama gelecek değişmez. Depoda bu tam olarak yaşandı
(`breadth_expand.py`, 2026-07-29): coin eklemek TÜM veride +$169..+563
kazandırıyordu ama TEST diliminde HEPSİ negatifti — ders kitabı seçim yanlılığı.

BU YÜZDEN: seçim YALNIZ TRAIN'den (giriş < 2025-01-01), karar YALNIZ TEST'ten
(giriş ≥ 2025-01-01). Train'de kötü olan coinleri atıp TEST'te ne olduğuna
bakarız. Test'te de kazandırıyorsa gerçek; kazandırmıyorsa gürültüydü.

Kullanım:  py ikiz_coin_analiz.py [islem_listesi.csv]
"""
import sys, os
import numpy as np, pandas as pd

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def _dbden():
    """CSV yoksa DOĞRUDAN veritabanından oku. DB birincil kaynak, CSV türev —
    ve bat bir kez CSV'yi uçurduğu için bu yol daha sağlam. WAL'daki veriler de
    okunur (aynı dizindeki -wal dosyası otomatik birleşir)."""
    import sqlite3
    from ikiz import db_yolu
    y = db_yolu()
    if not os.path.exists(y):
        return None
    c = sqlite3.connect(y)                    # ro DEĞİL: WAL'ı birleştirebilsin
    try:
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    d = pd.read_sql(
        "SELECT symbol,side,entry_price,exit_price,sl_price,quantity,"
        "entry_time,exit_time,pnl_usdt,exit_reason,strategy_scores "
        "FROM trades WHERE exit_time IS NOT NULL", c)
    c.close()
    print(f"  kaynak: {y} ({len(d)} kapanmış işlem)")
    return d


def yukle(yol):
    if os.path.exists(yol):
        print(f"  kaynak: {yol}")
        d = pd.read_csv(yol)
    else:
        d = _dbden()
        if d is None or not len(d):
            sys.exit("⛔ Ne CSV ne de veritabanı bulundu. Önce `2_TAM_KOSU.bat` koş.")
    d["giris"] = pd.to_datetime(d.entry_time, utc=True, format="mixed")
    d["cikis"] = pd.to_datetime(d.exit_time, utc=True, format="mixed")
    d["coin"] = d.symbol.str.split("/").str[0]
    yon = np.where(d.side.str.lower().str.startswith("s"), -1, 1)
    stop = (d.entry_price - d.sl_price).abs()
    d["R"] = np.where(stop > 0, yon * (d.exit_price - d.entry_price) / stop.replace(0, np.nan), np.nan)
    return d.dropna(subset=["R"])


def tablo(d, baslik):
    print(f"\n── {baslik} ──")
    print(f"  {'coin':<6s} {'n':>5s} {'ort R':>8s} {'toplam R':>9s} {'PnL $':>12s} {'kazanma':>8s}")
    g = d.groupby("coin").agg(n=("R", "size"), ortR=("R", "mean"),
                              topR=("R", "sum"), pnl=("pnl_usdt", "sum"),
                              wr=("R", lambda x: (x > 0).mean() * 100))
    for c, r in g.sort_values("ortR").iterrows():
        print(f"  {c:<6s} {int(r.n):>5d} {r.ortR:>+8.4f} {r.topR:>+9.1f} {r.pnl:>+12,.0f} %{r.wr:>6.1f}")
    return g


def main():
    yol = sys.argv[1] if len(sys.argv) > 1 else "ikiz_tam_islemler.csv"
    d = yukle(yol)
    print(f"\n{'='*82}\n=== COİN ANALİZİ · {len(d)} işlem · "
          f"{d.giris.min().date()} → {d.cikis.max().date()} ===")

    tr = d[d.giris < SPLIT]; te = d[d.giris >= SPLIT]
    print(f"  TRAIN (seçim burada): {len(tr)} işlem · TEST (karar burada): {len(te)} işlem")

    g_tr = tablo(tr, "TRAIN 2023-04 → 2024-12  ← SEÇİM YALNIZ BURADAN")
    g_te = tablo(te, "TEST 2025-01 → 2026-07  ← KARAR YALNIZ BURADAN")

    print(f"\n{'='*82}\n=== KARAR: TRAIN'de kötü olanları atsaydık TEST'te ne olurdu? ===")
    taban_te = te.R.mean(); taban_pnl = te.pnl_usdt.sum()
    print(f"  TEST tabanı: {len(te)} işlem · ort R {taban_te:+.4f} · PnL ${taban_pnl:+,.0f}")
    print(f"\n  {'kural':<34s} {'atılan coin':>28s} {'TEST n':>7s} {'TEST ortR':>10s} {'ΔortR':>8s} {'ΔPnL $':>11s}")
    for esik in (0.0, 0.05, 0.10):
        kotu = set(g_tr[g_tr.ortR < esik].index)
        if not kotu: continue
        kalan = te[~te.coin.isin(kotu)]
        if not len(kalan): continue
        d_r = kalan.R.mean() - taban_te
        d_p = kalan.pnl_usdt.sum() - taban_pnl
        ad = ",".join(sorted(kotu))
        print(f"  {'TRAIN ort R < ' + f'{esik:.2f}':<34s} {ad[:28]:>28s} {len(kalan):>7d} "
              f"{kalan.R.mean():>+10.4f} {d_r:>+8.4f} {d_p:>+11,.0f}")
    print(f"\n  ⚠ ΔortR pozitifse fikir YAŞIYOR; negatifse TRAIN'deki kötülük GÜRÜLTÜYDÜ.")
    print(f"{'='*82}\n")


if __name__ == "__main__":
    main()
