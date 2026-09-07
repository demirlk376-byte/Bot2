"""
cikis_dagilim.py — temiz dönemde çıkışlar hangi yoldan oldu?

NEDEN: uyum_testi.py'de en büyük 5 sapmanın DÖRDÜ `external_close` çıktı —
SL'e de TP'ye de varmadan ERKEN kapanmış pozisyonlar. Tasarlanmış bir çıkış
yolu DEĞİL. Toplamda zarar ettirmemiş (z=−0.24) ama açıklanmamış bir
mekanizma; kaç tane olduğunu ve ne kadar tuttuğunu görmek gerekiyor.

sqlite3 komutu VPS'te yok, o yüzden python ile.

Kullanım:  venv/bin/python cikis_dagilim.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)


def main():
    from config import load_config
    cfg = load_config()
    con = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=15)
    cut = con.execute("SELECT value FROM meta WHERE key='temiz_cut'").fetchone()
    cut = str(cut[0]) if cut else "0000-00-00"

    print("=" * 62)
    print(f"ÇIKIŞ DAĞILIMI — temiz dönem ({cut} sonrası)")
    print("=" * 62)
    rows = con.execute(
        "SELECT COALESCE(exit_reason,'(boş)'), COUNT(*), "
        "ROUND(SUM(COALESCE(pnl_usdt,0)),2), ROUND(AVG(COALESCE(pnl_usdt,0)),2) "
        "FROM trades WHERE is_paper=0 AND exit_time IS NOT NULL "
        "AND entry_time>=? GROUP BY 1 ORDER BY 2 DESC", (cut,)).fetchall()
    if not rows:
        print("  kapanmış işlem yok")
        con.close(); return
    tn = sum(r[1] for r in rows); tp = sum(r[2] for r in rows)
    print(f"  {'çıkış yolu':<20s}{'adet':>6s}{'pay':>7s}{'toplam$':>10s}{'ort$':>8s}")
    for r in rows:
        print(f"  {r[0]:<20s}{r[1]:>6d}{r[1]/tn*100:>6.0f}%{r[2]:>10.2f}{r[3]:>8.2f}")
    print(f"  {'TOPLAM':<20s}{tn:>6d}{100:>6.0f}%{tp:>10.2f}")

    # external_close ayrı incelensin — asıl merak edilen o
    ex = [r for r in rows if "external" in r[0].lower()]
    if ex:
        n, s = ex[0][1], ex[0][2]
        print(f"\n  ⚠ external_close: {n} işlem (%{n/tn*100:.0f}) · ${s:+.2f}")
        print(f"     Bu, botun KENDİ kapatmadığı ama MEXC'te kapanmış bulduğu")
        print(f"     pozisyon demek. SL/TP'ye yakın değilse bu etiketi alıyor")
        print(f"     (main.py mutabakat yolu). Yani ne stop ne hedef — arada.")
        det = con.execute(
            "SELECT entry_time, symbol, side, ROUND(pnl_usdt,2) FROM trades "
            "WHERE is_paper=0 AND exit_reason LIKE '%external%' AND entry_time>=? "
            "ORDER BY entry_time", (cut,)).fetchall()
        print(f"\n     tarih            coin   yön     $")
        for d in det:
            print(f"     {str(d[0])[:16]}  {d[1].split('/')[0]:<5s} {d[2]:<5s} {d[3]:>7.2f}")
        print(f"\n     → Hepsi AYNI güne kümeleniyorsa: günlük zarar freni ya da")
        print(f"       elle kapatma. Dağınıksa: borsa tarafında emir/senkron sorunu.")
    con.close()


if __name__ == "__main__":
    main()
