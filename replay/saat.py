"""Sanal saat. Gerçek bot `from datetime import datetime` yaptığı için modül
attribute'unu değiştirmek yeterli: main.datetime = sanal_datetime(saat)."""
from __future__ import annotations
from datetime import datetime as _dt, timezone, timedelta


class SanalSaat:
    """Tek bir 'şimdi'. İleri gider, geri gitmez."""
    __slots__ = ("_t",)

    def __init__(self, baslangic: _dt):
        if baslangic.tzinfo is None:
            baslangic = baslangic.replace(tzinfo=timezone.utc)
        self._t = baslangic

    @property
    def simdi(self) -> _dt:
        return self._t

    def ayarla(self, t: _dt) -> None:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t < self._t:
            raise ValueError(f"saat GERİ gidemez: {self._t} → {t}")
        self._t = t

    def ileri(self, saniye: float) -> None:
        self._t = self._t + timedelta(seconds=saniye)


def sanal_datetime(saat: SanalSaat):
    """Gerçek `datetime` sınıfının, yalnız `now()`/`utcnow()` değiştirilmiş hali.

    Diğer her şey (fromtimestamp, strptime, aritmetik, isinstance) aynen çalışır;
    bu yüzden üretim kodunda hiçbir şey bozulmaz."""
    class _SanalDatetime(_dt):
        @classmethod
        def now(cls, tz=None):
            t = saat.simdi
            return t if tz is not None else t.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return saat.simdi.replace(tzinfo=None)

    _SanalDatetime.__name__ = "datetime"
    return _SanalDatetime
