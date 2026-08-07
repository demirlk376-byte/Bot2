"""
pairs_paper.py — PAIRS'İ KÂĞIT ÜZERİNDE İLERİYE DÖNÜK KOŞTUR (sıfır risk, sıfır bot teması).

NEDEN BU, ŞİMDİ YAPILACAK DOĞRU ŞEY:
pairs ledger'ın TEK hayatta kalan bulgusu (+$532, PF 1.63, 4/4 yıl+, korelasyon −0.310,
permütasyon p=0.006) ve birleşik portföy ölçümü onu doğruladı (+$372 @k=0.70, dört yılın
dördü de iyileşiyor, puan başına $59 — en yakın alternatifin 2.5 katı).

AMA bu rakamların HEPSİ aynı 2023-2026 verisinden geliyor ve o veri bu oturumda 18 eksende
tarandı — yani epey aşındı. **İleriye dönük tek bir ay, o rakamların gerçekliği hakkında
bugüne kadarki tüm testlerden fazlasını söyler.** Overfit edilemeyen tek şey gelecektir.

BU BETİK NE YAPMAZ (güvenlik sınırları, hepsi kasıtlı):
  · EMİR GÖNDERMEZ. ccxt'in yalnızca PUBLIC uçlarını kullanır — API anahtarı bile İSTEMEZ.
  · bot'un hiçbir dosyasına dokunmaz (main.py / execution.py / exchange.py / trades.db).
  · kendi durumunu AYRI bir JSON'da tutar; bot'un veritabanına yazmaz.
  · bot ile aynı sembollerde "çakışma" diye bir sorunu yoktur — hiçbir pozisyon açmaz.

NE YAPAR: her çalıştığında günlük kapanışları çeker, 8 çiftin z-skorunu hesaplar, açık
kâğıt pozisyonların çıkış şartını kontrol eder, yeni giriş varsa kaydeder ve HER OLAYI
pairs_paper.csv'ye yazar. Böylece dönüşte "backtest ne dedi, gerçek ne oldu" doğrudan
karşılaştırılabilir.

PARAMETRELER LEDGER'DAN, DEĞİŞTİRİLMEDEN: z giriş 2.0 / çıkış 0.5 / stop 3.5 · pencere 60 gün
· maksimum tutuş 20 gün · çiftler TRAIN'de seçilmişti (in-sample seçim yok, liste SABİT).
Bu betikte hiçbir parametre "iyileştirilmedi" — amaç ölçmek, uydurmak değil.

Kullanım:
    python3 pairs_paper.py            # bir tur çalıştır (cron/timer için)
    python3 pairs_paper.py --ozet     # birikmiş kâğıt sonuçları raporla
"""
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get("PAIRS_STATE", os.path.join(BOT_DIR, "pairs_paper_state.json"))
LOG = os.environ.get("PAIRS_LOG", os.path.join(BOT_DIR, "pairs_paper.csv"))

# ── LEDGER PARAMETRELERİ — DEĞİŞTİRİLMEDİ ──
PAIRS = [("ETC", "ETH"), ("ATOM", "DOT"), ("BTC", "ETH"), ("ADA", "DOT"),
         ("XLM", "XRP"), ("ALGO", "DOT"), ("ADA", "ALGO"), ("ADA", "ATOM")]
Z_IN, Z_OUT, Z_STOP = 2.0, 0.5, 3.5
ZWIN = 60          # gün
MAXHOLD = 20       # gün
NOTIONAL = 190.0   # backtest ölçeği (çift başına toplam nominal, 2 bacak)
FEE = 0.0001


def coins():
    return sorted({c for p in PAIRS for c in p})


def fetch_daily(symbols, limit=200):
    """MEXC'ten günlük kapanışlar — PUBLIC uç, API anahtarı GEREKMEZ."""
    import ccxt
    ex = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    out = {}
    try:
        ex.load_markets()
        for c in symbols:
            sym = f"{c}/USDT:USDT"
            if sym not in ex.markets:
                print(f"  ⚠ {c}: piyasa yok, atlanıyor"); continue
            o = ex.fetch_ohlcv(sym, "1d", limit=limit)
            out[c] = {int(r[0] // 86400000): float(r[4]) for r in o if r[4]}
    finally:
        try: ex.close()
        except Exception: pass
    return out


def zscore(series_days, prices, day):
    """day gününde z. YALNIZCA o güne kadarki veriyle (lookahead yok)."""
    hist = [prices[d] for d in series_days if d <= day and d in prices]
    if len(hist) < ZWIN + 1:
        return None
    win = hist[-(ZWIN + 1):-1]        # SON GÜN HARİÇ — kendi barını ortalamaya katma
    mu = sum(win) / len(win)
    var = sum((v - mu) ** 2 for v in win) / (len(win) - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return None
    return (hist[-1] - mu) / sd


def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {"open": {}, "closed": []}


def save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    os.replace(tmp, STATE)          # atomik — yarıda kesilirse eski dosya bozulmaz


def log_event(row):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["zaman", "olay", "cift", "yon", "z", "fiyat_a", "fiyat_b",
                        "gun", "getiri", "sebep"])
        w.writerow(row)


def run_once():
    cs = coins()
    print(f"pairs_paper · {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"  {len(PAIRS)} çift · {len(cs)} coin · günlük kapanışlar çekiliyor…")
    px = fetch_daily(cs)
    if len(px) < len(cs):
        print(f"  ⚠ {len(cs)-len(px)} coin çekilemedi — eksik çiftler atlanacak")
    st = load_state()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for a, b in PAIRS:
        key = f"{a}/{b}"
        if a not in px or b not in px:
            continue
        days = sorted(set(px[a]) & set(px[b]))
        if len(days) < ZWIN + 2:
            continue
        today = days[-1]
        spread = {d: math.log(px[a][d]) - math.log(px[b][d]) for d in days}
        z = zscore(days, spread, today)
        if z is None:
            continue
        pa, pb = px[a][today], px[b][today]

        pos = st["open"].get(key)
        if pos:
            held = today - pos["gun"]
            reason = None
            if abs(z) < Z_OUT: reason = "hedef(z<0.5)"
            elif abs(z) > Z_STOP: reason = "stop(z>3.5)"
            elif held >= MAXHOLD: reason = f"süre({held}g)"
            if reason:
                d_ = pos["yon"]
                ra = d_ * (pa - pos["fiyat_a"]) / pos["fiyat_a"]
                rb = -d_ * (pb - pos["fiyat_b"]) / pos["fiyat_b"]
                ret = (ra + rb) / 2 - 4 * FEE
                st["closed"].append({**pos, "cift": key, "kapanis_gun": today,
                                     "cikis_a": pa, "cikis_b": pb,
                                     "getiri": ret, "sebep": reason})
                del st["open"][key]
                log_event([now, "KAPAT", key, d_, f"{z:.2f}", pa, pb, today,
                           f"{ret:.5f}", reason])
                print(f"  KAPAT {key:<12s} yön {d_:+d} · getiri {ret*100:+.2f}% · {reason}")
            else:
                print(f"  tut   {key:<12s} yön {pos['yon']:+d} · z {z:+.2f} · {held}g")
            continue

        if abs(z) >= Z_IN:
            d_ = -1 if z > 0 else 1        # spread yüksekse a'yı SAT / b'yi AL
            st["open"][key] = {"yon": d_, "gun": today, "fiyat_a": pa, "fiyat_b": pb,
                               "giris_z": z, "acilis": now}
            log_event([now, "AÇ", key, d_, f"{z:.2f}", pa, pb, today, "", ""])
            print(f"  AÇ    {key:<12s} yön {d_:+d} · z {z:+.2f}")
        else:
            print(f"  —     {key:<12s} z {z:+.2f} (eşik {Z_IN})")

    save_state(st)
    print(f"\n  açık {len(st['open'])} · kapanan {len(st['closed'])} · durum: {STATE}")


def ozet():
    st = load_state()
    cl = st["closed"]
    print("=" * 72)
    print("PAIRS KÂĞIT SONUÇLARI — ileriye dönük, örneklem-dışı")
    print("=" * 72)
    if not cl:
        print(f"\n  henüz kapanan işlem yok · açık {len(st['open'])}")
        print("  (giriş eşiği z≥2.0 — sabırlı olmak gerekiyor, ayda ~6-7 işlem beklenir)")
        return
    rets = [c["getiri"] for c in cl]
    n = len(rets)
    usd = [r * NOTIONAL for r in rets]
    wins = sum(1 for r in rets if r > 0)
    gp = sum(u for u in usd if u > 0); gl = -sum(u for u in usd if u < 0)
    m = sum(rets) / n
    var = sum((r - m) ** 2 for r in rets) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n) if n > 1 else float("nan")
    print(f"\n  kapanan {n} · açık {len(st['open'])}")
    print(f"  toplam  ${sum(usd):+.2f}  (nominal ${NOTIONAL:.0f}/çift, backtest ölçeği)")
    print(f"  ortalama getiri {m*100:+.3f}%  %95 aralık "
          f"[{(m-1.96*se)*100:+.3f}, {(m+1.96*se)*100:+.3f}]")
    print(f"  kazanma %{wins/n*100:.0f} · PF {gp/gl:.2f}" if gl > 0 else "  PF ∞")
    print(f"\n  BACKTEST BEKLENTİSİ: 260 işlemde +$532 → işlem başına ${532/260:+.2f}")
    print(f"  KÂĞIT GERÇEKLEŞEN   : {n} işlemde ${sum(usd):+.2f} → işlem başına ${sum(usd)/n:+.2f}")
    if n < 15:
        print(f"\n  ⚠ n={n} — HİÇBİR ÇIKARIM YAPMA. Aralık çok geniş, tek işlem tabloyu değiştirir.")
    print(f"\n  {'çift':<12s} {'n':>3s} {'toplam$':>9s}")
    per = {}
    for c in cl:
        per.setdefault(c["cift"], []).append(c["getiri"] * NOTIONAL)
    for k in sorted(per):
        print(f"  {k:<12s} {len(per[k]):>3d} {sum(per[k]):>+9.2f}")


if __name__ == "__main__":
    try:
        if "--ozet" in sys.argv:
            ozet()
        else:
            run_once()
    except Exception as e:
        print(f"✗ hata: {type(e).__name__}: {e}")
        sys.exit(1)
