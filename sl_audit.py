"""
sl_audit.py — SL işlemlerini denetle: TP mi önce geldi SL mi? (execution bug var mı)

Her kapanmış SL işlemi için:
  • rr = |tp-entry|/|entry-sl|  (tasarlanan RR)
  • fiyat cache'inden giriş→çıkış barlarını tara:
      first_tp_bar = fiyatın TP seviyesine İLK ulaştığı bar
      first_sl_bar = fiyatın SL seviyesine İLK ulaştığı bar
  • Eğer first_tp_bar < first_sl_bar  → TP ÖNCE geldi ama işlem SL kapandı
      = GERÇEK BUG (kaçırılmış TP fill'i). İncele.
  • first_tp_bar >= first_sl_bar (ya da TP hiç gelmedi) → SL önce/aynı mum → NORMAL.

Kullanım:
  python3 sl_audit.py /opt/bot2/trades.db          # canlı bot DB
  python3 sl_audit.py /opt/bot2-paper/trades.db     # paper bot DB
(data/{COIN}_fut_1h.csv fiyat cache'i gerekir — ~/Bot2'de var.)
"""
import sys, sqlite3, json
import pandas as pd, numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "trades.db"
_cache = {}


def price(coin):
    if coin not in _cache:
        _cache[coin] = pd.read_csv(f"data/{coin}_fut_1h.csv", index_col=0, parse_dates=True)
    return _cache[coin]


def main():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT symbol, side, entry_price, sl_price, tp_price, exit_price, "
        "entry_time, exit_time, pnl_usdt, strategy_scores FROM trades "
        "WHERE exit_reason='sl' AND exit_time IS NOT NULL"
    ).fetchall()
    print(f"{DB}: {len(rows)} SL işlemi denetleniyor\n")
    flagged = []; normal = 0; nodata = 0
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
        rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        strat = ""
        try: strat = json.loads(r["strategy_scores"] or "{}").get("strategy", "")
        except Exception: pass
        long = str(r["side"]).lower() in ("long", "buy")
        # ilk TP-barı ve ilk SL-barı
        if long:
            tp_hit = np.where(seg["high"].values >= tp)[0]
            sl_hit = np.where(seg["low"].values <= sl)[0]
        else:
            tp_hit = np.where(seg["low"].values <= tp)[0]
            sl_hit = np.where(seg["high"].values >= sl)[0]
        tp_bar = tp_hit[0] if len(tp_hit) else None
        sl_bar = sl_hit[0] if len(sl_hit) else None
        if tp_bar is not None and (sl_bar is None or tp_bar < sl_bar):
            flagged.append((coin, strat, r["side"], rr, tp_bar, sl_bar, r["pnl_usdt"]))
        else:
            normal += 1
    print(f"NORMAL (SL önce/aynı mum, doğru):        {normal}")
    print(f"⚠️  BUG ŞÜPHESİ (TP önce geldi, SL kapandı): {len(flagged)}")
    print(f"veri yok (cache eksik):                   {nodata}\n")
    if flagged:
        print("=== TP ÖNCE GELDİ AMA SL KAPANDI (incele) ===")
        for coin, strat, side, rr, tb, sb, pnl in flagged:
            sbtxt = "hiç" if sb is None else f"bar{sb}"
            print(f"  {coin:5s} {strat:9s} {side:5s} rr{rr:.1f}  TP bar{tb} < SL {sbtxt}  pnl{pnl:+.1f}")
        print("\n  Bunlarda TP limit emri fill olmalıydı ama SL kapandı → execution/fill")
        print("  mantığında sorun olabilir. sleeve + rr'ye bak; canlı fill kodunu inceleriz.")
    else:
        print("✅ Hiç kaçırılmış TP yok — tüm SL'ler doğru (TP gerçekten gelmedi ya da")
        print("   SL aynı mumda önce geldi). Execution temiz; SL'ler tasarım gereği.")


if __name__ == "__main__":
    main()
