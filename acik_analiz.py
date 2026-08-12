"""
acik_analiz.py — ASIL AÇIK: ankor +0.237R diyor, canlı +0.1096R veriyor. Fark NEREYE gidiyor?

23 EKSEN KAPANDI ve hepsi aynı soruyu soruyordu: "backtest'i nasıl daha iyi yaparız."
En iyi geçen bulgu ankoru %2-3 iyileştiriyordu. AMA CANLI, ANKORUN YARISINDA DURUYOR —
açık %54. Yani yenmeye çalıştığımız hedefin yarısındayız.

Bu açığı kapatmak YENİ ALFA ARAMAK DEĞİL, zaten sahip olduğumuz alfayı geri almaktır.
Ve kaynağı ölçülebilir olduğu için bulunursa kesindir.

VERİ KAYNAKLARI (ikisi de zaten mevcut, yeni toplama gerekmez):
 · signals_log.csv — execution.py:303 HER sinyalin sonucunu ve red sebebini yazıyor
   (ts, symbol, strategy, direction, executed, reason). Kaçırılan işlemler burada.
 · trades.db — gerçekleşen giriş/çıkış fiyatları. Çıkış kayması burada.

ÖLÇÜLENLER:
 [1] KAÇIRILAN SİNYALLER — sebep ve kol bazında. Ankor HİÇBİR sinyali kaçırmıyor
     (yalnız koltuk yarışı var). Canlıda marjin, cooldown, borsa hatası, halt gibi
     ek redler var. Sistematik olarak iyi işlemleri kaçırıyorsak sebebi düzeltilebilir.
 [2] ÇIKIŞ KAYMASI — hiç ölçülmedi. Ankor stopun TAM seviyede dolduğunu varsayar.
     Gerçekte stop emri kayarak dolar. SL çıkışlarında gerçekleşen fiyat ile stop
     seviyesi arasındaki fark, işlem başına doğrudan R kaybıdır.
     (sl_price defterde TRAIL EDİLMİŞ son stoptur — çıkışın ona yakınlığı bu yüzden
      dolum kaymasının doğru ölçüsüdür, giriş stopunun değil.)
 [3] R AYRIŞTIRMASI — açığın hangi parçası neyle açıklanıyor, kalan ne kadar.

Kullanım (VPS'te):  cd /opt/bot2 && python3 acik_analiz.py
"""
import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))
SIG = os.path.join(BOT_DIR, "signals_log.csv")

ANK_R = 0.237          # ankor ortalama R
CANLI_R = 0.1096       # live_verify, aktif kollar (güncelse yeniden ölç)
ANK_SLIP_BP = 13.4     # ölçülen giriş kayması
DEPLOY = ("donchian", "squeeze", "bb", "mean_rev")
FUNDING_YIL = 0.022    # ölçülen fonlama maliyeti
ORT_TUTMA_GUN = 2.03   # ankor ortalama tutma süresi


def kol(s):
    s = (s or "").lower()
    if "donch" in s or "breakout" in s: return "donchian"
    if "squeeze" in s: return "squeeze"
    if "mean" in s or "bb" in s: return "bb"
    return s or "?"


def kacirilan():
    if not os.path.exists(SIG):
        print(f"  signals_log.csv yok ({SIG}) — kaçırılan sinyal ölçülemiyor.")
        return None
    top = Counter(); red = defaultdict(Counter); n = 0
    with open(SIG, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            k = kol(row.get("strategy"))
            if k not in DEPLOY:
                continue
            n += 1
            ok = str(row.get("executed", "0")).strip() in ("1", "True", "true")
            top[k] += 1
            if not ok:
                sebep = (row.get("reason") or "?").strip()
                # sayısal ayrıntıyı sil ki gruplansın ("Cooldown active (37m ...)" → "Cooldown active")
                for kes in ("(", " — ", ":"):
                    if kes in sebep:
                        sebep = sebep.split(kes)[0].strip()
                red[k][sebep or "?"] += 1
    return top, red, n


def cikis_kaymasi():
    if not os.path.exists(DB):
        print(f"  trades.db yok ({DB})")
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, side, entry_price, exit_price, sl_price, tp_price, strategy_scores"
        " FROM trades WHERE is_paper=0 AND exit_price>0 AND entry_price>0"
        " AND sl_price>0 AND tp_price>0").fetchall()
    con.close()
    sl_bp = []; tp_bp = []
    for sym, side, ep, xp, slp, tpp, sc in rows:
        if kol((sc or "")) not in DEPLOY and "strategy" not in (sc or ""):
            pass
        risk = abs(ep - slp)
        if risk <= 0:
            continue
        d_sl = abs(xp - slp); d_tp = abs(xp - tpp)
        yon = 1 if (side or "").lower().startswith("l") or (tpp > ep) else -1
        if d_sl < risk * 0.10:
            # stop çıkışı: yön lehine olmayan sapma = KAYIP. long'da xp < slp ise kötü.
            kayma = (xp - slp) * yon / ep * 10000     # bp, pozitif = LEHİMİZE
            sl_bp.append(kayma)
        elif d_tp < abs(tpp - ep) * 0.10:
            kayma = (xp - tpp) * yon / ep * 10000
            tp_bp.append(kayma)
    return sl_bp, tp_bp


def ort(x):
    return sum(x) / len(x) if x else 0.0


def main():
    print(f"\n{'=' * 96}")
    print("=== AÇIK ANALİZİ: ankor +%.3fR vs canlı +%.4fR ===" % (ANK_R, CANLI_R))
    acik = ANK_R - CANLI_R
    print(f"  açık = {acik:.4f}R  (ankorun %{acik/ANK_R*100:.0f}'i)")
    print(f"  Bu açığı kapatmak, bulunabilecek herhangi bir filtreden değerli:")
    print(f"  bugüne kadarki en iyi bulgu ankoru %2-3 iyileştiriyordu.")

    # ── [1] KAÇIRILAN SİNYALLER ──
    print(f"\n[1] KAÇIRILAN SİNYALLER (signals_log.csv)")
    k = kacirilan()
    if k:
        top, red, n = k
        print(f"    {n} sinyal (yalnız aktif kollar)")
        print(f"\n    {'kol':<10s} {'sinyal':>7s} {'alınan':>7s} {'kaçan':>6s} {'kaçan%':>7s}")
        for kk in sorted(top, key=lambda x: -top[x]):
            kac = sum(red[kk].values())
            print(f"    {kk:<10s} {top[kk]:>7d} {top[kk]-kac:>7d} {kac:>6d} "
                  f"{kac/top[kk]*100:>6.1f}%")
        print(f"\n    RED SEBEPLERİ (kol × sebep):")
        for kk in sorted(red, key=lambda x: -sum(red[x].values())):
            if not red[kk]:
                continue
            print(f"      {kk}:")
            for s, c in red[kk].most_common(8):
                print(f"        {c:>5d}  {s[:64]}")
        print(f"\n    ⚠ 'No signal' ve 'below_threshold' redleri NORMALDİR (sinyal yok demek).")
        print(f"      Asıl bakılacaklar: Cooldown, Max positions, Yetersiz bakiye, halt,")
        print(f"      setup failed. Bunlar ankorun modellemediği KAYIPLARDIR.")

    # ── [2] ÇIKIŞ KAYMASI ──
    print(f"\n[2] ÇIKIŞ KAYMASI (trades.db) — ankor stopun TAM seviyede dolduğunu varsayar")
    c = cikis_kaymasi()
    if c:
        sl_bp, tp_bp = c
        print(f"    {'çıkış':>8s} {'n':>5s} {'ort kayma(bp)':>14s} {'en kötü':>9s}  (+ = lehimize)")
        for ad, v in (("stop", sl_bp), ("hedef", tp_bp)):
            if v:
                print(f"    {ad:>8s} {len(v):>5d} {ort(v):>14.1f} {min(v):>9.1f}")
            else:
                print(f"    {ad:>8s} {0:>5d} {'—':>14s}")
        if len(sl_bp) < 10:
            print(f"    ⚠ n={len(sl_bp)} — yön göstergesi, kanıt değil.")

    # ── [3] R AYRIŞTIRMASI ──
    print(f"\n[3] R AYRIŞTIRMASI — açığın {acik:.4f}R'si nereye gidiyor?")
    SL_ORT = 0.027       # ankor medyan stop mesafesi (oran)
    giris_R = (ANK_SLIP_BP / 10000) / SL_ORT
    fon_R = (FUNDING_YIL / 365 * ORT_TUTMA_GUN) / SL_ORT
    cikis_R = 0.0
    if c and c[0]:
        cikis_R = abs(min(0.0, ort(c[0]))) / 10000 / SL_ORT
    kalan = acik - giris_R - fon_R - cikis_R
    print(f"\n    {'kaynak':<26s} {'R':>8s} {'açığın %':>10s}")
    for ad, v in (("giriş kayması (13.4bp)", giris_R),
                  ("fonlama (%2.2/yıl)", fon_R),
                  ("çıkış kayması (ölçülen)", cikis_R),
                  ("AÇIKLANAMAYAN kalan", kalan)):
        print(f"    {ad:<26s} {v:>8.4f} {v/acik*100:>9.0f}%")
    print(f"\n    Kalan büyükse iki ihtimal var:")
    print(f"      a) örneklem küçük — canlı R'nin güven aralığı geniş, gerçek fark yok olabilir")
    print(f"      b) yürütmede henüz ölçülmemiş bir kayıp var (zamanlama, kaçan sinyal,")
    print(f"         yanlış boyutlandırma). [1] ve [2] bunu daraltır.")
    print(f"\n    NOT: CANLI_R={CANLI_R} sabiti live_verify'ın son çalıştırmasından. Yeni")
    print(f"    işlemler biriktiyse önce `python3 live_verify.py` çalıştırıp güncelleyin.")


if __name__ == "__main__":
    main()
