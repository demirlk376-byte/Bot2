"""
defter_gercek.py — DEFTER vs GERÇEK BAKİYE: görünmeyen kaçak ne kadar?

NEDEN BU ARAÇ VAR — edge_kacak.py'nin ortaya çıkardığı şey:
  Çıkış kayması ölçülemedi çünkü DEFTERDE YOK. squeeze kolunda 11 işlemin çıkış
  kayması tam 0.0000R ve varyans SIFIR çıktı. Gerçek piyasa dolumları böyle olmaz.
  Sebep main.py:1619-1631'de bulundu:

      if sl_hit:   exit_price = pos.sl_price      # ← GERÇEK DOLUM DEĞİL, HEDEF
      elif tp_hit: exit_price = pos.tp_price      # ← aynısı
      ...
      raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity

  Borsa SL/TP'yi tetikleyip pozisyonu kapattığında bot bunu ~2dk sonra mutabakat
  döngüsünde fark ediyor ve çıkışı SEVİYE FİYATINDAN kaydediyor. PnL de o
  varsayılan fiyattan hesaplanıyor. Gerçek dolum sorulmuyor.

  Çıkışların %83'ü SL/TP (sl %57 + tp %26). Yani defterdeki PnL'in %83'ü
  GERÇEKLEŞEN değil, VARSAYILAN.

BUNUN ÜÇ SONUCU VAR:
  1. Çıkış kayması defterde GÖRÜNMEZ → edge_kacak.py'nin −0.0110R'si ölçüm değil.
  2. Stop dolumları gerçekte seviyenin ALTINDA olur → defter kârı OLDUĞUNDAN İYİ
     gösterir → canlı +0.0555R muhtemelen ŞİŞKİN, gerçek daha düşük.
  3. daily_stats ve GÜNLÜK ZARAR DURDURUCUSU bu şişkin sayıları kullanıyor →
     %35 sınırı gerçekte biraz GEÇ tetikleniyor. Bu bir GÜVENLİK kalemi.

ÖLÇÜM YÖNTEMİ — varsayım gerektirmeyen tek yol:
  defter_equity = ilk gün başlangıç bakiyesi + Σ(pnl_usdt) + yatırılan para
  gerçek_equity = MEXC cüzdanı (+ açık pozisyonların uPnL'i)
  FARK = defterin HİÇ göremediği her şey: çıkış kayması + fonlama + eksik ücret.

  Bu fark tek bir sayıdır ve hiçbir modele dayanmaz. İşlem başına R'ye çevrilince
  edge_kacak.py'nin bütçesindeki +0.0955R'lik ARTIK ile doğrudan kıyaslanır.

⚠ TEK BAŞINA "bot para kaybediyor" DEMEZ. Para zaten borsada kaybedildi; yanlış
  olan MUHASEBE. Ama muhasebe yanlışsa (a) güvenlik ağı geç çalışır, (b) canlı R
  ölçümü ve ona dayanan her araştırma hükmü kayar.

Kullanım (VPS'te):  cd /opt/bot2 && python3 defter_gercek.py
                    python3 defter_gercek.py --self-test
"""
import asyncio
import os
import sqlite3
import sys

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))


def defter_oku():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    ilk = con.execute(
        "SELECT date, starting_balance FROM daily_stats WHERE is_paper=0"
        " AND starting_balance IS NOT NULL AND starting_balance>0"
        " ORDER BY date LIMIT 1").fetchone()
    kapali = con.execute(
        "SELECT COALESCE(SUM(pnl_usdt),0), COUNT(*) FROM trades"
        " WHERE is_paper=0 AND exit_time IS NOT NULL AND exit_time<>''").fetchone()
    acik = con.execute(
        "SELECT symbol, side, entry_price, quantity FROM trades"
        " WHERE is_paper=0 AND (exit_time IS NULL OR exit_time='')").fetchall()
    dep = con.execute("SELECT value FROM meta WHERE key='total_deposits'").fetchone()
    # çıkış türü dağılımı: kaçının fiyatı VARSAYILAN?
    tur = con.execute(
        "SELECT COALESCE(exit_reason,''), COUNT(*) FROM trades WHERE is_paper=0"
        " AND exit_time IS NOT NULL AND exit_time<>'' GROUP BY 1").fetchall()
    con.close()
    return dict(ilk=ilk, pnl=float(kapali[0]), n=int(kapali[1]), acik=acik,
                dep=float(dep[0]) if dep and dep[0] else 0.0, tur=tur)


def varsayilan_mi(reason):
    """main.py:1619-1622 — YALNIZ bu iki sebep seviye fiyatından kaydediliyor.
    Diğerleri (max_hold, manual, safety) gerçek dolum fiyatıyla geliyor."""
    r = (reason or "").strip().lower()
    return r in ("sl_hit", "tp_hit")


def self_test():
    print("=== SELF-TEST ===")
    ok = True
    for r, bek in (("sl_hit", True), ("tp_hit", True), ("max_hold", False),
                   ("manual_telegram", False), ("external_close", False), ("", False)):
        g = varsayilan_mi(r)
        print(f"  '{r or '(boş)'}' varsayılan fiyat mı? {g}  {'✓' if g == bek else '✗'}")
        ok &= g == bek
    return ok


async def main():
    if "--self-test" in sys.argv:
        print("✓ araç güvenilir" if self_test() else "✗ ARAÇ BOZUK")
        return
    print("=" * 96)
    print("=== DEFTER vs GERÇEK BAKİYE — defterin göremediği kaçak ===")
    if not self_test():
        print("\n✗ SELF-TEST GEÇMEDİ."); return
    if not os.path.exists(DB):
        print(f"\n✗ {DB} bulunamadı. VPS'te /opt/bot2 içinde çalıştırın."); return

    d = defter_oku()
    if not d["ilk"]:
        print("\n✗ daily_stats'ta başlangıç bakiyesi yok — köken belirlenemiyor.")
        return

    # ── çıkış fiyatlarının kaçı VARSAYILAN? ──
    print(f"\n{'=' * 96}\n=== [1] ÇIKIŞ FİYATLARININ KAÇI GERÇEK, KAÇI VARSAYILAN? ===")
    print(f"  main.py:1619-1622 — borsa SL/TP tetikleyince bot çıkışı SEVİYE")
    print(f"  fiyatından kaydediyor, gerçek dolumu sormuyor.")
    tv = sum(c for r, c in d["tur"] if varsayilan_mi(r))
    tg = sum(c for r, c in d["tur"] if not varsayilan_mi(r))
    print(f"\n  {'exit_reason':<22s} {'n':>4s}   fiyat kaynağı")
    for r, c in sorted(d["tur"], key=lambda x: -x[1]):
        print(f"  {(r or '(boş)'):<22s} {c:>4d}   "
              f"{'⚠ VARSAYILAN (seviye)' if varsayilan_mi(r) else 'gerçek dolum'}")
    tot = max(tv + tg, 1)
    print(f"\n  VARSAYILAN fiyatla kaydedilen: {tv}/{tot} = %{tv/tot*100:.0f}")
    print(f"  → Defterdeki PnL'in %{tv/tot*100:.0f}'i GERÇEKLEŞEN değil, HEDEFLENEN.")

    # ── gerçek bakiye ──
    print(f"\n{'=' * 96}\n=== [2] DEFTER vs BORSA ===")
    from config import load_config
    from exchange import LiveExchange
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("  PAPER modda — borsa sorgusu yok. .env LIVE olmalı."); return
    ex = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    syms = cfg.exchange.symbols or [cfg.exchange.symbol]
    try:
        await ex.initialize(syms[0])
    except Exception as e:
        print(f"  ⚠ initialize uyarısı: {e}")
    # ⚠ get_balance() YALNIZ SERBEST bakiyeyi döndürüyor (exchange.py: usdt["free"]).
    # Açık pozisyon varsa KİLİTLİ MARJİN dışarıda kalır ve defterle kıyaslanınca
    # sahte bir "kaçak" üretir. İlk sürümüm tam bu hatayı yaptı: 2 pozisyon açıkken
    # −$98.96 raporladı. Doğru sayı get_equity() — nakit + kilitli marjin + uPnL,
    # ki günlük zarar durdurucusu da onu kullanıyor (exchange.py: get_equity).
    serbest = eq = None
    try:
        serbest = float(await ex.get_balance())
    except Exception as e:
        print(f"  ⚠ serbest bakiye okunamadı: {e}")
    try:
        eq = float(await ex.get_equity())
    except Exception as e:
        print(f"  ✗ equity okunamadı: {e}")
    upnl = 0.0
    n_acik = 0
    okunamadi = []
    for sym, side, ep, qty in d["acik"]:
        try:
            p = await ex.get_position(sym)
        except Exception as e:
            p = None
        if p is None:
            okunamadi.append(sym)
            continue
        n_acik += 1
        u = getattr(p, "unrealized_pnl", None)
        if u is None:
            okunamadi.append(sym)
        else:
            upnl += float(u)
    try:
        await ex.close()
    except Exception:
        pass
    if eq is None or eq <= 0:
        print(f"\n  ⛔ GERÇEK EQUITY OKUNAMADI. Serbest bakiye ile kıyas YAPILMAZ —")
        print(f"     açık pozisyonların kilitli marjini dışarıda kalır ve sahte bir")
        print(f"     kaçak üretir. Hüküm verilmiyor.")
        return
    if okunamadi:
        print(f"\n  ⚠ {len(okunamadi)} açık pozisyonun uPnL'i OKUNAMADI: {okunamadi}")
        print(f"     Bu tutar farka karışıyor; sonuç o kadar belirsiz.")

    bas = float(d["ilk"][1])
    defter = bas + d["pnl"] + d["dep"]
    # Defter YALNIZ gerçekleşmiş PnL'i taşır; borsa equity'si açık pozisyonların
    # uPnL'ini de içerir. Elmayla elmayı kıyaslamak için uPnL çıkarılır.
    gercek_realize = eq - upnl
    fark = gercek_realize - defter
    print(f"\n  köken (ilk gün {d['ilk'][0]} başlangıç bakiyesi):  ${bas:>10.2f}")
    print(f"  + defterdeki kapanmış PnL ({d['n']} işlem):        ${d['pnl']:>+10.2f}")
    print(f"  + yatırılan/çekilen para:                         ${d['dep']:>+10.2f}")
    print(f"  {'─'*58}")
    print(f"  = DEFTERE GÖRE olması gereken (gerçekleşmiş):     ${defter:>10.2f}")
    print(f"\n  BORSA — doğru alan hangisi:")
    if serbest is not None:
        print(f"    serbest bakiye (free) ................... ${serbest:>10.2f}   "
              f"← kilitli marjin HARİÇ, KIYASA UYGUN DEĞİL")
    print(f"    GERÇEK EQUITY (nakit+marjin+uPnL) ...... ${eq:>10.2f}   ← doğru olan")
    if n_acik or okunamadi:
        print(f"    − açık {n_acik} pozisyonun uPnL'i ............ ${upnl:>+10.2f}")
        print(f"    = borsanın GERÇEKLEŞMİŞ kısmı .......... ${gercek_realize:>10.2f}")
    if serbest is not None and eq > 0:
        print(f"\n    (kilitli marjin ≈ ${eq - serbest - upnl:.2f} — ilk sürümüm bunu")
        print(f"     'kaçak' sanmıştı; o yüzden −$98.96 raporlamıştı)")
    print(f"  {'─'*58}")
    print(f"  FARK (borsa gerçekleşmiş − defter):               ${fark:>+10.2f}")
    print(f"\n  ⚠ SEN DOĞRULA: defter {d['ilk'][0]}'den beri toplam "
          f"${d['dep']:+.2f} yatırım/çekim kaydetmiş.")
    print(f"    Gerçekte yatırdığın tutar bu DEĞİLSE fark buradan gelir, kaçaktan")
    print(f"    değil. (Eksik kaydedilen yatırım = sahte 'kaçak'.)")

    # ── R'ye çevir ──
    print(f"\n{'=' * 96}\n=== [3] KAÇAK BÜTÇESİNE BAĞLA ===")
    risk_usd = bas * 0.0225
    if d["n"] > 0 and risk_usd > 0:
        farkR = fark / d["n"] / risk_usd
        print(f"  işlem başına: ${fark/d['n']:+.4f}  →  {farkR:+.4f}R")
        print(f"  (risk/işlem ≈ ${risk_usd:.2f} = köken bakiyenin %2.25'i)")
        print(f"\n  edge_kacak.py bütçesindeki ARTIK: +0.0955R")
        if abs(farkR) > 0.02:
            pay = min(abs(farkR) / 0.0955 * 100, 999)
            print(f"  bu ölçüm ARTIĞIN ~%{pay:.0f}'ini açıklıyor.")
        else:
            print(f"  bu fark küçük → görünmeyen kaçak ARTIĞI açıklamıyor;")
            print(f"  +0.0955R büyük ihtimalle n=41 gürültüsü.")

    print(f"\n{'=' * 96}\n=== HÜKÜM ===")
    if fark < -1.0:
        print(f"\n  ⛔ BORSA DEFTERDEN ${abs(fark):.2f} DAHA AZ.")
        print(f"     ÜÇ OLASI SEBEP — sırayla elenmeli, ATLAMA:")
        print(f"      (a) YATIRIM KAYDI EKSİK — defter ${d['dep']:+.2f} diyor. Gerçek")
        print(f"          rakam farklıysa 'kaçak' sahtedir. ÖNCE BUNU DOĞRULA.")
        print(f"      (b) Çıkış kayması (çıkışların %{tv/tot*100:.0f}'i seviyeden kaydediliyor)")
        print(f"      (c) Fonlama + eksik hesaplanan ücret")
        print(f"\n  YAPILACAK (sırayla):")
        print(f"   1. main.py:1619 — mutabakatta GERÇEK dolum fiyatı çekilsin")
        print(f"      (fetch_my_trades / closed orders), seviye yalnız YEDEK olsun.")
        print(f"      Bu bir MUHASEBE düzeltmesi: kâr getirmez ama günlük zarar")
        print(f"      durdurucusunun doğru sayıyla çalışmasını sağlar.")
        print(f"   2. Düzeltmeden sonra live_verify'ın canlı R'si DÜŞECEK — bu")
        print(f"      kötüleşme değil, gerçeğin görünmesi.")
    elif fark > 1.0:
        print(f"\n  ⚠ BORSA DEFTERDEN ${fark:.2f} DAHA FAZLA. Beklenmedik yön —")
        print(f"     defter kötümser kaydediyor demektir. Sebep araştırılmalı")
        print(f"     (yatırım kaydı eksik olabilir).")
    else:
        print(f"\n  ✓ Defter ile borsa ${abs(fark):.2f} içinde uyuşuyor.")
        print(f"     Görünmeyen kaçak YOK. Çıkış kaymasının kaydedilmemesi bir")
        print(f"     muhasebe eksiği ama DOLAR olarak zarar üretmiyor.")
    print(f"\n  ⚠ SINIRLILIK: açık pozisyon varsa MEXC'in bakiye alanının uPnL'i")
    print(f"    içerip içermediği belirsiz — iki senaryo da yukarıda verildi.")
    print(f"    Kesin ölçüm için TÜM pozisyonlar kapalıyken çalıştırın.")


if __name__ == "__main__":
    asyncio.run(main())
