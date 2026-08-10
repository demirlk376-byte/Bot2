"""
probe_xau2.py — ALTIN ENSTRÜMAN YOKLAMASI v2. SALT OKUNUR, emir YOK, anahtar GEREKMEZ.

probe_xau.py'nin DENETİMİ sonucu yazıldı. v1 doğru soruları soruyordu ama ALTI
ÖLÇÜMÜ ATLIYOR ve BİR HESABI YANLIŞ yapıyordu. Bu dosya onları kapatır.

v1'DE EKSİK / YANLIŞ OLAN (hepsi kodla doğrulandı):
 E1 MİN-NOTIONAL HİÇ HESAPLANMIYOR. v1 contractSize'ı yazdırıyor ama "bizim
    $237.50 nominalimiz KAÇ KONTRAT eder"i sormuyor. Bu, tek BİNARY geç/kal
    kapısı: exchange.py:679 `contracts <= 0` → ValueError → kol HİÇ işlem açmaz
    (sessizce; execution.py:625-627 hatayı yutar). Depo bu hatayı ZATEN bir kez
    yaptı: RESEARCH_LEDGER 2784, min-notional 2700× yanlış. Doğrusu:
    min_kontrat × contractSize × fiyat.
 E2 VOLATİLİTE ÖLÇÜLMÜYOR. v1'in docstring'i vol uyumsuzluğunu uzun uzun
    ANLATIYOR ama kod ATR'yi hiç hesaplamıyor — üstelik OHLCV zaten elde.
    Eşik ARİTMETİK ve KESİN: risk.py:185-194'te
        eff_risk = min(RISKF, CAP × sl_pct),  RISKF=0.0225, CAP=1.25
    → sl_pct < 0.0225/1.25 = %1.80 ise risk KIRPILIR. 22 coinde ölçülen
    ilişki (r=0.982): 2×ATR%(4h) ≈ 0.060 × yıllık_vol. Yani tavanın bağlamaması
    için yıllık vol ≥ %30 gerekiyor. Altın oraya yakın bile değil.
 E3 FONLAMA ANNUALİZASYONU YANLIŞ. v1:132 `r*3*365` = günde 3 kez VARSAYIYOR.
    MEXC'te aralık kontrata göre 8sa/4sa/1sa olabilir. 4 saatlikse gerçek yük
    2×, 1 saatlikse 8× yanlış. Aralık payload'dan OKUNMALI. Ayrıca TEK anlık
    okuma anlamsız — carry sorusu ORTALAMA ve İŞARET SÜREKLİLİĞİ, o yüzden
    fundingRateHistory gerekir.
 E4 SEANS/BOŞLUK ÖLÇÜLMÜYOR. Altın için ASIL yapısal soru bu: sembol 7/24 mum
    basıyor mu, yoksa hafta sonu duruyor mu? Üç canlı davranış buna bağlı
    (main.py:691 bitişiklik kontrolü, main.py:1192 duvar-saati max-hold,
    main.py:1376 durağanlık alarmı). ÖLÇÜM: eksik saatlik bar sayımı.
 E5 KALDIRAÇ TAVANI OKUNMUYOR. exchange.py:435-442 set_leverage'ı try/except
    içinde çağırıp hatayı yalnız DEBUG'a yazıyor; risk.py marjini her zaman
    CONFIG kaldıracıyla (10x) hesaplıyor, borsanın söylediğiyle değil. Sembolün
    tavanı 10x'in altındaysa marjin sessizce 2× olur, MAXPOS=7 sığmaz.
 E6 SPREAD TEK ANLIK ÖLÇÜLÜYOR, üstelik TEPE-KADEME. İkisi de yanlış metrik:
    (a) altının spread'i Londra saatiyle 03:00 UTC arasında uçurum farkeder,
        bot 00/04/08/12/16/20 UTC'de karar verir — birkaçı ölü saat;
    (b) doğru maliyet, $237.50'yi DOLDURMANIN defter-yürüyüşü maliyeti.
    Kripto ankoru 13.4 bp GERÇEKLEŞEN dolum kayması, tepe-spread değil.

ARTI: KONTROL TESTİ (depo dersi #5 — kendi kontrolünü geçmeyen araç güvenilmez).
Aynı ölçümler BTC/USDT:USDT üzerinde koşar ve bilinen değerlere karşı denetlenir
(contractSize 0.0001, min notional ~$6.45, 2×ATR(4h) ~%2.8). Kontrol düşerse
altın sonucu da GÜVENİLMEZ sayılır ve betik öyle raporlar.

Kullanım (VPS'te):
    cd /opt/bot2 && python3 probe_xau2.py 2>&1 | tee /tmp/probe_xau2.txt
"""
from __future__ import annotations

import datetime as dt
import sys
import time

# ── canlı boyutlandırma sabitleri (deployed_backtest.py:25-29 ile birebir) ──
BAL0 = 190.0
RISKF = 0.0225
CAP = 1.25
LEV = 10
HEDEF_NOTIONAL = CAP * BAL0            # $237.50 — tavan bağladığında pozisyon nominali
CAP_ESIK = RISKF / CAP                 # 0.0180 — bunun altındaki sl_pct kırpılır
KRIPTO_2ATR = 0.0471                   # 22 coin ort, yerel data ile ölçüldü
KRIPTO_KAYMA_BP = 13.4                 # donchian giriş kayması, ölçülmüş

ARANAN = ["XAU", "GOLD", "PAXG", "XAUT", "TGOLD", "XAG", "SILVER"]
KONTROL = "BTC/USDT:USDT"


# ── küçük yardımcılar (bağımlılık yok: numpy/pandas kullanmıyoruz) ──────────
def _atr_pct(ohlcv, p=14):
    """2×ATR / kapanış ortalaması. ohlcv = [[ts,o,h,l,c,v], ...]. Wilder EMA."""
    if len(ohlcv) < p + 5:
        return None
    tr = []
    for i in range(1, len(ohlcv)):
        h, l = ohlcv[i][2], ohlcv[i][3]
        pc = ohlcv[i - 1][4]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(tr[:p]) / p
    vals = []
    for i in range(p, len(tr)):
        a = (a * (p - 1) + tr[i]) / p
        c = ohlcv[i + 1][4]
        if c > 0:
            vals.append(2 * a / c)
    return sum(vals) / len(vals) if vals else None


def _yillik_vol(ohlcv, bar_saat):
    """Kapanış log-getirilerinden yıllıklaştırılmış gerçekleşen vol."""
    import math
    c = [r[4] for r in ohlcv if r[4] > 0]
    if len(c) < 30:
        return None
    lr = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    m = sum(lr) / len(lr)
    var = sum((x - m) ** 2 for x in lr) / max(len(lr) - 1, 1)
    return math.sqrt(var) * math.sqrt(24 / bar_saat * 365)


def _defter_yuru(book, taraf, notional):
    """$notional'ı doldurmanın orta-fiyata göre maliyeti (bp). Tepe-spread DEĞİL."""
    seviyeler = book["asks"] if taraf == "buy" else book["bids"]
    if not seviyeler or not book["bids"] or not book["asks"]:
        return None, None
    mid = (book["bids"][0][0] + book["asks"][0][0]) / 2
    kalan, maliyet, derinlik = notional, 0.0, 0.0
    for px, qty in seviyeler:
        v = px * qty
        derinlik += v
        al = min(kalan, v)
        maliyet += al * px
        kalan -= al
        if kalan <= 0:
            break
    if kalan > 0:
        return None, derinlik      # defter yetmedi
    vwap = maliyet / notional
    return abs(vwap - mid) / mid * 1e4, derinlik


def olc(ex, sym, etiket=""):
    """Tek sembol için TÜM ölçümler. Sözlük döner; eksikler None kalır."""
    r = {"sym": sym, "etiket": etiket}
    m = ex.markets.get(sym) or {}
    cs = float(m.get("contractSize") or 1.0)
    r["contractSize"] = cs
    r["aktif"] = m.get("active")
    r["tip"] = m.get("type")
    r["maker"] = m.get("maker")
    r["taker"] = m.get("taker")
    lim = (m.get("limits") or {})
    r["min_kontrat"] = ((lim.get("amount") or {}).get("min"))
    r["max_lev"] = ((lim.get("leverage") or {}).get("max"))
    r["prec_amount"] = ((m.get("precision") or {}).get("amount"))

    # fiyat
    try:
        t = ex.fetch_ticker(sym)
        r["fiyat"] = float(t.get("last") or t.get("close") or 0)
        r["hacim24"] = t.get("quoteVolume")
        info = t.get("info") or {}
        for k in ("indexPrice", "fairPrice", "markPrice"):
            if info.get(k):
                r[k] = float(info[k])
    except Exception as e:
        r["fiyat"] = 0.0
        r["hata_ticker"] = str(e)[:80]

    # E1 — min notional ve kontrat granülaritesi
    if r["fiyat"] > 0:
        mk = float(r["min_kontrat"] or 1.0)
        r["min_notional"] = mk * cs * r["fiyat"]        # ledger 2784'teki DOĞRU formül
        r["kontrat_degeri"] = cs * r["fiyat"]
        r["kontrat_sayisi"] = HEDEF_NOTIONAL / r["kontrat_degeri"]
        # taban alma sonrası nominal kaybı (risk.py floor + amount_to_precision)
        import math as _m
        n_int = _m.floor(r["kontrat_sayisi"])
        r["kuantizasyon_kaybi_pct"] = (
            (r["kontrat_sayisi"] - n_int) / r["kontrat_sayisi"] * 100
            if r["kontrat_sayisi"] > 0 else None)

    # E2 — volatilite (4h, canlı donchian'ın çalıştığı zaman dilimi)
    try:
        o4 = ex.fetch_ohlcv(sym, "4h", limit=500)
        r["n_4h"] = len(o4)
        r["atr2_pct"] = _atr_pct(o4)
        r["yillik_vol"] = _yillik_vol(o4, 4)
        if r["atr2_pct"]:
            r["eff_risk"] = min(RISKF, CAP * r["atr2_pct"])
            r["usd_per_R"] = r["eff_risk"] * BAL0
            r["kripto_orani"] = r["usd_per_R"] / (min(RISKF, CAP * KRIPTO_2ATR) * BAL0)
    except Exception as e:
        r["hata_4h"] = str(e)[:80]

    # E4 — seans/boşluk: son 30 günün saatlik barları, EKSİK bar sayımı
    try:
        since = ex.milliseconds() - 30 * 86400 * 1000
        rows, cur = [], since
        while True:
            b = ex.fetch_ohlcv(sym, "1h", since=cur, limit=1000)
            if not b:
                break
            rows += b
            if len(b) < 1000:
                break
            cur = b[-1][0] + 1
            time.sleep(ex.rateLimit / 1000)
        ts = sorted({x[0] for x in rows})
        if len(ts) > 24:
            beklenen = (ts[-1] - ts[0]) // 3_600_000 + 1
            r["bar_var"], r["bar_beklenen"] = len(ts), beklenen
            r["eksik_pct"] = (1 - len(ts) / beklenen) * 100
            # eksikler hafta sonuna mı yığılıyor?
            have = set(ts)
            hs_eksik = hi_eksik = hs_top = hi_top = 0
            for k in range(beklenen):
                t0 = ts[0] + k * 3_600_000
                wd = dt.datetime.utcfromtimestamp(t0 / 1000).weekday()
                if wd >= 5:
                    hs_top += 1
                    hs_eksik += (t0 not in have)
                else:
                    hi_top += 1
                    hi_eksik += (t0 not in have)
            r["hs_eksik_pct"] = hs_eksik / hs_top * 100 if hs_top else 0
            r["hi_eksik_pct"] = hi_eksik / hi_top * 100 if hi_top else 0
    except Exception as e:
        r["hata_1h"] = str(e)[:80]

    # geçmiş derinliği — SAYFALI (v1 limit=1500 tek atış yapıyordu, MEXC kırpar)
    try:
        rows, cur = [], ex.parse8601("2019-01-01T00:00:00Z")
        while True:
            b = ex.fetch_ohlcv(sym, "1d", since=cur, limit=1000)
            if not b:
                break
            rows += b
            if len(b) < 1000:
                break
            cur = b[-1][0] + 1
            time.sleep(ex.rateLimit / 1000)
        if rows:
            ilk = dt.datetime.utcfromtimestamp(rows[0][0] / 1000).date()
            son = dt.datetime.utcfromtimestamp(rows[-1][0] / 1000).date()
            r["gecmis_gun"] = (son - ilk).days
            r["gecmis_ilk"], r["gecmis_son"] = ilk, son
    except Exception as e:
        r["hata_1d"] = str(e)[:80]

    # E6 — defter YÜRÜYÜŞÜ (tepe-spread değil), $237.50 için
    try:
        ob = ex.fetch_order_book(sym, limit=50)
        r["saat_utc"] = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        if ob["bids"] and ob["asks"]:
            bid, ask = ob["bids"][0][0], ob["asks"][0][0]
            r["tepe_spread_bp"] = (ask - bid) / ((ask + bid) / 2) * 1e4
            r["dolum_bp_alis"], r["defter_derinlik"] = _defter_yuru(ob, "buy", HEDEF_NOTIONAL)
    except Exception as e:
        r["hata_book"] = str(e)[:80]

    # E3 — fonlama: ARALIK OKUNUR (varsayılmaz) + GEÇMİŞ ortalaması
    try:
        fr = ex.fetch_funding_rate(sym)
        r["fonlama_anlik"] = fr.get("fundingRate")
        info = fr.get("info") or {}
        saat = None
        for k in ("collectCycle", "fundingInterval", "interval", "fundingIntervalHours"):
            if info.get(k):
                try:
                    saat = float(info[k])
                    break
                except (TypeError, ValueError):
                    pass
        if saat is None and fr.get("fundingTimestamp") and fr.get("nextFundingTimestamp"):
            saat = (fr["nextFundingTimestamp"] - fr["fundingTimestamp"]) / 3_600_000
        r["fonlama_aralik_saat"] = saat        # None = BİLİNMİYOR, VARSAYMA
    except Exception as e:
        r["hata_fonlama"] = str(e)[:80]
    try:
        h = ex.fetch_funding_rate_history(sym, limit=1000)
        if h:
            v = [x["fundingRate"] for x in h if x.get("fundingRate") is not None]
            if v:
                r["fonlama_n"] = len(v)
                r["fonlama_ort"] = sum(v) / len(v)
                r["fonlama_poz_pay"] = sum(1 for x in v if x > 0) / len(v) * 100
                r["fonlama_ilk"] = dt.datetime.utcfromtimestamp(
                    h[0]["timestamp"] / 1000).date()
    except Exception as e:
        r["hata_fonlama_gecmis"] = str(e)[:80]
    return r


def yaz(r):
    p = print
    p(f"\n  ── {r['sym']} {r.get('etiket','')} ──")
    p(f"     tip {r.get('tip')} · aktif {r.get('aktif')} · contractSize {r.get('contractSize')}"
      f" · maker {r.get('maker')} taker {r.get('taker')}")
    # E5
    ml = r.get("max_lev")
    p(f"     [E5] borsa max kaldıraç: {ml}"
      + ("" if ml is None else
         ("   ✓ 10x sığar" if ml >= LEV else
          f"   ⛔ 10x YOK — risk.py marjini {LEV/ml:.1f}× DÜŞÜK hesaplar (sessiz)")))
    # E1
    if r.get("min_notional") is not None:
        p(f"     [E1] fiyat ${r['fiyat']:,.2f} · 1 kontrat = ${r['kontrat_degeri']:,.2f}"
          f" · min notional ${r['min_notional']:,.2f}")
        n = r["kontrat_sayisi"]
        p(f"          hedef ${HEDEF_NOTIONAL:.2f} → {n:.2f} kontrat"
          + ("   ⛔ 1 KONTRATTAN AZ: exchange.py:679 ValueError, kol HİÇ AÇILMAZ"
             if n < 1 else
             f"   ⚠ granülarite kaba (taban alma −%{r['kuantizasyon_kaybi_pct']:.0f} nominal)"
             if n < 5 else "   ✓ yeterli granülarite"))
    # E2
    if r.get("atr2_pct"):
        p(f"     [E2] 2×ATR(4h) = %{r['atr2_pct']*100:.2f} · yıllık vol %{(r.get('yillik_vol') or 0)*100:.0f}")
        p(f"          tavan eşiği %{CAP_ESIK*100:.2f} → eff risk %{r['eff_risk']*100:.2f}"
          f" = ${r['usd_per_R']:.2f}/R = kriptonun %{r['kripto_orani']*100:.0f}'i"
          + ("   ⛔ tavan kırpıyor" if r["atr2_pct"] < CAP_ESIK else "   ✓ kırpılmıyor"))
    # E4
    if r.get("eksik_pct") is not None:
        p(f"     [E4] son 30g saatlik bar: {r['bar_var']}/{r['bar_beklenen']}"
          f" (eksik %{r['eksik_pct']:.1f}) · hafta sonu eksik %{r['hs_eksik_pct']:.0f}"
          f" · hafta içi %{r['hi_eksik_pct']:.0f}")
        if r["hs_eksik_pct"] > 50:
            p("          ⛔ SEANSLI: hafta sonu mum YOK. Üç canlı davranış kırılır —")
            p("             main.py:691 4h bitişiklik kontrolü (donchian atlanır),")
            p("             main.py:1192 max-hold DUVAR SAATİ (backtest bar sayar → erken çıkış),")
            p("             main.py:1376 durağanlık alarmı (seyahatte HER HAFTA SONU spam).")
        elif r["eksik_pct"] < 2:
            p("          ✓ 7/24 basıyor — mevcut mum mantığı bozulmaz")
    # geçmiş
    if r.get("gecmis_gun"):
        g = r["gecmis_gun"]
        p(f"     geçmiş: {r['gecmis_ilk']} → {r['gecmis_son']} = {g} gün ({g/365:.1f} yıl)"
          + ("   ⛔ <2 yıl: TRAIN/TEST yapılamaz" if g < 730 else
             "   ~ 2-3 yıl: sınırda" if g < 1095 else "   ✓ yeterli"))
    # E6
    if r.get("tepe_spread_bp") is not None:
        p(f"     [E6] {r.get('saat_utc')} UTC · tepe spread {r['tepe_spread_bp']:.1f} bp")
        d = r.get("dolum_bp_alis")
        if d is None:
            p(f"          ⛔ ${HEDEF_NOTIONAL:.0f} defterin İLK 50 KADEMESİNE SIĞMADI"
              f" (görünen derinlik ${r.get('defter_derinlik') or 0:,.0f})")
        else:
            p(f"          ${HEDEF_NOTIONAL:.0f} dolum maliyeti {d:.1f} bp"
              f"  (kripto ölçülen kayma {KRIPTO_KAYMA_BP} bp)"
              + ("   ⛔ 2×+ pahalı" if d > 2 * KRIPTO_KAYMA_BP else
                 "   ⚠ daha pahalı" if d > KRIPTO_KAYMA_BP else "   ✓ rekabetçi"))
        p("          ⚠ TEK ANLIK. Bot 00/04/08/12/16/20 UTC'de karar verir;"
          " bu betiği o saatlerde AYRI AYRI koştur.")
    # E3
    if r.get("fonlama_anlik") is not None:
        s = r.get("fonlama_aralik_saat")
        if s:
            yil = r["fonlama_anlik"] * (24 / s) * 365
            p(f"     [E3] fonlama anlık %{r['fonlama_anlik']*100:.4f} / {s:.0f}sa"
              f" → yıllık %{yil*100:.1f}")
        else:
            p(f"     [E3] fonlama anlık %{r['fonlama_anlik']*100:.4f} —"
              " ⚠ ARALIK OKUNAMADI, yıllıklaştırma YAPILMIYOR (v1 8sa VARSAYIYORDU)")
    if r.get("fonlama_ort") is not None:
        s = r.get("fonlama_aralik_saat")
        ek = ""
        if s:
            ek = f" → yıllık %{r['fonlama_ort']*(24/s)*365*100:.1f}"
        p(f"          geçmiş n={r['fonlama_n']} ({r.get('fonlama_ilk')}'den)"
          f" ort %{r['fonlama_ort']*100:.4f}{ek} · pozitif oran %{r['fonlama_poz_pay']:.0f}")
        if r["fonlama_poz_pay"] > 80:
            p("          ⛔ TEK YÖNLÜ: long'lar neredeyse hep ödüyor — 120sa tutan trend kolu bunu yer")
    # endeks sapması
    if r.get("indexPrice") and r.get("fiyat"):
        p(f"     endeks ${r['indexPrice']:,.2f} vs son ${r['fiyat']:,.2f}"
          f" = {(r['fiyat']/r['indexPrice']-1)*1e4:+.0f} bp baz")
    p("     ⚠ PAXG/XAUT ise: bu TOKEN fiyatı. GERÇEK spot altına takip hatası"
      " BURADAN ÖLÇÜLEMEZ — ikinci bir altın kaynağı gerekir.")
    for k, v in r.items():
        if k.startswith("hata_"):
            p(f"     ! {k}: {v}")


def kontrol_testi(ex):
    """Depo dersi #5: kendi kontrolünü geçmeyen araç güvenilmez.
    Aynı ölçümleri BTC'de koş, BİLİNEN değerlerle karşılaştır."""
    print("\n" + "=" * 88)
    print("KONTROL TESTİ — aynı ölçümler BTC/USDT:USDT'de (bilinen değerlere karşı)")
    print("=" * 88)
    r = olc(ex, KONTROL, "[KONTROL]")
    yaz(r)
    gecti = []
    # ledger 2784: BTC contractSize 0.0001, min notional ~$6.45 @ $64.5k
    gecti.append(("contractSize == 0.0001", r.get("contractSize") == 0.0001))
    mn = r.get("min_notional")
    gecti.append(("min notional < $50 (ledger: $6.45 @64k)", mn is not None and mn < 50))
    a = r.get("atr2_pct")
    # yerel data ile ölçüldü: BTC 2xATR(4h) = %2.77 (2023-04..2026-07)
    gecti.append(("2×ATR(4h) %1.5-%5 arası (yerel ölçüm %2.77)",
                  a is not None and 0.015 < a < 0.05))
    gecti.append(("7/24 basıyor (eksik bar <%2)",
                  r.get("eksik_pct") is not None and r["eksik_pct"] < 2))
    gecti.append(("$237.50 defterin ilk 50 kademesine sığdı",
                  r.get("dolum_bp_alis") is not None))
    print("\n  KONTROL SONUCU:")
    for ad, ok in gecti:
        print(f"    {'✓' if ok else '✗'} {ad}")
    hepsi = all(ok for _, ok in gecti)
    print(f"\n  → {'✓ ARAÇ GÜVENİLİR' if hepsi else '✗ ARAÇ KENDİ KONTROLÜNÜ GEÇEMEDİ'}"
          f" — {'altın ölçümleri okunabilir' if hepsi else 'ALTIN SONUÇLARINA GÜVENME'}")
    return hepsi


def main():
    try:
        import ccxt
    except Exception as e:
        print(f"✗ ccxt yok: {e}")
        return 1

    print("=" * 88)
    print("probe_xau2 — ALTIN ENSTRÜMAN YOKLAMASI (SALT OKUNUR, emir YOK)")
    print(f"canlı boyut varsayımları: BAL ${BAL0} · RISKF %{RISKF*100:.2f} · CAP {CAP}"
          f" → hedef nominal ${HEDEF_NOTIONAL:.2f} · tavan eşiği sl%={CAP_ESIK*100:.2f}")
    print("=" * 88)

    ex = ccxt.mexc({"enableRateLimit": True,
                    "options": {"defaultType": "swap", "defaultSubType": "linear"}})
    try:
        ex.load_markets()
    except Exception as e:
        print(f"✗ piyasalar yüklenemedi: {e}")
        return 1

    guvenilir = kontrol_testi(ex)

    hits = sorted(s for s, m in ex.markets.items()
                  if any(k in str(m.get("base") or "").upper() for k in ARANAN))
    print("\n" + "=" * 88)
    print(f"[1] MEXC SWAP'ta ALTIN ADAYLARI: {hits or 'HİÇBİRİ'}")
    print("=" * 88)

    if not hits:
        print("  → MEXC vadelide altın YOK. Spot tarafına bakılıyor (kaldıraçsız,")
        print("    bot vadeli-perp varsayıyor: exchange.py openType/positionType,")
        print("    plan-order uçları, _to_contracts — spot'ta HİÇBİRİ geçerli değil).")
        try:
            ex2 = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "spot"}})
            ex2.load_markets()
            sp = sorted(s for s in ex2.markets
                        if any(k in s.upper().split("/")[0] for k in ARANAN))
            print(f"    SPOT: {sp or 'eşleşme yok'}")
            ex2.close()
        except Exception as e:
            print(f"    spot bakılamadı: {e}")
        print("\n  → Bu botla altın işlemek için YENİ BORSA + YENİ ENTEGRASYON gerekir.")
        print("    exchange.py MEXC'e sıkı bağlı: openType/positionType, contractPrivate*")
        print("    plan-order uçları, dealAvgPrice geri düşüşü, kod-510 kilidi (41 satır).")
        print("    RESEARCH_LEDGER kuralı: 'Seyahat öncesi KOD DEĞİŞİKLİĞİ YAPILMAZ.'")
    else:
        for s in hits[:8]:
            yaz(olc(ex, s))

    print("\n" + "=" * 88)
    print("KARAR AĞACI (sıra önemli — üsttekiler BINARY kapı):")
    print("  E1 kontrat < 1        → kol hiç açılmaz. DUR.")
    print("  E5 max kaldıraç < 10x → marjin muhasebesi sessizce bozuk. DUR.")
    print("  E4 hafta sonu bar yok → 3 canlı davranış kırık + seyahatte alarm spam'i. DUR.")
    print("  geçmiş < 3 yıl        → TRAIN/TEST yok; bu depoda hiçbir şey kabul edilmedi. DUR.")
    print("  E2 2×ATR% < %1.80     → tavan kırpar; $/R kriptonun yarısı. Ölçüp BEKLENTİYİ düşür.")
    print("  E6 dolum > 27 bp      → kripto kaymasının 2 katı; edge büyük ihtimalle yenir.")
    print("  E3 fonlama %80+ poz.  → tek yönlü carry; 120sa tutan trend kolu yer.")
    print(f"\n  ARAÇ KONTROLÜ: {'GEÇTİ' if guvenilir else 'DÜŞTÜ — yukarıdaki altın sayılarına güvenme'}")
    print("=" * 88)
    try:
        ex.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")
        sys.exit(1)
