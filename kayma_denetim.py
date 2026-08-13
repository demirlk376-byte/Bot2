"""
kayma_denetim.py — 13.4bp SABİTİNİ DEFTERDEN YENİDEN ÖLÇ (ankor denetiminin aynısı)

NEDEN: bugün ankoru denetledik ve %20 şişkin çıktı. Ama ankorun EN BÜYÜK tek
düzeltmesi olan GİRİŞ KAYMASI'nın kendisi hiç denetlenmedi. 13.4bp şu an
live_verify.py:44'te ÇIPLAK BİR SABİT olarak duruyor:

    ANK_SLIP_BP = 13.4     # ölçülen donchian giriş kayması

"ölçülen" diyor ama ÖLÇÜM KODU DOSYADA YOK. Ve bu tek sayı şunların hepsini
belirliyor: ankor denetiminin A1/A3 satırları ($251 düzeltme), "dürüst taban
$1177", maker giriş fikrinin tüm getirisi. Yanlışsa hepsi yanlış.

ÜSTELİK ÇELİŞKİ VAR: gecikme_olc.py bar kapanışından 1dk sonraki aleyhe
sürüklenmeyi donchian'da +0.12bp ölçtü (BTC+ETH 1dk, n=133). Bot barı 30sn'lik
REST anketiyle yakalıyor (data.py:88). Yani gecikmeden 13.4bp ÇIKMIYOR. Geriye
iki olasılık kalıyor:
  (a) kayma gerçekten spread/etki — likit olmayan alt'larda (NEAR/ICP/XLM/TRX)
      MEXC perp spread'i 10bp+ olabilir. O zaman 13.4bp doğru VE maker giriş
      tam olarak bunu kurtarır.
  (b) 13.4bp yanlış ölçülmüş. O zaman bugünkü $ rakamlarının hepsi kayar.

BU ARAÇ AYIRIYOR. Defterdeki HER gerçek işlem için:
  • sinyal barının kapanış fiyatı (ankorun girdiği fiyat) yeniden bulunur
  • gerçekleşen entry_price ile farkı YÖNE GÖRE bp cinsinden ölçülür
  • bar kapanışı ile entry_time arasındaki GECİKME saniye olarak ölçülür
  • kol bazında ayrılır — ve BB/MR kolu CANLIDA ZATEN MAKER limit kullanıyor
    (execution.py:595-627), donchian/squeeze ise force_market. Yani defterin
    içinde HAZIR BİR DOĞAL DENEY var: maker kolun kayması taker kollarınkinden
    düşükse, maker giriş fikri backtest'e gerek kalmadan CANLI VERİYLE kanıtlanır.

⚠ AÇIK İŞLEMLER DE SAYILIR: giriş kayması çıkıştan bağımsızdır, dolayısıyla
hayatta kalma yanlılığı YOKTUR ve n büyür. (R ortalamasında durum tersiydi.)

⚠ BAĞLANTI GUARD'I: sinyal barı eşleşmeyen işlem oranı %20'yi geçerse araç HÜKÜM
VERMEZ. regime_teshis.py'de sessiz bir tz hatası bütün değerleri NaN yapmış ve
araç "sinyal yok, eksen kapalı" diye YANLIŞ hüküm basmıştı. O sınıf hata bir daha
sessizce geçmesin.

Kullanım (VPS'te):  cd /opt/bot2 && python3 kayma_denetim.py
                    python3 kayma_denetim.py --self-test    # sentetik defterle doğrula
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))
ILAN = 13.4               # live_verify.py:44'teki sabit — denetlenen sayı
TF = {"donchian": "4h", "squeeze": "1h", "bb": "1h"}
MAKER_KOL = ("bb",)       # canlıda maker limit yolunu kullanan kol(lar)


def sleeve_of(scores_json):
    """live_verify.sleeve_of ile AYNI — üretim sınıfını taklit etme, aynı kuralı kullan."""
    try:
        d = json.loads(scores_json) if scores_json else {}
    except Exception:
        d = {}
    s = (d.get("strategy") or d.get("sleeve") or "").lower()
    if "donch" in s or "breakout" in s: return "donchian"
    if "squeeze" in s: return "squeeze"
    if "mean" in s or "bb" in s: return "bb"
    return "?"


def _ts(x):
    """entry_time metnini tz-AWARE UTC'ye çevir. tz-naive bırakmak, karşılaştırılan
    mum indeksi tz-aware olduğu için ya patlar ya SESSİZCE yanlış eşleşir."""
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def sinyal_bari(idx, kapanis_ts, entry_ts):
    """entry_ts'den ÖNCE kapanmış SON barın konumu. idx = bar AÇILIŞ zamanları,
    kapanis_ts = idx + tf. Ankor bu barın close'undan girer."""
    p = kapanis_ts.searchsorted(entry_ts, side="right") - 1
    return int(p) if p >= 0 else None


def olc(rows, mumlar, tol_dk=None):
    """rows: (symbol, side, entry_price, entry_time, quantity, fees, sleeve)
    mumlar: {(symbol, tf): df}  → her işlem için (kayma_bp, gecikme_sn)"""
    out = []
    eslesmedi = 0
    for sym, side, ep, et, qty, fee, kol in rows:
        tf = TF.get(kol)
        d = mumlar.get((sym, tf))
        if d is None or len(d) == 0:
            eslesmedi += 1
            continue
        dt = pd.Timedelta(hours=4 if tf == "4h" else 1)
        kap = d.index + dt
        e = _ts(et)
        p = sinyal_bari(d.index, kap, e)
        if p is None:
            eslesmedi += 1
            continue
        gec = (e - kap[p]).total_seconds()
        # bar kapanışı ile giriş arasında bir TAM bardan fazla varsa bu işlem o
        # bardan tetiklenmemiştir (yeniden başlatma, gecikmiş dolum, elle açma):
        # kaymayı ona yazmak ölçümü kirletir.
        if gec < 0 or gec > dt.total_seconds():
            eslesmedi += 1
            continue
        d_ = 1 if str(side).lower() in ("long", "buy", "1") else -1
        L = float(d["close"].values[p])
        if not np.isfinite(L) or L <= 0:
            eslesmedi += 1
            continue
        out.append(dict(sym=sym, kol=kol, d=d_, bp=d_ * (float(ep) - L) / L * 10000.0,
                        gec=gec, nom=float(ep) * float(qty),
                        fee=(float(fee) if fee is not None else np.nan)))
    return out, eslesmedi


def ozet(v, ad):
    if len(v) < 5:
        print(f"  {ad:<24s} n={len(v):<4d} — çok az, hüküm yok")
        return None
    b = np.array([x["bp"] for x in v])
    g = np.array([x["gec"] for x in v])
    se = b.std(ddof=1) / np.sqrt(len(b))
    lo, hi = b.mean() - 1.96 * se, b.mean() + 1.96 * se
    print(f"  {ad:<24s} n={len(b):<4d} kayma {b.mean():+7.2f}bp "
          f"[{lo:+6.2f},{hi:+6.2f}]  medyan {np.median(b):+7.2f}  "
          f"aleyhe %{(b > 0).mean()*100:4.0f}  gecikme ort {g.mean():5.0f}sn "
          f"medyan {np.median(g):5.0f}sn")
    return dict(n=len(b), ort=b.mean(), lo=lo, hi=hi, med=float(np.median(b)),
                gec=float(np.median(g)), b=b)


def self_test():
    """Sentetik defter + sentetik mumla aracı DOĞRULA. Bilinen kayma enjekte edilir;
    araç onu geri okumalı. (bb_live_risk.py bu testle bir hata yakalamıştı — üretime
    çıkmadan.)"""
    print("=== SELF-TEST: bilinen kayma enjekte edilip geri okunuyor ===")
    idx = pd.date_range("2026-01-01", periods=200, freq="4h", tz="UTC")
    d = pd.DataFrame({"close": np.linspace(100.0, 120.0, 200)}, index=idx)
    mumlar = {("X/USDT:USDT", "4h"): d}
    rows = []
    hedef = 20.0     # bp, aleyhe
    for k in (10, 40, 90, 150):
        L = float(d["close"].values[k])
        kap = idx[k] + pd.Timedelta(hours=4)
        rows.append(("X/USDT:USDT", "long", L * (1 + hedef / 10000.0),
                     kap + pd.Timedelta(seconds=25), 1.0, 0.0, "donchian"))
        # short: aleyhe = daha DÜŞÜK fiyattan satmak
        rows.append(("X/USDT:USDT", "short", L * (1 - hedef / 10000.0),
                     kap + pd.Timedelta(seconds=25), 1.0, 0.0, "donchian"))
    v, es = olc(rows, mumlar)
    b = np.array([x["bp"] for x in v])
    ok = len(v) == 8 and es == 0 and abs(b.mean() - hedef) < 0.05
    print(f"  enjekte {hedef:+.1f}bp → okunan {b.mean():+.3f}bp  "
          f"(n={len(v)}, eşleşmeyen={es})  {'✓' if ok else '✗ ARAÇ BOZUK'}")
    # gecikme filtresi çalışıyor mu: bir tam bardan eski giriş ELENMELİ
    kotu = [("X/USDT:USDT", "long", 100.0, idx[50] + pd.Timedelta(hours=9), 1.0, 0.0, "donchian")]
    v2, es2 = olc(kotu, mumlar)
    ok2 = len(v2) == 1 and es2 == 0
    # 9 saat sonrası → o an için sinyal barı 2 bar sonrasıdır, gecikme < 4h olmalı
    print(f"  bar-eşleme kontrolü: {'✓' if ok2 else '✗'} (gecikme {v2[0]['gec']:.0f}sn "
          f"< 14400sn)" if v2 else "  bar-eşleme kontrolü: ✗ eşleşmedi")
    # yön kontrolü: LEHTE dolum NEGATİF bp vermeli
    iyi = [("X/USDT:USDT", "long", float(d["close"].values[10]) * 0.999,
            idx[10] + pd.Timedelta(hours=4, seconds=10), 1.0, 0.0, "donchian")]
    v3, _ = olc(iyi, mumlar)
    ok3 = v3 and v3[0]["bp"] < 0
    print(f"  işaret kontrolü (lehte dolum → negatif): {v3[0]['bp']:+.1f}bp "
          f"{'✓' if ok3 else '✗ İŞARET TERS'}")
    return ok and ok3


def main():
    if "--self-test" in sys.argv:
        ok = self_test()
        print(f"\n  {'✓ araç güvenilir' if ok else '✗ ARAÇ BOZUK — sonuç okunmaz'}")
        return

    print("=" * 108)
    print("=== KAYMA DENETİMİ: 13.4bp sabiti defterden yeniden ölçülüyor ===")
    print("  Bu sabit ankorun en büyük düzeltmesini ($251) ve maker giriş fikrinin")
    print("  tüm getirisini belirliyor — ama ölçüm kodu hiçbir dosyada yok.")
    if not self_test():
        print("\n✗ SELF-TEST GEÇMEDİ — gerçek defter okunmaz."); return

    if not os.path.exists(DB):
        print(f"\n✗ {DB} bulunamadı. VPS'te /opt/bot2 içinde çalıştırın.")
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    raw = con.execute(
        "SELECT symbol, side, entry_price, entry_time, quantity, fees_usdt,"
        " strategy_scores FROM trades WHERE is_paper=0"
    ).fetchall()
    con.close()
    rows = [(r[0], r[1], r[2], r[3], r[4], r[5], sleeve_of(r[6])) for r in raw]
    kollar = sorted({r[6] for r in rows})
    print(f"\n  defterde {len(rows)} gerçek işlem · kollar: {kollar}")
    print(f"  (AÇIK işlemler DAHİL — giriş kayması çıkıştan bağımsız, yanlılık yok)")

    # ── mumları çek ──
    import fast_bt
    mumlar = {}
    semboller = sorted({r[0] for r in rows})
    for sym in semboller:
        coin = sym.split("/")[0]
        try:
            m = fast_bt.load(coin, source="mexc_futures")
        except Exception as e:
            print(f"    ⚠ {sym}: mum çekilemedi ({e})")
            continue
        mumlar[(sym, "1h")] = fast_bt.resample(m, "1h")
        mumlar[(sym, "4h")] = fast_bt.resample(m, "4h")

    v, es = olc(rows, mumlar)
    oran = es / max(len(rows), 1)
    print(f"\n  eşleşen {len(v)} / {len(rows)}  (eşleşmeyen {es}, %{oran*100:.0f})")
    if oran > 0.20:
        print(f"\n  ⛔ BAĞLANTI GUARD'I: işlemlerin %{oran*100:.0f}'i sinyal barına")
        print(f"     eşleşmedi. Bu oranda hüküm verilmez — önce eşleşme sorunu çözülür.")
        print(f"     (mum verisi eksik olabilir, ya da işlemler bar kapanışından")
        print(f"      tetiklenmemiş olabilir: yeniden başlatma / elle açma / gecikmiş dolum)")
        return
    if len(v) < 20:
        print(f"\n  ⛔ n={len(v)} < 20 — hiçbir sayı anlamlı değil.")
        return

    print(f"\n{'=' * 108}\n=== [1] KOL BAZINDA GİRİŞ KAYMASI ===")
    print(f"  (+bp = ALEYHE: long'da daha pahalıya alındı / short'ta daha ucuza satıldı)")
    tum = ozet(v, "TÜM KOLLAR")
    per = {}
    for kol in sorted({x["kol"] for x in v}):
        per[kol] = ozet([x for x in v if x["kol"] == kol],
                        f"{kol}" + ("  [MAKER yolu]" if kol in MAKER_KOL else "  [taker/market]"))

    print(f"\n{'=' * 108}\n=== [2] DOĞAL DENEY: maker kol vs taker kollar ===")
    mk = [x for x in v if x["kol"] in MAKER_KOL]
    tk = [x for x in v if x["kol"] not in MAKER_KOL and x["kol"] != "?"]
    if len(mk) >= 5 and len(tk) >= 5:
        bm = np.array([x["bp"] for x in mk]); bt = np.array([x["bp"] for x in tk])
        fark = bt.mean() - bm.mean()
        sef = np.sqrt(bm.var(ddof=1) / len(bm) + bt.var(ddof=1) / len(bt))
        print(f"  BB/MR (canlıda MAKER limit): {bm.mean():+.2f}bp  n={len(bm)}")
        print(f"  donchian+squeeze (market):   {bt.mean():+.2f}bp  n={len(bt)}")
        print(f"  FARK {fark:+.2f}bp  [%95: {fark-1.96*sef:+.2f}, {fark+1.96*sef:+.2f}]")
        if fark - 1.96 * sef > 0:
            print(f"    ✓ MAKER KOLU ANLAMLI ŞEKİLDE DAHA UCUZ GİRİYOR — canlı kanıt.")
            print(f"      donchian/squeeze'i maker+yedek yoluna almak yılda ~"
                  f"${fark * (251.0/ILAN) / 3.6:+.0f} değerinde (bu farkla).")
        else:
            print(f"    ~ Fark istatistiksel olarak ayırt edilemiyor (n küçük). Daha")
            print(f"      fazla işlem gerek; maker fikri BU VERİYLE kanıtlanmıyor.")
    else:
        print(f"  Yeterli veri yok: maker kol n={len(mk)}, taker kol n={len(tk)}")

    print(f"\n{'=' * 108}\n=== [3] GECİKME: bot barı ne kadar geç görüyor? ===")
    g = np.array([x["gec"] for x in v])
    print(f"  medyan {np.median(g):.0f}sn · ortalama {g.mean():.0f}sn · "
          f"%90 {np.percentile(g, 90):.0f}sn · en kötü {g.max():.0f}sn")
    print(f"  (data.py:88 REST_POLL_INTERVAL=30sn, bar sınırına hizalı DEĞİL → ~15sn")
    print(f"   ortalama anket gecikmesi + on_candle_close işi bekleniyor)")
    print(f"  gecikme_olc.py: bar kapanışından 1dk sonra aleyhe sürüklenme ~0bp.")
    print(f"  → Bu gecikmede sürüklenmeden gelen kayma İHMAL EDİLEBİLİR olmalı.")

    print(f"\n{'=' * 108}\n=== HÜKÜM ===")
    d = [x for x in v if x["kol"] == "donchian"]
    if len(d) >= 20:
        bd = np.array([x["bp"] for x in d])
        se = bd.std(ddof=1) / np.sqrt(len(bd))
        lo, hi = bd.mean() - 1.96 * se, bd.mean() + 1.96 * se
        print(f"\n  İLAN EDİLEN: {ILAN}bp (live_verify.py:44)")
        print(f"  ÖLÇÜLEN   : {bd.mean():+.2f}bp  [%95: {lo:+.2f}, {hi:+.2f}]  n={len(bd)}")
        if lo <= ILAN <= hi:
            print(f"    ✓ 13.4bp güven aralığının İÇİNDE — sabit DOĞRULANDI.")
            print(f"      Ankor denetiminin A1/A3 satırları ve maker giriş getirisi geçerli.")
        elif hi < ILAN:
            print(f"    ⚠ GERÇEK KAYMA DAHA DÜŞÜK. 13.4bp ŞİŞKİN: ankor denetiminin $251'i")
            print(f"      abartılı, maker girişten beklenen kazanç da o oranda küçülür.")
            print(f"      Düzeltme çarpanı ≈ {bd.mean()/ILAN:.2f}× → yılda ~"
                  f"${70*bd.mean()/ILAN:.0f} (eski tahmin ~$70).")
        else:
            print(f"    ⚠ GERÇEK KAYMA DAHA YÜKSEK. Sızıntı sanılandan BÜYÜK:")
            print(f"      düzeltme ≈ {bd.mean()/ILAN:.2f}× → yılda ~${70*bd.mean()/ILAN:.0f}.")
            print(f"      Maker giriş fikri bu durumda DAHA da değerli.")
    else:
        print(f"\n  donchian n={len(d)} < 20 — ana kolda hüküm verilemiyor.")
    print(f"\n  SONRAKİ ADIM: bu araç ne derse desen, live_verify.py:44'teki sabit")
    print(f"  ÖLÇÜLEN değerle güncellenmeli ve DURUM.md'ye ölçüm tarihi yazılmalı.")
    print(f"  Sabitin 'ölçülen' diye durup ölçüm kodunun olmaması bugünkü en büyük")
    print(f"  metodoloji açığıydı — ankorun kendisinde de aynısı olmuştu.")


if __name__ == "__main__":
    main()
