# Devir Raporu — Bot2 (2026-09-26)

Bu rapor, bota ikinci bir teknik inceleme ekibinin katılması için hazırlandı. Amaç,
şimdiye kadarki araştırmanın **dayanaklarını**, **kanıt düzeyini** ve **eksiklerini**
aktarmak. Bu turda canlı kod, ayarlar, emirler ve çalışan süreçler değiştirilmedi; yeni
filtre, optimizasyon veya backtest başlatılmadı.

Kaynak dosyalar: `RESEARCH_LEDGER.md` (araştırma defteri), `DURUM.md` (sistem durumu),
`erken_uyari.py`, `ikiz/`, `ikiz_paralel.py`, repo kökündeki `ikiz_*_islemler.csv` ve
bu turun analiz betikleri: `arastirma/2026-09-26/` (bkz. oradaki README).

**Kanıt etiketleri:**
- **[D]** doğrudan doğrulanabilir: repodaki veri ve kodla yeniden üretildi.
- **[V]** yöntem varsayımına bağlı: null model, bootstrap, simülasyon.
- **[E]** eksik: veri yok ya da test yapılmadı.

---

## 1. Güncel bot ve araştırmanın kapsamı

### 1.1 Canlı stratejiler

Kaynak: `.env` (2026-09-26, VPS, gizli satırlar hariç), `strategies/*.py`, `main.py`,
`execution.py`, `risk.py`, `config.py`.

**Donchian** — `strategies/donchian.py`
- Zaman dilimi: 4h. Analiz her 4h kapanışında çalışır (1h döngüsü içinden).
- Coinler: SOL, ETH, ADA, NEAR, BCH, ICP, BNB.
- Long: 4h mum, önceki 40 barın en yükseğinin **üstünde kapanır** (kırılım barı hariç)
  ve kapanış > EMA200(4h).
- Short: 40 barın en düşüğünün altında kapanır ve kapanış < EMA200(4h).
- Ek kapılar (canlıda açık):
  - Hacim: `DONCHIAN_VOL_MULT=2.5`, tanımı 1.2'de.
  - Günlük trend hizası: `DONCHIAN_MTF=true`. Günlük kapanış, günlük EMA20'nin
    üstündeyse yalnız long, altındaysa yalnız short (`main.py:1146-1156`).
- Giriş: sinyal barının kapanışında **market** emir (`force_market`).
- Stop: giriş ∓ 2.0×ATR(14, 4h). Hedef: giriş ± **2.5**×stop mesafesi (`DONCHIAN_RR=2.5`).
- Çıkış: stop veya hedef (borsada bekleyen SL/TP emirleri) ya da **120 saat** max-hold
  (`execution.py`, `DONCHIAN_MAX_HOLD` varsayılanı 120).
- Stop taşıma yok: `STOP_MOVE_ENABLED=true`, ama BE/trailing yalnız kapalı orb/ifvg
  kollarına uygulanıyor (`main.py:1103`, ledger L1404-1408).

**Squeeze** — `strategies/squeeze.py`
- Zaman dilimi: 1h. Coinler: XRP, DOGE, XLM (TRX 09-22 kararıyla çıkarıldı).
- Kurulum: Bollinger(20, 2.0), Keltner kanalının (EMA20 ± 1.5×ATR) içinde ≥5 bar kalır.
  BB kanal dışına çıktığında sinyal oluşur.
- Yön: kapanış > EMA20 ise long, < ise short (`SQUEEZE_MOD=orta`, varsayılan).
- 4h teyidi: 4h kapanış, 4h KC orta çizgisiyle aynı tarafta olmalı (`SQUEEZE_MTF`,
  varsayılan açık).
- Rejim kapısı: 1h **ADX ≤ 20 ("ranging") ise squeeze girişi yok**
  (`main.py:273, 633`; `REGIME_FILTER_ENABLED` varsayılan açık).
- Giriş: sinyal kapanışında market emir.
- Stop: ∓2.0×ATR. Hedef: ±2.5×stop mesafesi.
- Çıkış: stop, hedef veya **48 saat** max-hold.

**Mean-reversion / BB** (diğer etkin strateji) — `strategies/mean_reversion.py`
- 1h, yalnız LTC ve yalnız **hafta sonu** (`BB_WEEKDAY_ENABLED=false`).
- Giriş: kapanış Bollinger(20, 2) bandının dışında ve hacim 20 bar ortalamasının
  üstünde (`VOL_FILTER_ENABLED=true`). Hareketin **tersine** işlem açılır.
- Rejim kapısı: ADX ≥ 28 ("trending") ise BB girişi yok.
- Stop: 3×ATR. Hedef: 5×ATR (RR 1.667). Max-hold 48 saat.
- Giriş: maker limit (`MAKER_ENTRY=true`), dolmazsa market.

**Portföy kuralları**
- Kaldıraç 10×, izole marjin, en fazla 7 pozisyon.
- Coin başına tek pozisyon: MEXC tek-yön modu (`tests/test_one_per_symbol.py`).
- Ardışık 2 kayıpta ilgili `strateji:coin` anahtarı 240 dk bekler. Değerler kod
  varsayılanı; `.env`'de satır yok.
- Günlük zarar %35'e ulaşırsa durma ve tüm pozisyonları kapatma.
- Marjin, serbest bakiyenin %95'ini aşarsa işlem reddedilir (`execution.py:663`).
- Kapalı olanlar: ORB, FVG, IFVG, S/R, Asia, whale, yapı. Portföy stopu ve aynı yön
  kısıtı: 0 (kapalı).

### 1.2 Hacim 2.5, risk %3.5 ve CAP 2.5 kodda ne demek

- **Hacim 2.5** (`donchian._hacim_tamam`): kırılım barının hacmi, **önceki 20 4h barın
  ortalama hacminin** 2.5 katından büyük olmalı. Değilse sinyal atılır.
- **Risk %3.5** = `MAX_RISK_PCT (0.02) × RISK_SCALE (1.75)`. Hedef zarar tutarı
  **equity × 0.035**. Equity = serbest bakiye + kilitli marjin + gerçekleşmemiş PnL
  (`execution.py:541-546`; boyutlama `sizing_balance = equity`).
- **CAP 2.5** = `POSITION_CAP_FRACTION`. Birimi **equity'nin katı olarak pozisyon
  büyüklüğü (notional)**; kaldıraç veya risk değil. Hesaplama (`risk.py:185-194`):

```
miktar_risk = (equity × 0.035) / (giriş × stop_mesafesi_%)
miktar_cap  = (equity × 2.5) / giriş             # notional ≤ 2.5 × equity
miktar      = floor(min(miktar_risk, miktar_cap), 0.001)
```

  Sonuç olarak gerçekleşen risk = **min(%3.5, 2.5 × stop_%)**. Stopu %1.4'ten dar olan
  işlemlerde CAP bağlar ve risk %3.5'in altına düşer. Marjin = notional / 10.

### 1.3 Canlı sürüm ile araştırılan sürüm

- **Kod:** İkiz, repodaki botun kendisidir (aynı `main.py`, `execution.py`,
  stratejiler). 26 Eylül'de ikiz ayarları canlı `.env` ile eşitlendi (31 anahtar).
  - Canlı bot süreci 2026-09-26 12:31:45 UTC'de başladı; o anki diskteki kodla çalışıyor.
  - Araştırma koşuları ondan sonraki commit'lerle yapıldı.
  - Aradaki işlem yolu farkları: `DONCHIAN_MAX_HOLD` env'i (varsayılan 120, davranış
    aynı) ve portföy-stopu soğuma saatinin düzeltilmesi (özellik canlıda kapalı).
  - Yani **işlevsel olarak aynı, bayt olarak doğrulanmadı [E]**.
  - Doğrulamak için: VPS'te `git -C /opt/bot2 log -1` ile bu repodaki commit karşılaştırılır.
- **⚠ 26 Eylül öncesi ikiz sonuçları farklı bir botu ölçtü.** İkiz `DONCHIAN_RR`'yi
  almadığı için donchian'ı 2.0R hedefle koşuyordu; canlı 2.5R kullanıyor (2026-07-21'den
  beri). Ledger'da o tarihten önceki bütün İKİZ hükümleri bu hatayla verildi. Doğru ikiz
  bu raporun temelidir.
- **Tarih aralıkları:**
  - Veri: 1h mumlar, 2023-04-06 → 2026-07-19.
  - Bölme, çıkış zamanına göre: **TRAIN** 2025-01-01'den önce (538 işlem), **TEST**
    2025-01-01 → 2026-07-19 (398 işlem).
  - Canlı: ilk işlem 2026-06-18. Canlı ile ikiz 06-18 → 07-19 arasında örtüşüyor.

### 1.4 "İkiz" nasıl üretiliyor, canlıdan nerede ayrılıyor

`ikiz/kos.py` + `ikiz_tam.py`:
- Botun `main()` kurulumunu aynen çalıştırır.
- Sonra her tarihsel 1h/4h mum için `main.on_candle_close`'u çağırır.
- `datetime.now` sanal saatle değiştirilir; mum kapanışından önce bilgi verilmez.
- Emirler `PaperExchange`'e gider.
- Başlangıç bakiyesi **$10,000**, kârlar bileşiklenir.

| konu | ikiz | canlı |
|---|---|---|
| Giriş kayması | **sabit 15.85bp** (canlıda n=54 ile ölçüldü, %95 [8.3, 23.4]) | değişken. Son 60 market girişinde 10.0bp [4.4, 15.5] (erken_uyari). Hacme bağlılığı ölçülmedi [E] |
| Çıkış kayması, ücret | 0.24bp; taker 1bp/taraf; maker 0 | gerçek dolum |
| Funding | **pnl'de yok.** `PAPER_FUNDING=true` verildiği halde fonlamasız yeniden hesap 1e-14 tutuyor. Tahmini gerçek etki −0.003R/işlem | var |
| Mum içi sıra | aynı 1h mumda hem stop hem hedef değerse **önce stop** (kötümser) | borsadaki SL/TP emirleri tick sırasıyla |
| Zamanlama | mum kapanışında anında | 30 sn'lik poll ve ağ gecikmesi |
| Hesap büyüklüğü | $10k'dan ~$790k'ya. Min-emir yuvarlaması ve büyük notional kayması yok | $280-373. Yuvarlama, min emir ve deposit etkileri var |
| Operasyon | kesinti, restart, API hatası, hayalet pozisyon yok; soğuma durumu kalıcı | restart'ta soğuma durumu sıfırlanır (ledger L5706) |
| Kayıt | SL/TP çıkış zaman damgası 1 bar geç (P&L'i etkilemez) | — |
| Orderflow | kapalı (ağ yok) | `monitor` modunda: yalnız log, BB kararını değiştirmez |

---

## 2. Önceki sonuçların kanıtı

### 2.1 R'nin tanımı

Bu turdaki bütün analizler (ve `erken_uyari.py`) şu tanımı kullanır:

```
R_net = pnl_usdt / (quantity × |intended_entry − sl0|)
```

- **Net:** ücret ve giriş/çıkış kayması dahil, funding hariç (ikizde yok).
- **Payda:** kaymasız sinyal fiyatındaki ilk stop mesafesi.
- Tabloda aksi yazmadıkça "R" **işlem başı ortalama** net R'dir; "toplam" açıkça belirtilir.
- İkiz CSV'sindeki `R` sütunu farklı bir büyüklüktür (kaymalı dolumdan brüt, 0.40R'ye
  kadar sapar); analizlerde kullanılmadı.
- **Brüt R:** kaymasız ve ücretsiz fiyat hareketi / aynı payda.

Veri: `ikiz_k25_cap25_islemler.csv`, **936 işlem**: donchian 412, squeeze 368,
mean_rev 156.

### 2.2 İddialar tablosu

| İddia | Veri, n | Yöntem | Sonuç / belirsizlik | Kaynak |
|---|---|---|---|---|
| Hedef stoptan önce ~%35 vuruluyor; rastgele girişte ~%26-29 | k25_cap25. Hedef veya stopla biten işlemler: donchian 319, squeeze 307, mean_rev 124 | Gerçekleşen TP payı, iki null ile kıyaslandı: (i) teorik suruklenmesiz 1/(1+RR) = %28.6 (RR 2.5 için); (ii) sonlu süreli simülasyon, aynı coin, rastgele zaman/yön, stop yerel ATR14'e ölçekli | Gerçek: **%35.4 / %34.5 / %44.4**. Null (ii), doğrulayıcı: %25.5 / %25.5 / %34.5. Analistin ilk null'u %22.9 / %25.8 / %35.1 idi. Hafta-kümeli bootstrap P(TP payı ≤ teorik): 0.016 / 0.024 / 0.063. **[D]** gerçek pay, **[V]** null | `edge/attr/attrib.py`, `edge/review` |
| ~70 "fazla kazanan" kârı açıklıyor | aynı | Fazla TP = gerçek − null(ii) × çözülen işlem | **+32 / +28 / +12 = ~72** (ilk null ile 78). "Kârı açıklar" ifadesi **kaba bir tutarlılık kontrolü**: 72 × ~3.45R ≈ 248R, net toplam 183.9R + maliyet ~57R ≈ 241R ile aynı büyüklükte. Resmi ayrıştırma değil; 186 max-hold çıkışı (ort +0.37R) ayrı bir kalem, rastgele girişler de max-hold'da benzer R alıyor. **[V]** | `edge/attr/attrib_out.txt` |
| Sinyalin yönü +0.19R; genel piyasa ~0 | 936 işlem, bar-bar yeniden simülasyon (ikizi 936/936 birebir üretiyor) | Plasebolar (bkz. 2.3). Ay-kümeli bootstrap güven aralıkları | Yön (gerçek − a): **+0.190R [+0.103, +0.272]**. Piyasa sürüklenmesi (d − c): **+0.009 [+0.002, +0.017]**. Geometri + maliyet (c): −0.053R (maliyetsiz +0.008). Geç giriş (gerçek − b_ileri): +0.253 [+0.154, +0.349]. **[V]** | `edge/sim.py`, `placebo.py`, `analyze.py`, `new_report.txt`; doğrulayıcı `edge/rv_placebo/` |
| 11/11 coin ve iki yön kârlı | 936 işlem | Coin ve yön bazında ortalama R. Coin farklarına permütasyon testi | **Nokta tahminleri** 11/11 coinde ve iki yönde pozitif. Tek tek anlamlılık **iddia edilmiyor**. Short +0.220 [+0.054, +0.378]; long +0.168 [+0.013, +0.316]; squeeze-long +0.051 [−0.21, +0.31] (sıfırı içeriyor). Coin farkları şans içinde (p 0.50 / 0.92). ⚠ Evren seçilmiş: aynı ayar 19 ve 31 coinde kaybediyordu (ledger). **[D]** | `edge/attr/attrib_out.txt` |
| Squeeze'de maliyet brüt kârın %42'si; net avantaj kanıtlanmamış | 368 squeeze işlemi | Brüt ve net R, hafta-kümeli bootstrap | Brüt **+0.254 [+0.069, +0.433]** → net **+0.147 [−0.031, +0.323]**. Maliyet 0.107R (kayma 0.094 + ücret 0.012). Stoplar dar (medyan %1.87) olduğu için 15.85bp büyük bir R'ye denk geliyor. ⚠ Kayma ikizde sabit bir model; canlıdaki son ölçüm 10bp. Oran bu varsayıma bağlı. **[D]** hesap, **[V]** kayma modeli | `edge/attr/attrib_out.txt` |
| Hacim filtresinin elediği 801 donchian işlemi +0.135R | `ikiz_k25_eski` (filtresiz; risk %2.8, CAP 1.5, TRX'li) ile k25_cap25 karşılaştırması. Yalnız donchian, R cinsinden | (sembol, yön, giriş zamanı) ile eşleştirme; oranın yeniden kurulumu birebir | Filtresizde 1107, filtreli 412 donchian işlemi. Elenen (oran < 2.5): **801** (TRAIN 390 / TEST 411), **ort +0.135R**. Güven aralığı iid [+0.034, +0.236]; hafta-kümeli [−0.008, +0.280], tek yönlü p = 0.031. Elenen eksi geçen: TRAIN −0.16R (p 0.08-0.11), TEST +0.02R (p ≈ 0.5). En küçük saptanabilir fark ~0.34R. **[D]** | `edge/volfilter_audit.py`, `volfilter_tests.csv` (arşivlenmedi, betik üretir) |

### 2.3 Rastgele giriş karşılaştırmalarında neler eşleştirildi

| plasebo | coin | zaman | yön | stop mesafesi | hedef/süre (RR, max-hold) | maliyet | eşzamanlılık |
|---|---|---|---|---|---|---|---|
| a: yön rastgele | aynı | **aynı bar** | yazı-tura (beklenti tam hesap: (R + R_ters)/2) | aynı | aynı | aynı | yok |
| c: tamamen rastgele | aynı | aynı yarıda (TRAIN/TEST) düzgün rastgele | yazı-tura | aynı stop_% (doğrulayıcı ayrıca ATR'ye ölçekli sürüm koştu) | aynı | aynı | yok |
| d: yön aynı, zaman rastgele | aynı | aynı yarıda rastgele | **gerçek yön** | aynı | aynı | aynı | yok |
| b_ileri: geç giriş | aynı | 1-30 gün **sonra** | gerçek yön | aynı | aynı | aynı | yok |

- **Eşleştirilmeyenler:**
  - Portföy kısıtları: koltuk, coin başına tek pozisyon, CAP/marjin.
  - Bileşiklenme ve pozisyon büyüklüğü (analiz işlem başı R üzerinden).
  - Gerçek pozisyon süreleri (süreyi aynı braket belirliyor, eşlenmedi).
  - Funding.
  - Eşzamanlı pozisyon yoğunluğu.
- **Sonuç:** Plasebolar **işlem başı R'yi** açıklıyor, equity eğrisini değil. Risk
  ağırlıklı sürüm aynı tabloyu verdi.
- **"En sıkı istatistik düzeltme":** Plasebo doğrulamasında ~50 test üzerinde **Bonferroni**
  uygulandı (12 grup × 9 plasebo; eşik 0.05/50 = 0.001).
  - Geçen üçü: tam örneklemde yön (gerçek − a), gerçek − d ve gerçek − b_ileri.
    Hepsinin p değeri < 0.00025 (ay-kümeli bootstrap).
  - Geçmeyenler: yönden bağımsız zamanlama etkisi (a − c = +0.060, p 0.006-0.019),
    TEST'e özel ve kol bazındaki sonuçlar.
  - Piyasa analizinde ayrıca Holm düzeltmesi kullanıldı. Örneğin donchian ile |BTC| arasındaki
    ilişki bu düzeltmeden sonra anlamsız.
- **"Hindsight" düzeltmesi:** Simetrik ±30 gün kaydırma geçmişe bakıyordu; kırılım yönü,
  önceki hareketin işaretidir. Bu yüzden yalnız **ileri** kaydırma kullanıldı.
  - Aynı yönde gecikmeli giriş: donchian +1s +0.23, +4s +0.19, +12s +0.13, +24s +0.07,
    +48s +0.02R.
  - Squeeze: +1s +0.07, +4s −0.03R.

---

## 3. Kayıp serileri ve düşüş simülasyonu

### 3.1 Modeller

Seri, k25_cap25'in **çıkış sırasındaki** 936 işlemi. İşlem getirisi = pnl / çıkış
öncesi gerçekleşmiş equity; bu seri ikizin ×79.2 equity yolunu birebir üretiyor.

- **Model A:** İşlem sonuçları sabit çıkış yuvaları üzerinde **tek tek** karıştırılır.
  5000 permütasyon; her yuva kendi takvim ayını korur.
- **Model B:** **Aynı gün açılan** işlemler 599 blokta birlikte tutulur ve bloklar
  karıştırılır. 5000 permütasyon. Aynı gün, farklı coin pozisyonlarının bağımlılığını
  (işlem düzeyinde +0.38 korelasyon) korur.
- **Ek kontroller:** C: ay-blok bootstrap. D: ay sırası permütasyonu. Doğrulayıcı ayrıca
  durağan blok bootstrap (ortalama blok 20 işlem) koştu.
- **Günler arası bağımlılık** A ve B'de korunmuyor. Ölçülen değer küçük ve negatif:
  haftalık R'nin lag-1 korelasyonu −0.127. Ay-blok modeli (C) bunu kısmen içeriyor.

### 3.2 Soruların cevapları

- **"13 kayıplık seri için %23":** 936 işlemlik geçmişin tamamında, en uzun ardışık
  zararlı işlem (R < 0) serisinin **en az 13** olma olasılığı.
  - Model A: 0.22-0.23 (20.000 iid simülasyon ve Schilling formülü de 0.23; beklenen
    en uzun seri 11.2).
  - Model B: 0.39. Doğrulayıcı notu: gözlenen seri aynı-gün sırasına dizilince 11 oluyor
    ve p = 0.74.
  - Gerçek seri: 2026-04-18 → 05-04 (12 stop, 1 max-hold).
- **Eşzamanlılık, değişen hesap, %3.5 risk ve CAP:** Bunlar ikizin kendi pnl'inde zaten
  var. Her işlem, girişteki equity ile gerçek kurallarla boyutlanmış.
  - Null modeller **yeniden simüle etmiyor**; yalnız işlem sonuçlarının **sırasını**
    değiştiriyor.
  - Karıştırmada boyut, equity'nin sabit bir yüzdesi gibi davranıyor.
  - Koltuk, marjin ve eşzamanlılık kısıtları yeniden koşulmadı **[V]**.
- **Hangi equity serisi:** **Gerçekleşmiş**, kapanan işlemler çıkış sırasıyla.
  **Açık pozisyonların gerçekleşmemiş zararı dahil değil [E].** Gerçek (mark-to-market)
  düşüş %46'dan büyük olabilir.
- **Düşüş dağılımı (maxDD):**

| | %5 | %50 (medyan) | %95 | P(null ≥ gözlenen) |
|---|---|---|---|---|
| Gözlenen | | **%46.0** (veri sonunda hâlâ açık) | | |
| Model A | %42.4 | **%54.5** | %70.8 | 0.86 |
| Model B | %47.4 | **%60.4** | %76.2 | 0.97 |

  "%55-60" bu iki modelin **medyanıdır**. Gözlenen yol, karıştırılmış yolların çoğundan
  hafif. Bu yalnız eldeki yolun bir özelliği; **gelecek için bir olasılık ya da kabul
  edilmesi gereken risk seviyesi değil.**
- **Diğer istatistikler:**
  - En kötü 20/50 işlem penceresi: p 0.90-0.99.
  - Çok ölçekli tarama: p 0.43 (A) / 0.70 (B).
  - Negatif ay: 13/40 (A p = 0.66, B p = 0.79). Ay-ay dağılma p = 0.57.
  - Tek nominal uç, en kötü 10 işlem penceresi: −11.0R, A p = 0.014. Sağlam değil: B'de
    0.078, blok bootstrap'ta 0.49, Bonferroni'yi (14 istatistik) geçmiyor.
- **"Filtre kaldırılınca %71":** Ablasyon koşusu `a_filtresiz`.
  - Aynı dönem, aynı maliyet modeli, aynı %3.5 risk, CAP 2.5, RR 2.5, TRX'siz;
    **tek fark `DONCHIAN_VOL_MULT=0`**.
  - %70.7 **TEST yarısının** maxDD'si (TRAIN %53.2).
  - `ikiz_donem_analiz.olc` ile gerçekleşmiş equity üzerinden; TEST, TRAIN sonu
    bakiyesinden başlar.
  - Tek bir tarihsel yol; belirsizlik aralığı yok **[D]** / **[E]**.
- **İki ifadenin ayrımı:**
  - "Test edilen modeller altında olağandışı bulunmadı" — **kanıtlanan bu**.
  - "Nedenin yalnız rastgelelik olduğu kanıtlandı" — **kanıtlanmadı.** Null modeller
    gözlenen R dağılımını (kötü dönemler dahil) yeniden kullanıyor. Sırayı ve kümelenmeyi
    test ediyorlar, edge'in sabit olduğunu değil. ~0.3R'den küçük bir ortalama düşüşü
    göremezler.
- **Açık uyarı:** İkiz verisinin son 30 işlemi (2026-06-08 → 07-19, ort −0.57R)
  değişim-noktası testinde sınırda: p 0.04-0.05 (A), 0.11 (B). 30 işlemle gürültü ile
  edge kaybı ayrılamaz; veri, düşüş açıkken bitiyor.

---

## 4. Canlıdaki 112 işlem

Kaynak: kullanıcının VPS'te 2026-09-26'da koştuğu `erken_uyari.py` çıktısı (ekran
görüntüsü). **Canlı veritabanı bu incelemeye verilmedi.** Aşağıdaki boşluklar bu yüzden.

| bilgi | durum |
|---|---|
| Kapsam | 112 kapanmış işlem, **yalnız etkin kollar** (donchian, squeeze, mean_rev). 36 eski orb/fvg/asia/sr işlemi hariç |
| Tarih | 2026-06-18 → 2026-09-23 (çıkış) |
| Ort. net R | **+0.295**. Aralık [+0.027, +0.563]: **iid t-aralığı**, işlemler arası bağımlılık hesaba katılmadı |
| Toplam net R | ≈ +33.0R (112 × 0.295; türetilmiş) |
| Kol ve yön ayrımı | **[E] yok.** Ledger'daki 09-13 tablosu (125 işlem, tüm kollar): donchian 56, squeeze 19, mean_rev 14, eski kollar 36 |
| Parasal PnL | Ekran görüntüsünde yok. Repodaki son kayıt (09-23 `/status`): yatırılan $280.38, equity $373.17, kâr +$92.79. Tüm kollar ve açık pozisyonlar (+$16.15) dahil |
| Maliyet | Son 60 market girişinde kayma 10.0bp [4.4, 15.5]. Ücret ve funding ayrımı **[E]** |
| Düşüş | Aracın "birim değer" DD'si −%14.2 (şimdi), −%40.8 (en büyük). Bu, **bugünkü** %3.5/CAP 2.5 boyutlamasının geriye uygulanması; gerçek hesap düşüşü değil. Gerçek hesap: 08-17 olayı $380 → $278 (−%26.8, DURUM) |
| Bağımlılığa dayanıklı aralık | **[E] hesaplanmadı** |

**Bu dönemdeki sürüm değişiklikleri** (işlemlerin hangi sürüme ait olduğu işlem bazında
eşlenmedi [E]):
- 06-18 → 07-21: donchian RR 2.0 (sonra 2.5).
- 07-16/17: orb/fvg/asia/sr kapatıldı.
- 07-22: risk %2.25. 08-12: CAP 1.25 → 1.5. ~09-07: risk %2.8.
- 09-09 → 09-14: donchian maker giriş, sonra market.
- **~09-22: hacim 2.5 + risk %3.5 + TRX çıkarıldı.** Kesin uygulama saati kayıtlı değil;
  `.env`'in son değişikliği 09-26 12:31.
- **09-26: CAP 2.5.** 112 işlemin penceresinden sonra.

Sonuç: 112 işlemin çok büyük kısmı **bugünkü ayarla değil**; filtresiz, daha düşük risk
ve TRX'li ayarlarla açıldı.

**Bağımsızlık uyarıları:**
- (a) Eski kollar kısmen **canlıdaki kötü sonuçlarına bakılarak** kapatıldı. Onları
  dışarıda bırakan +0.295, sonradan seçilmiş bir alt kümedir. Aynı dönemin tüm kollu
  ölçümü (09-12, n=124, farklı R tanımıyla: fiyattan brüt) **+0.084 [−0.15, +0.32]** idi.
- (b) Canlı ile ikiz 06-18 → 07-19 arasında örtüşüyor.
- (c) Defter PnL'inin borsadan fazla yazdığı bir dönem oldu ($62.80, kısmen izlendi).
- Bu nedenlerle canlı veri **bütünüyle bağımsız bir doğrulama sayılmamalı.**

---

## 5. Kazancı geri verme ve filtrenin işlevi

### 5.1 A / B / C ayrımı

Mevcut araştırma bu soruyu **doğru ikiz üzerinde cevaplamıyor [E].**

- İkiz her işlem için MFE/MAE (açıkken ulaşılan en iyi/en kötü nokta) kaydetmiyor.
- Düşüş analizleri gerçekleşmiş equity üzerinden. Açık pozisyonlardaki kâr erimesi
  görünmüyor.

Kısmi dayanaklar (farklı veri ya da tek olay):
- **A için (tek canlı olay):** 2026-08-17'de 6 pozisyon birlikte stop oldu; kaybın yarısı
  açık kârın geri verilmesiydi (DURUM L787-812).
- **A'nın sınırı (eski, maliyetsiz ankor):** Stop olan işlemlerin %76.5'i hiç +1R'ye
  ulaşmamıştı (ledger L960-974, `mfe_anatomy.py`). Yani işlem başına büyük açık kârın
  geri verilmesi o veride nadir.
- **B için:** Doğru ikizin en büyük iki düşüşü, kazanma oranının %20-28'e indiği stop
  serileri (episodes). Bu B ile tutarlı, ama A'yı dışlamıyor.
- **Çıkış testleri:** Breakeven ve trailing İKİZ'de (RR 2.0 ile) reddedildi:
  BE −3.30/−1.73.

Cevap için gerekenler (bkz. 7. bölüm, kontrol 2):
- Mevcut bar simülatörüyle 936 işlemin MFE/MAE'si.
- Mark-to-market equity serisi.

### 5.2 Hacim filtresi ile rastgele eleme

- **Eşitlenen:** Yalnız **işlem sayısı**. Filtresiz donchian işlemlerinden her yarıda
  filtrenin bıraktığı kadar (TRAIN 179, TEST 127) rastgele işlem tutuldu; 2000 çekiliş.
  Doğrulayıcı ayrıca coin tabakalı bir sürüm koştu.
- **Eşitlenmeyen:**
  - Toplam risk (aynı formülle boyutlandı ama tutarlar eşlenmedi).
  - **Eşzamanlı pozisyon yoğunluğu.**
  - Boşalan coin koltuğuna giren yeni işlemler (null, koltuk doluluğunu sabit tuttu).
  - Rastgele eleme ikizde **yeniden koşulmadı**; R tabanlı bir defter simülasyonu
    kullanıldı (ikizi ~%6 farkla üretiyor).
- **"Seçim mi, maruziyet mi" ayrımının dayanağı:**
  1. İşlem düzeyi: elenenler ile geçenler arasında iki yarıda da anlamlı fark yok.
     TRAIN −0.16R (p 0.08-0.11), TEST +0.02R. Oranla R arasındaki sıra korelasyonu ~0.
  2. Portföy düzeyi: filtrenin seçtiği alt kümenin MAR'ı rastgele alt kümelerin
     dağılımının içinde (P = 0.27 / 0.51). Rastgele eleme de düşüşü %92 (TRAIN) ve
     %99.7 (TEST) oranında azaltıyor.
  3. TRAIN'de canlı düşüş iyileşmesinin ~%83'ü boşalan koltuğa giren yeni işlemlerden
     (+0.268R) geliyor.
- **Sınırlar:**
  - Saptanabilir en küçük fark ~0.34R; küçük bir seçim etkisi dışlanamaz.
  - Eşzamanlılık eşleşmediği için "tamamen maruziyet" ifadesi **[V]**.
  - Filtre ~30-60 ayar içinden TEST'e bakılarak seçildi.

---

## 6. İzleme: `erken_uyari.py`

- **Veri:** `trades.db`, salt okunur. Kapanmış canlı işlemler (`is_paper=0`), isteğe
  bağlı `--bas`; yalnız etkin kollar.
- **Etki:** **Yalnız rapor ve uyarı üretir; emir göndermez, canlı işlemi etkilemez.**
  Aylık `sentinel.py --dogrula` Telegram mesajına bir satır ekler.
- **Ölçüler ve eşikler:**
  1. **R-CUSUM:** `S = max(0, S + 0.09 − R_net)`, S > 35 → ALARM. Pencere yok; tüm geçmiş
     boyunca birikir. k = 0.09, sağlıklı ikiz ort R'sinin (~0.18) yarısı.
  2. **Birim değer:** Her işlem `R_net × min(risk, CAP × stop_%)` ile bileşiklenir. Risk
     ve CAP o anki `.env`'den alınır ve **tüm geçmişe uygulanır**. Deposit etkisi yok.
     - Bantlar: <%40 olağan, <%48 "5 yılda bir", <%60 "20 yılda bir", ≥%60 kırmızı
       çizgi (ALARM).
  3. **Yürütme:** Son 60 market girişinde kayma. %95 alt sınır 15.85 + 1bp'yi aşarsa
     uyarı. Son 30 günde R < −1.5 olan işlem ya da kapalı koldan işlem varsa uyarı.
- **Eşiklerin belirlendiği veri:** Canlı ile birebir ikiz (k25_cap25, 936 işlem).
  - Ay-blok bootstrap, 3000 yol, 24 ay. Edge senaryoları: %100 / %75 / %50 / %0 / −0.10R.
  - Birleşik alarm: sağlıklıyken 12 ayda %3.2, 24 ayda %9.1 yanlış alarm.
  - Edge sıfırsa: 24 ayda %94, medyan 9. ay. −0.10R ise medyan 6. ay.
  - İkizin kendi 40 ayında CUSUM tepe değeri 19.1 (eşiğin %55'i).
- **Tekrarlanan kontroller:** Simülasyonda alarm **her işlemden sonra** kontrol edildi.
  Yani %3.2 / %9.1 sürekli izlemedeki ufuk olasılığıdır; aylık bakmak bunu artırmaz.
  Ama ufuk uzadıkça birikir (yaklaşık %9'dan sonrası ölçülmedi).
- **Varsayımlar:**
  - İkizin R dağılımı canlıyı temsil ediyor.
  - Aylar bağımsız.
  - k = 0.09 sabit.
  - Birim değer düşüşü geriye dönük bugünkü boyutla hesaplanıyor.
  - Eski kural "3 ay üst üste negatif → dur" sağlıklı botta 12 ayda ~%24 alarm veriyordu;
    DURUM'da "not et, bekle"ye indirildi.

---

## 7. Özet

### Doğrudan doğrulanabilen bulgular [D]

- Canlı ile birebir ikiz: 936 işlem, net +0.197R/işlem. Hafta, ay ve çeyrek kümeli
  güven aralıkları sıfırı dışlıyor.
- Bar simülatörü ikizi 936/936 işlemde birebir üretiyor.
- Kazanma oranı %42.9, başa baş %35.8. Maliyet brüt edge'in %24'ü, squeeze'de %42'si
  (kayma modeline bağlı).
- 26 Eylül öncesi İKİZ hükümleri donchian RR 2.0 ile verildi. Düzeltilmiş ikizde canlı
  ayarın beş kararından her biri tek tek geri alındığında iki yarıda da kötüleşiyor.
- Hacim filtresinin elediği 801 donchian işleminin ortalaması pozitif (+0.135R).
  Elenenler ile geçenler arasında istatistiksel fark gösterilemedi.
- Filtresiz ablasyonda TEST düşüşü %70.7.
- CAP'in tanımı: notional ≤ 2.5 × equity; gerçekleşen risk = min(%3.5, 2.5 × stop_%).

### Yöntem varsayımına bağlı çıkarımlar [V]

- Edge'in kaynağı sinyalin yönü (+0.19R). Plasebolar portföy kısıtı ve eşzamanlılık
  içermiyor.
- ~72 fazla kazanan sayısı null seçimine bağlı (72-78).
- Kötü seriler ve düşüşler test edilen null'lar altında olağandışı değil. Bu, "yalnız
  şans" kanıtı değildir.
- Hacim filtresinin faydası işlem seçmekten değil maruziyet azalmasından geliyor.
  Eşzamanlılık eşlenmedi.
- `erken_uyari` yanlış alarm oranları ikiz dağılımına ve ay bağımsızlığına bağlı.

### Henüz cevaplanmamış sorular [E]

1. İkiz canlıyı işlem düzeyinde doğru tahmin ediyor mu? Örtüşen 06-18 → 07-19 ve sonrası
   için işlem-işlem karşılaştırma bu turda yapılmadı.
2. Kayıplar A mı (açık kârın erimesi), B mi, C mi? Gerçekleşmemiş zarar dahil gerçek
   düşüş ne kadar?
3. Canlı 112 işlemin kol/yön ayrımı, sürüm bazında dağılımı ve bağımlılığa dayanıklı
   güven aralığı.
4. Gerçek kayma hacme ve boyuta bağlı mı? (İkizde sabit 15.85bp; hesap büyüdükçe
   ölçülmemiş bölgeye giriliyor.)
5. İkizde funding neden pnl'e yansımıyor (`PAPER_FUNDING=true` iken)?
6. TEST temiz bir sınama değil: ayarlar ona bakılarak seçildi. Seçim öncesi ayarın TEST
   edge'i +0.134 [−0.010, +0.271] ile anlamsız.
7. İkiz verisinin son 30 işlemindeki düşüş: gürültü mü, edge kaybı mı?

### Önerilen en fazla üç küçük çevrimdışı kontrol (bu tur uygulanmadı)

1. **Canlı–ikiz işlem eşleştirmesi (en önemli belirsizlik).**
   - VPS'ten gizli bilgi içermeyen bir dışa aktarım alınır: kapanmış işlemler, sembol,
     yön, zamanlar, fiyatlar, sl0, pnl, kol.
   - Bu, ikizin 06-18 → 07-19 işlemleriyle (sembol, yön, giriş zamanı) üzerinden
     eşleştirilir.
   - Ölçülecekler: eşleşme oranı, R farkı, kayma dağılımı. Kaçan ve fazla sinyaller
     listelenir.
   - Aynı dışa aktarımla 112 işlemin kol/yön ve sürüm ayrımı da yapılır, ay-kümeli güven
     aralığı hesaplanır.
   - Backtest gerektirmez.
2. **MFE/MAE ve mark-to-market düşüşü.**
   - Arşivdeki `edge/sim.py` bar simülatörü mevcut 936 işlem için MFE/MAE'yi ve saatlik
     açık pozisyon PnL'ini üretir.
   - Böylece A/B/C ayrımı yapılır ve gerçekleşmemiş zarar dahil gerçek düşüş, %46 ile
     karşılaştırılır.
   - Yeni strateji koşusu değil; eldeki işlemlerin yeniden okunması.
3. **Filtre için eşzamanlılığı eşleşmiş rastgele eleme.**
   - Mevcut R tabanlı defter simülasyonunda rastgele elemeyi, coin, ay ve **eşzamanlı
     açık donchian pozisyon sayısı** dağılımı filtreninkiyle aynı olacak şekilde tabakalı
     yapmak.
   - Filtre bu null'dan ayrışmıyorsa "maruziyet" açıklaması güçlenir; ayrışıyorsa hacmin
     seçici bilgi taşıdığına dair ilk kanıt olur.
