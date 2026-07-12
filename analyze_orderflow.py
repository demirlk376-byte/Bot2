"""
analyze_orderflow.py — orderflow kolektörünün İLERİ VERİSİ ile sinyal kalitesi.

Soru: sinyal anında taker akışı / derinlik dengesi sinyalle AYNI yöndeyken
trade'ler daha mı iyi? (Cevap evet ise "sniper filtresi" adayı doğar.)

Neden değerli: orderflow_log.csv İLERİYE DÖNÜK toplandı — geçmişe uydurulamaz.
Backtest'in aksine bu verideki her ilişki gerçektir (örneklem yeterliyse).

Yöntem: orderflow_log.csv satırları (sinyal anı) trades.db'deki canlı
trade'lerle sembol + zaman yakınlığı (±15 dk) üzerinden eşleştirilir; sonuçlar
flow_aligned (kolektörün kendi bayrağı) ve tekil özellik kovalarına bölünür.

ÖN-KAYITLI KARAR KURALI (test-tuning yok):
  Filtre canlıya ancak şu üçü BİRDEN sağlanırsa girer:
    1. n_aligned ve n_contrary her ikisi >= 40
    2. aligned PF - contrary PF >= 0.30 (anlamlı fark)
    3. Kural, veri 2x büyüdüğünde (sonraki kontrol) yönünü korur
  Bugünkü koşu n~50 ile SADECE KEŞİF — karar 4 haftalık değerlendirmede.

Kullanım (VPS):  cd /opt/bot2 && venv/bin/python analyze_orderflow.py
"""
from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

OF_CSV = Path(os.getenv("ORDERFLOW_CSV", "orderflow_log.csv"))
DB     = os.getenv("DB_PATH", "./trades.db")
MATCH_TOL = timedelta(minutes=15)


def _t(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pf(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    return gp / gl if gl > 0 else float("inf") if gp > 0 else 0.0


def _row(label: str, pnls: list[float]) -> str:
    if not pnls:
        return f"  {label:<26s}   n=0"
    wr = sum(1 for p in pnls if p > 0) / len(pnls)
    pf = _pf(pnls)
    pf_s = f"{pf:5.2f}" if pf != float("inf") else "  inf"
    return (f"  {label:<26s}   n={len(pnls):<3d} WR={wr:4.0%}  PF={pf_s}  "
            f"net={sum(pnls):+7.2f}")


def main() -> None:
    if not OF_CSV.exists():
        print(f"{OF_CSV} yok — kolektör henüz veri yazmamış.")
        return
    with open(OF_CSV) as f:
        sigs = list(csv.DictReader(f))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    trades = con.execute(
        "SELECT symbol, side, entry_time, pnl_usdt FROM trades "
        "WHERE is_paper=0 AND exit_time IS NOT NULL AND exit_time!=''"
    ).fetchall()
    tparsed = [(r["symbol"], r["side"], _t(r["entry_time"]), r["pnl_usdt"] or 0.0)
               for r in trades]

    matched, unmatched = [], 0
    used = set()
    for s in sigs:
        st = _t(s.get("ts", ""))
        if st is None:
            continue
        want_side = "long" if str(s.get("direction", "")).strip() in ("1", "+1") else "short"
        best = None
        for i, (sym, side, et, pnl) in enumerate(tparsed):
            if i in used or et is None or sym != s.get("symbol") or side != want_side:
                continue
            dt = abs(et - st)
            if dt <= MATCH_TOL and (best is None or dt < best[0]):
                best = (dt, i, pnl)
        if best is None:
            unmatched += 1
            continue
        used.add(best[1])
        matched.append((s, best[2]))

    print("=" * 72)
    print("  ORDERFLOW → TRADE SONUCU (ileri veri; KEŞİF modu, karar değil)")
    print("=" * 72)
    print(f"  sinyal: {len(sigs)}  |  trade ile eşleşen: {len(matched)}  |  "
          f"eşleşmeyen (atlanmış/paper): {unmatched}")

    if not matched:
        print("  Eşleşme yok — canlı trade penceresiyle log penceresi kesişmiyor.")
        return

    def bucket(pred, label_t, label_f):
        yes = [p for s, p in matched if pred(s)]
        no  = [p for s, p in matched if not pred(s)]
        print(_row(label_t, yes))
        print(_row(label_f, no))

    print("\n  [kolektörün kendi bayrağı]")
    bucket(lambda s: str(s.get("flow_aligned", "0")).strip() == "1",
           "flow_aligned = 1", "flow_aligned = 0")

    print("\n  [taker delta yönü sinyalle aynı mı]  (long→delta>0, short→delta<0)")
    def delta_agree(s):
        try:
            d = float(s.get("delta", 0) or 0)
        except ValueError:
            return False
        want_long = str(s.get("direction", "")).strip() in ("1", "+1")
        return d > 0 if want_long else d < 0
    bucket(delta_agree, "delta uyumlu", "delta ters")

    print("\n  [derinlik dengesizliği yönü]  (long→imb>0, short→imb<0)")
    def depth_agree(s):
        try:
            di = float(s.get("depth_imbalance", 0) or 0)
        except ValueError:
            return False
        want_long = str(s.get("direction", "")).strip() in ("1", "+1")
        return di > 0 if want_long else di < 0
    bucket(depth_agree, "derinlik uyumlu", "derinlik ters")

    print("\n" + "-" * 72)
    print("  ÖN-KAYITLI KURAL: filtre canlıya ancak şunlarla girer —")
    print("    n>=40/40 + PF farkı >=0.30 + veri 2x'te yön korunuyor.")
    print("  Bugünkü örneklem küçükse çıkan fark HİPOTEZ'dir, karar değil.")
    print("-" * 72)


if __name__ == "__main__":
    main()
