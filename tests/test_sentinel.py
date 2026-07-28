"""
test_sentinel.py — dış nöbetçinin alarm mantığı (ölü-adam anahtarı).

NEDEN KRİTİK: bot bir ay gözetimsiz çalışacak. Nöbetçi YANLIŞ SESSİZ kalırsa
(sorun var ama mesaj yok) arıza fark edilmez; YANLIŞ GÜRÜLTÜLÜ olursa (her 30
dk'da aynı uyarı) kullanıcı bildirimleri kapatır ve sonuç aynı kapıya çıkar.
İkisi de tek bir şeye bağlı: alarm durum makinesinin doğruluğu.

Doğrulananlar (sentinel.main durum makinesi):
  1. Her şey temizse mesaj ATILMAZ (sessizlik = sağlık).
  2. Sorun çıkınca TEK mesaj atılır.
  3. Sorun sürerken cooldown içinde TEKRAR atılmaz (spam yok).
  4. Cooldown dolunca sorun sürüyorsa YENİDEN hatırlatır (unutulmaz).
  5. Sorun düzelince "düzeldi" mesajı atılır (kapanış görünür).
  6. --report HER ZAMAN mesaj atar ve SORUNLARI da içerir — yalnız sağlıklıları
     listeleyen bir rapor, servis ölüyken "iyi görünen" çıktı üretirdi.

Run:  python tests/test_sentinel.py
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_tmp = tempfile.mkdtemp(prefix="sentinel-test-")
os.environ["SENTINEL_STATE"] = os.path.join(_tmp, "state.json")
os.environ["COOLDOWN_H"] = "6"

import sentinel

SENT: list[str] = []
sentinel.notify = lambda text: (SENT.append(text), True)[1]
sentinel.summary_text = lambda: "(özet)"

STATE = {"checks": []}
sentinel.checks = lambda: STATE["checks"]

CLOCK = {"t": 1_000_000.0}
_real_time = sentinel.time.time
sentinel.time.time = lambda: CLOCK["t"]

CLEAN = [("service", False, "servis aktif"), ("disk", False, "disk %40 boş")]
BROKEN = [("service", True, "🔴 servis ÇALIŞMIYOR"), ("disk", False, "disk %40 boş")]


def run(argv=None):
    SENT.clear()
    old = sys.argv
    sys.argv = ["sentinel.py"] + (argv or [])
    try:
        sentinel.main()
    finally:
        sys.argv = old
    return list(SENT)


def main() -> int:
    # 1) temiz → sessiz
    STATE["checks"] = CLEAN
    assert run() == [], "temizken mesaj atılmamalı"
    print("✓ her şey temiz → mesaj YOK (sessizlik = sağlık)")

    # 2) sorun → tek mesaj
    STATE["checks"] = BROKEN
    out = run()
    assert len(out) == 1 and "ÇALIŞMIYOR" in out[0], out
    assert "🚨" in out[0], "uyarı başlığı olmalı"
    print("✓ sorun çıktı → TEK uyarı atıldı")

    # 3) cooldown içinde tekrar atma
    CLOCK["t"] += 60 * 60          # +1 saat (cooldown 6 saat)
    assert run() == [], "cooldown içinde tekrar atmamalı"
    CLOCK["t"] += 60 * 60 * 2      # +2 saat daha (toplam 3 < 6)
    assert run() == [], "cooldown içinde tekrar atmamalı"
    print("✓ sorun sürüyor, cooldown içinde → tekrar mesaj YOK (spam yok)")

    # 4) cooldown dolunca hatırlat
    CLOCK["t"] += 60 * 60 * 4      # toplam 7 saat > 6
    out = run()
    assert len(out) == 1 and "ÇALIŞMIYOR" in out[0], out
    print("✓ cooldown doldu, sorun sürüyor → yeniden hatırlattı")

    # 5) düzelme
    STATE["checks"] = CLEAN
    out = run()
    assert len(out) == 1 and "düzeldi" in out[0] and "✅" in out[0], out
    print("✓ sorun düzeldi → 'düzeldi' mesajı atıldı")

    # düzeldikten sonra tekrar sessiz
    assert run() == [], "düzelme mesajı bir kez atılmalı"
    print("✓ düzelme sonrası tekrar sessiz")

    # 6) rapor her zaman atar VE sorunları içerir
    STATE["checks"] = CLEAN
    out = run(["--report"])
    assert len(out) == 1 and "📊" in out[0], out
    print("✓ --report temizken de özet atıyor (sağ olduğunun kanıtı)")

    STATE["checks"] = BROKEN
    out = run(["--report"])
    assert len(out) == 1, out
    assert "ÇALIŞMIYOR" in out[0], "rapor SORUNU göstermeli"
    assert "SORUN VAR" in out[0], "rapor başlığı sorunu belli etmeli"
    print("✓ --report sorunluyken uyarı başlığı + sorun detayı içeriyor")

    # 7) durum dosyası bozuksa çökmemeli (bir ay boyunca disk/güç kesintisi olabilir)
    Path(os.environ["SENTINEL_STATE"]).write_text("{bozuk json")
    STATE["checks"] = BROKEN
    out = run()
    assert len(out) == 1, "bozuk durum dosyası alarmı engellememeli"
    print("✓ bozuk durum dosyası → yine de alarm veriyor (fail-loud)")

    sentinel.time.time = _real_time
    print("\n" + "=" * 68)
    print("✓ NÖBETÇİ ALARM MANTIĞI DOĞRU — yanlış sessiz de değil, spam de değil")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
