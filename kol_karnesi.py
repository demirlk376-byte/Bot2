"""
kol_karnesi.py — CANLI KOL KARNESİ (YALNIZ OKUR: trades.db salt-okunur açılır, emir/ayar yok).

Her kol (strateji) için canlı kapanmış işlemlerden:
  n, kazanma oranı, toplam net USDT, ortalama net R (ücret+funding dahil, ilk stopa göre)
  ve ortalama R'nin %95 önyükleme güven aralığı; tüm dönem ve son 60 gün ayrı.
Hüküm (önceden sabit, yalnız bilgi amaçlı — kol kapatma kararı DEĞİL):
  n < 20                    → "KANIT YETERSİZ"
  güven aralığı üstü < 0    → "ZARAR ŞÜPHESİ (anlamlı)"
  güven aralığı altı > 0    → "KÂRLI (anlamlı)"
  aksi                      → "BELİRSİZ"
Ayrıca kolun şu anki .env ayarıyla ETKİN olup olmadığı yazılır (SYMBOLS listelerine göre).

Kullanım (VPS):  cd /opt/bot2 && venv/bin/python kol_karnesi.py [trades.db yolu]
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import erken_uyari as EU  # noqa: E402  (kol_adi, r_net, islemleri_oku — botun kanonik tanımları)

SON_GUN = 60
TOHUM = 20261004


def _guven(rs):
    if len(rs) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(TOHUM)
    a = np.asarray(rs, float)
    ort = [rng.choice(a, len(a)).mean() for _ in range(5000)]
    return float(np.percentile(ort, 2.5)), float(np.percentile(ort, 97.5))


def _hukum(n, lo, hi):
    if n < 20:
        return "KANIT YETERSİZ"
    if hi < 0:
        return "ZARAR ŞÜPHESİ (anlamlı)"
    if lo > 0:
        return "KÂRLI (anlamlı)"
    return "BELİRSİZ"


def _ozet(islemler):
    rs = [r for r in (EU.r_net(t) for t in islemler) if r is not None]
    usd = sum(t["pnl_usdt"] for t in islemler)
    kaz = sum(1 for t in islemler if t["pnl_usdt"] > 0)
    lo, hi = _guven(rs)
    return dict(n=len(islemler), wr=kaz / len(islemler) * 100 if islemler else 0.0, usd=usd,
                r=float(np.mean(rs)) if rs else float("nan"), lo=lo, hi=hi, hukum=_hukum(len(rs), lo, hi))


def _etkin_kollar():
    """.env'deki sembol listelerinden hangi kolların açık olduğu (yalnız bilgi)."""
    try:
        import config  # noqa: F401  (.env'i ortam değişkenlerine yükler; başka bir şey yapmaz)
    except Exception:
        return {}
    e = os.environ
    d = {"donchian": e.get("DONCHIAN_SYMBOLS", ""), "squeeze": e.get("SQUEEZE_SYMBOLS", ""),
         "mean_rev": e.get("BB_SYMBOLS", ""), "sr_breakout": e.get("SR_BREAKOUT_SYMBOLS", ""),
         "ifvg": e.get("IFVG_SYMBOLS", ""), "trend_kolu": e.get("TREND_MODE", "kapali")}
    return d


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db")
    islemler = EU.islemleri_oku(db, paper=False)
    if not islemler:
        print("Canlı kapanmış işlem yok.")
        return
    kollar = defaultdict(list)
    for t in islemler:
        kollar[EU.kol_adi(t.get("strategy_scores"))].append(t)
    son_t = max(t["exit_time"] for t in islemler)
    sinir = (datetime.fromisoformat(son_t.replace("Z", "+00:00")) - timedelta(days=SON_GUN)).isoformat()
    etkin = _etkin_kollar()
    print("=" * 96)
    print(f"  CANLI KOL KARNESİ — {len(islemler)} kapanmış işlem, {islemler[0]['entry_time'][:10]} → {son_t[:10]}")
    print("  (R = net sonuç / ilk stop riski; ücret+funding dahil. Güven aralığı: %95 önyükleme.)")
    print("=" * 96)
    bas = f"{'kol':<13}{'n':>4}{'kaz%':>6}{'net USDT':>10}{'ort R':>8}{'%95 aralık':>18}  {'hüküm':<24}| son {SON_GUN}g: n  ort R   USDT"
    print(bas)
    print("-" * len(bas))
    for kol, ts in sorted(kollar.items(), key=lambda kv: -sum(t["pnl_usdt"] for t in kv[1])):
        a = _ozet(ts)
        son = [t for t in ts if t["exit_time"] >= sinir]
        b = _ozet(son) if son else dict(n=0, r=float("nan"), usd=0.0)
        aralik = f"[{a['lo']:+.2f}, {a['hi']:+.2f}]" if np.isfinite(a["lo"]) else "—"
        print(f"{kol:<13}{a['n']:>4}{a['wr']:>6.0f}{a['usd']:>10.2f}{a['r']:>+8.2f}{aralik:>18}  {a['hukum']:<24}|"
              f" {b['n']:>4} {b['r']:>+6.2f} {b['usd']:>7.2f}")
    a = _ozet(islemler)
    print("-" * len(bas))
    print(f"{'TOPLAM':<13}{a['n']:>4}{a['wr']:>6.0f}{a['usd']:>10.2f}{a['r']:>+8.2f}")
    if etkin:
        print("\nŞu anki .env ayarı (kolların coin listeleri):")
        for k, v in etkin.items():
            print(f"  {k:<12} {v or '— (kapalı/boş)'}")
    print("\nNot: hüküm yalnız bilgi amaçlıdır. Az işlemde ortalama R gürültülüdür; bir kolu kapatma kararı"
          " ikiz/araştırma ile birlikte verilmelidir.")


if __name__ == "__main__":
    main()
