"""
ayri_havuz.py — 1D TREND KOLU KENDİ KOLTUK HAVUZUYLA, TOPLAM RİSK EŞİTLENMİŞ.

NEDEN BU TEST DAHA ÖNCE YAPILMADI:
  Ledger'da 1D trend kolunun edge'i GÜÇLÜ ölçülmüş (519 işlem, ort R +0.4106,
  z=+4.77, 20/22 coin pozitif, 259/270 TEST hücresi pozitif) — kitabın kendi
  +0.2373'ünden belirgin yüksek. Reddedilme sebebi edge DEĞİL, YER DEĞİŞTİRME:
  kol ankorun 459 işlemini ($442) dışarı itip yerine $339 koyuyor → net −$97.
  Ama yer değiştirme ORTAK 7 KOLTUĞUN sonucu — doğa kanunu değil, konfigürasyon.
  Önceki ÜÇ tasarımın üçü de kolu ortak havuza soktu. Ayrı havuz hiç denenmedi.

ÖN-KAYIT (koşmadan önce sabitlendi, argmax YOK):
  · Parametre = IZGARANIN ORTASI: ch=50, sl=2.0, rr=3.0, mh=40, ema=200.
    Kesitsel testte kullanılan aynı disiplin ("merkezi konfig, en iyi hücre DEĞİL").
  · Coin = 11 deploy coini (DONCH+SQZ). Coin seçimi YOK.
  · Ölçüm uzayları AYRI: KÂR sabit-kesir uzayında (doğrusal), RİSK bileşik
    uzayında (bot canlı equity'den boyutlanıyor). Ledger'ın doğrulanmış yöntemi.
  · RİSK EŞİTLEME: C konfigürasyonunun BİLEŞİK maxDD'si A'nınkine eşitlenene
    kadar iki kitap birlikte ölçeklenir. Ancak ondan sonra kâr kıyaslanır.
    (Eşitleme olmadan "daha çok pozisyon = daha çok kâr" totolojisi ölçülür.)
  · GEÇME BARI: (a) risk-eşitlenmiş Δ$ ≥ +36, (b) TEST diliminde (giriş ≥
    2025-01-01) de pozitif, (c) en kötü ay kötüleşmiyor, (d) S taramasının
    gürültü tavanı σ√(2 ln N) aşılıyor.

Kullanım:  py ayri_havuz.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
import daily_trend_test as D

# canlı ölçek (ankor değil) — deployed_backtest'te doğrulanmış sabitler
RISKF, CAP, BAL0 = DB.CANLI_RISKF, DB.CANLI_CAP, DB.BAL0
KAYMA = 15.85 / 1e4
CH, SL_A, RR, MH, EMA = 50, 2.0, 3.0, 40, 200      # ← IZGARA ORTASI, ön-kayıtlı
SPLIT = D.SPLIT


def koltuk(trades, maxpos):
    """daily_trend_test.seat_select ile birebir (stable, giriş zamanına göre)."""
    ev = sorted(trades, key=lambda t: t[0]); oh = []; tk = []; ctr = 0
    for tr in ev:
        while oh and oh[0][0].value <= tr[0]: heapq.heappop(oh)
        if len(oh) < maxpos:
            ctr += 1; heapq.heappush(oh, (tr[1], ctr, 0.0)); tk.append(tr)
    return tk


def _seri(tk, olcek, kayma):
    """Çıkışa göre sıralı (R, eff) — kind='stable' ZORUNLU (eşit damgalar var)."""
    tk = sorted(tk, key=lambda t: (pd.Timestamp(t[1]).value, t[0]))
    R = np.array([t[2] for t in tk], dtype=float)
    sp = np.array([t[3] for t in tk], dtype=float)
    if kayma: R = R - KAYMA / sp
    return R, np.minimum(RISKF, CAP * sp) * olcek, [pd.Timestamp(t[1]) for t in tk]


def kar_sabit(tk, olcek=1.0, kayma=True):
    """KÂR: sabit-kesir uzayı (doğrusal, üstel patlamaz)."""
    if not tk: return 0.0, pd.Series(dtype=float)
    R, eff, ex = _seri(tk, olcek, kayma)
    pnl = R * eff * BAL0
    ay = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum()
    return float(pnl.sum()), ay / BAL0 * 100


def dd_bilesik(tk, olcek=1.0, kayma=True):
    """RİSK: bileşik uzay — bot canlı equity'den boyutlandığı için GERÇEK olan bu."""
    if not tk: return 0.0
    R, eff, _ = _seri(tk, olcek, kayma)
    eq = np.cumprod(1.0 + R * eff)
    eq = np.concatenate([[1.0], eq])
    return float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max() * 100)


def olcek_bul(tk, hedef_dd, kayma=True):
    """Bileşik maxDD'yi hedefe getiren ölçeği ikili aramayla bul."""
    lo, hi = 0.05, 1.0
    if dd_bilesik(tk, 1.0, kayma) <= hedef_dd: return 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if dd_bilesik(tk, mid, kayma) > hedef_dd: hi = mid
        else: lo = mid
    return (lo + hi) / 2


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    kitap = D.base_trades(src)
    kol = []
    for c in DB.DONCH + DB.SQZ:
        kol += D.gen_daily(D.daily_cache(c, src), CH, EMA, SL_A, RR, MH, c)

    A = koltuk(kitap, 7)
    if len(A) != 1579:
        sys.exit(f"⛔ taban {len(A)} işlem, 1579 değil — kıyas geçersiz.")
    kolA = koltuk(kol, 7)
    print(f"\n{'='*100}\n=== 1D TREND KOLU · AYRI HAVUZ · RİSK EŞİTLENMİŞ ===")
    print(f"  ön-kayıtlı parametre: ch={CH} sl={SL_A} rr={RR} mh={MH}g ema={EMA} (ızgara ortası)")
    Rk = np.array([t[2] for t in kolA]); spk = np.array([t[3] for t in kolA])
    Rkk = Rk - KAYMA / spk
    print(f"  kol tek başına: {len(kolA)} işlem · ort R kaymasız {Rk.mean():+.4f} · "
          f"KAYMALI {Rkk.mean():+.4f} · z={Rkk.mean()/Rkk.std(ddof=1)*np.sqrt(len(Rkk)):+.2f}")
    print(f"  (kitap kaymalı ort R = +0.1764 — kol bunu geçmezse ortak havuzda zaten negatif)")

    dd_A = dd_bilesik(A); kar_A, ay_A = kar_sabit(A)
    print(f"\n  A) yalnız kitap : ${kar_A:+8.2f} · bileşik maxDD %{dd_A:.2f} · en kötü ay %{ay_A.min():.2f}")

    # B) ORTAK havuz — ledger'ın zaten reddettiği tasarım, kontrol olarak yeniden üretiliyor
    B = koltuk(kitap + kol, 7)
    nb = sum(1 for t in B if t[4] == "daily")
    o_B = olcek_bul(B, dd_A); kar_B, ay_B = kar_sabit(B, o_B)
    print(f"  B) ORTAK 7 koltuk: ${kar_B:+8.2f} · Δ{kar_B-kar_A:+7.2f} · ölçek {o_B:.3f} · "
          f"kol {nb} işlem · kitap {len(B)-nb}/{len(A)} kaldı · en kötü ay %{ay_B.min():.2f}")

    # C) AYRI havuz — HİÇ YAPILMAMIŞ TEST
    print(f"\n  {'C) AYRI havuz':<18} {'kol n':>6} {'ölçek':>7} {'TÜM $':>9} {'Δ$':>8} "
          f"{'TEST $':>8} {'ΔTEST':>7} {'kötü ay':>8}  BAR")
    kar_A_te, _ = kar_sabit([t for t in A if t[0] >= SPLIT.value])
    sonuc = []
    for S in (1, 2, 3):
        C = A + koltuk(kol, S)
        o = olcek_bul(C, dd_A)
        kar_C, ay_C = kar_sabit(C, o)
        te = [t for t in C if t[0] >= SPLIT.value]
        kar_C_te, _ = kar_sabit(te, o)
        d, dte = kar_C - kar_A, kar_C_te - kar_A_te
        gec = d >= 36 and dte > 0 and ay_C.min() >= ay_A.min()
        sonuc.append(d)
        print(f"  {'S='+str(S)+' koltuk':<18} {sum(1 for t in C if t[4]=='daily'):>6} {o:>7.3f} "
              f"{kar_C:>9.2f} {d:>+8.2f} {kar_C_te:>8.2f} {dte:>+7.2f} {ay_C.min():>+8.2f}  "
              f"{'✓ GEÇTİ' if gec else '✗'}")
    s = np.std(sonuc, ddof=1) if len(sonuc) > 1 else 0.0
    tav = s * np.sqrt(2 * np.log(len(sonuc)))
    print(f"\n  gürültü tavanı (N={len(sonuc)} hücre, σ={s:.1f}): ±{tav:.1f} · "
          f"en iyi hücre {max(sonuc):+.2f} → tavanın %{max(sonuc)/tav*100 if tav>0 else 0:.0f}'i")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
