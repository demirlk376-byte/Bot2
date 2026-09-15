"""
REPLAY — CANLI BOTUN KENDİ KODUNU geçmiş veri üzerinde koşturur.

KRONOS'tan FARKI: KRONOS orkestrasyonu (olay döngüsü, koltuk, kapılar,
boyutlandırma) BENİM yeniden yazdığım bir replikaydı. REPLAY hiçbir şey yeniden
yazmaz — `main.py`'nin kendisini kurar, `main.on_candle_close`'u çağırır,
emirleri `PaperExchange`'e verdirir. Orkestrasyon farkı diye bir şey kalmaz.

NEDEN GEREKLİ (2026-09-14'te kanıtlandı): KRONOS'un "ayrı havuz sıfır itme
yapar" iddiası YANLIŞ çıktı, çünkü ben canlıdaki netted tek-pozisyon/coin
kısıtını mimaride unutmuştum. Gerçek kod koşsaydı o kısıt zaten içinde olurdu.

ÜÇ PARÇA:
  saat.py     — sanal saat; `datetime.now()` modül attribute'u olarak değiştirilir
  besleme.py  — ReplayFeed: fetch_ohlcv/watch_ticker geçmiş CSV'den, saate göre
  kos.py      — sürücü: main()'i kurulum bitene kadar koşturur, sonra mumları sürer
"""
from .saat import SanalSaat, sanal_datetime
from .besleme import ReplayFeed

__all__ = ["SanalSaat", "sanal_datetime", "ReplayFeed"]
