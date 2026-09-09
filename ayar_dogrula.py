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

# Ankorun risk oranı — deployed_backtest.py kaynağından OKUNUR, elle yazılmaz.
def _ankor_sabit(ad, varsayilan):
    """deployed_backtest.py'den sabiti metin olarak çek. import etmiyoruz:
    bu betik VPS'te koşuyor ve ağır import zinciri (fast_bt, strategies) bir
    ayar doğrulamasını data eksikliği yüzünden düşürmemeli."""
    try:
        src = open(os.path.join(BOT_DIR, "deployed_backtest.py"), encoding="utf-8").read()
        m = re.search(rf"^{ad}\s*=\s*([0-9.]+)", src, re.M)
        return float(m.group(1)) if m else varsayilan
    except OSError:
        return varsayilan


ANKOR_RISKF = _ankor_sabit("RISKF", 0.0225)
ANKOR_CAP = _ankor_sabit("CAP", 1.25)

# Risk oranının ankorun kaç katına kadar çıkmasına izin var. Aşılırsa ✗.
# Gerekçe: ankorun ölçülen maxDD'si %24.43. 1.5 kat = ~%37 maxDD; $306'lık
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

    # ── POLİTİKA: rakamın kendisi doğru mu? Ankora kıyasla. ──
    # Kullanıcıya verilen her getiri/maxDD tahmini ankor birimindedir
    # (1579 işlem / +$1420.66 · RISKF %2.25 · CAP 1.25). Canlı ondan
    # saparsa o tahminlerin hepsi aynı oranda kayar.
    canli_risk = getattr(r, "max_risk_per_trade", None)
    canli_cap = getattr(r, "position_cap_fraction", None)
    print(f"\n  {'—' * 60}")
    print(f"  ANKORA KIYAS (tüm getiri tahminleri bu birimde)")
    if canli_risk:
        oran = canli_risk / ANKOR_RISKF
        ok = oran <= ORAN_TAVAN
        hepsi &= ok
        print(f"    risk/işlem   canlı %{canli_risk*100:.3f}  ankor %{ANKOR_RISKF*100:.3f}"
              f"   → {oran:.3f}x  {'✓' if ok else f'✗ TAVAN {ORAN_TAVAN}x AŞILDI'}")
        print(f"      beklenen maxDD  ~%{ANKOR_MAXDD*oran:.1f}   (ankor %{ANKOR_MAXDD:.2f} × {oran:.2f})")
        print(f"      ankorun aylık rakamlarını {oran:.2f} ile ÇARP.")
    if canli_cap is not None and abs(canli_cap - ANKOR_CAP) > 1e-9:
        hepsi = False
        print(f"    ✗ POSITION_CAP_FRACTION canlı {canli_cap:.2f} ≠ ankor {ANKOR_CAP:.2f}")
        print(f"      Bu ikisi AYNI olmalı, yoksa ankorun +$1420.66'sı canlıyı temsil ETMİYOR.")
        print(f"      Ya .env'i ankora çek, ya deployed_backtest.py'deki CAP'i canlıya çek")
        print(f"      ve ankoru YENİDEN koş (1579/+$1420.66 rakamı değişir).")
    elif canli_cap is not None:
        print(f"    cap fraction canlı {canli_cap:.2f}  ankor {ANKOR_CAP:.2f}   ✓ aynı")

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
