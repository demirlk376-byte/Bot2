"""
edge_kacak.py — ANKORUN +0.190R'Sİ CANLIDA NEDEN +0.0555R? Kaçak nerede?

BU, SİSTEMDEKİ EN BÜYÜK AÇIKLANMAMIŞ SAYI. Ve bugün kapatılan 14 filtre ekseninin
hepsinden büyük: fark 0.135R, yani ankorun edge'inin %71'i. Herhangi bir filtrenin
bulabildiği en iyi şey ~%5'ti. Buranın yarısını bile kurtarmak, bugün denenen her
şeyin toplamından fazla eder.

BUGÜNE KADAR NE BİLİYORUZ:
  • Fark İSTATİSTİKSEL OLARAK ANLAMLI DEĞİL: canlı %95 aralığı [−0.357, +0.468],
    ankorun +0.190'ı İÇİNDE. n=41. Yani fark tamamen gürültü OLABİLİR.
  • Ama gürültü "hiçbir şey yok" demek değil — sistematik kaçaklar gürültünün
    ALTINDA gizlenebilir. Onları tek tek ÖLÇMEK gerekir, ortalamadan çıkarım değil.
  • Giriş kayması ÖLÇÜLDÜ (kayma_denetim.py): donchian +15.32bp ≈ 0.05R.

BU ARAÇ GERİ KALANI ARIYOR. Dört şüpheli, biri hiç bakılmamış:

 [1] KAPALI KOLLAR HÂLÂ İŞLEM AÇIYOR MU?
     Defterin 79 işleminin 33'ü kapalı kollardan ('?': asia_bo/orb/fvg/sr).
     Bunlar 2026-07-16'da kapatıldı. Eğer HÂLÂ açılıyorlarsa iki türlü zarar:
     (a) live_verify'ın notuna göre ort R'yi +0.11'den −0.10'a çekiyorlar,
     (b) MAX_POSITIONS=7 koltuğu işgal edip KÂRLI kolların işlemini engelliyorlar.
     (b) ölçülmedi ve (a)'dan büyük olabilir: koltuk_kapasite.py boş koltuğun
     doldurulmasının zarar verdiğini gösterdi — VASAT sinyalle dolduruluyorsa.

 [2] ÇIKIŞ KAYMASI — HİÇ ÖLÇÜLMEDİ. Bugünün asıl boşluğu.
     Stop, borsada TETİKLİ PİYASA emri. Tetiklendiğinde fiyat zaten hareket
     halindedir → dolum stop seviyesinin ALTINDA olur. Çıkışların %56'sı stop.
     Girişte 15bp ölçtük; çıkışta hiç bakmadık. Simetri yoksa sebebi öğrenilmeli.
     live_verify çıkışları sl/tp/mh diye SINIFLANDIRIYOR ama kaymayı ÖLÇMÜYOR.

 [3] ÜCRET + FONLAMA — ücret ölçüldü (0.751bp/taraf, ihmal edilebilir).
     Fonlama defterde ayrı kalem değil; pnl_usdt'ye gömülü. Tutma süresinden
     tahmin edilir.

 [4] ARTIK — yukarıdakiler çıkınca kalan. Sıfıra yakınsa kaçak yok, fark gürültü.
     Büyükse HENÜZ BULUNMAMIŞ bir kaçak var ve aranmaya devam edilir.

⚠ HER KALEM R CİNSİNDEN ölçülür (dolar değil): R karşılaştırılabilir tek birim.
  Sonra $/yıl'a çevrilir ki "tamir etmeye değer mi" sorusu yanıtlanabilsin.

⚠ TRAILING UYARISI: database.py:218 girişten SONRA sl_price'ı güncelliyor. Yani
  defterdeki sl_price ÇIKIŞ ANINDA GEÇERLİ olan stop'tur — çıkış kayması için
  DOĞRU referans budur (girişteki stop değil). Girişteki risk için ise |giriş−sl|
  yanıltıcı olabilir; bu yüzden risk ölçüsü olarak çıkış anındaki stop kullanılır
  ve bu SINIRLILIK açıkça raporlanır.

Kullanım (VPS'te):  cd /opt/bot2 && python3 edge_kacak.py
                    python3 edge_kacak.py --self-test
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))
ANK_R = 0.190              # ankor_denetim.py A3 — DÜRÜST ankor (1476'lık değil)
KAPANIS_TARIHI = "2026-07-16"   # kapalı kolların emekli edildiği gün
AKTIF = ("donchian", "squeeze", "bb")


def sleeve_of(scores_json):
    try:
        d = json.loads(scores_json) if scores_json else {}
    except Exception:
        d = {}
    s = (d.get("strategy") or d.get("sleeve") or "").lower()
    if "donch" in s or "breakout" in s: return "donchian"
    if "squeeze" in s: return "squeeze"
    if "mean" in s or "bb" in s: return "bb"
    return "?"


def _d(side):
    return 1 if str(side).lower() in ("long", "buy", "1") else -1


def cikis_turu(reason, d_, ep, xp, slp, tpp):
    """Çıkış hangi seviyede oldu?

    ⚠ ÖNCE DEFTERİN KENDİ KAYDI (exit_reason). Çıkarım yapmak yerine sistemin
    yazdığını oku.

    Neden önemli: live_verify yakınlık kuralı kullanıyor — çıkış stop'a risk'in
    %10'undan yakınsa 'sl'. Ama TAM DA ÖLÇMEK İSTEDİĞİMİZ ŞEY dolumun stop'tan
    UZAK olması. 0.10R kayma yaşamış bir stop çıkışı o kuralla 'mh' kovasına
    düşüyor ve kayma ÖLÇÜLEMİYOR. Bu aracın kendi self-test'i bu tuzağa düştü
    (30 sentetik stop çıkışı 'mh' sayıldı) — kural o yüzden değişti.

    exit_reason yoksa yakınlığa düşülür ama tolerans %10 değil %25.
    """
    r = (reason or "").strip().lower()
    if r:
        if "safety" in r or "manual" in r or "halt" in r or "flip" in r:
            return "diger"
        if "max" in r or "hold" in r:
            return "mh"
        if "tp" in r or "take" in r or "profit" in r:
            return "tp"
        if "sl" in r or "stop" in r or "loss" in r:
            return "sl"
    risk = abs(ep - slp)
    if risk <= 0:
        return None
    d_sl = abs(xp - slp)
    d_tp = abs(xp - tpp) if tpp else float("inf")
    if d_sl < risk * 0.25 and d_sl <= d_tp:
        return "sl"
    if tpp and d_tp < abs(tpp - ep) * 0.25:
        return "tp"
    return "mh"


def cikis_kaymasi(d_, xp, seviye, risk):
    """ALEYHE çıkış kayması, R cinsinden. Long'da seviyenin ALTINDA dolmak aleyhe
    (stop'ta daha çok kaybettin, TP'de daha az kazandın). Short'ta ÜSTÜNDE dolmak.
    Tek formül ikisini de kapsıyor: d*(seviye − dolum)/risk."""
    return d_ * (seviye - xp) / risk


def topla(rows):
    """rows: (symbol, side, entry, exit, qty, sl, tp, entry_time, exit_time, pnl,
              sc, exit_reason)"""
    out = []
    for (sym, side, ep, xp, qty, slp, tpp, et, xt, pnl, sc, rsn) in rows:
        if not xp or not xt or ep is None:
            continue
        d_ = _d(side)
        risk = abs(ep - slp)
        if risk <= 0:
            continue
        tur = cikis_turu(rsn, d_, ep, xp, slp, tpp)
        if tur is None:
            continue
        seviye = slp if tur == "sl" else (tpp if tur == "tp" else None)
        kay = cikis_kaymasi(d_, xp, seviye, risk) if seviye else None
        out.append(dict(kol=sleeve_of(sc), tur=tur, d=d_, R=d_ * (xp - ep) / risk,
                        kayR=kay, risk=risk, nom=float(ep) * float(qty),
                        et=et, xt=xt, pnl=pnl, rsn=(rsn or "").strip().lower()))
    return out


def ozet_kayma(v, ad):
    x = np.array([t["kayR"] for t in v if t["kayR"] is not None])
    if len(x) < 5:
        print(f"    {ad:<28s} n={len(x):<3d} — çok az")
        return None
    se = x.std(ddof=1) / np.sqrt(len(x))
    print(f"    {ad:<28s} n={len(x):<3d} {x.mean():+.4f}R "
          f"[{x.mean()-1.96*se:+.4f}, {x.mean()+1.96*se:+.4f}]  "
          f"medyan {np.median(x):+.4f}  aleyhe %{(x > 0).mean()*100:.0f}")
    return dict(n=len(x), ort=float(x.mean()), lo=float(x.mean()-1.96*se),
                hi=float(x.mean()+1.96*se))


def self_test():
    print("=== SELF-TEST: bilinen çıkış kayması enjekte edilip geri okunuyor ===")
    ok = True
    # long, stop 98, risk 2, dolum 97.8 → aleyhe 0.2/2 = +0.10R
    r = cikis_kaymasi(1, 97.8, 98.0, 2.0)
    print(f"  long stop altında dolum → {r:+.4f}R  {'✓' if abs(r-0.10) < 1e-9 else '✗'}")
    ok &= abs(r - 0.10) < 1e-9
    # short, stop 102, risk 2, dolum 102.2 → aleyhe +0.10R
    r = cikis_kaymasi(-1, 102.2, 102.0, 2.0)
    print(f"  short stop üstünde dolum → {r:+.4f}R  {'✓' if abs(r-0.10) < 1e-9 else '✗'}")
    ok &= abs(r - 0.10) < 1e-9
    # long, TP 104, dolum 103.8 → aleyhe +0.10R (daha az kâr)
    r = cikis_kaymasi(1, 103.8, 104.0, 2.0)
    print(f"  long TP altında dolum    → {r:+.4f}R  {'✓' if abs(r-0.10) < 1e-9 else '✗'}")
    ok &= abs(r - 0.10) < 1e-9
    # LEHTE dolum NEGATİF olmalı (long stop ÜSTÜNDE = daha az kayıp)
    r = cikis_kaymasi(1, 98.2, 98.0, 2.0)
    print(f"  long stop ÜSTÜNDE dolum  → {r:+.4f}R  {'✓ (lehte=negatif)' if r < 0 else '✗ İŞARET TERS'}")
    ok &= r < 0
    # sınıflandırma — defterin kaydı öncelikli
    for rsn, bek in (("stop_loss", "sl"), ("take_profit", "tp"), ("max_hold", "mh"),
                     ("manual_telegram", "diger"), ("no_stop_safety", "diger")):
        t = cikis_turu(rsn, 1, 100.0, 99.0, 98.0, 104.0)
        print(f"  exit_reason '{rsn}' → {t}  {'✓' if t == bek else '✗'}")
        ok &= t == bek
    # ⚠ ASIL TUZAK: kaymalı bir stop çıkışı. exit_reason varsa DOĞRU sınıflanmalı;
    # eski %10 yakınlık kuralı bunu 'mh' sayıp kaymayı GİZLİYORDU.
    t = cikis_turu("stop_loss", 1, 100.0, 97.8, 98.0, 104.0)
    print(f"  KAYMALI stop (dolum 0.10R uzakta) → {t}  "
          f"{'✓ (eski kural mh derdi — kaymayı gizlerdi)' if t == 'sl' else '✗ TUZAĞA DÜŞTÜ'}")
    ok &= t == "sl"
    # exit_reason YOKKEN yedek kural da bunu yakalamalı (%25 tolerans)
    t = cikis_turu("", 1, 100.0, 97.8, 98.0, 104.0)
    print(f"  aynısı, exit_reason YOK → {t}  {'✓' if t == 'sl' else '✗'}")
    ok &= t == "sl"
    t = cikis_turu("", 1, 100.0, 101.0, 98.0, 104.0)
    print(f"  gerçek max-hold (arada) → {t}  {'✓' if t == 'mh' else '✗'}")
    ok &= t == "mh"
    # uçtan uca: bilinen kaymalı sentetik defter
    rows = [("X/USDT:USDT", "long", 100.0, 97.8, 1.0, 98.0, 104.0,
             "2026-08-01T00:00:00", "2026-08-01T04:00:00", -2.2,
             '{"strategy":"donchian"}', "stop_loss") for _ in range(30)]
    # yarısı SHORT ve LEHTE dolmuş olsun → ortalama düşmeli, işaret sınanmış olsun
    rows += [("X/USDT:USDT", "short", 100.0, 102.2, 1.0, 102.0, 96.0,
              "2026-08-01T00:00:00", "2026-08-01T04:00:00", -2.2,
              '{"strategy":"squeeze"}', "stop_loss") for _ in range(10)]
    v = topla(rows)
    x = np.array([t["kayR"] for t in v])
    bek = (30 * 0.10 + 10 * 0.10) / 40
    e2e = len(v) == 40 and abs(x.mean() - bek) < 1e-9
    print(f"  uçtan uca (40 işlem, long+short, +{bek:.2f}R enjekte) → {x.mean():+.4f}R "
          f"{'✓' if e2e else '✗'}")
    return ok and e2e


def main():
    if "--self-test" in sys.argv:
        print("✓ araç güvenilir" if self_test() else "✗ ARAÇ BOZUK")
        return
    print("=" * 104)
    print("=== EDGE KAÇAK DENETİMİ: ankor +0.190R → canlı +0.0555R, aradaki 0.135R nerede? ===")
    if not self_test():
        print("\n✗ SELF-TEST GEÇMEDİ — gerçek defter okunmaz.")
        return
    if not os.path.exists(DB):
        print(f"\n✗ {DB} bulunamadı. VPS'te /opt/bot2 içinde çalıştırın.")
        return

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, side, entry_price, exit_price, quantity, sl_price, tp_price,"
        " entry_time, exit_time, pnl_usdt, strategy_scores, exit_reason"
        " FROM trades WHERE is_paper=0"
    ).fetchall()
    acik = con.execute(
        "SELECT entry_time, strategy_scores FROM trades"
        " WHERE is_paper=0 AND (exit_time IS NULL OR exit_time='')"
    ).fetchall()
    con.close()
    v = topla(rows)
    print(f"\n  defterde {len(rows)} gerçek işlem · kapanmış+ölçülebilir {len(v)} · açık {len(acik)}")

    # ── [1] KAPALI KOLLAR HÂLÂ İŞLEM AÇIYOR MU? ──
    print(f"\n{'=' * 104}\n=== [1] KAPALI KOLLAR HÂLÂ AÇIYOR MU? (koltuk hırsızlığı) ===")
    print(f"  Kapalı kollar {KAPANIS_TARIHI}'da emekli edildi. O tarihten SONRA giriş varsa")
    print(f"  hem ort R'yi aşağı çekiyor hem MAX_POSITIONS koltuğunu işgal ediyorlar.")
    print(f"  exit_reason kaydı olan: {sum(1 for r in rows if (r[11] or '').strip())}"
          f" / {len(rows)}  (yoksa yakınlık kuralına düşülür)")
    tum = [(r[7], sleeve_of(r[10])) for r in rows] + [(a[0], sleeve_of(a[1])) for a in acik]
    sonra = {}
    for et, kol in tum:
        if not et:
            continue
        sonra.setdefault(kol, []).append(str(et))
    bulgu = False
    for kol in sorted(sonra):
        ts = sorted(sonra[kol])
        yeni = [t for t in ts if t[:10] > KAPANIS_TARIHI]
        isaret = ""
        if kol not in AKTIF and yeni:
            isaret = f"  ⛔ KAPALI OLMASI GEREKEN KOL {len(yeni)} İŞLEM AÇMIŞ!"
            bulgu = True
        print(f"    {kol:<10s} n={len(ts):<3d}  ilk {ts[0][:10]}  son {ts[-1][:10]}  "
              f"{KAPANIS_TARIHI} sonrası: {len(yeni)}{isaret}")
    if not bulgu:
        print(f"\n    ✓ Kapalı kolların {KAPANIS_TARIHI} sonrası girişi YOK — koltuk çalınmıyor.")
        print(f"      (Defterdeki '?' işlemleri o tarihten ÖNCE. Ortalamaya katılmamalı,")
        print(f"       live_verify zaten katmıyor.)")

    # ── [2] ÇIKIŞ KAYMASI ──
    print(f"\n{'=' * 104}\n=== [2] ÇIKIŞ KAYMASI — bugüne kadar HİÇ ÖLÇÜLMEDİ ===")
    print(f"  Stop = borsada TETİKLİ PİYASA emri. Tetiklendiğinde fiyat hareket halinde")
    print(f"  → dolum seviyenin ALTINDA olur. (+R = ALEYHE)")
    akt = [t for t in v if t["kol"] in AKTIF]
    dagilim = {}
    for t in akt:
        dagilim[t["tur"]] = dagilim.get(t["tur"], 0) + 1
    n_akt = max(len(akt), 1)
    print(f"\n  aktif kollarda çıkış dağılımı: " + " · ".join(
        f"{k} {n} (%{n/n_akt*100:.0f})" for k, n in sorted(dagilim.items())))
    print(f"\n  ÇIKIŞ KAYMASI (R):")
    top = ozet_kayma(akt, "TÜM aktif kollar (sl+tp)")
    sl_ = ozet_kayma([t for t in akt if t["tur"] == "sl"], "  yalnız STOP çıkışları")
    tp_ = ozet_kayma([t for t in akt if t["tur"] == "tp"], "  yalnız TP çıkışları")
    for kol in AKTIF:
        ozet_kayma([t for t in akt if t["kol"] == kol], f"  kol: {kol}")

    # ── [3] BİLEŞENLER ──
    print(f"\n{'=' * 104}\n=== [3] KAÇAK BÜTÇESİ — 0.135R'nin dökümü ===")
    giris_R = 0.050        # kayma_denetim.py: donchian +15.32bp ≈ 0.05R (A0→A1 kalibrasyonu)
    ucret_R = 0.000        # ucret_olc.py: gerçek 0.751bp < ankorun 1.00bp varsayımı → LEHTE
    cikis_R = top["ort"] if top else 0.0
    fark = ANK_R - 0.0555
    artik = fark - giris_R - cikis_R - ucret_R
    print(f"  {'kalem':<34s} {'R':>9s}   kaynak")
    print(f"  {'ankor (dürüst, A3)':<34s} {ANK_R:>+9.4f}   ankor_denetim.py")
    print(f"  {'canlı (aktif kollar)':<34s} {0.0555:>+9.4f}   live_verify.py")
    print(f"  {'AÇIKLANMASI GEREKEN FARK':<34s} {fark:>+9.4f}")
    print(f"  {'  − giriş kayması':<34s} {giris_R:>+9.4f}   kayma_denetim.py (ÖLÇÜLDÜ)")
    print(f"  {'  − çıkış kayması':<34s} {cikis_R:>+9.4f}   BU ARAÇ (İLK KEZ)")
    print(f"  {'  − ücret':<34s} {ucret_R:>+9.4f}   ucret_olc.py (ihmal)")
    print(f"  {'  = ARTIK (açıklanamayan)':<34s} {artik:>+9.4f}")

    # ── HÜKÜM ──
    print(f"\n{'=' * 104}\n=== HÜKÜM ===")
    if top is None:
        print("  Çıkış kayması ölçülemedi (n çok az).")
        return
    if top["lo"] > 0:
        print(f"\n  ⛔ ÇIKIŞ KAYMASI VAR ve SIFIRDAN BÜYÜK: {top['ort']:+.4f}R "
              f"[{top['lo']:+.4f}, {top['hi']:+.4f}]")
        print(f"     Bu, ankorun HİÇ hesaba katmadığı bir maliyet — ankor çıkışın tam")
        print(f"     stop/TP fiyatından olduğunu varsayıyor (deployed_backtest.py:70-76).")
        if sl_ and sl_["ort"] > 0.02:
            print(f"     Ağırlık STOP çıkışlarında: {sl_['ort']:+.4f}R (çıkışların %"
                  f"{dagilim.get('sl',0)/n_akt*100:.0f}'i)")
            print(f"\n     TAMİR EDİLEBİLİR Mİ? Stop şu an borsa-taraflı TETİKLİ PİYASA emri.")
            print(f"     Seçenekler: (a) stop-LİMİT — kayma biter ama DOLMAMA riski,")
            print(f"     canlı parada TEHLİKELİ. (b) stop'u biraz GENİŞ koyup gerçek")
            print(f"     kaymayı fiyatlamak. (c) kabul et ve ankoru düzelt.")
            print(f"     ⚠ (a) ASLA test edilmeden açılmaz: dolmayan stop = sınırsız kayıp.")
    elif top["hi"] < 0:
        print(f"\n  ✓ Çıkış LEHTE: {top['ort']:+.4f}R — dolumlar seviyeden İYİ.")
    else:
        print(f"\n  ~ Çıkış kayması sıfırdan ayırt EDİLEMİYOR: {top['ort']:+.4f}R "
              f"[{top['lo']:+.4f}, {top['hi']:+.4f}], n={top['n']}")
        print(f"    Bu kalem BÜYÜK BİR KAÇAK DEĞİL. Aramaya devam.")
    print(f"\n  ARTIK {artik:+.4f}R:")
    if abs(artik) < 0.03:
        print(f"    Sıfıra yakın → 0.135R'lik fark ölçülen kalemlerle AÇIKLANDI.")
        print(f"    Yeni bir kaçak aramaya gerek yok; kalan gürültüdür.")
    else:
        print(f"    HÂLÂ BÜYÜK. Ölçülen kalemler farkı açıklamıyor. İki ihtimal:")
        print(f"      (a) n=41 gürültüsü — canlı %95 aralığı [−0.357,+0.468] zaten")
        print(f"          ankoru içeriyor, yani fark 'yok' da olabilir.")
        print(f"      (b) henüz bakılmamış bir kaçak var.")
        print(f"    AYIRMANIN TEK YOLU: daha çok işlem. n=100'de aralık ~yarıya iner.")
    print(f"\n  ⚠ SINIRLILIK: risk ölçüsü |giriş − sl_price| ve sl_price TRAILING ile")
    print(f"    güncelleniyor (database.py:218). Trailing çalışan işlemlerde bu, giriş")
    print(f"    anındaki riskten farklıdır → R'ler bir miktar kayabilir. Çıkış kayması")
    print(f"    için doğru referans yine de ÇIKIŞ ANINDAKİ stop'tur.")


if __name__ == "__main__":
    main()
