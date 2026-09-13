"""
KRONOS — nedensel (causal) olay güdümlü backtest motoru.

TASARIM SÖZÜ: motor hiçbir anda geleceği göremez. Bu bir konvansiyon değil,
YAPISAL bir kısıt: strateji ham DataFrame'e ERİŞEMEZ, yalnızca `Besleme.pencere(i)`
üzerinden `i` DAHİL, `i+1` ASLA olacak şekilde bir dilim alır.

Ve iddia kanıtlanır: `kronos_test.py` veriyi rastgele bir T anında keser, motoru
yeniden koşar ve T öncesi BÜTÜN kararların birebir aynı olmasını şart koşar.
Tek bir karar değişirse gelecek bilgisi sızıyordur ve test SystemExit ile durur.

Kullanım:
    from kronos import Kronos, Ayar, DonchianKol, SqueezeKol, BbKol
    k = Kronos([DonchianKol(c) for c in ...] + [...], Ayar(maxpos=7))
    islemler = k.kos()
"""
from .motor import Kronos, Ayar, Besleme, Islem
from .kollar import Kol, DonchianKol, SqueezeKol, BbKol

__all__ = ["Kronos", "Ayar", "Besleme", "Islem", "Kol",
           "DonchianKol", "SqueezeKol", "BbKol"]
