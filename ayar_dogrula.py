"""
ayar_dogrula.py — .env'i değiştirmek ile BOTUN ONU OKUMUŞ OLMASI ayrı şeylerdir.

Bot başlangıçta config'i loglamıyor. Yani `grep .env` sana dosyanın içeriğini gösterir
ama çalışan sürecin O DEĞERLERLE boyutlandırdığını göstermez (servis yeniden başlatılmadıysa
eski değerlerle çalışmaya devam eder ve bunu hiçbir yerde belli etmez).

Bu betik config'i BOTUN YÜKLEDİĞİ GİBİ yükler (config.load_config) ve üretim risk
sınıfını çağırarak gerçek boyutlandırmayı gösterir. Beklenen değerlerle karşılaştırıp
GEÇTİ/KALDI der.

⚠️ Betik .env'i okur, çalışan süreci değil. Servis yeniden başlatılmadıysa dosya doğru
ama süreç eski olabilir — bu yüzden servisin başlama zamanı da yazdırılıyor; .env'in
değiştirilme zamanından SONRA olmalı.

Kullanım (VPS'te):  cd /opt/bot2 && python3 ayar_dogrula.py
"""
import os
import re
import subprocess
import sys

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BOT_DIR, ".env")

# ⚠ 2026-09-09: BU BLOK ESKİDEN SABİT SAYI EZBERLİYORDU ve o yüzden BOZULDU.
# RISK_SCALE 1.125 → 1.4 yapıldığında burada 0.0225 yazılı kaldı; betik canlı
# DOĞRUYKEN "✗ UYUŞMUYOR" diyecekti. Aylık rutinde yalancı alarm veren bir
# doğrulayıcı, doğrulayıcı değildir — insan onu görmezden gelmeye başlar.
#
# Artık hiçbir risk rakamı burada YAZMIYOR. Beklenen değerler .env'den TÜRETİLİYOR.
# Betiğin işi (docstring'deki iddia) zaten buydu: "dosyayı değiştirdim" ile
# "botun config katmanı onu doğru okudu" ayrı şeylerdir. Türetme tam olarak o
# katmanı sınar ve RISK_SCALE ne olursa olsun geçerli kalır.
#
# Politika sorusu ("bu rakam DOĞRU rakam mı") ayrı bir bölümde, ANKORA kıyasla
# yanıtlanıyor — çünkü kullanıcıya verdiğim her getiri tahmini ankor birimindedir.

# Ankorun ve canlının sabitleri — deployed_backtest.py KAYNAĞINDAN okunur, elle yazılmaz.
# Bu betiği 2026-09-09'da bozan hata tam olarak "elle yazılmış sayı bayatladı"ydı.
def _ankor_sabit(ad):
    """deployed_backtest.py'den sabiti metin olarak çek.

    import ETMİYORUZ: betik VPS'te koşuyor ve ağır import zinciri (fast_bt,
    strategies, veri) bir AYAR doğrulamasını düşürmemeli.

    ⚠ Bulunamazsa VARSAYILANA DÜŞMEZ, çöker. İlk sürüm `^RISKF` diye arıyordu
    ama RISKF paylaşımlı satırda (`BAL0 = ...; RISKF = 0.0225; ...`) tanımlı,
    yani hiç bulunamıyor ve sessizce varsayılanı kullanıyordu. Doğru sayıyı
    ŞANSA veriyordu. Sessiz geri düşüş = bayat sabitin ta kendisi.
    """
    yol = os.path.join(BOT_DIR, "deployed_backtest.py")
    try:
        src = open(yol, encoding="utf-8").read()
    except OSError as e:
        print(f"✗ ankor sabitleri okunamadı ({yol}): {e}")
        sys.exit(2)
    m = re.search(rf"(?:^|;)\s*{ad}\s*=\s*([0-9.]+)", src, re.M)
    if not m:
        print(f"✗ '{ad}' sabiti deployed_backtest.py içinde BULUNAMADI.")
        print(f"  Yeniden adlandırıldıysa burayı da güncelle. Tahmin YÜRÜTMÜYORUM.")
        sys.exit(2)
    return float(m.group(1))


ANKOR_RISKF = _ankor_sabit("RISKF")      # çıpanın riski (regresyon sabiti)
ANKOR_CAP = _ankor_sabit("CAP")
CANLI_CAP = _ankor_sabit("CANLI_CAP")    # canlının GERÇEKTE koştuğu — .env buna uymalı
CANLI_RISKF = _ankor_sabit("CANLI_RISKF")
CANLI_OLCEK = _ankor_sabit("CANLI_OLCEK")
CANLI_MAXDD = _ankor_sabit("CANLI_MAXDD")

# Risk oranının ankorun kaç katına kadar çıkmasına izin var. Aşılırsa ✗.
# Gerekçe: ankorun ölçülen maxDD'si %24.43. 1.5 kat ≈ %37 maxDD; $306'lık
# hesapta ~$113'lük tepe-dip. Bunun ötesi "normal dalgalanma" diye savunulamaz.
ORAN_TAVAN = 1.5
ANKOR_MAXDD = 24.43     # ölçüldü (çıkış sırasına göre equity eğrisi)


def _yukle_env():
    """.env'i ortama yükle — config.load_config os.environ'dan okuyor."""
    try:
        with open(ENV, encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("export "):
                    s = s[7:].lstrip()
                if "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k, v = k.strip(), v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k:
                    os.environ[k] = v          # .env DOSYASI otorite
    except FileNotFoundError:
        print(f"✗ .env bulunamadı: {ENV}")
        sys.exit(1)


def main():
    _yukle_env()
    import config as C
    try:
        cfg = C.load_config()
    except Exception as e:
        print(f"✗ config YÜKLENEMEDİ: {type(e).__name__}: {e}")
        print("  Bot bu hâliyle BAŞLAMAZ. .env'i geri al: bash rollback.sh --snapshot ile")
        print("  aldığın yedekteki .env.kopya dosyasını geri koy.")
        sys.exit(1)

    r = cfg.risk

    # .env'in SÖYLEDİĞİ — beklenen değerler buradan TÜRETİLİYOR, ezberden değil.
    def _env(ad, vars_):
        try:
            return float(os.environ.get(ad, vars_))
        except ValueError:
            return None

    olcek = _env("RISK_SCALE", 1.0)
    if olcek is None or olcek <= 0:
        print(f"✗ RISK_SCALE okunamadı ya da geçersiz: {os.environ.get('RISK_SCALE')!r}")
        sys.exit(1)

    # config.py:392-410 — her risk %'si RISK_SCALE ile çarpılıyor. Beklenen
    # değer = .env tabanı × ölçek. Bu, config KATMANINI sınar.
    BEK = {
        "max_risk_per_trade":  _env("MAX_RISK_PCT", 0.02) * olcek,
        "donchian_risk_pct":   _env("DONCHIAN_RISK_PCT", 0.02) * olcek,
        "squeeze_risk_pct":    _env("SQUEEZE_RISK_PCT", 0.02) * olcek,
        "position_cap_fraction": _env("POSITION_CAP_FRACTION", 1.0),
    }

    print(f"\n{'=' * 78}\n=== AYAR DOĞRULAMA (config botun yüklediği gibi yüklendi) ===\n")
    print(f"  RISK_SCALE = {olcek:.3f}  → beklenenler .env tabanlarından türetildi\n")
    print(f"  {'alan':<26s} {'değer':>10s} {'beklenen':>10s}  durum")
    hepsi = True
    for alan, bek in BEK.items():
        val = getattr(r, alan, None)
        ok = val is not None and abs(val - bek) < 1e-9
        hepsi &= ok
        print(f"  {alan:<26s} {val if val is None else f'{val:>10.4f}'} {bek:>10.4f}  "
              f"{'✓' if ok else '✗ UYUŞMUYOR'}")
    print(f"  ↑ bu bölüm 'config .env'i doğru okudu mu' sorusudur, "
          f"'rakam doğru mu' DEĞİL.")

    # ── POLİTİKA: rakamın kendisi doğru mu? İKİ AYRI SORU. ──
    # (a) Canlı, KOŞMASINI İSTEDİĞİMİZ ayarda mı? Referans deployed_backtest.py'deki
    #     CANLI_* sabitleri. Sapma = ya .env kaydı yapılmadan değişti, ya biri
    #     bu sabitleri güncellemeyi unuttu. İkisi de ✗.
    # (b) Canlı, ÇIPADAN ne kadar sapıyor? Çünkü kullanıcıya verilen her
    #     getiri/maxDD tahmini çıpa birimindedir ve o oranla kayar.
    canli_risk = getattr(r, "max_risk_per_trade", None)
    canli_cap = getattr(r, "position_cap_fraction", None)
    print(f"\n  {'—' * 60}")
    print(f"  (a) CANLI, OLMASI GEREKEN AYARDA MI?")
    for ad, gercek, bek in (("risk/işlem", canli_risk, CANLI_RISKF),
                            ("cap fraction", canli_cap, CANLI_CAP)):
        ok = gercek is not None and abs(gercek - bek) < 1e-9
        hepsi &= ok
        print(f"    {ad:<14s} {gercek if gercek is None else f'{gercek:>7.4f}'} "
              f"beklenen {bek:>7.4f}  {'✓' if ok else '✗ SAPMA'}")
    if not (canli_cap is not None and abs(canli_cap - CANLI_CAP) < 1e-9):
        print(f"      .env bilerek mi değişti? Öyleyse deployed_backtest.py'deki")
        print(f"      CANLI_CAP / CANLI_RISKF / CANLI_OLCEK sabitlerini de güncelle —")
        print(f"      yoksa bu doğrulayıcı bayatlar (2026-09-09'da tam olarak bu oldu).")

    print(f"\n  (b) ÇIPAYA KIYAS (tüm getiri tahminleri bu birimde)")
    if canli_risk:
        oran = canli_risk / ANKOR_RISKF
        ok = oran <= ORAN_TAVAN
        hepsi &= ok
        print(f"    risk/işlem   canlı %{canli_risk*100:.3f}  çıpa %{ANKOR_RISKF*100:.3f}"
              f"   → {oran:.3f}x  {'✓' if ok else f'✗ TAVAN {ORAN_TAVAN}x AŞILDI'}")
        print(f"    cap          canlı {canli_cap:.2f}      çıpa {ANKOR_CAP:.2f}")
        print(f"    ── ikisi birlikte, TEK SEFERDE ölçüldü: kâr ölçeği {CANLI_OLCEK:.4f}x ──")
        # maxDD tabanı cap 1.50'de ÖLÇÜLEN değer (24.79), çıpanınki (24.43) değil —
        # yoksa cap'in katkısı düşer ve drawdown OLDUĞUNDAN AZ görünür.
        dd_bek = CANLI_MAXDD_BAZ * oran
        print(f"    beklenen maxDD  ~%{dd_bek:.1f}   "
              f"(cap1.50'de ölçülen %{CANLI_MAXDD_BAZ:.2f} × {oran:.2f})")
        print(f"    çıpanın aylık DOLAR rakamlarını {CANLI_OLCEK:.2f} ile ÇARP.")
        print(f"    (yüzde rakamları ölçekten BAĞIMSIZ değildir — onlar da çarpılır)")

    # ── BB kolunun gerçekte alacağı boyut ──
    # ⚠ 2026-09-09: BU TEST DE BOZUKTU. "hepsi AYNI olmalı" diyordu; oysa
    # gerçek boyutlandırma  risk = min(max_risk, CAP × stop)  modelidir ve dar
    # stopta CAP bağlar, yani risk DÜŞÜK olmalıdır — arıza değil, tasarım.
    # Eski test sadece (CAP 1.5, risk %2.25) çiftinde ve seçilen stop ızgarası
    # tam sınırda başladığı için geçiyordu. RISK_SCALE 1.4 ile ızgara sınırın
    # içine düştü ve test CANLI DOĞRUYKEN "düzeltme UYGULANMAMIŞ" dedi.
    #
    # Yeni test ankorun kendi formülünü sınıyor. Bu hem daha doğru hem daha
    # güçlü: canlı boyutlandırma ankorunkiyle AYNI mı sorusunu yanıtlıyor —
    # +$1420.66 rakamının canlıya taşınması buna bağlı.
    #
    # Asıl korunan hata (BB'nin oynaklıkla riski BÜYÜTMESİ, %1.87 → %5.62)
    # hâlâ yakalanıyor: o model tavanı aşıyordu, min() ise asla aşamaz.
    from risk import RiskManager
    rm = RiskManager(r)
    BAL, ENTRY = 203.0, 90.0
    tavan = BEK["max_risk_per_trade"]
    cap = BEK["position_cap_fraction"]
    print(f"\n  BB (LTC hafta sonu) kolu — bakiye ${BAL:.0f}, farklı oynaklıklarda")
    print(f"  model:  risk = min(%{tavan*100:.3f}, {cap:.2f} × stop)")
    print(f"    {'stop%':>7s} {'risk%':>7s} {'model%':>7s}  durum")
    uyum, olcum = True, 0
    for atr_pct in (0.002, 0.005, 0.0072, 0.010, 0.015, 0.020, 0.030):
        st = rm.build_trade_setup(1, ENTRY, ENTRY * atr_pct, BAL,
                                  cfg.exchange.leverage, "LTC/USDT:USDT")
        stop_f = atr_pct * r.atr_sl_multiplier
        beklenen = min(tavan, cap * stop_f)
        if st is None:
            # Çok dar stopta borsa minimumları işlemi reddedebilir; bu ayrı bir
            # konudur ve BOYUTLANDIRMA hatası değildir. Reddi bildir, teste sokma.
            print(f"    {stop_f*100:>6.2f}%       —  {beklenen*100:>6.2f}%  "
                  f"⊘ reddedildi (borsa minimumu olabilir — boyutlandırma testi DIŞI)")
            continue
        olcum += 1
        ok = abs(st.risk_pct - beklenen) / beklenen < 0.01   # quantity yuvarlaması
        asim = st.risk_pct > tavan * 1.01
        uyum &= ok
        etiket = "✓" if ok else ("✗ TAVAN AŞILDI" if asim else "✗ MODELE UYMUYOR")
        print(f"    {stop_f*100:>6.2f}% {st.risk_pct*100:>6.2f}% {beklenen*100:>6.2f}%  {etiket}")
    if olcum < 4:
        uyum = False
        print(f"    ✗ yalnız {olcum} ölçüm alınabildi — test anlamlı değil")
    print(f"    → {'✓ ANKOR MODELİYLE AYNI' if uyum else '✗ SAPMA VAR — yukarıya bak'}")
    hepsi &= uyum

    # servis gerçekten yeniden başladı mı
    print(f"\n  {'—' * 60}")
    try:
        st = subprocess.run(["systemctl", "show", "btc-bot",
                             "--property=ActiveEnterTimestamp,ActiveState"],
                            capture_output=True, text=True, timeout=10).stdout.strip()
        env_mt = subprocess.run(["date", "-u", "-r", ENV, "+%a %Y-%m-%d %H:%M:%S UTC"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        print(f"  .env son değişiklik : {env_mt}")
        for satir in st.splitlines():
            print(f"  {satir}")
        print(f"\n  ⚠ ActiveEnterTimestamp, .env değişikliğinden SONRA olmalı.")
        print(f"    Önce ise süreç ESKİ değerlerle çalışıyor → systemctl restart btc-bot")
    except Exception as e:
        print(f"  (servis durumu okunamadı: {e})")

    print(f"\n{'=' * 78}")
    print(f"  SONUÇ: {'✓ AYARLAR DOĞRU' if hepsi else '✗ SORUN VAR — yukarıdaki ✗ satırlarına bak'}")


if __name__ == "__main__":
    main()
