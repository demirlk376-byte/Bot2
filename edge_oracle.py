"""
edge_oracle.py — MOTOR SAĞLAMLIK TESTİ: bu hat bir edge'i GÖREBİLİYOR MU?

NEDEN ZORUNLU: üç strateji de brüt edge ~0 verdi.
    sweep   −0.0103R (n=24.307)
    vwap    −0.0105R (n=29.991)
    squeeze −0.0026R (n=9.824)
Üç FARKLI strateji, üçü de tam sıfırda. İki açıklaması var:
  (a) Hiçbirinin edge'i yok — bu ölçekte piyasa etkin. (Beklenen sonuç.)
  (b) MOTOR her şeyi sıfıra düzlüyor. (Felaket; tüm hükümler geçersiz.)
İkisini ayırmadan hiçbir sonuca güvenilemez.

⚠ İLK LOOK-AHEAD TESTİM BOZUKTU. edge_sweep --lookahead-testi swing_k=0 yapıyordu
ve ben bunun "geleceği gösterdiğini" sanıyordum. Kodu okuyunca çıktı ki k=0'da
fractal penceresi TEK ELEMANA iniyor, fractal şartı anlamsızlaşıyor ve seviye
"son 40 barın en düşüğü"ne dönüşüyor — GELECEĞE HİÇ BAKMIYOR. Farklı bir seviye
tanımı, hile değil. Sonuç gerçek koldan KÖTÜ çıktı ve hiçbir şey kanıtlamadı.

BU DOSYA GERÇEK HİLEYİ YAPAR: geleceği DOĞRUDAN okur.
    kâhin(i) → i+1..i+max_hold aralığındaki barlara BAKAR ve TP'ye mi SL'e mi
    önce değeceğini bilerek yön seçer.
Bu, mümkün olan EN İYİ stratejidir. Motor doğruysa ort R ≈ +rr_hedef çıkmalı
(maliyet düşüldükten sonra). Sıfıra yakın çıkarsa motor bozuktur.

İKİNCİ KOL — KÖR KÂHİN: aynı kod ama geleceğe bakmadan rastgele yön seçer.
Beklenen: ~0 eksi maliyet. Bu, "her stratejinin sıfır vermesi normal mi" sorusunun
kontrol grubudur. Kâhin +2.5R, kör kâhin ~−0.3R veriyorsa hat SAĞLAMDIR:
edge varsa görüyor, yoksa görmüyor.

Kullanım:  python3 edge_oracle.py            (sentetik + gerçek veri)
           python3 edge_oracle.py SOL ETH
"""
from __future__ import annotations

import sys

import numpy as np

import edge_lab as EL
from edge_lab import Cfg, Sinyal


def varsayilan_cfg() -> Cfg:
    c = Cfg(tf_base="5m", tf_setup="15m", tf_regime="1h",
            swing_k=3, swing_lookback=40, atr_period=14,
            sl_atr=2.0, rr_min=1.4, max_hold_bar=96)
    c.ekstra = dict(rr_hedef=1.5, her_n_bar=20)
    return c


def _bracket(cl, a, yon, cfg):
    e = cl * (1 + yon * cfg.slip_bp / 1e4)
    sld = cfg.sl_atr * a
    return e, e - yon * sld, e + yon * cfg.ekstra["rr_hedef"] * sld


def kahin(i, veri, cfg, ctx):
    """⛔ GELECEĞE BAKAR. Yalnız motoru sınamak için."""
    if "atr" not in ctx:
        b = veri["base"]
        ctx["atr"] = EL.atr(b["high"].values, b["low"].values,
                            b["close"].values, cfg.atr_period)
    if i % cfg.ekstra["her_n_bar"]:
        return None
    b = veri["base"]
    hi = b["high"].values; lo = b["low"].values; cl = b["close"].values
    a = ctx["atr"][i]
    n = len(cl)
    if not np.isfinite(a) or a <= 0 or i + 2 >= n:
        return None
    for yon in (1, -1):
        e, sl, tp = _bracket(cl[i], a, yon, cfg)
        for j in range(i + 1, min(i + 1 + cfg.max_hold_bar, n)):
            if yon == 1:
                if lo[j] <= sl: break          # önce STOP → bu yön kötü
                if hi[j] >= tp: return Sinyal(yon, sl, tp, "kahin")
            else:
                if hi[j] >= sl: break
                if lo[j] <= tp: return Sinyal(yon, sl, tp, "kahin")
    return None


def kor_kahin(i, veri, cfg, ctx):
    """Aynı kurgu ama geleceğe BAKMAZ — yön deterministik olarak değişir.
    KONTROL GRUBU: motor edge OLMAYAN bir stratejide ne veriyor?"""
    if "atr" not in ctx:
        b = veri["base"]
        ctx["atr"] = EL.atr(b["high"].values, b["low"].values,
                            b["close"].values, cfg.atr_period)
    if i % cfg.ekstra["her_n_bar"]:
        return None
    a = ctx["atr"][i]
    if not np.isfinite(a) or a <= 0:
        return None
    cl = veri["base"]["close"].values
    yon = 1 if (i // cfg.ekstra["her_n_bar"]) % 2 == 0 else -1
    e, sl, tp = _bracket(cl[i], a, yon, cfg)
    return Sinyal(yon, sl, tp, "kor")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    coins = [a for a in args if a in EL.COINS] or ["SOL", "ETH", "BTC"]
    cfg = varsayilan_cfg()
    print("=" * 100)
    print("=== MOTOR SAĞLAMLIK TESTİ — hat bir edge'i görebiliyor mu? ===")
    print("  Üç strateji de brüt ~0 verdi. Bu 'edge yok' mu, yoksa 'motor kör' mü?")
    print(f"  hedef R:R = {cfg.ekstra['rr_hedef']} → KÂHİN ~+{cfg.ekstra['rr_hedef']}R")
    print("  vermeli (maliyet düşülünce biraz altı). KÖR KÂHİN ~−maliyet vermeli.")

    print(f"\n--- SENTETİK (rastgele yürüyüş) ---")
    df = EL.sentetik(60000, tohum=99)
    v = EL.veri_paketi(df, cfg)
    for ad, fn in (("KÂHİN (geleceği görür)", kahin), ("KÖR KÂHİN (kontrol)", kor_kahin)):
        m = EL.metrik(EL.kos("SYN", v, cfg, fn))
        print(f"  {ad:<26s} n={m.get('n',0):>5d}  ort R {m.get('ortR',0):>+8.4f}  "
              f"PF {m.get('pf',0):>6.2f}  WR {m.get('wr',0):>5.1f}%  "
              f"maliyet/R {m.get('maliyet_R',0):.3f}")

    print(f"\n--- GERÇEK VERİ ({', '.join(coins)}) ---")
    sonuc = {}
    for ad, fn in (("KÂHİN (geleceği görür)", kahin), ("KÖR KÂHİN (kontrol)", kor_kahin)):
        tum = []
        for c in coins:
            vv = EL.yukle(c, cfg)
            if vv is None:
                print(f"  {c} veri YOK"); continue
            tum += EL.kos(c, vv, cfg, fn)
        m = EL.metrik(tum)
        sonuc[ad] = m
        print(f"  {ad:<26s} n={m.get('n',0):>5d}  ort R {m.get('ortR',0):>+8.4f}  "
              f"PF {m.get('pf',0):>6.2f}  WR {m.get('wr',0):>5.1f}%  "
              f"maliyet/R {m.get('maliyet_R',0):.3f}")

    print(f"\n{'='*100}\n=== HÜKÜM ===")
    k = sonuc.get("KÂHİN (geleceği görür)", {})
    b = sonuc.get("KÖR KÂHİN (kontrol)", {})
    if not k.get("n"):
        print("  ✗ kâhin işlem üretmedi — test yapılamadı."); return
    fark = k["ortR"] - b.get("ortR", 0.0)
    print(f"  kâhin {k['ortR']:+.4f}R  ·  kör {b.get('ortR',0):+.4f}R  ·  FARK {fark:+.4f}R")
    if k["ortR"] > 0.8 * cfg.ekstra["rr_hedef"]:
        print(f"  ✓ MOTOR SAĞLAM. Geleceği bilen strateji ~+{cfg.ekstra['rr_hedef']}R")
        print(f"    alıyor → hat gerçek bir edge'i GÖRÜYOR.")
        print(f"    Dolayısıyla üç stratejinin brüt ~0 vermesi motor hatası DEĞİL:")
        print(f"    o stratejilerde gerçekten edge YOK.")
    elif fark > 0.5:
        print(f"  ~ Motor edge'i görüyor ama beklenenden zayıf. Kısmi güven.")
    else:
        print(f"  ⛔ MOTOR KÖR. Geleceği bilen strateji bile kazanamıyor →")
        print(f"    bu hattın ürettiği TÜM sonuçlar geçersiz. Önce motor onarılmalı.")


if __name__ == "__main__":
    main()
