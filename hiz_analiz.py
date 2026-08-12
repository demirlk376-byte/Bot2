"""
hiz_analiz.py — İŞLEM HIZI AÇIĞI: neden ankordan az işlem alıyoruz?

live_verify: canlı 0.8 işlem/gün, ankor 1.3/gün. 53 günde 41 işlem, beklenen ~69.
Poisson'a göre z≈-3.4 — şans değil, gerçek bir açık.

⚠️ ÖNCE ELENEN AÇIKLAMA: "tek-pozisyon kuralı" (execution.py:405, bir coinde pozisyon
açıkken yeni sinyal alınmıyor). ANKOR AYNI KURALI UYGULUYOR (deployed_backtest.py:64
`i <= occ` + satır 78 `occ = j`). Dolayısıyla sebep bu DEĞİL. Canlı loglardaki
"already holds a position" redlerinin çokluğu bir kayıp değil, botun her tarama
turunda aynı ısrarcı sinyali yeniden loglamasıdır (ankor bar başına bir kez bakar).

ASIL ŞÜPHE — TUTMA SÜRESİ: tek-pozisyon kuralı ikisinde de varsa, işlem hızını
belirleyen şey pozisyonun coini NE KADAR BLOKE ETTİĞİDİR. Canlı tutma süresi
ankorunkinden uzunsa, coin daha uzun kapalı kalır ve hız düşer. Bu ölçülebilir.

ANKOR REFERANSLARI (deployed_backtest local, 1579 işlem / 1187 gün — bu betikte
hesaplanmadı, ayrıca ölçülüp buraya yazıldı):
    kol         n     işlem/gün   ort tutma(gün)   medyan
    donchian  1008      0.849         2.65          2.17
    squeeze    410      0.345         0.87          0.67
    bb         161      0.136         1.09          1.04
    TOPLAM    1579      1.330         2.03          1.50

⚠️ TARİH PENCERESİ ŞART: defter, konfigürasyonun değiştiği eski dönemi de içeriyor
(BB bir ara çok coinde çalışıyordu, kapalı kollar var). Karşılaştırma ancak MEVCUT
konfigürasyonun geçerli olduğu pencerede anlamlı. --since ile sınırlayın.

Kullanım (VPS'te):
    python3 hiz_analiz.py                  # tüm defter + son 30 gün ayrı ayrı
    python3 hiz_analiz.py 2026-07-20       # bu tarihten itibaren
"""
import math
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from live_verify import sleeve_of

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))

ANK = {                       # (işlem/gün, ort tutma gün, medyan tutma)
    "donchian": (0.849, 2.65, 2.17),
    "squeeze":  (0.345, 0.87, 0.67),
    "bb":       (0.136, 1.09, 1.04),
}
ANK_TOP = (1.330, 2.03, 1.50)


def _ts(s):
    if not s:
        return None
    t = str(s).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def oku(since=None):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, entry_time, exit_time, strategy_scores FROM trades"
        " WHERE is_paper=0 AND entry_time IS NOT NULL").fetchall()
    con.close()
    out = []
    for sym, et, xt, sc in rows:
        e = _ts(et)
        if e is None or (since and e < since):
            continue
        out.append((sleeve_of(sc), sym, e, _ts(xt)))
    return out


def rapor(kayit, etiket):
    if not kayit:
        print(f"\n  {etiket}: işlem yok.")
        return
    e0 = min(k[2] for k in kayit)
    e1 = max(k[2] for k in kayit)
    gun = max((e1 - e0).total_seconds() / 86400, 1.0)
    print(f"\n  ── {etiket} ──  {e0.date()} → {e1.date()}  ({gun:.0f} gün, "
          f"{len(kayit)} işlem)")
    print(f"    {'kol':<10s} {'n':>4s} {'işlem/gün':>10s} {'ankor':>7s} {'oran':>6s} "
          f"{'z':>6s} {'tutma(gün)':>11s} {'ankor':>7s} {'oran':>6s}")
    grp = defaultdict(list)
    for k, sym, e, x in kayit:
        grp[k].append((e, x))
    top_n = 0
    for kol in ("donchian", "squeeze", "bb"):
        v = grp.get(kol, [])
        n = len(v); top_n += n
        hiz = n / gun
        a_hiz, a_tut, _ = ANK[kol]
        bek = a_hiz * gun
        z = (n - bek) / math.sqrt(bek) if bek > 0 else 0.0
        kapali = [(x - e).total_seconds() / 86400 for e, x in v if x]
        tut = sum(kapali) / len(kapali) if kapali else float("nan")
        bayrak = ""
        if abs(z) > 2:
            bayrak = "  ⚠" if z < 0 else "  ↑"
        print(f"    {kol:<10s} {n:>4d} {hiz:>10.3f} {a_hiz:>7.3f} "
              f"{hiz/a_hiz:>6.2f} {z:>+6.1f} "
              f"{tut:>11.2f} {a_tut:>7.2f} "
              f"{(tut/a_tut if a_tut and tut == tut else float('nan')):>6.2f}{bayrak}")
    diger = len(kayit) - top_n
    if diger:
        print(f"    {'(diğer)':<10s} {diger:>4d}   ← kapalı/eski kollar, ankorda YOK")
    hiz = top_n / gun
    bek = ANK_TOP[0] * gun
    z = (top_n - bek) / math.sqrt(bek) if bek > 0 else 0.0
    print(f"    {'AKTİF 3':<10s} {top_n:>4d} {hiz:>10.3f} {ANK_TOP[0]:>7.3f} "
          f"{hiz/ANK_TOP[0]:>6.2f} {z:>+6.1f}")


def main():
    if not os.path.exists(DB):
        print(f"trades.db bulunamadı: {DB}")
        return
    print(f"\n{'=' * 96}")
    print("=== İŞLEM HIZI AÇIĞI — canlı vs ankor, kol bazında ===")
    print("  Tek-pozisyon kuralı ikisinde de var → sebep O DEĞİL.")
    print("  Asıl şüphe: canlı tutma süresi uzunsa coin daha uzun bloke kalır, hız düşer.")

    tum = oku()
    rapor(tum, "TÜM DEFTER (⚠ eski konfigürasyon dönemi dahil — kirli)")

    if len(sys.argv) > 1:
        try:
            since = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=timezone.utc)
            rapor(oku(since), f"{sys.argv[1]}'DEN İTİBAREN")
        except ValueError:
            print(f"\n  tarih okunamadı: {sys.argv[1]} (YYYY-MM-DD bekleniyor)")
    else:
        son = datetime.now(timezone.utc) - timedelta(days=30)
        rapor(oku(son), "SON 30 GÜN (mevcut konfigürasyona daha yakın)")

    print(f"\n{'=' * 96}\n=== NASIL OKUNUR ===")
    print("  · 'oran' 1.00 ise ankor hızındayız. 0.40 ise ankorun %40'ı kadar işlem alıyoruz.")
    print("  · 'z' Poisson sapması: |z|>2 ise fark şansla açıklanamaz.")
    print("  · TUTMA 'oran'ı 1'den BÜYÜKse pozisyonlar ankordan UZUN duruyor demektir →")
    print("    coin daha uzun bloke → hız düşer. AÇIĞIN SEBEBİ BU OLABİLİR.")
    print("  · Tutma oranı ~1 ama hız düşükse sebep başka: sinyal üretimi (tarama aralığı,")
    print("    bar kapanışını kaçırma) ya da girişte reddedilme (marjin, halt).")
    print("  · '(diğer)' satırı kapalı kollardan gelen işlemler — ankorda karşılığı yok,")
    print("    hız karşılaştırmasına KATILMAZ.")


if __name__ == "__main__":
    main()
