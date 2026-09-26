"""
erken_uyari.py — "Bu kayıp NORMAL mi, ALARM mı?" Tek komut, SALT OKUR, emir göndermez.

NEDEN (2026-09-26 kayıp anatomisi, RESEARCH_LEDGER.md):
  · Kaybın tamamı −1R stoplardan geliyor ve düşüşler şans dizisi: İKİZ işlemleri rastgele
    sıraya dizilince maxDD medyanı %50, gerçek tarih %41. Kötü dönemi önceden tanıyan kural
    YOK (defterde 30+ deneme reddedildi). Koruma "kaybı öngörmek" değil, NORMAL kaybı
    ANORMALDEN ayırmak.
  · Eski durdurma kuralları kalibre değildi: "3 ay üst üste negatif" sağlıklı botu 12 ayda
    ~%27 durduruyor (DURUM %0.8 diyordu, %80-pozitif-ay ankoruna göre hesaplanmıştı);
    "canlı R alt sınırı < 0" sağlıklı botta 3. ayda %87 alarm veriyor.
  · HAM equity'ye bakan kırmızı çizgi aylık katkıyla KÖRLEŞİYOR ($340 + $150/ay): edge
    ölse 24 ayda yalnız %20 çalıyor. Katkıdan bağımsız endeksle %92, medyan 9. ay.

ÜÇ ÖLÇÜ — hepsi yalnız KAPANMIŞ işlemlerden; katkı, çekim, restart etkilemez:
  1) R-CUSUM (edge ölümü): S = max(0, S + 0.09 − R), S > 35 → ALARM.
     İKİZ ay-blok bootstrap (3000 yol, ~24 işlem/ay): sağlıklıyken 12 ayda %3, 24 ayda %11
     yanlış alarm; edge sıfırsa medyan 10. ayda, −0.10R ise medyan 6. ayda yakalar.
     Daha hızlısı yok: işlem başı R'nin std'si 1.4, edge 0.18 — gürültü fiziği bu.
  2) Katkıdan bağımsız birim değer: her işlem R × min(risk%, CAP × stop%) ile bileşiklenir
     (botun kendi boyutlama formülü). Tepeden düşüş İKİZ bantlarıyla kıyaslanır.
  3) Yürütme (hızlı katman, gürültüsü düşük): giriş kayması bp vs model 15.85bp,
     stoptan kötü kapanış, etkin olmayan koldan işlem.

Kullanım (VPS, /opt/bot2):
    venv/bin/python erken_uyari.py                   # tüm canlı işlemler
    venv/bin/python erken_uyari.py --bas 2026-09-22  # ayar değişikliğinden itibaren
    venv/bin/python erken_uyari.py --db ikiz_duzeltilmis.db --paper --risk 0.035 --cap 1.5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from datetime import datetime, timedelta

CUSUM_K = 0.09          # sağlıklı İKİZ ort R'si (0.18) ile ölü edge (0) arasının ortası
CUSUM_H = 35.0          # sağlıklıyken 12 ayda %3 yanlış alarm (bootstrap)
KIRMIZI_CIZGI = 0.60    # birim değer tepeden −%60 (sağlıklıyken 24 ayda ~%7)
DD_BANTLARI = ((0.40, "olağan (tipik yıl)"),
               (0.48, "sık değil (5 yılda bir)"),
               (0.60, "nadir (20 yılda bir) — ama hâlâ normal aralıkta"))
KAYMA_MODEL_BP = 15.85  # kayma_denetim.py, n=54
STOPTAN_KOTU_R = -1.5   # İKİZ'de en kötü net R −1.31; daha kötüsü stop sorunu demek
AKTIF_KOLLAR = ("donchian", "squeeze", "mean_rev")
SON_GUN = 30            # yabancı kol / stoptan kötü: yalnız son 30 gün
SON_KAYMA_N = 60        # kayma: son 60 market girişi (eski ortalama yeni bozulmayı sulandırmasın)
DB_VARSAYILAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db")


def kol_adi(skor_json: str | None) -> str:
    try:
        s = (json.loads(skor_json) if skor_json else {}).get("strategy", "")
    except (TypeError, ValueError):
        s = ""
    s = (s or "").lower()
    if "donch" in s:
        return "donchian"
    if "squeeze" in s:
        return "squeeze"
    if "mean" in s or s == "bb":
        return "mean_rev"
    return s or "?"


def _skor(t: dict) -> dict:
    try:
        return json.loads(t.get("strategy_scores") or "{}")
    except (TypeError, ValueError):
        return {}


def r_net(t: dict) -> float | None:
    """Net R: defterdeki pnl (ücret+funding dahil) / ilk stop mesafesindeki risk."""
    sl = _skor(t).get("sl0") or t["sl_price"]
    risk_usd = abs(t["entry_price"] - sl) * t["quantity"]
    if risk_usd <= 0 or t.get("pnl_usdt") is None:
        return None
    return t["pnl_usdt"] / risk_usd


def kayma_bp(t: dict) -> float | None:
    niyet = _skor(t).get("intended_entry")
    if not niyet:
        return None
    yon = 1.0 if str(t["side"]).lower() in ("long", "buy") else -1.0
    return yon * (t["entry_price"] - niyet) / niyet * 1e4


def islem_riski(t: dict, risk: float, cap: float) -> float:
    """Botun boyutlaması: min(hedef risk, CAP × stop mesafesi%)."""
    sl = _skor(t).get("sl0") or t["sl_price"]
    stop_pct = abs(t["entry_price"] - sl) / t["entry_price"]
    return min(risk, cap * stop_pct)


def cusum(Rs: list[float], k: float = CUSUM_K) -> list[float]:
    S, out = 0.0, []
    for r in Rs:
        S = max(0.0, S + k - r)
        out.append(S)
    return out


def dusus(getiriler: list[float]) -> tuple[float, float]:
    """(şu anki düşüş, en büyük düşüş) — birim değer 1'den başlar."""
    v, tepe, en = 1.0, 1.0, 0.0
    for g in getiriler:
        v *= 1.0 + g
        tepe = max(tepe, v)
        en = max(en, 1.0 - v / tepe)
    return 1.0 - v / tepe, en


def dd_bandi(dd: float) -> str:
    for sinir, ad in DD_BANTLARI:
        if dd < sinir:
            return ad
    return "KIRMIZI ÇİZGİ"


def _guven(xs: list[float]) -> tuple[float, float, float]:
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, float("nan"), float("nan")
    se = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n)
    return m, m - 1.96 * se, m + 1.96 * se


def islemleri_oku(db: str, paper: bool = False, bas: str | None = None) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    q = ("SELECT symbol, side, entry_price, exit_price, quantity, sl_price, entry_time,"
         " exit_time, pnl_usdt, exit_reason, strategy_scores FROM trades"
         " WHERE is_paper=? AND exit_time IS NOT NULL AND pnl_usdt IS NOT NULL")
    satirlar = [dict(r) for r in con.execute(q, (1 if paper else 0,))]
    con.close()
    if bas:
        satirlar = [t for t in satirlar if t["entry_time"] >= bas]
    satirlar.sort(key=lambda t: (t["exit_time"], t["entry_time"]))
    return satirlar


def _son_pencere(islemler: list[dict], gun: int = SON_GUN) -> list[dict]:
    """Son işlemin tarihinden geriye `gun` gün (duvar saati değil: eski db'lerde de çalışır)."""
    if not islemler:
        return []
    son = datetime.fromisoformat(max(t["entry_time"] for t in islemler).replace("Z", "+00:00"))
    esik = (son - timedelta(days=gun)).isoformat()
    return [t for t in islemler if t["entry_time"] >= esik]


def degerlendir(islemler: list[dict], risk: float, cap: float) -> dict:
    aktif = [t for t in islemler if kol_adi(t["strategy_scores"]) in AKTIF_KOLLAR]
    # Yürütme kontrolleri YAKIN geçmişe bakar: eski, düzeltilmiş olaylar (07-16'da
    # kapatılan orb/fvg işlemleri, eski stop hataları) kalıcı uyarı üretmesin.
    son = _son_pencere(islemler)
    yabanci = sum(1 for t in son if kol_adi(t["strategy_scores"]) not in AKTIF_KOLLAR)
    yabanci_toplam = len(islemler) - len(aktif)
    Rs, getiri, aylar = [], [], {}
    for t in aktif:
        r = r_net(t)
        if r is None:
            continue
        Rs.append(r)
        g = r * islem_riski(t, risk, cap)
        getiri.append(g)
        ay = t["exit_time"][:7]
        aylar[ay] = (1 + aylar.get(ay, 0.0)) * (1 + g) - 1
    S = cusum(Rs)
    dd_simdi, dd_en = dusus(getiri)
    # model 15.85bp market girişler için ölçüldü; mean_rev maker giriyor
    kaymalar = [k for k in (kayma_bp(t) for t in aktif
                            if kol_adi(t["strategy_scores"]) != "mean_rev") if k is not None]
    kaymalar = kaymalar[-SON_KAYMA_N:]
    kayma = _guven(kaymalar) if len(kaymalar) >= 20 else None
    kotu = [r_net(t) for t in son if kol_adi(t["strategy_scores"]) in AKTIF_KOLLAR]
    stoptan_kotu = sum(1 for r in kotu if r is not None and r < STOPTAN_KOTU_R)
    stoptan_kotu_toplam = sum(1 for r in Rs if r < STOPTAN_KOTU_R)
    seri = en_seri = 0
    for r in Rs:
        seri = seri + 1 if r < 0 else 0
        en_seri = max(en_seri, seri)
    neg_seri = 0
    for ay in sorted(aylar, reverse=True):
        if aylar[ay] >= 0:
            break
        neg_seri += 1
    return {
        "n": len(Rs), "yabanci": yabanci, "yabanci_toplam": yabanci_toplam,
        "stoptan_kotu_toplam": stoptan_kotu_toplam,
        "ortR": _guven(Rs) if Rs else None,
        "S": S[-1] if S else 0.0, "S_en": max(S) if S else 0.0,
        "dd_simdi": dd_simdi, "dd_en": dd_en,
        "kayma": kayma, "stoptan_kotu": stoptan_kotu,
        "en_seri": en_seri, "aylar": aylar, "neg_ay_seri": neg_seri,
        "edge_alarm": bool(S) and S[-1] > CUSUM_H,
        "kirmizi": dd_simdi >= KIRMIZI_CIZGI,
        "yurutme": (kayma is not None and kayma[1] > KAYMA_MODEL_BP + 1.0)
                   or stoptan_kotu > 0 or yabanci > 0,
    }


def hukum(s: dict) -> str:
    if s["edge_alarm"] or s["kirmizi"]:
        return "ALARM"
    if s["yurutme"]:
        return "YÜRÜTME UYARISI"
    return "NORMAL"


def rapor(s: dict, risk: float, cap: float, ilk: str | None, son: str | None) -> str:
    L = ["=" * 78, f"ERKEN UYARI — {hukum(s)}", "=" * 78,
         f"  {s['n']} kapanmış işlem ({(ilk or '?')[:10]} → {(son or '?')[:10]}) · "
         f"endeks risk %{risk*100:.2f}, CAP {cap}"]
    if s["n"] < 20:
        L.append("  n<20 — ölçüler henüz anlamsız; bekle.")
    m = s["ortR"]
    if m:
        L.append(f"  ort net R {m[0]:+.3f}  [%95: {m[1]:+.3f}, {m[2]:+.3f}]  (İKİZ ~+0.17)"
                 + ("  ← aralığın sıfırı içermesi n~220'ye kadar NORMAL" if m[1] < 0 else ""))
    L.append("")
    L.append(f"[1] EDGE ALARMI (R-CUSUM)   S = {s['S']:.1f} / eşik {CUSUM_H:.0f}"
             f"  (%{min(100, s['S']/CUSUM_H*100):.0f})   en yüksek {s['S_en']:.1f}")
    L.append("    ✗ ALARM: edge beklenenden anlamlı zayıf." if s["edge_alarm"] else
             "    ✓ eşiğin altında — S yükselse bile eşik aşılmadıkça hiçbir şeye dokunma.")
    L.append(f"[2] BİRİM DEĞER (katkıdan bağımsız)  tepeden şu an −%{s['dd_simdi']*100:.1f}"
             f" → {dd_bandi(s['dd_simdi'])}   en büyük −%{s['dd_en']*100:.1f}")
    L.append(f"    bantlar: <%40 olağan · <%48 5 yılda bir · <%60 20 yılda bir · "
             f"≥%{KIRMIZI_CIZGI*100:.0f} kırmızı çizgi")
    k = s["kayma"]
    L.append("[3] YÜRÜTME")
    L.append(f"    giriş kayması (son {SON_KAYMA_N} market girişi): " + (f"{k[0]:.1f}bp [%95: {k[1]:.1f}, {k[2]:.1f}] vs model "
             f"{KAYMA_MODEL_BP}bp" + ("  ✗ modelden KÖTÜ" if k[1] > KAYMA_MODEL_BP + 1.0 else "  ✓")
             if k else "n<20 ya da niyet fiyatı kayıtlı değil"))
    L.append(f"    stoptan kötü kapanış (R<{STOPTAN_KOTU_R}), son {SON_GUN} gün: {s['stoptan_kotu']}"
             + ("  ✗" if s["stoptan_kotu"] else "  ✓") + f"   (tüm geçmiş {s['stoptan_kotu_toplam']})")
    L.append(f"    etkin olmayan koldan işlem, son {SON_GUN} gün: {s['yabanci']}"
             + ("  ✗" if s["yabanci"] else "  ✓") + f"   (tüm geçmiş {s['yabanci_toplam']})")
    L.append("")
    L.append(f"  bağlam: en uzun kayıp serisi {s['en_seri']} (normal ≤14) · "
             f"şu an {s['neg_ay_seri']} ay üst üste negatif (tek başına alarm DEĞİL)")
    L.append("")
    h = hukum(s)
    if h == "NORMAL":
        L.append("  NE YAPMALI: HİÇBİR ŞEY. Kayıplar botun beklenen bilet maliyeti.")
        L.append("  Ayar değiştirmek ya da kapatmak defterde 30+ kez PARA KAYBETTİRDİ.")
    elif h == "YÜRÜTME UYARISI":
        L.append("  NE YAPMALI: strateji değil DOLUM/AYAR sorunu olabilir → kayma_denetim.py,")
        L.append("  kar_farki.py, ayar_dogrula.py. Riskli değil ama hızlı bakılmalı.")
    else:
        L.append("  NE YAPMALI: Telegram'dan yeni girişleri duraklat. Aynı dönemi İKİZ'le")
        L.append("  karşılaştır (uyum_testi.py): ikiz de kaybettiyse edge/piyasa, ikiz")
        L.append("  kazandıysa yürütme. Karar ondan sonra.")
    L.append("=" * 78)
    return "\n".join(L)


def kisa_ozet(db: str = DB_VARSAYILAN, risk: float | None = None,
              cap: float | None = None) -> str:
    risk, cap = _ayarlar(risk, cap)
    s = degerlendir(islemleri_oku(db), risk, cap)
    return (f"Erken uyarı: {hukum(s)}\n"
            f"edge S {s['S']:.1f}/{CUSUM_H:.0f} · birim değer tepeden −%{s['dd_simdi']*100:.0f}"
            f" ({dd_bandi(s['dd_simdi'])}) · n={s['n']}")


def _ayarlar(risk: float | None, cap: float | None) -> tuple[float, float]:
    if risk is None or cap is None:
        from config import load_config
        r = load_config().risk
        risk = r.max_risk_per_trade if risk is None else risk
        cap = r.position_cap_fraction if cap is None else cap
    return risk, cap


def main() -> None:
    ap = argparse.ArgumentParser(description="Kayıp normal mi, alarm mı?")
    ap.add_argument("--db", default=DB_VARSAYILAN)
    ap.add_argument("--paper", action="store_true", help="is_paper=1 işlemler (İKİZ db'leri)")
    ap.add_argument("--bas", help="bu tarihten sonra AÇILAN işlemler (YYYY-AA-GG)")
    ap.add_argument("--risk", type=float, help="işlem başı risk (varsayılan .env)")
    ap.add_argument("--cap", type=float, help="POSITION_CAP_FRACTION (varsayılan .env)")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        raise SystemExit(f"✗ {a.db} yok. /opt/bot2 içinde çalıştır ya da --db ver.")
    risk, cap = _ayarlar(a.risk, a.cap)
    islemler = islemleri_oku(a.db, a.paper, a.bas)
    s = degerlendir(islemler, risk, cap)
    ilk = islemler[0]["entry_time"] if islemler else None
    son = islemler[-1]["exit_time"] if islemler else None
    print(rapor(s, risk, cap, ilk, son))


if __name__ == "__main__":
    main()
