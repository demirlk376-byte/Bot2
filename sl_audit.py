"""
sl_audit.py — ÖZ-DENETİMLİ execution denetimi. Aracın kendisini de doğrular.

Her kapanmış SL/TP işlemi için fiyat yolundan "önce hangi seviye geldi"yi
(first_tp_bar vs first_sl_bar) yeniden kurar ve botun kaydettiği exit_reason ile
KARŞILAŞTIRIR:
  • tp_hit işleminde araç 'tp önce' demeli, sl_hit'te 'sl önce' demeli.
  • UYUŞMA → hem araç doğru (tp_hit'leri de doğru okuyor) hem execution temiz.
  • UYUŞMAZLIK → araç mı bozuk (zaman hizası/çözünürlük) yoksa execution bug mı
    (TP önce geldi ama SL kapandı / tersi) — incele.

Bu ikili kontrol, aracın "0 bug" demesine körü körüne güvenmeyi engeller.

Kullanım:  python3 sl_audit.py /opt/bot2/trades.db
(data/{COIN}_fut_1h.csv fiyat cache'i gerekir — ~/Bot2'de.)
"""
import sys, sqlite3, json
import pandas as pd, numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "trades.db"
_cache = {}


def price(coin):
    if coin not in _cache:
        _cache[coin] = pd.read_csv(f"data/{coin}_fut_1h.csv", index_col=0, parse_dates=True)
    return _cache[coin]


def first_touch(seg, entry, sl, tp, long):
    """(first_sl_bar, first_tp_bar) — fiyatın seviyelere İLK ulaştığı bar indeksi."""
    if long:
        tp_hit = np.where(seg["high"].values >= tp)[0]
        sl_hit = np.where(seg["low"].values <= sl)[0]
    else:
        tp_hit = np.where(seg["low"].values <= tp)[0]
        sl_hit = np.where(seg["high"].values >= sl)[0]
    return (sl_hit[0] if len(sl_hit) else None, tp_hit[0] if len(tp_hit) else None)


def main():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT symbol, side, entry_price, sl_price, tp_price, exit_price, "
        "entry_time, exit_time, pnl_usdt, exit_reason, strategy_scores FROM trades "
        "WHERE exit_reason IN ('sl','sl_hit','stop_loss','tp','tp_hit','take_profit') "
        "AND exit_time IS NOT NULL"
    ).fetchall()
    print(f"{DB}: {len(rows)} SL/TP işlemi — ÖZ-DENETİM (araç ↔ bot uyuşuyor mu?)\n")
    agree = 0; disagree = []; nodata = 0; neither = 0
    for r in rows:
        coin = r["symbol"].split("/")[0]
        try:
            d = price(coin)
        except Exception:
            nodata += 1; continue
        e0 = pd.to_datetime(r["entry_time"]); e1 = pd.to_datetime(r["exit_time"])
        seg = d[(d.index >= e0) & (d.index <= e1)]
        if len(seg) == 0:
            nodata += 1; continue
        entry = r["entry_price"]; sl = r["sl_price"]; tp = r["tp_price"]
        if abs(entry - sl) <= 0:
            nodata += 1; continue
        long = str(r["side"]).lower() in ("long", "buy")
        sl_bar, tp_bar = first_touch(seg, entry, sl, tp, long)
        if sl_bar is None and tp_bar is None:
            predicted = "neither"      # ne SL ne TP — muhtemelen max_hold penceresi/veri boşluğu
        elif tp_bar is None:
            predicted = "sl"
        elif sl_bar is None:
            predicted = "tp"
        else:
            predicted = "tp" if tp_bar < sl_bar else "sl"
        recorded = "tp" if "tp" in r["exit_reason"] or "take" in r["exit_reason"] else "sl"
        strat = ""
        try: strat = json.loads(r["strategy_scores"] or "{}").get("strategy", "")
        except Exception: pass
        if predicted == "neither":
            neither += 1
            # kayıtlı SL/TP ama fiyat cache'te seviyeye değmedi → hizalama/çözünürlük şüphesi
            disagree.append((coin, strat, r["side"], recorded, predicted, sl_bar, tp_bar, r["pnl_usdt"]))
        elif predicted == recorded:
            agree += 1
        else:
            disagree.append((coin, strat, r["side"], recorded, predicted, sl_bar, tp_bar, r["pnl_usdt"]))
    print(f"✅ UYUŞMA (araç = bot; hem araç doğru hem execution temiz): {agree}/{len(rows)-nodata}")
    print(f"⚠️  UYUŞMAZLIK / belirsiz:                                  {len(disagree)}")
    print(f"veri yok (cache eksik):                                    {nodata}\n")
    if disagree:
        print("=== UYUŞMAZLIKLAR (araç mı execution mı — incele) ===")
        for coin, strat, side, rec, pred, sb, tb, pnl in disagree:
            print(f"  {coin:5s} {strat:9s} {side:5s}  bot={rec}  araç={pred}  "
                  f"(SL bar{sb} / TP bar{tb})  pnl{pnl:+.1f}")
        print("\n  bot=tp/araç=sl ya da tersi → gerçek execution ya da araç-hizası sorunu.")
        print("  'neither' → fiyat cache'te seviyeye hiç değmemiş: zaman hizası (entry mum-içi)")
        print("  ya da çözünürlük (1h) meselesi olabilir; o işlemleri elle bakarız.")
    else:
        print("✅ TAM UYUŞMA — araç botun HER SL ve TP kararını fiyat yolundan doğru")
        print("   yeniden üretti. Yani: (1) araç güvenilir, (2) execution temiz. İkisi de OK.")


if __name__ == "__main__":
    main()
