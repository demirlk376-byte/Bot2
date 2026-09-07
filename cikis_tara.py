"""
cikis_tara.py — ÇIKIŞ PARAMETRELERİ: 3 yıllık veriyle YENİDEN doğrulama.

NEDEN: 30 kapanan eksenin HEPSİ giriş tarafındaydı ("hangi işlemi almayalım").
Çıkış parametreleri (rr, sl_atr, max_hold) yıllar önce seçilmiş ve 3 yıllık
veriyle HİÇ doğrulanmamış — main.py:1089 bunu kendisi istiyor. Çıkışı
değiştirmek hiçbir işlemi KESMİYOR, her işlemin ne kazandığını değiştiriyor.

⚠⚠ BU EKSENİN ASIL TEHLİKESİ AŞIRI-UYDURMA. Ölçüldü, sonuca bakmadan:
    toplam kârın gürültü ölçeği (1σ) = σ_R × eff × √n = 1.465 × $4.27 × √1579
                                     = ±$249
    48 hücrelik ızgarada, HEPSİ SAF GÜRÜLTÜ olsa bile beklenen en yüksek hücre
    ≈ √(2 ln 48) = 2.78σ = **+$692**
Ankorun toplamı $1421. Yani bu taramada +$690'lık bir "kazanan", hiçbir gerçek
etki olmasa bile BEKLENEN şeydir. **Karar en yüksek hücreden VERİLEMEZ.**

O yüzden iki savunma:
  [A] YÜZEY ŞEKLİ — gürültü hücreler arasında BAĞIMSIZ, gerçek etki DÜZGÜNDÜR.
      Tek bir sivri hücre gürültüdür; geniş bir plato sinyaldir. Marjinaller
      (her parametrenin tek başına ortalaması) bu yüzden basılıyor.
  [B] WALK-FORWARD OOS — asıl hakem. Her yıl için, DİĞER yıllarda en iyi hücre
      seçilir ve TUTULAN yılda ölçülür. Bu "uyarlanabilir seçim" mevcut sabit
      ayarı OOS'ta yenemiyorsa parametreler AYIRT EDİLEMEZ demektir ve mevcut
      ayar yerinde kalır.

⚠ ÖN-KAYIT (sonuca bakılmadan): değişiklik ancak (1) OOS'ta mevcut ayarı
  yenerse VE (2) aday hücrenin komşuları da iyiyse (plato) VE (3) en kötü ay
  kötüleşmezse önerilir. Üçü birden sağlanmazsa MEVCUT AYAR KALIR.

⚠ Yalnız DONCHIAN taranır (baskın kol, 1008/1579 işlem). squeeze/bb ankor
  ayarında SABİT tutulur — aynı anda üç kolu taramak ızgarayı ve uydurma
  riskini katlar.

Kullanım:  python3 cikis_tara.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn

BAL = 190.0
SL_ATR = [1.5, 2.0, 2.5, 3.0]
RR = [1.5, 2.0, 2.5, 3.0]
MH = [15, 30, 45]
MEVCUT = (2.0, 2.0, 30)


def sinyal_cek(coin, source):
    """Sinyalleri BİR KEZ çıkar. direction yalnız kanal+EMA'ya bağlı, rr/sl_atr'a
    DEĞİL (strategies/donchian.py:107-125 ile doğrulandı) → ızgara ucuzlar.
    occ UYGULANMAZ: çıkış barına bağlı, o da parametreye bağlı."""
    from strategies.donchian import DonchianStrategy
    m = fast_bt.load(coin, source=source)
    d = fast_bt.resample(m, "4h")
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
        d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    sig = []
    for i in range(260, len(d) - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sg = s.analyze(d.iloc[max(0, i - 259):i + 1], float(a))
        if sg.direction == 0:
            continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((sg.direction == 1 and dup) or (sg.direction == -1 and not dup)):
            continue
        sig.append((i, sg.direction, float(a)))
    return d, sig


def kol_uret(d, sig, sl_a, rr, mh):
    """Bir parametre hücresi için donchian işlemleri (occ dahil) — A.gen'in
    çıkış/occ mantığıyla BİREBİR."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i, d_, a in sig:
        if i <= occ:
            continue
        e = cl[i]; sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e))
        occ = j
    return out


def olc(taken):
    """Döner: (toplam$, maxDD, en_kötü_ay, n, yıl→$ sözlüğü)"""
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    e = np.concatenate([[BAL], BAL + np.cumsum(pnl)])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    ser = pd.Series(pnl, index=[x.tz_localize(None) for x in ex])
    mon = ser.groupby(ser.index.to_period("M")).sum() / BAL * 100
    yil = ser.groupby(ser.index.year).sum().to_dict()
    return pnl.sum(), dd, mon.min(), len(taken), yil


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("cikis_tara.py — çıkış parametreleri 3 yıllık veriyle yeniden doğrulanıyor\n")
    sd = 1.4650 * A.RISKF * BAL * np.sqrt(1579)
    N = len(SL_ATR) * len(RR) * len(MH)
    print(f"  ⚠ ÖNCE GÜRÜLTÜ: 1σ = ${sd:.0f} · {N} hücrede saf gürültünün beklenen")
    print(f"    en yükseği ≈ {np.sqrt(2*np.log(N)):.2f}σ = +${sd*np.sqrt(2*np.log(N)):.0f}")
    print(f"    → en yüksek hücre KARAR DEĞİLDİR. Hakem: yüzey şekli + OOS.\n")

    print("  sinyaller bir kez çıkarılıyor...", flush=True)
    coin_sig = {c: sinyal_cek(c, source) for c in A.DONCH}
    sabit = []
    for c in A.SQZ:
        sabit += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        sabit += A.gen_bb(fast_bt.load(c, source=source))
    print(f"  donchian sinyali: {sum(len(v[1]) for v in coin_sig.values())} ham")

    sonuc = {}
    for sa in SL_ATR:
        for rr in RR:
            for mh in MH:
                ham = list(sabit)
                for c in A.DONCH:
                    d, sig = coin_sig[c]
                    ham += kol_uret(d, sig, sa, rr, mh)
                taken = A.seat_select(sorted(ham, key=lambda t: t[0]))
                sonuc[(sa, rr, mh)] = olc(taken)

    kar, dd, ay, n, yil = sonuc[MEVCUT]
    ok = (n == 1579) and abs(kar - 1420.66) < 0.5
    print(f"\n  MAKİNE DOĞRULAMASI (mevcut ayar {MEVCUT}): {n} işlem / ${kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")

    # ── [A] YÜZEY ŞEKLİ ──────────────────────────────────────────────────────
    print(f"\n{'='*76}\n[A] YÜZEY — marjinaller (tek sivri hücre gürültü, plato sinyal)\n{'='*76}")
    for ad, degerler, ix in (("sl_atr", SL_ATR, 0), ("rr", RR, 1), ("max_hold", MH, 2)):
        print(f"  {ad:>9s}: ", end="")
        for v in degerler:
            alt = [k for kk, k in sonuc.items() if kk[ix] == v]
            print(f"{v:>5} → ort ${np.mean([x[0] for x in alt]):>+7.0f}   ", end="")
        print()
    en = max(sonuc, key=lambda k: sonuc[k][0])
    print(f"\n  en yüksek hücre: sl_atr={en[0]} rr={en[1]} mh={en[2]} → "
          f"${sonuc[en][0]:+.0f} (mevcut ${kar:+.0f}, fark ${sonuc[en][0]-kar:+.0f})")
    print(f"  ⚠ Bu fark ${sd*np.sqrt(2*np.log(N)):.0f}'ın altındaysa gürültüden ayırt EDİLEMEZ.")
    # komşu platosu
    kom = [sonuc[(a, b, c)][0] for a in SL_ATR for b in RR for c in MH
           if abs(SL_ATR.index(a) - SL_ATR.index(en[0])) <= 1
           and abs(RR.index(b) - RR.index(en[1])) <= 1
           and abs(MH.index(c) - MH.index(en[2])) <= 1]
    print(f"  en yüksek hücrenin KOMŞULARI: ort ${np.mean(kom):+.0f} "
          f"(n={len(kom)}) — mevcut ${kar:+.0f}")
    print(f"  → komşu ortalaması mevcudun altındaysa o tepe SİVRİ = gürültü.")

    # ── [B] WALK-FORWARD OOS — ASIL HAKEM ────────────────────────────────────
    print(f"\n{'='*76}\n[B] WALK-FORWARD OOS — asıl hakem\n{'='*76}")
    yillar = sorted({y for v in sonuc.values() for y in v[4]})
    print(f"  Her yıl için DİĞER yıllarda en iyi hücre seçilir, TUTULAN yılda ölçülür.")
    print(f"  {'yıl':>6s} {'seçilen (diğer yıllarda en iyi)':>34s} {'OOS $':>9s} "
          f"{'mevcut $':>10s} {'fark':>8s}")
    oos_a = oos_m = 0.0
    for Y in yillar:
        skor = {k: sum(v for y, v in sonuc[k][4].items() if y != Y) for k in sonuc}
        sec = max(skor, key=skor.get)
        a = sonuc[sec][4].get(Y, 0.0)
        m = sonuc[MEVCUT][4].get(Y, 0.0)
        oos_a += a; oos_m += m
        print(f"  {Y:>6d} {str(sec):>34s} {a:>+9.0f} {m:>+10.0f} {a-m:>+8.0f}")
    print(f"  {'TOPLAM':>6s} {'':>34s} {oos_a:>+9.0f} {oos_m:>+10.0f} {oos_a-oos_m:>+8.0f}")

    print(f"\n{'='*76}\nHÜKÜM\n{'='*76}")
    if oos_a - oos_m <= 0:
        print(f"  ✗ Uyarlanabilir seçim OOS'ta mevcut ayarı YENEMEDİ "
              f"(${oos_a-oos_m:+.0f}).")
        print(f"    Parametreler AYIRT EDİLEMEZ: her yıl 'en iyi' olan hücre, ertesi")
        print(f"    yıl daha iyi olmuyor. Bu, ızgaranın gürültü ölçtüğünün doğrudan")
        print(f"    kanıtıdır. **MEVCUT AYAR KALIR** — ve bu bir başarısızlık değil,")
        print(f"    mevcut ayarın savunulabilir olduğunun kanıtı.")
    else:
        print(f"  ⚠ Uyarlanabilir seçim OOS'ta ${oos_a-oos_m:+.0f} önde. Ama tek başına")
        print(f"    YETMEZ — ön-kayıt plato ve en kötü ay şartlarını da istiyor.")
        print(f"    Yukarıdaki komşu ortalamasına ve aşağıdaki en kötü aya bak.")
        print(f"    en kötü ay: mevcut {ay:.1f} · en yüksek hücre {sonuc[en][2]:.1f}")


if __name__ == "__main__":
    main()
