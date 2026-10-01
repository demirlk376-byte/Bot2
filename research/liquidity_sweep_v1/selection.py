"""
Aday seçimi ve karar (şartname §18.2–18.5). Sabit fonksiyonlar; sonuç görüldükten sonra
sıralama ölçütü değişmez.

Genel karar önceliği (kodda sabit):
  1. Teknik/veri/muhasebe hatası, örneklem tabanı yok, çözülemeyen maliyet → KANIT YETERSİZ
  2. NORMAL veya STRESS ortalama net_R ya da net_USDT <= 0 → ELENDİ
  3. Ortalama ve toplam pozitif ama gereken LCB yok → KANIT YETERSİZ
  4. Final bağımsız değil / en iyi 5 çıkarılınca kalan <= 0 → KANIT YETERSİZ
  5. Hepsi sağlanırsa → İLERİ PAPER TEST ADAYI
"""
from __future__ import annotations

from . import config as C

ELENDI, YETERSIZ, ADAY = "ELENDİ", "KANIT YETERSİZ", "İLERİ PAPER TEST ADAYI"


def _num(x):
    return x if isinstance(x, (int, float)) else float("nan")


def floors_ok(m, phase):
    n, wk_tr, wk = C.SAMPLE_FLOORS[phase]
    return m["closed"] >= n and m["weeks_with_trades"] >= wk_tr and m["full_weeks"] >= wk


def technical_ok(m):
    return bool(m["metrics_valid"]) and not m["data_gap_exposure"] and not m["funding_order_ambiguous"]


def positive(m):
    return _num(m.get("expectancy_net_R")) > 0 and m["net_USDT"] > 0


def stage_status(mN, mS, phase, need_lcb):
    """Bir varyantın bir aşamadaki durumu: (uygun_mu, kod, açıklama)."""
    if not (technical_ok(mN) and technical_ok(mS)):
        return False, YETERSIZ, "TECHNICAL_INVALID"
    if not (floors_ok(mN, phase) and floors_ok(mS, phase)):
        if positive(mN) and positive(mS):
            return False, YETERSIZ, "SAMPLE_FLOOR_POSITIVE"
        return False, YETERSIZ, "SAMPLE_FLOOR"
    if not (positive(mN) and positive(mS)):
        return False, ELENDI, "NOT_POSITIVE"
    if need_lcb and not (_num(mN["LCB"]) > 0 and mN.get("boot_reliable")):
        return False, YETERSIZ, "LCB_NOT_POSITIVE"
    return True, "ELIGIBLE", "OK"


def rank_key(vid, mN, mS):
    return (-_num(mN["LCB"]), -_num(mS["LCB"]), _num(mN["MDD_close_pct"]), vid)


def select(results, phase):
    """results: {variant_id: (mN, mS)}. Döner (seçilenler, tablo)."""
    need_lcb = phase in ("VALIDATION", "FINAL")
    rows, elig = [], []
    for vid in sorted(results):
        mN, mS = results[vid]
        ok, code, why = stage_status(mN, mS, phase, need_lcb)
        rows.append(dict(variant_id=vid, eligible=ok, status=code, reason=why,
                         normal_LCB=mN["LCB"], stress_LCB=mS["LCB"], normal_MDD=mN["MDD_close_pct"],
                         normal_exp_R=mN.get("expectancy_net_R"), stress_exp_R=mS.get("expectancy_net_R"),
                         normal_net_USDT=mN["net_USDT"], stress_net_USDT=mS["net_USDT"],
                         normal_closed=mN["closed"], stress_closed=mS["closed"]))
        if ok:
            elig.append(vid)
    elig.sort(key=lambda v: rank_key(v, *results[v]))
    lim = C.CANDIDATE_LIMITS.get(phase, 1)
    return elig[:lim], rows


def final_decision(mN, mS, top5_removed_net, final_independent):
    ok, code, why = stage_status(mN, mS, "FINAL", need_lcb=True)
    if not ok:
        return code, why
    if not final_independent:
        return YETERSIZ, "FINAL_NOT_INDEPENDENT"
    if not top5_removed_net > 0:
        return YETERSIZ, "TOP5_REMOVED_NOT_POSITIVE"
    return ADAY, "ALL_FINAL_CONDITIONS"


def overall_without_final(disc_rows, val_rows):
    """Final açılmadıysa genel karar (MANIFEST'te önceden yazıldı):
       • Doğrulamaya aday seçildiyse: seçilenlerin doğrulama durumları; hepsi ELENDİ ise ELENDİ,
         aksi hâlde KANIT YETERSİZ.
       • Keşifte uygun aday yoksa: herhangi bir varyant teknik geçersiz ya da örneklemi yetersiz
         ama iki maliyette de pozitifse KANIT YETERSİZ; değilse ELENDİ."""
    if val_rows:
        return (ELENDI, "VALIDATION_ALL_NOT_POSITIVE") if all(r["status"] == ELENDI for r in val_rows) \
            else (YETERSIZ, "VALIDATION_UNCERTAIN")
    if any(r["reason"] in ("TECHNICAL_INVALID", "SAMPLE_FLOOR_POSITIVE") for r in disc_rows):
        return YETERSIZ, "DISCOVERY_SOME_UNDETERMINED"
    return ELENDI, "DISCOVERY_NO_ELIGIBLE"
