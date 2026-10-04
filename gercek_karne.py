"""
gercek_karne.py — GERÇEK KOL KARNESİ: her işlemin sonucu BORSANIN kendi kayıtlarından (YALNIZ OKUR).

Defter (trades.db) kârı borsadan fazla yazıyor (DURUM 4t): ücret 1bp sabit yazılıyor, funding hiç
yazılmıyor, eski çıkışlar seviye fiyatından. Bu araç her canlı işlem için:
  • o sembolde işlemin [giriş − 1 dk, çıkış + 3 dk] penceresindeki GERÇEK dolumları (fetch_my_trades),
  • gerçek ücretleri (dolumların fee alanı, yalnız USDT),
  • (giriş, çıkış] arasındaki GERÇEK funding kayıtlarını (fetch_funding_history)
toplar ve gerçek net sonucu, defterle farkını ve kol bazında gerçek R'yi verir.
Eşleşmeyen işlem (alış/satış miktarı dengesiz ya da dolum yok) "eşleşmedi" sayılır, rakama KATILMAZ.

HİÇBİR emir/ayar göndermez (kaldıraç ayarı bile yok). Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python gercek_karne.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import erken_uyari as EU  # noqa: E402
from config import load_config  # noqa: E402

PENCERE_ONCE = 60_000
PENCERE_SONRA = 180_000


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


async def dolumlar(ex, sym, bas, bit, gun=7, sayfa_boyu=100):
    """Tüm dolumlar: 7 günlük pencereler × sayfa numarası (MEXC order_deals sırası ve 100 sınırı yüzünden
    'son zamandan devam' yöntemi kayıp verir). Kimliğe göre tekilleştirilir."""
    out, gorulen, hata = [], set(), None
    w = bas
    while w < bit:
        w2 = min(w + gun * 86_400_000, bit)
        for sayfa in range(1, 60):
            try:
                r = await ex.fetch_my_trades(sym, w, sayfa_boyu, {"end_time": w2, "page_num": sayfa})
            except Exception as e:
                hata = str(e)
                break
            yeni = [x for x in (r or []) if x.get("id") not in gorulen]
            for x in yeni:
                gorulen.add(x.get("id"))
            out += yeni
            await asyncio.sleep(0.2)
            if len(r or []) < sayfa_boyu or not yeni:
                break
        w = w2
    return out, hata


async def fundingler(ex, sym, bas, sayfa_boyu=100):
    """Funding kayıtları: sayfa numarasıyla geriye doğru, bas'tan eski kayda ulaşınca dur."""
    out, gorulen, hata = [], set(), None
    for sayfa in range(1, 200):
        try:
            r = await ex.fetch_funding_history(sym, None, sayfa_boyu, {"page_num": sayfa})
        except Exception as e:
            hata = str(e)
            break
        yeni = [x for x in (r or []) if (x.get("id"), x.get("timestamp")) not in gorulen]
        for x in yeni:
            gorulen.add((x.get("id"), x.get("timestamp")))
        out += yeni
        await asyncio.sleep(0.2)
        if len(r or []) < sayfa_boyu or not yeni or min(int(x.get("timestamp") or 0) for x in yeni) < bas:
            break
    return out, hata


def guven(rs):
    if len(rs) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(20261004)
    a = np.asarray(rs, float)
    o = [rng.choice(a, len(a)).mean() for _ in range(5000)]
    return float(np.percentile(o, 2.5)), float(np.percentile(o, 97.5))


async def main():
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — çalıştırılmadı.")
        return
    islemler = EU.islemleri_oku(cfg.db_path, paper=False)
    if not islemler:
        print("Canlı kapanmış işlem yok.")
        return
    import ccxt.pro as ccxtpro
    ex = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                       "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    ex.has["fetchCurrencies"] = False
    try:
        await ex.load_markets()
        bas = min(ms(t["entry_time"]) for t in islemler) - 86_400_000
        semboller = sorted({t["symbol"] for t in islemler})
        dolum, fon, hata = {}, {}, {}
        bit = max(ms(t["exit_time"]) for t in islemler) + 86_400_000
        for s in semboller:
            d, e1 = await dolumlar(ex, s, bas, bit)
            f, e2 = await fundingler(ex, s, bas) if hasattr(ex, "fetch_funding_history") else ([], "yok")
            dolum[s], fon[s] = sorted(d, key=lambda x: x["timestamp"]), f
            if e1 or e2:
                hata[s] = (e1, e2)
            cs = float((ex.market(s).get("contractSize") or 1))
            for x in dolum[s]:
                x["_cs"] = cs
    finally:
        await ex.close()

    kullanildi = set()
    satirlar = []
    for t in sorted(islemler, key=lambda x: x["entry_time"]):
        s = t["symbol"]
        a, b = ms(t["entry_time"]) - PENCERE_ONCE, ms(t["exit_time"]) + PENCERE_SONRA
        ds = [x for x in dolum.get(s, []) if a <= x["timestamp"] <= b and id(x) not in kullanildi]
        alis = sum(float(x["amount"]) for x in ds if x["side"] == "buy")
        satis = sum(float(x["amount"]) for x in ds if x["side"] == "sell")
        risk = None
        sl = EU._skor(t).get("sl0") or t["sl_price"]
        risk = abs(t["entry_price"] - sl) * t["quantity"]
        if not ds or abs(alis - satis) > 1e-9 * max(alis, 1) + 1e-12:
            satirlar.append(dict(kol=EU.kol_adi(t.get("strategy_scores")), eslesti=False, defter=t["pnl_usdt"]))
            continue
        for x in ds:
            kullanildi.add(id(x))
        tutar = lambda x: float(x.get("cost") or float(x["price"]) * float(x["amount"]) * x["_cs"])
        brut = sum(tutar(x) for x in ds if x["side"] == "sell") - sum(tutar(x) for x in ds if x["side"] == "buy")
        ucret = sum(float((x.get("fee") or {}).get("cost") or 0) for x in ds
                    if ((x.get("fee") or {}).get("currency") or "USDT").upper() == "USDT")
        g0, g1 = ms(t["entry_time"]), ms(t["exit_time"]) + PENCERE_SONRA
        funding = sum(float(f.get("amount") or 0) for f in fon.get(s, []) if g0 < int(f.get("timestamp") or 0) <= g1)
        net = brut - ucret + funding
        satirlar.append(dict(kol=EU.kol_adi(t.get("strategy_scores")), eslesti=True, defter=t["pnl_usdt"], gercek=net,
                             ucret=ucret, funding=funding, R=net / risk if risk and risk > 0 else None))

    print("=" * 100)
    print(f"  GERÇEK KOL KARNESİ — borsanın dolum, ücret ve funding kayıtlarından · {len(islemler)} canlı işlem")
    print("=" * 100)
    print(f"{'kol':<12}{'eşleşen':>8}{'defter USDT':>13}{'GERÇEK USDT':>13}{'fark':>9}{'gerçek ort R':>14}"
          f"{'%95 aralık':>18}{'ücret':>8}{'funding':>9}")
    gr = defaultdict(list)
    for x in satirlar:
        gr[x["kol"]].append(x)
    top_d = top_g = 0.0
    for kol, xs in sorted(gr.items(), key=lambda kv: -sum(x.get("gercek", 0) for x in kv[1] if x["eslesti"])):
        e = [x for x in xs if x["eslesti"]]
        d = sum(x["defter"] for x in e)
        g = sum(x["gercek"] for x in e)
        rs = [x["R"] for x in e if x["R"] is not None]
        lo, hi = guven(rs)
        top_d += d
        top_g += g
        ar = f"[{lo:+.2f}, {hi:+.2f}]" if np.isfinite(lo) else "—"
        print(f"{kol:<12}{len(e):>4}/{len(xs):<3}{d:>13.2f}{g:>13.2f}{g - d:>9.2f}"
              f"{(np.mean(rs) if rs else float('nan')):>+14.2f}{ar:>18}"
              f"{sum(x['ucret'] for x in e):>8.2f}{sum(x['funding'] for x in e):>9.2f}")
    print("-" * 100)
    print(f"(okunan dolum: {sum(len(v) for v in dolum.values())}, funding kaydı: {sum(len(v) for v in fon.values())})")
    print(f"{'TOPLAM':<12}{sum(x['eslesti'] for x in satirlar):>4}/{len(satirlar):<3}{top_d:>13.2f}{top_g:>13.2f}"
          f"{top_g - top_d:>9.2f}")
    if hata:
        print("\n⚠ Bazı sembollerde okuma hatası (o sembolün işlemleri eşleşmemiş olabilir):")
        for s, (e1, e2) in hata.items():
            print(f"  {s}: dolum={e1} funding={e2}")
    print("\nNot: 'GERÇEK' = satış tutarı − alış tutarı − gerçek ücret + gerçek funding (borsa kaydı). Eşleşmeyen")
    print("işlemler toplama katılmaz. Borsa equity − yatırılan ile kıyaslarken açık pozisyonun uPnL'ini ekleyin.")


if __name__ == "__main__":
    asyncio.run(main())
