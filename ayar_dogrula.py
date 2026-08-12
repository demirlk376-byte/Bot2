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
import subprocess
import sys

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(BOT_DIR, ".env")

# Paket sonrası beklenen değerler
BEK = {
    "max_risk_per_trade": 0.0225,      # MAX_RISK_PCT 0.02 × RISK_SCALE 1.125
    "position_cap_fraction": 1.5,
    "donchian_risk_pct": 0.0225,       # değişmemeli
    "squeeze_risk_pct": 0.0225,        # değişmemeli
}


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
    print(f"\n{'=' * 78}\n=== AYAR DOĞRULAMA (config botun yüklediği gibi yüklendi) ===\n")
    print(f"  {'alan':<26s} {'değer':>10s} {'beklenen':>10s}  durum")
    hepsi = True
    for alan, bek in BEK.items():
        val = getattr(r, alan, None)
        ok = val is not None and abs(val - bek) < 1e-9
        hepsi &= ok
        print(f"  {alan:<26s} {val if val is None else f'{val:>10.4f}'} {bek:>10.4f}  "
              f"{'✓' if ok else '✗ UYUŞMUYOR'}")

    # BB kolunun gerçekte alacağı boyut — asıl düzeltilen şey buydu
    from risk import RiskManager
    rm = RiskManager(r)
    BAL, ENTRY = 203.0, 90.0
    print(f"\n  BB (LTC hafta sonu) kolu — bakiye ${BAL:.0f}, farklı oynaklıklarda:")
    print(f"    {'stop%':>7s} {'risk%':>7s}  (hepsi AYNI olmalı: %2.25)")
    riskler = []
    for atr_pct in (0.005, 0.0072, 0.010, 0.015):
        s = rm.build_trade_setup(1, ENTRY, ENTRY * atr_pct, BAL, cfg.exchange.leverage,
                                 "LTC/USDT:USDT")
        if s is None:
            print(f"    {atr_pct*3*100:>6.2f}%   ⛔ İŞLEM REDDEDİLDİ — BB SUSAR, bu bir ARIZADIR")
            hepsi = False
        else:
            riskler.append(s.risk_pct)
            print(f"    {atr_pct*3*100:>6.2f}% {s.risk_pct*100:>6.2f}%")
    # Tolerans: quantity 3 haneye AŞAĞI yuvarlanıyor (risk.py floor), bu yüzden risk%
    # 5. hanede oynar. 1e-6 mutlak eşik bunu yanlışlıkla "değişken" sayıyordu.
    # Anlamlı test: her risk% hedefin (%2.25) %1'i içinde mi.
    hedef = BEK["max_risk_per_trade"]
    sabit = len(riskler) == 4 and all(abs(x - hedef) / hedef < 0.01 for x in riskler)
    if riskler:
        yay = (max(riskler) - min(riskler)) / hedef * 100
        print(f"    → {'✓ SABİT — düzeltme çalışıyor' if sabit else '✗ DEĞİŞKEN — düzeltme UYGULANMAMIŞ'}"
              f"   (yayılma %{yay:.2f}, hedeften sapma "
              f"%{max(abs(x-hedef)/hedef*100 for x in riskler):.2f})")
    hepsi &= sabit

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
