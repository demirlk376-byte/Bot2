"""
yapi.py — YAPI ZINCIRI:  supurme -> [displacement] -> MSS -> [FVG] -> limit retest

⚠ NEDEN TEK KOL, ALTI AYRI STRATEJI DEGIL.
Kullanicinin onerdigi A2/A3/A4 ve "Liquidity Sweep + FVG" aileleri AYNI zincirin
farkli kesitleri. Ayri ayri kurmak, tespit tabanini (n~1752, sigma_R~1.35)
gereksiz yere bolerdi. Burada her bacak bir ANAHTAR:
    supurme_sart=False            -> A2  (BOS + FVG retest, supurme yok)
    fvg_sart=False                -> A3  (supurme + MSS, dogrudan giris)
    ikisi de True                 -> A4 / "Liquidity Sweep + FVG"
    displacement_atr>0            -> displacement kapisi

NEDEN 1h (4h DEGIL). MSS kapisi cok seciciydi: 4h'te 8 coinde supurme
barlarinin yalnizca %1-10'u MSS onayi aliyor (n=3579 -> 35..342). 1h dort kat
bar verir; olculebilir orneklem ancak orada olusuyor.

NEDEN 5m/15m DEGIL. Olculdu (DURUM.md): 5m taban/15m setup/1h rejim kurulumunda
Sweep+Reclaim n=24.307 brut edge -0.0103, VWAP n=29.991 -0.0105, BB/Keltner
n=9.824 -0.0026 -- ucu de MALIYET ONCESI sifir. Sebebi yazili: o olcekte yapisal
stoplar %0.56-0.81 ve 20.3bp gidis-donus maliyet bunun 0.32-0.52 R'si.
Uretimdeki 1h/4h sistem kismen bu yuzden calisiyor: stoplar %2-3, maliyet 0.10R.

STANDART SL/TP (kullanicinin istedigi): yapisal SL = supurulen swing'in otesi,
TP = sabit RR. Ilk turda TP varyanti YOK ki setup'lar karsilastirilabilir kalsin.

GELECEGE BAKIS YOK: bir swing ancak k bar SONRA onaylanir; i barinda yalnizca
j+k <= i olan swingler bilinir (bkz. onayli_swingler).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

VARSAYILAN_K = 2          # fractal yari-genisligi (swing i barinda i+k'de onaylanir)
VARSAYILAN_MSS_BAR = 12   # supurmeden sonra MSS icin en fazla kac bar beklenir
VARSAYILAN_BEKLE_BAR = 12 # MSS'ten sonra limit emri kac bar acik kalir
VARSAYILAN_RR = 2.0
VARSAYILAN_SL_TAMPON = 0.25   # yapisal SL'e eklenen ATR payi


@dataclass
class Kurulum:
    yon: int                 # +1 long | -1 short
    giris: float             # emir fiyati (limit ise seviye, degilse kapanis)
    sl: float
    tp: float
    limit_mi: bool           # True -> dolum beklenir, kayma YOK
    supurme_bar: int
    mss_bar: int
    fvg_bar: int             # -1 = FVG kullanilmadi
    gecerlilik_bar: int      # limit emrinin son gecerli bar indisi


def onayli_swingler(high: np.ndarray, low: np.ndarray, k: int = VARSAYILAN_K):
    """Her i bari icin, O ANDA BILINEN en son onayli swing high/low indisi.

    Bir swing high j, high[j] o pencerenin tepesiyse olusur ama ancak j+k
    barinda ONAYLANIR (sonraki k barin da gorulmesi gerekir). Bu yuzden
    son_sh[i], j+k <= i sartini saglayan en buyuk j'dir. Gelecege bakis YOK.
    """
    n = len(high)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for j in range(k, n - k):
        pencere_h = high[j - k:j + k + 1]
        pencere_l = low[j - k:j + k + 1]
        if high[j] == pencere_h.max() and (pencere_h == high[j]).sum() == 1:
            sh[j] = True
        if low[j] == pencere_l.min() and (pencere_l == low[j]).sum() == 1:
            sl[j] = True
    son_sh = np.full(n, -1, dtype=np.int64)
    son_sl = np.full(n, -1, dtype=np.int64)
    a = b = -1
    for i in range(n):
        j = i - k                      # i barinda j=i-k'ye kadar onaylanmis olur
        if j >= 0:
            if sh[j]:
                a = j
            if sl[j]:
                b = j
        son_sh[i] = a
        son_sl[i] = b
    return son_sh, son_sl


def _fvg_bul(high, low, bas, son, yon):
    """[bas, son] araliginda EN SON bosluk (fair value gap).
    bogа (yon=+1): low[i] > high[i-2]  -> bolge [high[i-2], low[i]]
    ayi (yon=-1): high[i] < low[i-2]  -> bolge [high[i], low[i-2]]
    Doner: (i, alt, ust) veya None."""
    for i in range(son, max(bas, 2) - 1, -1):
        if yon > 0 and low[i] > high[i - 2]:
            return i, float(high[i - 2]), float(low[i])
        if yon < 0 and high[i] < low[i - 2]:
            return i, float(high[i]), float(low[i - 2])
    return None


def kurulumlari_bul(
    high, low, close, atr,
    *,
    k: int = VARSAYILAN_K,
    supurme_sart: bool = True,
    mss_sart: bool = True,     # False -> YAPI KIRILIMI ARANMAZ (null kolu)
    null_gecikme: int = 4,     # null kolunda s'den kac bar sonra girilir
    fvg_sart: bool = True,
    displacement_atr: float = 0.0,
    fvg_derinlik: float = 0.0,
    sahte_seviye_atr: float = 0.0,   # >0 -> FVG YERINE duz ATR mesafesi (PLASEBO)
    mss_bar: int = VARSAYILAN_MSS_BAR,
    bekle_bar: int = VARSAYILAN_BEKLE_BAR,
    rr: float = VARSAYILAN_RR,
    sl_tampon: float = VARSAYILAN_SL_TAMPON,
    bas: int = 300,
):
    """Zinciri tarar ve Kurulum listesi dondurur. Her bar yalnizca KENDINE ve
    GECMISE bakar."""
    high = np.asarray(high, dtype="float64")
    low = np.asarray(low, dtype="float64")
    close = np.asarray(close, dtype="float64")
    atr = np.asarray(atr, dtype="float64")
    n = len(close)
    son_sh, son_sl = onayli_swingler(high, low, k)
    cikti: list[Kurulum] = []

    # ⚠ ust sinir n-1: MSS en erken s+1'de olabilir, yani son bar bile
    # gecerli bir supurme bari olabilir. Once n-2 yazmistim; bu, seriyi
    # kesip 'gelecege bakis' testi yaparken son kurulumu KAYBEDIYORDU ve
    # testi sahte bir sizinti alarmi veriyordu.
    for s in range(max(bas, k + 3), n - 1):
        for yon in (1, -1):
            # --- 1) SUPURME: son onayli swing'in fitille delinip geri alinmasi
            if yon > 0:
                j = son_sl[s]
                if j < 0:
                    continue
                seviye = float(low[j])
                supuruldu = (low[s] < seviye) and (close[s] > seviye)
            else:
                j = son_sh[s]
                if j < 0:
                    continue
                seviye = float(high[j])
                supuruldu = (high[s] > seviye) and (close[s] < seviye)
            if supurme_sart and not supuruldu:
                continue
            if not supurme_sart:
                # A2: supurme aranmiyor -> her bar MSS adayi olabilir, ama
                # ayni MSS'i defalarca almamak icin yalnizca swing'in kendisi
                # taze oldugunda basla.
                if j != (son_sl[s] if yon > 0 else son_sh[s]) or s - j > mss_bar:
                    continue

            # --- 2) MSS: supurmeden SONRA, karsi taraftaki son onayli swing'in
            #            KAPANISLA kirilmasi. Referans supurme anindakidir.
            ref = son_sh[s] if yon > 0 else son_sl[s]
            if ref < 0:
                continue
            ref_seviye = float(high[ref]) if yon > 0 else float(low[ref])
            if mss_sart:
                m = -1
                for t in range(s + 1, min(s + 1 + mss_bar, n)):
                    if (yon > 0 and close[t] > ref_seviye) or \
                       (yon < 0 and close[t] < ref_seviye):
                        m = t
                        break
                if m < 0:
                    continue
            else:
                # ⚠ NULL KOLU -- GEOMETRISI ESLESTIRILMIS.
                # Ilk surumde m = s yazmistim: giris bari supurme barinin
                # KENDISI oluyordu, yani giris yapisal SL'e cok yakin dusuyor,
                # risk paydasi sifira gidiyor ve R patliyordu (olculdu: PF 0.15,
                # R = -3.47 +- 6.66 -- bu bir olcum degil, payda artefaktidir).
                # Dogrusu: MSS'in ZAMANLAMASINI koru, BILGISINI kaldir. Kurulum
                # yine s'den `null_gecikme` bar sonra kurulur ama hicbir yapi
                # sarti aranmaz.
                m = s + null_gecikme
                if m >= n:
                    continue

            # --- 3) DISPLACEMENT (istege bagli): MSS bari guclu olmali
            if displacement_atr > 0:
                if not atr[m] > 0:
                    continue
                if abs(close[m] - close[m - 1]) < displacement_atr * atr[m]:
                    continue

            # --- 4) YAPISAL SL: supurulen swing'in otesi
            pay = sl_tampon * (atr[m] if atr[m] > 0 else 0.0)
            sl = seviye - pay if yon > 0 else seviye + pay

            # --- 5) GIRIS
            if sahte_seviye_atr > 0:
                # ⚠ PLASEBO KOLU. Ayni zincir, ayni SL/TP, ayni limit dolum
                # modeli -- ama seviye FVG'den DEGIL, MSS kapanisindan duz bir
                # ATR mesafesi. FVG bilgi tasiyorsa bu kol ondan KOTU olmali.
                # Tasimiyorsa edge'in kaynagi "limitle geri cekilmeden al"dir,
                # yapi degil.
                if not atr[m] > 0:
                    continue
                giris = close[m] - yon * sahte_seviye_atr * atr[m]
                limit_mi, fvg_bar = True, -2
            elif fvg_sart:
                bulgu = _fvg_bul(high, low, s + 1, m, yon)
                if bulgu is None:
                    continue
                fi, alt, ust = bulgu
                if not ust > alt:
                    continue
                # derinlik 0.0 = bolgenin YAKIN kenari (sig retest)
                #          1.0 = uzak kenari (tam dolum)
                giris = (ust - fvg_derinlik * (ust - alt)) if yon > 0 else \
                        (alt + fvg_derinlik * (ust - alt))
                limit_mi, fvg_bar = True, fi
            else:
                giris = float(close[m])
                limit_mi, fvg_bar = False, -1

            risk = (giris - sl) if yon > 0 else (sl - giris)
            if not risk > 0:
                continue
            tp = giris + yon * rr * risk
            cikti.append(Kurulum(yon, float(giris), float(sl), float(tp),
                                 limit_mi, s, m, fvg_bar,
                                 min(m + bekle_bar, n - 1)))
    return cikti
