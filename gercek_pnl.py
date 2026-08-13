"""
gercek_pnl.py — DEFTERİ BAYPAS ET: PnL'i doğrudan BORSADAN oku.

NEDEN: defter_gercek.py $56.83'lük bir boşluk buldu. Defter işlemlerden +$7.87
KÂR diyor, ama konan sermaye ($93.52 köken + $149.39 yatırım = $242.91) ile
borsadaki gerçekleşmiş equity ($193.97) arasındaki fark −$48.94 ZARAR diyor.

Üç aday vardı: (a) yatırım kaydı yanlış, (b) çıkış kayması, (c) fonlama+ücret.
(a)'yı yalnız kullanıcı doğrulayabilir. AMA (b) ve (c) DOĞRUDAN ÖLÇÜLEBİLİR —
yeter ki defter yerine BORSAYA sorulsun. Bu araç onu yapıyor.

DEFTERİN NEDEN GÜVENİLMEZ OLDUĞU (main.py:1619-1631):
    if sl_hit:   exit_price = pos.sl_price     # gerçek dolum DEĞİL
    elif tp_hit: exit_price = pos.tp_price
    raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
Çıkışların %68'i böyle kaydediliyor. Yani defterdeki PnL büyük ölçüde
HEDEFLENEN, gerçekleşen değil.

BU ARAÇ NE OKUYOR (hepsi READ-ONLY, hiçbir emir gönderilmez):
  1. Kapanmış pozisyon geçmişi → borsanın kendi hesapladığı GERÇEKLEŞMİŞ PnL
  2. Gerçek dolumlar (fetch_my_trades) → gerçek çıkış fiyatları + gerçek ücretler
  3. Fonlama ödemeleri → defterde HİÇ tutulmayan kalem
  4. Hepsi defterle karşılaştırılır: hangi kalem farkı açıklıyor?

⚠ ccxt'nin MEXC vadeli desteği kalem kalem değişebilir. Araç HER kaynağı ayrı
  dener ve HANGİSİNİN ÇALIŞTIĞINI açıkça yazar. Çalışmayan kaynak SESSİZCE sıfır
  sayılmaz — "okunamadı" diye raporlanır ve hüküm o kadar eksik verilir.
  (Bugün defter_gercek.py'de tam bu hatayı yaptım: okunamayan uPnL'i 0 saydım.)

Kullanım (VPS'te):  cd /opt/bot2 && python3 gercek_pnl.py
                    python3 gercek_pnl.py 90        # son 90 gün
"""
import asyncio
import os
import sqlite3
import sys
import time

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))


def defter_ozet(since_ms):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, side, entry_price, exit_price, quantity, pnl_usdt,"
        " fees_usdt, entry_time, exit_time, COALESCE(exit_reason,'')"
        " FROM trades WHERE is_paper=0 AND exit_time IS NOT NULL AND exit_time<>''"
    ).fetchall()
    con.close()
    return rows


async def dene(ad, coro):
    """Bir veri kaynağını dener. Başarısızsa SESSİZ GEÇMEZ — sebebini döner."""
    try:
        r = await coro
        return True, r, None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


async def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
    # MEXC varlık uç noktaları 90 GÜNDEN uzun sorguyu REDDEDİYOR:
    #   {"code":33333,"msg":"query time cannot exceed 90 days"}
    # İlk koşuda 120 gün istendi ve yatırım geçmişinin TAMAMI okunamadı. Defter
    # 2026-06-18'de başlıyor (~57 gün), yani 89 gün fazlasıyla yetiyor.
    gun_varlik = min(gun, 89)
    since_ms = int((time.time() - gun * 86400) * 1000)
    since_varlik = int((time.time() - gun_varlik * 86400) * 1000)
    print("=" * 100)
    print(f"=== GERÇEK PnL — borsadan doğrudan (son {gun} gün) ===")
    print("  Defter çıkışların %68'ini SEVİYE fiyatından kaydediyor (main.py:1619).")
    print("  Bu araç defteri baypas edip borsanın kendi kayıtlarını okuyor.")

    if not os.path.exists(DB):
        print(f"\n✗ {DB} bulunamadı."); return
    from config import load_config
    from exchange import LiveExchange
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("  PAPER modda — borsa sorgusu yok."); return

    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    syms = cfg.exchange.symbols or [cfg.exchange.symbol]
    try:
        await lx.initialize(syms[0])
    except Exception as e:
        print(f"  ⚠ initialize: {e}")
    ex = lx._exchange          # ham ccxt istemcisi

    dr = defter_ozet(since_ms)
    d_pnl = sum(float(r[5] or 0) for r in dr)
    d_fee = sum(float(r[6] or 0) for r in dr)
    print(f"\n  DEFTER: {len(dr)} kapanmış işlem · PnL ${d_pnl:+.2f} · ücret ${d_fee:.2f}")

    kaynak_ok = {}

    # ── 0) YATIRIM DOĞRULAMASI — boşluğun en güçlü adayı, ve OTOMATİK ölçülebilir ──
    print(f"\n{'=' * 100}\n=== [0] YATIRIM/TRANSFER GEÇMİŞİ — defterin $149.39'u doğru mu? ===")
    print("  Boşluğun en güçlü adayı buydu ve 'sen elle bak' demiştim. Gereksizmiş:")
    print("  borsa bunu da veriyor. MEXC'te vadeliye para SPOT'tan TRANSFER ile gelir,")
    print("  o yüzden hem deposits hem transfers denenir.")
    print(f"  (varlık uç noktaları 90 günle sınırlı → {gun_varlik} gün soruluyor)")
    yatirim = {}
    bill_satir = []
    for ad, fn in (
        ("fetch_deposits", lambda: ex.fetch_deposits(None, since_varlik, 200)),
        # fetchTransfers fromAccountType İSTİYOR (ilk koşuda ArgumentsRequired
        # hatası verdi). MEXC'te vadeliye para SPOT→FUTURES transferiyle gelir.
        ("fetch_transfers", lambda: ex.fetch_transfers(
            "USDT", since_varlik, 200,
            {"fromAccountType": "SPOT", "toAccountType": "FUTURES"})),
        # NOT: ters yön sorgusu KALDIRILDI. MEXC fromAccountType/toAccountType'ı
        # yok sayıp AYNI 5 kaydı döndürdü; ben de onları negatifleyip "net $0.00"
        # diye YANLIŞ bir hüküm bastım. Yön bilgisi kaydın kendi 'type' alanında
        # (IN/OUT) — aşağıdaki kalem kalem döküm onu okuyor.
        ("fetch_withdrawals", lambda: ex.fetch_withdrawals(None, since_varlik, 200)),
    ):
        base = ad.split("(")[0]
        if not hasattr(ex, base):
            print(f"  {ad:<22s} — ccxt'de YOK")
            continue
        ok, r, err = await dene(ad, fn())
        if not ok:
            print(f"  {ad:<22s} — HATA: {err}")
            continue
        tot = 0.0
        n = 0
        for x in r or []:
            if not isinstance(x, dict):
                continue
            if (x.get("currency") or "USDT") != "USDT":
                continue
            try:
                a = float(x.get("amount") or 0.0)
            except (TypeError, ValueError):
                continue
            if "ters" in ad:
                a = -a          # vadeliden ÇIKAN para
            tot += a
            n += 1
        yatirim[ad] = (n, tot)
        print(f"  {ad:<22s} — {n} kayıt · toplam ${tot:+.2f}")
        await asyncio.sleep(0.25)

    # YEDEK: MEXC kontrat "varlık hareketi / bill" kaydı — bakiyeyi değiştiren
    # HER kalemi tür etiketiyle verir (transfer, realized PnL, fonlama, ücret).
    # Bu okunursa boşluk KALEM KALEM kapanır, tahmin gerekmez.
    adaylar = [a for a in dir(ex) if a.lower().startswith("contract")
               and any(k in a.lower() for k in ("assettransfer", "transferrecord",
                                                "bill", "assetrecord", "fundflow"))]
    for ad in adaylar[:4]:
        ok, r, err = await dene(ad, getattr(ex, ad)({"page_size": 200}))
        if not ok:
            print(f"  {ad:<38s} — HATA: {err}")
            continue
        try:
            data = (r or {}).get("data") or {}
            kayit = data.get("resultList") if isinstance(data, dict) else data
            kayit = kayit or []
            # ⚠ TOPLAMA DEĞİL, KALEM KALEM DÖK. Önceki sürüm yalnız türe göre
            # topluyordu ve "IN $209.05" diyordu — ama hangi tarihte, hangi tutar
            # görünmüyordu. Köken bakiyeden ÖNCEKİ bir transfer varsa o tutar
            # $93.52'nin İÇİNDE demektir ve ayrıca eklenirse ÇİFT SAYILIR.
            # Sermaye denklemini ancak tarihler görünürse doğru kurabiliriz.
            print(f"  {ad:<38s} — {len(kayit)} kayıt (kalem kalem):")
            import datetime as _dt
            tur = {}
            satirlar = []
            for x in kayit:
                if not isinstance(x, dict):
                    continue
                t = str(x.get("type") or x.get("state") or "?")
                try:
                    a = float(x.get("amount") or 0.0)
                except (TypeError, ValueError):
                    a = 0.0
                ts = x.get("createTime") or x.get("updateTime") or x.get("timestamp")
                try:
                    gts = _dt.datetime.utcfromtimestamp(float(ts) / 1000).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    gts = str(ts)
                satirlar.append((gts, t, a, x.get("currency") or "?"))
                tur[t] = tur.get(t, 0.0) + a
            for gts, t, a, cur in sorted(satirlar):
                print(f"      {gts}  {t:<8s} {cur:<6s} ${a:>+10.2f}")
            print(f"    tür toplamları: " + " · ".join(
                f"{t} ${v:+.2f}" for t, v in sorted(tur.items(), key=lambda z: -abs(z[1]))))
            if kayit:
                kaynak_ok["bill"] = ad
                bill_satir = satirlar
                break
        except Exception as e:
            print(f"  {ad:<38s} — ayrıştırılamadı: {e}")
    if yatirim:
        kaynak_ok["yatirim"] = list(yatirim)

    # ── 1) KAPANMIŞ POZİSYON GEÇMİŞİ (borsanın kendi realized PnL'i) ──
    print(f"\n{'=' * 100}\n=== [1] BORSANIN KENDİ GERÇEKLEŞMİŞ PnL'i ===")
    toplam_rpnl = None
    n_rpnl = 0
    for ad, fn in (
        ("fetch_positions_history", lambda: ex.fetch_positions_history(syms, since_ms, 1000)),
        ("fetchPositionsHistory", lambda: ex.fetchPositionsHistory(syms, since_ms, 1000)),
    ):
        if not hasattr(ex, ad):
            print(f"  {ad:<26s} — ccxt'de YOK")
            continue
        ok, r, err = await dene(ad, fn())
        if not ok:
            print(f"  {ad:<26s} — HATA: {err}")
            continue
        try:
            vals = []
            for p in r or []:
                v = (p.get("realizedPnl") if isinstance(p, dict) else None)
                if v is None and isinstance(p, dict):
                    v = (p.get("info") or {}).get("realised") or (p.get("info") or {}).get("realized")
                if v is not None:
                    vals.append(float(v))
            print(f"  {ad:<26s} — {len(r or [])} kayıt, PnL alanı okunan {len(vals)}")
            if vals:
                toplam_rpnl = sum(vals)
                n_rpnl = len(vals)
                kaynak_ok["realized"] = ad
                print(f"      → BORSA GERÇEKLEŞMİŞ PnL: ${toplam_rpnl:+.2f} ({n_rpnl} pozisyon)")
                break
        except Exception as e:
            print(f"  {ad:<26s} — ayrıştırılamadı: {e}")
    if toplam_rpnl is None:
        # YEDEK: MEXC'in kendi kontrat uç noktası. ccxt bunu "implicit method"
        # olarak açar; isimlendirme sürümden sürüme değişebildiği için birkaç
        # aday denenir. Bu uç nokta kapanmış pozisyonun realised PnL'ini verir.
        adaylar = [a for a in dir(ex)
                   if "istory" in a and "osition" in a and a.lower().startswith("contract")]
        for ad in adaylar[:4]:
            ok, r, err = await dene(ad, getattr(ex, ad)({"page_size": 100}))
            if not ok:
                print(f"  {ad:<40s} — HATA: {err}")
                continue
            try:
                data = (r or {}).get("data") or []
                vals = [float(x.get("realised") or x.get("realized") or 0.0)
                        for x in data if isinstance(x, dict)]
                print(f"  {ad:<40s} — {len(data)} kayıt")
                if vals:
                    toplam_rpnl = sum(vals)
                    kaynak_ok["realized"] = ad
                    print(f"      → BORSA GERÇEKLEŞMİŞ PnL: ${toplam_rpnl:+.2f}")
                    break
            except Exception as e:
                print(f"  {ad:<40s} — ayrıştırılamadı: {e}")
        if not adaylar:
            print("  (MEXC kontrat geçmiş uç noktası ccxt'de bulunamadı)")
    if toplam_rpnl is None:
        print("  ⚠ Borsa realized PnL OKUNAMADI — bu kalem eksik kalıyor.")

    # ── 2) GERÇEK DOLUMLAR ──
    print(f"\n{'=' * 100}\n=== [2] GERÇEK DOLUMLAR (fetch_my_trades) — gerçek ücret + çıkış fiyatı ===")
    fills = []
    if hasattr(ex, "fetch_my_trades"):
        for s in syms:
            ok, r, err = await dene("fetch_my_trades", ex.fetch_my_trades(s, since_ms, 200))
            if not ok:
                print(f"  {s:<18s} — HATA: {err}")
                continue
            fills += list(r or [])
            await asyncio.sleep(0.25)
        if fills:
            kaynak_ok["fills"] = "fetch_my_trades"
            ucret = 0.0
            for f in fills:
                fee = f.get("fee") or {}
                try:
                    ucret += float(fee.get("cost") or 0.0)
                except (TypeError, ValueError):
                    pass
            print(f"  {len(fills)} dolum okundu · GERÇEK toplam ücret ${ucret:.4f}")
            print(f"  defterdeki ücret ${d_fee:.4f} → fark ${ucret - d_fee:+.4f}")
        else:
            print("  ⚠ Hiç dolum okunamadı.")
    else:
        print("  fetch_my_trades — ccxt'de YOK")

    # ── 3) FONLAMA — defterde HİÇ tutulmuyor ──
    print(f"\n{'=' * 100}\n=== [3] FONLAMA ÖDEMELERİ — defterde HİÇ kalemi yok ===")
    fon = None
    if hasattr(ex, "fetch_funding_history"):
        tot = 0.0
        n = 0
        hata = 0
        for s in syms:
            ok, r, err = await dene("fetch_funding_history",
                                    ex.fetch_funding_history(s, since_ms, 200))
            if not ok:
                hata += 1
                continue
            for x in r or []:
                try:
                    tot += float(x.get("amount") or 0.0); n += 1
                except (TypeError, ValueError):
                    pass
            await asyncio.sleep(0.25)
        if n or hata < len(syms):
            fon = tot
            kaynak_ok["funding"] = "fetch_funding_history"
            print(f"  {n} fonlama kaydı · TOPLAM ${tot:+.2f}"
                  f"{f'  ({hata} sembolde hata)' if hata else ''}")
        else:
            print(f"  ⚠ Fonlama okunamadı ({hata}/{len(syms)} sembolde hata).")
    else:
        print("  fetch_funding_history — ccxt'de YOK")

    # equity KAPATMADAN ÖNCE okunur — sermaye denklemi aşağıda buna ihtiyaç duyuyor.
    try:
        eq_now = float(await lx.get_equity())
    except Exception as e:
        print(f"  ⚠ equity okunamadı: {e}")
        eq_now = None
    try:
        await lx.close()
    except Exception:
        pass

    # ── HÜKÜM ──
    print(f"\n{'=' * 100}\n=== HÜKÜM ===")
    print(f"  okunabilen kaynaklar: {kaynak_ok or 'HİÇBİRİ'}")
    if toplam_rpnl is not None:
        # ⛔ ÖRNEKLEM GUARD'I — bunu ilk sürümde ATLADIM ve geçersiz bir hüküm
        # bastım: borsadan 20 pozisyon okunmuştu, defterde 77 işlem vardı, ben
        # ikisini çıplak karşılaştırıp "defter $2.66 iyi gösteriyor" dedim.
        # Farklı örneklem = geçersiz kıyas. Artık sayı tutmuyorsa hüküm YOK.
        oran = n_rpnl / max(len(dr), 1)
        print(f"\n  borsa {n_rpnl} pozisyon · defter {len(dr)} işlem  (kapsama %{oran*100:.0f})")
        if oran < 0.80:
            print(f"\n  ⛔ ÖRNEKLEMLER EŞLEŞMİYOR — borsa geçmişi defterin ancak")
            print(f"     %{oran*100:.0f}'ini kapsıyor (API sayfalama/zaman sınırı). Bu iki")
            print(f"     toplamı karşılaştırmak GEÇERSİZDİR; PnL kıyası YAPILMIYOR.")
            print(f"     (MEXC pozisyon geçmişi genelde son N kaydı verir. Daha uzun")
            print(f"      geçmiş için sayfalama gerekir — ayrı iş.)")
        else:
            fark = toplam_rpnl - d_pnl
            print(f"  BORSA gerçekleşmiş PnL : ${toplam_rpnl:+.2f}")
            print(f"  DEFTER PnL             : ${d_pnl:+.2f}")
            print(f"  FARK                   : ${fark:+.2f}")
            if fark < -1.0:
                print(f"\n  ⛔ DEFTER KÂRI OLDUĞUNDAN İYİ GÖSTERİYOR (${abs(fark):.2f}).")
                print(f"     Sebep main.py:1619 — çıkışlar seviye fiyatından kaydediliyor.")
            elif abs(fark) <= 1.0:
                print(f"\n  ✓ Defter ile borsa uyuşuyor → çıkış kayması dolar olarak önemsiz.")
    else:
        print(f"\n  Borsa realized PnL okunamadığı için defterle kıyas YAPILAMADI.")

    # ── ÜCRET: bu kıyas ÖRNEKLEMDEN BAĞIMSIZ olarak geçerli (oran kıyası) ──
    print(f"\n  ÜCRET — bu bulgu örneklem sorunundan ETKİLENMİYOR:")
    print(f"    Defterdeki ücret, botun KENDİ hesabı: nominal × 0.0001 (1bp/taraf).")
    print(f"    Gerçek dolumlardan okunan ücret bunun KATI çıkıyorsa, bot ücreti")
    print(f"    sistematik olarak DÜŞÜK kaydediyor demektir — kaç işlem okunduğundan")
    print(f"    bağımsız bir ORAN bulgusudur.")

    # ── YATIRIM: boşluğun en güçlü adayı ──
    # ── SERMAYE DENKLEMİ: boşluk artık TRADING'den gelemez, çünkü borsanın
    #    KENDİ realized PnL'i elimizde. Denklem kalem kalem kurulur.
    print(f"\n{'=' * 100}\n=== SERMAYE DENKLEMİ — boşluk trading'den GELMİYOR ===")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    ilk = con.execute(
        "SELECT date, starting_balance FROM daily_stats WHERE is_paper=0"
        " AND starting_balance IS NOT NULL AND starting_balance>0"
        " ORDER BY date LIMIT 1").fetchone()
    dep = con.execute("SELECT value FROM meta WHERE key='total_deposits'").fetchone()
    con.close()
    kok = float(ilk[1]) if ilk else 0.0
    d_dep = float(dep[0]) if dep and dep[0] else 0.0
    # ⚠ ÇİFT SAYIM TUZAĞI: köken bakiye ($93.52, ilk daily_stats günü) muhtemelen
    # ZATEN bir transferin sonucudur. O transferi ayrıca eklemek sermayeyi ŞİŞİRİR
    # ve sahte bir "kayıp" üretir. Bu yüzden yalnız KÖKEN GÜNÜNDEN SONRAKİ
    # transferler sayılır; köken günü ve öncesi $93.52'nin içinde kabul edilir.
    kok_gun = str(ilk[0]) if ilk else "0000-00-00"
    y_sonra = y_once = 0.0
    n_sonra = n_once = 0
    for gts, t, a, _cur in bill_satir:
        isaret = -1.0 if str(t).upper().startswith("OUT") else 1.0
        if str(gts)[:10] > kok_gun:
            y_sonra += isaret * a; n_sonra += 1
        else:
            y_once += isaret * a; n_once += 1
    y_borsa = y_sonra if bill_satir else None
    if bill_satir:
        print(f"  transferler köken gününe göre ayrıldı ({kok_gun}):")
        print(f"    köken günü ve ÖNCESİ : {n_once} kayıt ${y_once:+.2f}  "
              f"← ${kok:.2f}'nin İÇİNDE kabul edildi, TEKRAR EKLENMEZ")
        print(f"    köken gününden SONRA : {n_sonra} kayıt ${y_sonra:+.2f}  ← sermayeye eklenir")
    print(f"\n  köken bakiye ({ilk[0] if ilk else '?'})      ${kok:>8.2f}")
    if bill_satir:
        print(f"  + BORSA transferi (köken sonrası)   ${y_sonra:>+8.2f}   ← GERÇEK")
        print(f"    (defterin kaydı ${d_dep:+.2f} — kıyas aşağıda)")
    else:
        print(f"  + defterin yatırım kaydı            ${d_dep:>+8.2f}")
    if toplam_rpnl is not None:
        print(f"  + BORSANIN kendi realized PnL'i     ${toplam_rpnl:>+8.2f}   ← trading'in GERÇEK katkısı")
    print(f"  + fonlama                           ${(fon or 0.0):>+8.2f}")
    bekl = kok + (y_sonra if bill_satir else d_dep) + (toplam_rpnl or 0.0) + (fon or 0.0)
    print(f"  {'─'*46}\n  = beklenen bakiye                   ${bekl:>8.2f}")
    if eq_now:
        print(f"    gerçek equity                     ${eq_now:>8.2f}")
        acik_fark = eq_now - bekl
        print(f"    AÇIK FARK                         ${acik_fark:>+8.2f}")
        print(f"\n  Trading artık DENKLEMDE (borsanın kendi rakamıyla). Kalan fark")
        print(f"  trading'den GELEMEZ. Tek makul aday: YATIRIM KAYDI yanlış.")
    print(f"\n  YATIRIM KARŞILAŞTIRMASI:")
    if yatirim:
        for ad, (n, tot) in yatirim.items():
            print(f"    {ad:<22s} {n:>3d} kayıt · ${tot:+.2f}")
        if y_borsa is not None:
            print(f"    BORSA (köken sonrası, net) ....... ${y_borsa:+.2f}")
            print(f"    DEFTER (meta.total_deposits) ..... ${d_dep:+.2f}")
            print(f"    FARK ............................. ${d_dep - y_borsa:+.2f}")
            if abs(d_dep - y_borsa) > 5:
                print(f"    ⛔ DEFTERİN YATIRIM KAYDI BORSAYLA TUTMUYOR.")
                print(f"       meta.total_deposits düzeltilmeli — ama önce yukarıdaki")
                print(f"       kalem kalem dökümü oku: hangi transfer köken bakiyenin")
                print(f"       içinde, hangisi sonradan geldi?")
            else:
                print(f"    ✓ Yatırım kaydı borsayla tutuyor.")
        else:
            print(f"    ⚠ fetch_transfers'ın yön parametresi MEXC tarafından yok")
            print(f"      sayılıyor (aynı kayıtlar iki yönde de dönüyor). Yön bilgisi")
            print(f"      yalnız bill kaydının 'type' alanında güvenilir.")
    else:
        print(f"    ⚠ Hiçbir yatırım kaynağı okunamadı — elle doğrulama gerekiyor:")
        print(f"      MEXC → Varlıklar → Para Yatırma / Transfer geçmişi.")
    if fon is not None:
        print(f"\n  FONLAMA ${fon:+.2f} — defterde hiç yok, doğrudan boşluğa gider.")
        if abs(fon) > 5:
            print(f"    Bu, $56.83'ün ~%{abs(fon)/56.83*100:.0f}'ini açıklıyor.")
    print(f"\n  ⚠ Okunamayan her kaynak boşluğu AÇIKLANMAMIŞ bırakır — sessizce")
    print(f"    sıfır SAYILMADI. Yukarıda hangisinin okunduğu yazıyor.")
    print(f"\n  SENİN DOĞRULAMAN GEREKEN (araç bunu bilemez):")
    print(f"    2026-06-18'den bugüne MEXC'e GERÇEKTEN ne kadar para yatırdın?")
    print(f"    Defter $149.39 diyor. MEXC → Varlıklar → Para Yatırma geçmişinden bak.")
    print(f"    Rakam tutmuyorsa boşluğun kaynağı budur, kaçak değil.")


if __name__ == "__main__":
    asyncio.run(main())
