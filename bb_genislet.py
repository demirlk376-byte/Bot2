"""
bb_genislet.py — BB/HAFTA-SONU KOLUNU GENİŞLET. 35 eksende hiç denenmedi.

NEDEN BU, KAPALI "COIN EKLEME" EKSENİNDEN FARKLI:
`coin_expand.py` yalnız donchian ve squeeze'i test etti (kodu okundu, CFG'de
yalnız o ikisi var). İkisi de MOMENTUM/kırılım kolu. Coin eklemek KORELE
kırılım maruziyeti ekliyordu → korele çöküşte hepsi birden stop → en kötü ay
−21 → −58.8. Mekanizma DURUM'da kayıtlı.

BB kolu YAPISAL OLARAK TERS:
  • mekanizma: FADE (ortalamaya dönüş), donchian'ın tam tersi
  • zaman: YALNIZ HAFTA SONU — hacmin ve momentumun zayıf olduğu an
  • DURUM: "hafta sonu hacim düşük, momentum zayıf — ortalamaya dönüşün
    çalıştığı tek yer orası. Kısıtlaması keyfi değil, DOĞRU YERDE."
Yani BB, donchian'ın çalıştığı rejimin BOŞLUĞUNDA çalışıyor. Coin eklemek
burada korele kırılım değil, DEKORELE fade maruziyeti ekler.

⚠ NEDEN LTC olduğu HİÇBİR YERDE YAZMIYOR. Hafta sonu gerekçesi belgeli,
  tek-coin gerekçesi DEĞİL. Boşluk bu.

⚠⚠ SEÇİM YAPILMIYOR — bu testin en önemli kuralı.
   "Geçmişte iyi gideni seç" walk-forward'da ÖLDÜ (coin_expand: TRAIN muhteşem,
   TEST −$254). O yüzden burada ana aday **HEPSİNİ EKLE**: seçim yoksa
   aşırı-uydurma da yok. Seçimli varyantlar yalnız KIYAS için, ve onlar
   walk-forward OOS ile yargılanıyor.

⚠ ÖN-KAYIT (sonuç görülmeden, gevşetilmeyecek):
   (1) Δ$ ≥ +28 · (2) en kötü ay KÖTÜLEŞMESİN · (3) maxDD +2 puandan fazla
   bozulmasın · (4) walk-forward OOS'ta tabanı yensin.
   DÖRDÜ BİRDEN olmazsa RET.

Kullanım:  python3 bb_genislet.py local
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt

BAL = 190.0
TUM = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "DOGE", "DOT",
       "ETC", "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET",
       "XLM", "XMR", "XRP"]


def olc(taken):
    if not taken:
        return 0.0, 0.0, 0.0, 0, {}
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    o = np.argsort([x.value for x in ex]); p = pnl[o]
    e = np.concatenate([[BAL], BAL + np.cumsum(p)])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    idx = [ex[k].tz_localize(None) for k in o]
    ser = pd.Series(p, index=idx)
    mon = ser.groupby(ser.index.to_period("M")).sum() / BAL * 100
    yil = ser.groupby(ser.index.year).sum().to_dict()
    return pnl.sum(), dd, mon.min(), len(taken), yil


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("bb_genislet.py — BB/hafta-sonu kolu genişletilebilir mi?\n")

    # ── sabit kollar (donchian + squeeze) — DOKUNULMUYOR ────────────────────
    sabit = []
    for c in A.DONCH:
        sabit += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:
        sabit += A.gen("squeeze", fast_bt.load(c, source=source))

    # ── her coin için BB/hafta-sonu işlemleri ──────────────────────────────
    print("  her coin için BB/hafta-sonu üretiliyor...")
    bb = {}
    for c in TUM:
        try:
            m = fast_bt.load(c, source=source)
        except SystemExit:
            continue
        bb[c] = A.gen_bb(m)
        r = np.array([t[2] for t in bb[c]]) if bb[c] else np.array([0.0])
        s = np.array([t[3] for t in bb[c]]) if bb[c] else np.array([1.0])
        kar = float((r * np.minimum(A.RISKF, A.CAP * s) * BAL).sum()) if bb[c] else 0.0
        print(f"    {c:<5s} n={len(bb[c]):>3d} ${kar:>+7.0f}", flush=True)
    uygun = sorted(bb, key=lambda c: c)

    def portfoy(bb_coinler):
        ham = list(sabit)
        for c in bb_coinler:
            ham += bb[c]
        return olc(A.seat_select(ham))

    # ── TABAN: yalnız LTC — ankoru birebir üretmeli ────────────────────────
    t_kar, t_dd, t_ay, t_n, t_yil = portfoy(A.BB_COINS)
    ok = (t_n == 1579) and abs(t_kar - 1420.66) < 0.5
    print(f"\n  MAKİNE DOĞRULAMASI (BB=LTC): {t_n} işlem / ${t_kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")
    print(f"  taban: maxDD {t_dd:.1f} · en kötü ay {t_ay:.1f}")

    # ── ADAYLAR ────────────────────────────────────────────────────────────
    print(f"\n{'='*84}")
    print(f"  ÖN-KAYIT: Δ$≥+28 VE en kötü ay kötüleşmesin VE maxDD +2'den fazla")
    print(f"            bozulmasın VE walk-forward OOS'ta tabanı yensin.")
    print(f"{'='*84}")
    adaylar = {"TABAN (yalnız LTC)": A.BB_COINS}
    adaylar["HEPSİ (seçim YOK)"] = uygun
    # kıyas için: yalnız likit/büyük olanlar — yine SEÇİM ama YAPISAL bir ölçüte
    # göre (geçmiş performansa göre DEĞİL), o yüzden aşırı-uydurma riski düşük
    buyuk = [c for c in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE",
                         "LTC", "LINK", "BCH", "AVAX", "DOT") if c in bb]
    adaylar["BÜYÜK-KAP (yapısal ölçüt)"] = buyuk

    print(f"  {'aday':<28s}{'BB coin':>8s}{'işlem':>7s}{'kâr$':>9s}{'Δ$':>7s}"
          f"{'maxDD':>7s}{'kötü ay':>9s}  ÖN-ELEME")
    sonuc = {}
    for ad, cs in adaylar.items():
        kar, dd, ay, n, yil = portfoy(cs)
        sonuc[ad] = (kar, dd, ay, n, yil)
        if ad.startswith("TABAN"):
            print(f"  {ad:<28s}{len(cs):>8d}{n:>7d}{kar:>+9.0f}{0:>7.0f}"
                  f"{dd:>7.1f}{ay:>9.1f}")
            continue
        neden = []
        if kar - t_kar < 28: neden.append("Δ$")
        if ay < t_ay - 0.05: neden.append("ay↓")
        if dd > t_dd + 2.0: neden.append("DD↑")
        bar = "✓ geçti" if not neden else "✗ " + "+".join(neden)
        print(f"  {ad:<28s}{len(cs):>8d}{n:>7d}{kar:>+9.0f}{kar-t_kar:>+7.0f}"
              f"{dd:>7.1f}{ay:>9.1f}  {bar}")

    # ── WALK-FORWARD OOS — asıl hakem ──────────────────────────────────────
    print(f"\n{'='*84}\nWALK-FORWARD OOS — asıl hakem\n{'='*84}")
    yillar = sorted(t_yil)
    adlar = list(sonuc)
    oa = om = 0.0
    print(f"  {'yıl':>6s} {'diğer yıllarda en iyi':>28s} {'OOS $':>8s} "
          f"{'taban $':>9s} {'fark':>7s}")
    for Y in yillar:
        skor = {a: sum(v for y, v in sonuc[a][4].items() if y != Y) for a in adlar}
        sec = max(skor, key=skor.get)
        aa = sonuc[sec][4].get(Y, 0.0); mm = t_yil.get(Y, 0.0)
        oa += aa; om += mm
        print(f"  {Y:>6d} {sec[:28]:>28s} {aa:>+8.0f} {mm:>+9.0f} {aa-mm:>+7.0f}")
    print(f"  {'TOPLAM':>6s} {'':>28s} {oa:>+8.0f} {om:>+9.0f} {oa-om:>+7.0f}")

    print(f"\n{'='*84}\nHÜKÜM\n{'='*84}")
    gecen = [a for a in sonuc if not a.startswith("TABAN")
             and sonuc[a][0] - t_kar >= 28 and sonuc[a][2] >= t_ay - 0.05
             and sonuc[a][1] <= t_dd + 2.0]
    if gecen and oa - om > 0:
        print(f"  ✓ ÖN-KAYDIN DÖRDÜ DE SAĞLANDI: {gecen}")
        print(f"    Bu, 35 eksende İLK geçen aday. Canlıya almadan önce")
        print(f"    dayanıklılık (ek kayma) ve uygulanabilirlik ölçülmeli.")
    elif gecen:
        print(f"  ✗ Ön-elemeyi geçen var ({gecen}) ama OOS'ta taban önde "
              f"(${oa-om:+.0f}). RET.")
    else:
        print(f"  ✗ Hiçbir aday ön-elemeyi geçmedi. BB genişletme de kapanıyor.")
        print(f"    Not: 'hepsi' varyantı SEÇİMSİZDİ — yani düşmesi aşırı-uydurma")
        print(f"    değil, kolun gerçekten LTC'ye özel olduğu anlamına gelir.")


if __name__ == "__main__":
    main()
