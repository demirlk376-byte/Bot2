"""
test_tanimsiz_isim.py — aylık doğrulama betiklerinde TANIMSIZ isim kalmasın.

NEDEN: 2026-09-09'da ayar_dogrula.py'de CANLI_MAXDD_BAZ → CANLI_MAXDD yeniden
adlandırıldı, iki kullanım eski adla kaldı. Betik 17 gün boyunca (b) bölümünde
NameError ile çöktü ve "✓ AYARLAR DOĞRU" satırına hiç ulaşmadı; fark edilmedi
çünkü bu betikler yalnız VPS'te, elle koşuluyor.

Run:  python tests/test_tanimsiz_isim.py
"""
from __future__ import annotations

import builtins
import os
import symtable

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BETIKLER = ("ayar_dogrula.py", "erken_uyari.py", "live_verify.py", "sentinel.py")


def _tanimsizlar(yol: str) -> list[str]:
    kaynak = open(yol, encoding="utf-8").read()
    ust = symtable.symtable(kaynak, yol, "exec")
    modul = {s.get_name() for s in ust.get_symbols() if s.is_assigned() or s.is_imported()}
    modul |= set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    eksik = []

    def gez(tablo):
        for s in tablo.get_symbols():
            if s.is_referenced() and s.is_global() and s.get_name() not in modul:
                eksik.append(f"{tablo.get_name()}: {s.get_name()}")
        for alt in tablo.get_children():
            gez(alt)

    for alt in ust.get_children():
        gez(alt)
    return eksik


def test_dogrulama_betiklerinde_tanimsiz_isim_yok():
    for ad in BETIKLER:
        eksik = _tanimsizlar(os.path.join(KOK, ad))
        assert not eksik, f"{ad}: tanımsız isim(ler): {eksik}"


def test_dedektor_CANLI_MAXDD_BAZ_hatasini_yakalardi():
    import tempfile
    yol = os.path.join(tempfile.mkdtemp(prefix="tanimsiz-"), "x.py")
    with open(yol, "w", encoding="utf-8") as f:
        f.write("CANLI_MAXDD = 1.0\ndef main():\n    return CANLI_MAXDD_BAZ * 2\n")
    assert _tanimsizlar(yol) == ["main: CANLI_MAXDD_BAZ"]


if __name__ == "__main__":
    test_dogrulama_betiklerinde_tanimsiz_isim_yok()
    test_dedektor_CANLI_MAXDD_BAZ_hatasini_yakalardi()
    print("✓ doğrulama betiklerinde tanımsız isim yok")
