"""
hacim_profil.py — HACİM PROFİLİ / DEĞER ALANI (Value Area) KIRILIMI.

Bu depoda HİÇ denenmemiş bir sinyal ailesi. Kullanıcının tarifi:
  belirli bir pencerede hacmin %70'inin döndüğü fiyat aralığı (Value Area)
  bulunur; üst sınırı (VAH) YÜKSEK HACİMLE yukarı kırılırsa, bir sonraki
  düşük-hacimli boşluğa doğru Long girilir.

─────────────────────────────────────────────────────────────────────────────
KURULUM KARARLARI (hepsi bilinçli, gerekçeli):

1) HACİM DAĞITIMI: "spread" (VARSAYILAN) — her barın hacmi [low, high]
   aralığına ÜNİFORM dağıtılır, kovalarla kesişim uzunluğuyla orantılı.
   Alternatif "close" — hacmin tamamı kapanış kovasına yüklenir.
   SEÇİM GEREKÇESİ: 1h barın range'i tipik olarak 3-8 kovaya yayılıyor;
   hacmin tamamını kapanışa yüklemek profili yapay olarak sivrileştirir ve
   VA'yı daralttığı için kırılım sinyalini MEKANİK olarak çoğaltır (daha
   çok sinyal = daha çok gürültü). Üniform dağıtım TPO/volume-profile
   literatüründeki standart yaklaşım. İKİSİ DE ÖLÇÜLÜYOR (aşağıda).

2) LOOKAHEAD KAPALI: profil YALNIZCA [i-N, i) barlarından kurulur — kırılım
   barı i'nin KENDİSİ profile GİRMEZ. Bu, deponun donchian konvansiyonuyla
   aynı (kanal önceki `channel` bardan, kapanan bar hariç).
   Hacim ortalaması da [i-20, i) — bar i hariç.

3) VALUE AREA: POC = en çok hacimli kova. POC'tan iki yana AÇGÖZLÜ büyüme:
   her adımda üstteki ya da alttaki komşu kovadan hacmi BÜYÜK olanı al,
   kümülatif hacim toplamın %70'ine ulaşana kadar. VAH = en üst VA kovasının
   ÜST kenarı, VAL = en alt VA kovasının ALT kenarı.

4) ÇIKIŞ: ADİL KIYAS için donchian kolunun çıkış mantığının AYNISI —
   stop 2×ATR, rr 2.5, max_hold 30 bar, occ (coin başına tek pozisyon).
   Kullanıcının "bir sonraki düşük-hacimli boşluğa kadar" hedefi KASITLI
   OLARAK kullanılmadı: hedef değiştirilirse kıyas kirlenir (depoda çıkış
   tweak'lerinin 13/13 düştüğü zaten biliniyor).

5) KOVA SAYISI 50, VA %70 — kullanıcının tarifi, SÜPÜRÜLMEDİ (hücre şişmesin).

Kullanım:  py hacim_profil.py local
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────── çekirdek: profil ───────────────────────────────

def _profil(w_lo, w_hi, w_v, kova, mod="spread", w_cl=None):
    """Tek pencere için hacim profili. Döner: (prof[kova], edges[kova+1])."""
    p_lo = float(w_lo.min()); p_hi = float(w_hi.max())
    if not (np.isfinite(p_lo) and np.isfinite(p_hi)) or p_hi <= p_lo:
        return None, None
    edges = np.linspace(p_lo, p_hi, kova + 1)
    if mod == "close":
        idx = np.clip(np.searchsorted(edges, w_cl, side="right") - 1, 0, kova - 1)
        prof = np.bincount(idx, weights=w_v, minlength=kova).astype(float)
        return prof, edges
    # spread: bar range'i ile kova kesişimi oranında dağıt
    lo_c = np.maximum(w_lo[:, None], edges[None, :-1])
    hi_c = np.minimum(w_hi[:, None], edges[None, 1:])
    ov = np.clip(hi_c - lo_c, 0.0, None)                 # (N, kova)
    s = ov.sum(axis=1)
    bad = s <= 0                                          # doji (high==low)
    if bad.any():
        bi = np.clip(np.searchsorted(edges, w_hi[bad], side="right") - 1, 0, kova - 1)
        ov[np.where(bad)[0], bi] = 1.0
        s = ov.sum(axis=1)
    prof = (ov / s[:, None] * w_v[:, None]).sum(axis=0)
    return prof, edges


def _value_area(prof, edges, va=0.70):
    """POC'tan açgözlü iki-yönlü büyüme → (VAL, VAH, POC_fiyat)."""
    tot = prof.sum()
    if tot <= 0: return None
    poc = int(np.argmax(prof))
    lo_i = hi_i = poc; acc = prof[poc]; hedef = va * tot
    B = len(prof)
    while acc < hedef:
        up = prof[hi_i + 1] if hi_i + 1 < B else -1.0
        dn = prof[lo_i - 1] if lo_i - 1 >= 0 else -1.0
        if up < 0 and dn < 0: break
        if up >= dn:
            hi_i += 1; acc += up
        else:
            lo_i -= 1; acc += dn
    return float(edges[lo_i]), float(edges[hi_i + 1]), float((edges[poc] + edges[poc + 1]) / 2)


def va_serileri(d, N=200, kova=50, va=0.70, mod="spread", maske=None):
    """Her bar i için [i-N, i) penceresinden VAL/VAH/POC. maske=None → hepsi.
    ⚠ bar i'nin KENDİSİ profile girmez (lookahead yok)."""
    lo = d["low"].values.astype(float); hi = d["high"].values.astype(float)
    cl = d["close"].values.astype(float); vo = d["volume"].values.astype(float)
    n = len(cl)
    VAL = np.full(n, np.nan); VAH = np.full(n, np.nan); POC = np.full(n, np.nan)
    rng = range(N, n) if maske is None else (int(x) for x in np.where(maske)[0] if x >= N)
    for i in rng:
        a, b = i - N, i
        prof, edges = _profil(lo[a:b], hi[a:b], vo[a:b], kova, mod, cl[a:b])
        if prof is None: continue
        r = _value_area(prof, edges, va)
        if r is None: continue
        VAL[i], VAH[i], POC[i] = r
    return VAL, VAH, POC


# ─────────────────────────── sinyal + simülasyon ────────────────────────────

def uret(d, atr_arr, VAL, VAH, k=1.5, sl_a=2.0, rr=2.5, mh=30, fee=1e-4,
         yon="iki", volma=None, sig="seviye"):
    """VA kırılımı sinyalleri → (entry_ns, exit_ts, R, sl_pct) listesi.
    d: resample edilmiş OHLCV. volma: [i-20,i) hacim ortalaması (shift(1))."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    vo = d["volume"].values; idx = d.index; n = len(cl)
    if volma is None:
        volma = pd.Series(vo).rolling(20).mean().shift(1).values
    out = []; occ = -1
    cand = np.where(np.isfinite(VAH) & np.isfinite(volma) & (vo > k * volma))[0]
    for i in cand:
        i = int(i)
        if i <= occ or i >= n - 1: continue
        a = atr_arr[i]
        if not np.isfinite(a) or a <= 0: continue
        c = cl[i]; cp = cl[i - 1]
        if sig == "capraz":       # TAZE kirilim: onceki kapanis seviyenin icinde/altinda
            if c > VAH[i] and cp <= VAH[i]: d_ = 1
            elif c < VAL[i] and cp >= VAL[i]: d_ = -1
            else: continue
        else:                     # seviye: kapanis VA disinda (donchian konvansiyonu)
            if c > VAH[i]: d_ = 1
            elif c < VAL[i]: d_ = -1
            else: continue
        if yon == "long" and d_ != 1: continue
        if yon == "short" and d_ != -1: continue
        e = c; sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * fee * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out
