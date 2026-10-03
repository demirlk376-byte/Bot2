"""
trend_canli.py — trend kolunun canlı bota bağlantısı. 1. AŞAMA: YALNIZ SİNYAL MODU (EMİR YOK).

  TREND_MODE=kapali (varsayılan) → hiçbir şey çalışmaz; bot davranışı bit bit aynı.
  TREND_MODE=sinyal              → her 4 saatlik kapanışta trend kolu sanal defteri günceller ve
                                   giriş / piramit / çıkış olaylarını Telegram'a yazar. Borsaya YALNIZ
                                   mum verisi okumak için gidilir (fetch_ohlcv). Emir, stop, teminat YOK.

Diğer ayarlar:
  TREND_COINS          virgüllü liste (boşsa botun SYMBOLS listesi)
  TREND_RISK_PCT       mesajlarda gösterilen risk tutarı için (varsayılan 0.01)
  TREND_DURUM_DOSYASI  sanal defterin JSON dosyası (varsayılan: trend_durum.json, bot klasöründe)

Tasarım: research/trend_takip_v1/TREND_KOLU_TASARIM.md. Mantık: trend_kolu.py (araştırma motoruyla
birebir eşdeğerliği research/trend_takip_v1/canli_esdegerlik.py ile doğrulandı: 441/441 işlem).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import pandas as pd

import trend_kolu as TK

logger = logging.getLogger(__name__)

MOD = os.environ.get("TREND_MODE", "kapali").strip().lower()
AKTIF = MOD == "sinyal"
RISK_PCT = float(os.environ.get("TREND_RISK_PCT", "0.01") or 0.01)
DURUM_DOSYASI = os.environ.get("TREND_DURUM_DOSYASI",
                               os.path.join(os.path.dirname(os.path.abspath(__file__)), "trend_durum.json"))
GECMIS_GUN = 95          # her sembol için çekilen 4h geçmişi (1D: 50 gün + ATR ısınması; 4H: 180 mum)
ETH_GECMIS_GUN = 215     # ETH SMA200 için

_kilit = asyncio.Lock()
_son_tetik: int | None = None
_gorevler: set = set()


def _coinler(bot_semboller: list[str]) -> list[str]:
    ham = os.environ.get("TREND_COINS", "").strip()
    if ham:
        return [f"{c.strip().upper()}/USDT:USDT" for c in ham.split(",") if c.strip()]
    return list(bot_semboller)


async def _mumlar_4h(exchange, sembol: str, gun: int) -> pd.DataFrame:
    """Tamamlanmış 4h mumları (t, open, high, low, close); sayfalı çekim."""
    simdi = int(time.time() * 1000)
    since = simdi - gun * TK.DAY_MS
    satirlar: list = []
    for _ in range(6):
        parca = await exchange.fetch_ohlcv(sembol, "4h", since, 1000)
        if not parca:
            break
        satirlar.extend(parca)
        son = int(parca[-1][0])
        if son + TK.H4_MS >= simdi or len(parca) < 2:
            break
        since = son + TK.H4_MS
        await asyncio.sleep(0.3)
    if not satirlar:
        return pd.DataFrame(columns=["t", "open", "high", "low", "close"])
    df = pd.DataFrame([r[:5] for r in satirlar], columns=["t", "open", "high", "low", "close"])
    df = df.astype({"t": "int64", "open": float, "high": float, "low": float, "close": float})
    df = df.drop_duplicates("t").sort_values("t")
    df = df[df.t + TK.H4_MS <= simdi]                     # yalnız kapanmış mumlar
    return df.reset_index(drop=True)


def _yukle() -> "TK.Defter | None":
    try:
        with open(DURUM_DOSYASI) as f:
            return TK.Defter.yukle(json.load(f))
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.error("trend: durum dosyası okunamadı (%s) — sıfırdan başlanıyor", e)
        return None


def _kaydet(d: "TK.Defter") -> None:
    gecici = DURUM_DOSYASI + ".tmp"
    with open(gecici, "w") as f:
        json.dump(d.durum(), f, ensure_ascii=False)
    os.replace(gecici, DURUM_DOSYASI)


async def _calistir(exchange, bot_semboller, gonder, ozsermaye) -> None:
    async with _kilit:
        defter = _yukle()
        ilk_kurulum = defter is None
        if ilk_kurulum:
            defter = TK.Defter()
        eth = await _mumlar_4h(exchange, "ETH/USDT:USDT", ETH_GECMIS_GUN)
        rejim = TK.eth_rejim(TK.gunluk_4h_den(eth))
        olaylar: list = []
        for s in _coinler(bot_semboller):
            kisa = s.split("/")[0]
            try:
                df4 = eth if kisa == "ETH" else await _mumlar_4h(exchange, s, GECMIS_GUN)
            except Exception as e:
                logger.warning("trend: %s mumları alınamadı: %s", s, e)
                continue
            if len(df4) < 300:
                logger.info("trend: %s yetersiz geçmiş (%d mum)", s, len(df4))
                continue
            d1 = TK.gunluk_4h_den(df4)
            # aynı UTC 00:00'da iki modül kapanırsa önce 1D (araştırmadaki ilk gelen kuralıyla uyumlu)
            olaylar += defter.mum_isle(kisa, "1D", d1, rejim)
            olaylar += defter.mum_isle(kisa, "4H", df4, rejim)
            await asyncio.sleep(0.2)
        _kaydet(defter)
    if ilk_kurulum:
        acik = ", ".join(f"{k}({p.modul})" for k, p in defter.poz.items()) or "yok"
        await gonder(f"TREND (sinyal modu) başladı. Geçmişten kurulan sanal açık pozisyonlar: {acik}")
        return
    if not olaylar:
        return
    try:
        eq = await ozsermaye()
    except Exception:
        eq = None
    for o in olaylar:
        if o.tur in ("GIRIS_SINYALI", "GIRIS", "EK", "CIKIS"):
            ek = ""
            if o.tur == "GIRIS_SINYALI" and eq:
                ek = f" — gerçek modda %{RISK_PCT * 100:.2f} risk ≈ {eq * RISK_PCT:.2f} USDT"
            await gonder(o.metin() + ek)


def tetikle(son_mum_acilis: pd.Timestamp, exchange, bot_semboller, gonder, ozsermaye) -> None:
    """on_candle_close'tan çağrılır. YALNIZ TREND_MODE=sinyal iken ve bir 4h kapanışında (1h mumu
    saat%4==3) bir kez arka plan görevi başlatır; hatalar loglanır, bot akışını ASLA bozmaz."""
    global _son_tetik
    if not AKTIF:
        return
    try:
        if son_mum_acilis.hour % 4 != 3:
            return
        anahtar = int(son_mum_acilis.timestamp())
        if _son_tetik == anahtar:
            return
        _son_tetik = anahtar

        async def _gorev():
            await asyncio.sleep(45)            # borsanın 4h mumu kesinleşsin
            try:
                await _calistir(exchange, bot_semboller, gonder, ozsermaye)
            except Exception as e:
                logger.error("trend sinyal turu hatası: %s", e, exc_info=True)

        g = asyncio.get_running_loop().create_task(_gorev())
        _gorevler.add(g)
        g.add_done_callback(_gorevler.discard)
    except Exception as e:
        logger.error("trend tetikleme hatası: %s", e)
