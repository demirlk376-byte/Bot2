"""
mtf.py — ÇOK ZAMAN DİLİMLİ HİZALAMA, look-ahead'e karşı SERT KİLİTLİ.

BU DOSYA YENİ ARAŞTIRMANIN TEMELİ. Brief 1H rejim + 15M setup + 5M teyit istiyor.
Bu üç katmanı hizalamak, sahte edge üretmenin EN KOLAY yolu — ve en sinsi olanı,
çünkü sonuç "makul" görünür, sadece imkânsızdır.

TUZAK ŞU: 5dk barı 10:10'da açılıp 10:15'te KAPANIR. O anda 10:00 başlangıçlı 15dk
barı da tam 10:15'te kapanır → GÖRÜLEBİLİR. Ama 5dk barı 10:05→10:10 için aynı 15dk
barı HENÜZ KAPANMAMIŞTIR. Naif bir `reindex(method="ffill")` o barı yine de verir ve
strateji 5 dakika sonrasını bilerek karar verir. Backtest parlar, canlı çöker.

KURAL: bir üst-dilim barı, ancak KAPANIŞ ZAMANI alt-dilim barının kapanış zamanına
EŞİT VEYA ONDAN ÖNCEyse görülebilir.
    T_ust + tf_ust  <=  T_alt + tf_alt
→   T_ust <= T_alt + tf_alt - tf_ust

Bu dosyadaki her eşleme bu kuralla kurulur ve `dogrula()` ile ZORLA denetlenir.
Denetim başarısızsa AssertionError atılır — sessiz geçiş YOK.

(Bugün regime_teshis.py'de sessiz bir tz hatası bütün değerleri NaN yapmış ve araç
"sinyal yok" diye YANLIŞ hüküm basmıştı. Aynı sınıf hata bir daha geçmesin diye
buradaki kontrol öneri değil, ASSERT.)

Kullanım:  python3 mtf.py            # self-test
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TF_TD = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

_AGG = {"open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}

# pandas 2.x artık dakika için 'm' KABUL ETMİYOR ('m' = ay ile karıştığı için).
# Borsa gösterimi ("5m") ile pandas frekansı ("5min") ayrı tutulur; karıştırmak
# ya patlar ya da — daha kötüsü — AYLIK resample yapıp sessizce saçmalar.
_PD_FREQ = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
            "1h": "1h", "4h": "4h", "1d": "1D"}


def resample_tf(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Alt dilimden üst dilim üretir. Index = barın BAŞLANGIÇ zamanı (pandas
    varsayılanı, sol etiket). Kapanış = index + TF_TD[tf].

    ⚠ Eksik bar ATILIR (dropna): borsa boşluğu varsa uydurma bar üretmeyiz."""
    if tf not in TF_TD:
        raise ValueError(f"bilinmeyen tf: {tf}")
    out = df.resample(_PD_FREQ[tf]).agg(_AGG).dropna()
    # Üretilen barın süresi gerçekten istenen mi? (yanlış frekans dizesi sessizce
    # AYLIK bar üretebilirdi — burada patlasın)
    if len(out) > 2:
        adim = out.index[1] - out.index[0]
        assert adim == TF_TD[tf], f"resample {tf} istendi ama adım {adim} çıktı"
    return out


def mtf_pos(alt_idx: pd.DatetimeIndex, ust_idx: pd.DatetimeIndex,
            tf_alt: str, tf_ust: str) -> np.ndarray:
    """Her ALT bar için, o barın kapanışında GÖRÜLEBİLİR olan SON üst barın konumu.

    Döner: alt_idx uzunluğunda int dizi. −1 = henüz görülebilir üst bar yok.

    Formül: T_ust <= T_alt + tf_alt − tf_ust
    (türetimi dosya başındaki açıklamada; `dogrula()` bunu bağımsız olarak sınar)"""
    if len(alt_idx) == 0 or len(ust_idx) == 0:
        return np.full(len(alt_idx), -1, dtype=int)
    if alt_idx.tz is None or ust_idx.tz is None:
        raise ValueError("index'ler tz-AWARE olmalı — tz-naive karşılaştırma "
                         "sessizce yanlış eşleşir (bugün regime_teshis'i bu vurdu)")
    esik = alt_idx + TF_TD[tf_alt] - TF_TD[tf_ust]
    return ust_idx.searchsorted(esik, side="right") - 1


def dogrula(alt_idx: pd.DatetimeIndex, ust_idx: pd.DatetimeIndex,
            tf_alt: str, tf_ust: str, pos: np.ndarray) -> None:
    """SERT DENETİM. mtf_pos'un formülünden BAĞIMSIZ olarak, her eşlemeyi
    zaman aritmetiğiyle tek tek sınar. Formül yanlışsa burada patlar.

    İki yönlü kontrol — sadece 'ileri bakmıyor mu' yetmez, 'gereksiz geride mi
    kalmış' da sınanır. Yoksa `pos = 0` döndüren bozuk bir fonksiyon testi geçer."""
    alt_kapanis = alt_idx + TF_TD[tf_alt]
    for i in range(len(alt_idx)):
        p = int(pos[i])
        if p < 0:
            # görülebilir bar yoksa: İLK üst bar gerçekten sonra kapanmalı
            assert ust_idx[0] + TF_TD[tf_ust] > alt_kapanis[i], (
                f"[{i}] pos=-1 ama {ust_idx[0]} barı zaten kapanmış")
            continue
        assert 0 <= p < len(ust_idx), f"[{i}] konum aralık dışı: {p}"
        # (1) LOOK-AHEAD YOK: seçilen bar alt barın kapanışında KAPANMIŞ olmalı
        assert ust_idx[p] + TF_TD[tf_ust] <= alt_kapanis[i], (
            f"⛔ LOOK-AHEAD: alt bar {alt_idx[i]} (kapanış {alt_kapanis[i]}) "
            f"→ üst bar {ust_idx[p]} (kapanış {ust_idx[p] + TF_TD[tf_ust]})")
        # (2) GEREKSİZ GECİKME YOK: bir SONRAKİ üst bar henüz kapanmamış olmalı
        if p + 1 < len(ust_idx):
            assert ust_idx[p + 1] + TF_TD[tf_ust] > alt_kapanis[i], (
                f"⛔ ESKİ VERİ: alt bar {alt_idx[i]} için {ust_idx[p+1]} barı da "
                f"kapanmıştı ama {ust_idx[p]} seçildi")


def hizala(alt: pd.DataFrame, ust: pd.DataFrame, tf_alt: str, tf_ust: str,
           kolonlar: list[str] | None = None, denetle: bool = True) -> pd.DataFrame:
    """Üst dilim kolonlarını alt dilime, look-ahead OLMADAN taşır.
    Sonuç alt ile aynı index'te; henüz görünmeyen yerler NaN.

    denetle=True → her çağrıda dogrula() koşar. Araştırmada AÇIK BIRAK; kapatmak
    yalnız binlerce kez çağrılan sıcak döngüler için."""
    pos = mtf_pos(alt.index, ust.index, tf_alt, tf_ust)
    if denetle:
        dogrula(alt.index, ust.index, tf_alt, tf_ust, pos)
    kol = kolonlar or list(ust.columns)
    out = pd.DataFrame(index=alt.index)
    gecerli = pos >= 0
    for k in kol:
        v = np.full(len(alt), np.nan, dtype=float)
        v[gecerli] = ust[k].values[pos[gecerli]]
        out[f"{tf_ust}_{k}"] = v
    out[f"{tf_ust}_pos"] = pos
    return out


# ══════════════════════════════════════════════════════════════════════════════
def _self_test() -> bool:
    print("=== mtf.py SELF-TEST ===")
    ok = True

    # 5dk seri: 10:00'dan 12:00'a
    alt_idx = pd.date_range("2026-01-01 10:00", "2026-01-01 12:00",
                            freq="5min", tz="UTC")
    ust_idx = pd.date_range("2026-01-01 09:00", "2026-01-01 12:00",
                            freq="15min", tz="UTC")
    pos = mtf_pos(alt_idx, ust_idx, "5m", "15m")

    # ELLE HESAP — formülden bağımsız, kâğıt üstünde doğrulanabilir üç nokta:
    kontroller = [
        ("2026-01-01 10:10", "2026-01-01 10:00",
         "10:10→10:15 kapanışında, 10:00 barı TAM 10:15'te kapanır → görülür"),
        ("2026-01-01 10:05", "2026-01-01 09:45",
         "10:05→10:10 kapanışında, 10:00 barı HENÜZ kapanmadı → 09:45 görülür"),
        ("2026-01-01 10:25", "2026-01-01 10:00",
         "10:25→10:30 kapanışında, 10:15 barı TAM 10:30'da kapanır → görülür değil? "
         "HAYIR: 10:15+15dk=10:30 <= 10:30 → GÖRÜLÜR"),
    ]
    for alt_s, bek_s, aciklama in kontroller:
        i = alt_idx.get_loc(pd.Timestamp(alt_s, tz="UTC"))
        got = ust_idx[pos[i]]
        bek = pd.Timestamp(bek_s, tz="UTC")
        # üçüncü kontrolün beklentisi 10:15 olmalı — açıklamada gerekçesi yazıyor
        if alt_s.endswith("10:25"):
            bek = pd.Timestamp("2026-01-01 10:15", tz="UTC")
        iyi = got == bek
        ok &= iyi
        print(f"  {alt_s[-5:]} → {str(got)[11:16]} (beklenen {str(bek)[11:16]}) "
              f"{'✓' if iyi else '✗'}")

    # SERT DENETİM tüm seride
    try:
        dogrula(alt_idx, ust_idx, "5m", "15m", pos)
        print("  dogrula() tüm seride ✓")
    except AssertionError as e:
        print(f"  dogrula() ✗ {e}")
        ok = False

    # ── DENETİMİN KENDİSİ ÇALIŞIYOR MU? Bilerek BOZUK eşleme ver, YAKALAMALI.
    #    (Bir testin en kolay yalanı: hiçbir şey yakalamayan denetim.)
    bozuk = np.clip(pos + 1, 0, len(ust_idx) - 1)          # 1 bar İLERİ = look-ahead
    try:
        dogrula(alt_idx, ust_idx, "5m", "15m", bozuk)
        print("  ⛔ denetim ileri-bakan eşlemeyi YAKALAMADI — TEST DEĞERSİZ")
        ok = False
    except AssertionError:
        print("  denetim ileri-bakan eşlemeyi yakaladı ✓")
    geride = np.clip(pos - 1, 0, len(ust_idx) - 1)          # 1 bar GERİ = eski veri
    try:
        dogrula(alt_idx, ust_idx, "5m", "15m", geride)
        print("  ⛔ denetim eski-veri eşlemesini YAKALAMADI — TEST DEĞERSİZ")
        ok = False
    except AssertionError:
        print("  denetim eski-veri eşlemesini yakaladı ✓")

    # ── 1 SAAT katmanı da aynı kuralla
    ust1h = pd.date_range("2026-01-01 08:00", "2026-01-01 12:00", freq="1h", tz="UTC")
    p1 = mtf_pos(alt_idx, ust1h, "5m", "1h")
    try:
        dogrula(alt_idx, ust1h, "5m", "1h", p1)
        # SINIR NOKTASI: 10:50 barı 10:55'te kapanır → 10:00'lık saat barı henüz
        # kapanmamıştır (11:00'da kapanır) → 09:00 görülür.
        # 10:55 barı 11:00'da kapanır → 10:00'lık bar TAM o an kapanır → görülür.
        i = alt_idx.get_loc(pd.Timestamp("2026-01-01 10:50", tz="UTC"))
        j = alt_idx.get_loc(pd.Timestamp("2026-01-01 10:55", tz="UTC"))
        iyi = ust1h[p1[i]].hour == 9 and ust1h[p1[j]].hour == 10
        print(f"  1h sınır: 10:50→{str(ust1h[p1[i]])[11:16]} (bek 09:00) · "
              f"10:55→{str(ust1h[p1[j]])[11:16]} (bek 10:00) {'✓' if iyi else '✗'}")
        ok &= iyi
    except AssertionError as e:
        print(f"  1h ✗ {e}")
        ok = False

    # ── UÇTAN UCA: gerçek OHLCV ile hizala(), ve NAİF yöntemle FARK göster
    n = 240
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.arange(n, dtype=float)
    df = pd.DataFrame({"open": 100 + rng, "high": 101 + rng, "low": 99 + rng,
                       "close": 100.5 + rng, "volume": 1.0}, index=idx)
    d15 = resample_tf(df, "15m")
    h = hizala(df, d15, "5m", "15m")
    # NAİF (YANLIŞ) yöntem: reindex+ffill → oluşmakta olan barı sızdırır
    naif = d15["close"].reindex(df.index, method="ffill")
    farkli = int((h["15m_close"].values != naif.values).sum())
    print(f"  uçtan uca: {len(h)} bar hizalandı, naif ffill'den {farkli} barda FARKLI")
    print(f"    (fark 0 olsaydı ya veri dejenere ya kod naifle aynı — ikisi de kötü)")
    ok &= farkli > 0
    ok &= bool(h["15m_close"].isna().sum() >= 1)   # ilk barlarda görünür üst bar yok

    tz = pd.date_range("2026-01-01", periods=10, freq="5min")     # tz-NAIVE
    try:
        mtf_pos(tz, ust_idx, "5m", "15m")
        print("  ⛔ tz-naive index KABUL EDİLDİ — sessiz hata riski"); ok = False
    except ValueError:
        print("  tz-naive index reddedildi ✓")

    print(f"\n{'✓ mtf.py GÜVENİLİR' if ok else '✗ mtf.py BOZUK — kullanma'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _self_test() else 1)
