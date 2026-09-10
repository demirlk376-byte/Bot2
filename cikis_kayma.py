"""
cikis_kayma.py — ÇIKIŞ KAYMASINI GERÇEK DOLUMDAN ÖLÇ (VPS'te koşar).

NEDEN: 2026-09-10'da sürtünme dökümü çıkarıldı ve kârın %46'sı sürtünmeye
gidiyor. Ama tablodaki tek ÖLÇÜLMÜŞ kalem giriş kayması (15.85bp, n=54).
Çıkış kalemi ($302/3.24 yıl) donchian GİRİŞ ölçümünden **ödünç alınmış bir
varsayım**. Süre çıkışlarını limite çevirme fikri de o varsayıma dayanıyordu.
Ölçmeden kod değiştirmek, bu depoda sekiz kez yakalanan hatanın aynısıdır.

YÖNTEM: kaydedilen GERÇEK çıkış fiyatını HEDEFLENEN seviyeyle karşılaştır.
  SL çıkışı  → hedef `sl_price` (stop-market seviyenin ÖTESİNDE dolar)
  TP çıkışı  → hedef `tp_price` (LİMİT emir; kayma ~0 ÇIKMALI)
  süre/diğer → referans seviye YOK, ayrıca raporlanır

⚠ TP SATIRI BU ÖLÇÜMÜN KENDİ DENETİMİDİR. TP limit emirdir ve kaymamalıdır.
   TP'de kayda değer kayma çıkıyorsa ölçüm YANLIŞTIR, bulgu değil.

⚠ `exit_price_estimated` İŞARETLİ İŞLEMLER DIŞLANIR. Onlarda çıkış fiyatı
   zaten SL/TP seviyesinden yazıldı; seviyeyle karşılaştırmak tanım gereği
   sıfır verir ve ölçümü DAİRESEL yapar.

İşaret kuralı: kayma = yon × (seviye − dolum) / seviye,  POZİTİF = ALEYHİMİZE.

Kullanım (VPS'te):  cd /opt/bot2 && python3 cikis_kayma.py
"""
import json
import os
import sqlite3
import sys

import numpy as np

DB = os.environ.get("DB_PATH", "trades.db")
MIN_N = 8


def yon_of(side):
    s = str(side).lower()
    if s in ("buy", "long", "1", "+1"): return 1
    if s in ("sell", "short", "-1"): return -1
    return 0


def main():
    if not os.path.exists(DB):
        print(f"✗ {DB} bulunamadı. VPS'te /opt/bot2 içinde koşun.")
        sys.exit(2)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT symbol, side, entry_price, exit_price, sl_price, tp_price, "
            "exit_reason, strategy_scores, exit_time, is_paper "
            "FROM trades WHERE exit_price IS NOT NULL AND is_paper = 0"
        ).fetchall()
    except sqlite3.Error as e:
        print(f"✗ trades okunamadı: {e}")
        sys.exit(2)
    if not rows:
        print("✗ kapanmış canlı işlem yok.")
        sys.exit(2)

    kova = {}
    tahmini = 0
    atlanan = 0
    for r in rows:
        try:
            sc = json.loads(r["strategy_scores"] or "{}")
        except (json.JSONDecodeError, TypeError):
            sc = {}
        if sc.get("exit_price_estimated"):
            tahmini += 1
            continue                      # DAİRESEL olurdu
        yon = yon_of(r["side"])
        sebep = (r["exit_reason"] or "bilinmiyor").lower()
        seviye = r["sl_price"] if "sl" in sebep or "stop" in sebep else (
            r["tp_price"] if "tp" in sebep or "profit" in sebep else None)
        if yon == 0 or seviye is None or not seviye or not r["exit_price"]:
            atlanan += 1
            kova.setdefault(sebep, {"n": 0, "bp": [], "R": []})["n"] += 1
            continue
        slip = yon * (seviye - r["exit_price"]) / seviye
        sld = abs(r["entry_price"] - r["sl_price"])
        k = kova.setdefault(sebep, {"n": 0, "bp": [], "R": []})
        k["n"] += 1
        k["bp"].append(slip * 1e4)
        if sld > 0:
            k["R"].append(slip * r["exit_price"] / sld)

    print(f"\n{'=' * 84}")
    print(f"=== ÇIKIŞ KAYMASI — gerçek dolum vs hedeflenen seviye ===")
    print(f"  {len(rows)} kapanmış canlı işlem · {tahmini} tanesi 'tahmini çıkış' "
          f"diye DIŞLANDI (dairesel olurdu)")
    print(f"  işaret: POZİTİF = aleyhimize\n")
    print(f"  {'çıkış':<14s} {'n':>4s} {'ort bp':>9s} {'medyan':>9s} "
          f"{'%95 aralık (bp)':>20s} {'ort R':>9s}")
    olculdu = {}
    for sebep, k in sorted(kova.items(), key=lambda x: -x[1]["n"]):
        if not k["bp"]:
            print(f"  {sebep:<14s} {k['n']:>4d} {'—':>9s} {'—':>9s} "
                  f"{'referans seviye yok':>20s} {'—':>9s}")
            continue
        b = np.array(k["bp"])
        se = b.std(ddof=1) / np.sqrt(len(b)) if len(b) > 1 else float("nan")
        ar = f"[{b.mean()-1.96*se:+.1f}, {b.mean()+1.96*se:+.1f}]" if len(b) > 1 else "n<2"
        rr = np.mean(k["R"]) if k["R"] else float("nan")
        print(f"  {sebep:<14s} {len(b):>4d} {b.mean():>+9.2f} {np.median(b):>+9.2f} "
              f"{ar:>20s} {rr:>+9.4f}")
        olculdu[sebep] = (b, rr)

    # ── ÖZ-DENETİM ──
    print(f"\n  {'—' * 76}\n  ÖZ-DENETİM (bulguyu okumadan ÖNCE)")
    tp = next((v for k, v in olculdu.items() if "tp" in k or "profit" in k), None)
    if tp is None:
        print(f"    ⚠ TP çıkışı yok — ölçümün kendi kontrolü YAPILAMADI.")
        print(f"       Sonuçlara temkinli yaklaşın.")
    else:
        b = tp[0]
        if len(b) < MIN_N:
            print(f"    ⚠ TP n={len(b)} < {MIN_N} — kontrol zayıf.")
        elif abs(b.mean()) > 5.0:
            print(f"    ✗ TP kayması {b.mean():+.2f}bp — LİMİT emir kaymamalıydı.")
            print(f"       ÖLÇÜM YANLIŞ. Sonuçları KULLANMAYIN, önce sebebini bulun.")
            sys.exit(2)
        else:
            print(f"    ✓ TP kayması {b.mean():+.2f}bp (limit emir, ~0 bekleniyordu) → ölçüm tutarlı")

    sl = next((v for k, v in olculdu.items() if "sl" in k or "stop" in k), None)
    if sl is not None and len(sl[0]) >= MIN_N:
        b = sl[0]
        print(f"\n  SONUÇ: SL çıkış kayması {b.mean():+.2f}bp (n={len(b)}), "
              f"R cinsinden {sl[1]:+.4f}")
        print(f"    Giriş kayması ölçümü 15.85bp idi. Oran: {b.mean()/15.85:.2f}x")
        print(f"    → 1'e yakınsa sürtünme tablosundaki varsayım TUTUYOR.")
        print(f"    → çok küçükse çıkış kalemi ŞİŞİRİLMİŞ, süre-limit fikri değersiz.")
    else:
        n = len(sl[0]) if sl else 0
        print(f"\n  ⚠ SL çıkışı n={n} < {MIN_N}. HÜKÜM YOK — daha çok işlem gerek.")
    print(f"{'=' * 84}\n")


if __name__ == "__main__":
    main()
