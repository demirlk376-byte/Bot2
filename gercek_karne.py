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

    # 1) Borsa dolumlarından GİDİŞ-DÖNÜŞLERİ kur: (sembol, bacak) başına pozisyon sıfırdan açılıp sıfıra dönene kadar.
    #    MEXC order_deals 'side': 1 long aç, 2 short kapat, 3 short aç, 4 long kapat (bacak ve yön buradan;
    #    alış = 1/2, satış = 3/4).
    turlar = defaultdict(list)
    for s, ds in dolum.items():
        acik = {}
        for x in ds:
            kod = str((x.get("info") or {}).get("side") or "")
            if kod not in ("1", "2", "3", "4"):
                continue
            bacak = "long" if kod in ("1", "4") else "short"
            ac = kod in ("1", "3")
            v = float(x["amount"])
            tutar = float(x["price"]) * v * x["_cs"]    # ccxt 'cost' alanına güvenme
            ucr = float((x.get("fee") or {}).get("cost") or 0) \
                if ((x.get("fee") or {}).get("currency") or "USDT").upper() == "USDT" else 0.0
            tr = acik.get(bacak)
            if tr is None:
                if not ac:
                    continue                       # pencere başında yarım kalmış kapanış
                tr = acik[bacak] = dict(bacak=bacak, ilk=int(x["timestamp"]), son=int(x["timestamp"]), poz=0.0,
                                        alis=0.0, satis=0.0, ucret=0.0)
            tr["poz"] += v if ac else -v
            tr["son"] = int(x["timestamp"])
            if kod in ("1", "2"):                      # ccxt 'side' alanı yanlış (2→sell, 3/4 çevrilmez)
                tr["alis"] += tutar
            else:
                tr["satis"] += tutar
            tr["ucret"] += ucr
            if abs(tr["poz"]) < 1e-9:
                turlar[s].append(tr)
                del acik[bacak]
    # 2) Defter işlemlerini en yakın girişli tura eşle (aynı sembol ve bacak, giriş farkı ≤ 3 saat)
    kullanildi = set()
    satirlar, eslesmeyen = [], []
    for t in sorted(islemler, key=lambda x: x["entry_time"]):
        s = t["symbol"]
        bacak = "long" if str(t["side"]).lower() in ("long", "buy") else "short"
        g = ms(t["entry_time"])
        aday = [(abs(tr["ilk"] - g), i) for i, tr in enumerate(turlar.get(s, []))
                if tr["bacak"] == bacak and (s, i) not in kullanildi]
        sl = EU._skor(t).get("sl0") or t["sl_price"]
        risk = abs(t["entry_price"] - sl) * t["quantity"]
        kol = EU.kol_adi(t.get("strategy_scores"))
        if not aday or min(aday)[0] > 3 * 3_600_000:
            satirlar.append(dict(kol=kol, eslesti=False, defter=t["pnl_usdt"], cikis=ms(t["exit_time"])))
            eslesmeyen.append((t, min(aday)[0] if aday else None))
            continue
        _, i = min(aday)
        kullanildi.add((s, i))
        tr = turlar[s][i]
        brut = tr["satis"] - tr["alis"]
        funding = sum(float(f.get("amount") or 0) for f in fon.get(s, [])
                      if tr["ilk"] < int(f.get("timestamp") or 0) <= tr["son"])
        net = brut - tr["ucret"] + funding
        satirlar.append(dict(kol=kol, eslesti=True, defter=t["pnl_usdt"], gercek=net, ucret=tr["ucret"],
                             funding=funding, R=net / risk if risk > 0 else None,
                             giris_fark_dk=(tr["ilk"] - g) / 60_000, cikis=tr["son"]))

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
    print(f"(borsadan kurulan gidiş-dönüş: {sum(len(v) for v in turlar.values())})")
    # SON 7 GÜN — çıkışı (borsadaki son dolum) son 7 günde olan işlemler, kol kol
    sinir = int(datetime.now().timestamp() * 1000) - 7 * 86_400_000
    yakin = [x for x in satirlar if x.get("cikis", 0) >= sinir]
    print(f"\nSON 7 GÜN (kapanan işlem: {len(yakin)})")
    if yakin:
        print(f"{'kol':<12}{'işlem':>6}{'GERÇEK USDT':>13}{'defter USDT':>13}")
        g7 = defaultdict(list)
        for x in yakin:
            g7[x["kol"]].append(x)
        for kol, xs in sorted(g7.items(), key=lambda kv: -sum(x.get("gercek", 0) for x in kv[1])):
            e = [x for x in xs if x["eslesti"]]
            esl = "" if len(e) == len(xs) else f"  ({len(xs) - len(e)} eşleşmedi)"
            print(f"{kol:<12}{len(xs):>6}{sum(x['gercek'] for x in e):>13.2f}{sum(x['defter'] for x in xs):>13.2f}{esl}")
        print(f"{'TOPLAM':<12}{len(yakin):>6}{sum(x.get('gercek', 0) for x in yakin):>13.2f}"
              f"{sum(x['defter'] for x in yakin):>13.2f}")
    else:
        print("  bu hafta kapanan işlem yok")
    if not any(turlar.values()) and any(dolum.values()):
        x = next(d for ds in dolum.values() for d in ds)
        print(f"(uyarı: dolumlarda yön kodu okunamadı; info alanları: {sorted((x.get('info') or {}).keys())})")
    fk = [x["giris_fark_dk"] for x in satirlar if x["eslesti"]]
    if fk:
        print(f"(defter girişi ile borsa ilk dolumu arasındaki fark, dakika: medyan {np.median(fk):+.1f}, "
              f"en büyük {max(fk, key=abs):+.1f})")
    if eslesmeyen:
        print("\nEşleşmeyenlerden örnekler (defter giriş → en yakın borsa turu farkı):")
        for t, f in eslesmeyen[:5]:
            print(f"  {t['symbol']:<16}{t['side']:<6}giriş {t['entry_time'][:19]}  "
                  f"{'tur yok' if f is None else f'{f / 60_000:+.0f} dk'}")
    if hata:
        print("\n⚠ Bazı sembollerde okuma hatası (o sembolün işlemleri eşleşmemiş olabilir):")
        for s, (e1, e2) in hata.items():
            print(f"  {s}: dolum={e1} funding={e2}")
    print("\nNot: 'GERÇEK' = satış tutarı − alış tutarı − gerçek ücret + gerçek funding (borsa kaydı). Eşleşmeyen")
    print("işlemler toplama katılmaz. Borsa equity − yatırılan ile kıyaslarken açık pozisyonun uPnL'ini ekleyin.")


async def telegram_gonder(metin: str) -> None:
    """Çıktıyı Telegram'a eş genişlikli yazıyla gönderir (haftalık zamanlanmış görev için: --telegram)."""
    import html
    import aiohttp
    tg = load_config().telegram
    if not (tg.token and tg.chat_id):
        print("Telegram ayarı yok (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID) — gönderilmedi.")
        return
    satirlar, parca, parcalar = metin.splitlines(), "", []
    for sat in satirlar:                       # Telegram sınırı 4096 karakter (kaçışlı metin üzerinden)
        sat = html.escape(sat)[:3500]
        if len(parca) + len(sat) + 1 > 3500:
            parcalar.append(parca)
            parca = ""
        parca += sat + "\n"
    if parca.strip():
        parcalar.append(parca)
    url = f"https://api.telegram.org/bot{tg.token}/sendMessage"
    async with aiohttp.ClientSession() as oturum:
        for pr in parcalar:
            async with oturum.post(url, json={"chat_id": tg.chat_id, "parse_mode": "HTML",
                                              "text": f"<pre>{pr}</pre>"}) as r:
                if r.status != 200:
                    print(f"Telegram gönderimi başarısız: HTTP {r.status}")


async def _telegramli() -> None:
    import contextlib
    import io
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon):
            await main()
    except Exception as e:                     # karne hata verirse bunu da bildir
        tampon.write(f"\n⚠ Gerçek karne çalışırken hata: {type(e).__name__}: {e}\n")
    metin = tampon.getvalue()
    print(metin)
    await telegram_gonder("📊 HAFTALIK GERÇEK KARNE\n" + metin)


if __name__ == "__main__":
    asyncio.run(_telegramli() if "--telegram" in sys.argv else main())
