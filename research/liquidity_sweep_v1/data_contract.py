"""
Veri sözleşmesi (şartname §3): ham 5m mumların okunması, denetimi, ortak 5m ızgaraya
oturtulması, 15m/1H/gün/seans türetimi, funding ve sözleşme metadatası, T0/T1/B1/B2.

Kurallar:
  • Zaman damgası birimi KAYNAK ŞEMASINDAN gelir: indirici `open_time_ms` alanını milisaniye
    olarak yazar (MEXC saniye×1000, Binance ms; µs dosyaları indiricide şema sütununa göre
    dönüştürüldü). Burada yalnız ızgara uyumu ve makul aralık DOĞRULANIR, tahmin edilmez.
  • Eksik bar NaN kalır; sentetik bar, ileri/geri doldurma YOK.
  • 15m = 3 tam 5m, 1H = 12 tam 5m, gün = 288 tam 5m, seans [00:00,08:00) = 96 tam 5m.
  • OHLC tutarsız / sonlu olmayan / negatif hacim satırı DATA_INVALID (NaN) ve sayılır.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C


@dataclass
class SymbolData:
    symbol: str
    source: str
    g0: int                      # ızgara başlangıcı (ms, UTC gün başı)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    valid5: np.ndarray           # bool
    tick: float
    contract_size: float
    vol_unit: float              # sözleşme adedi adımı
    min_vol: float               # minimum sözleşme adedi
    meta_source: str
    funding_t: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype="int64"))   # ms
    funding_rate: np.ndarray = field(default_factory=lambda: np.zeros(0))
    funding_on_grid: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    funding_source: str = "NOT_MODELED"
    quality: dict = field(default_factory=dict)

    @property
    def n5(self):
        return len(self.c)

    def t_open(self, k):
        return self.g0 + int(k) * C.M5


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ───────────────────────────── ham okuma ve denetim ──────────────────────────
def load_raw_npz(path):
    z = np.load(path)
    t = z["open_time_ms"].astype("int64")
    return dict(t=t, o=z["open"].astype(float), h=z["high"].astype(float), l=z["low"].astype(float),
                c=z["close"].astype(float), v=z["volume"].astype(float))


def validate_rows(raw):
    """Satır düzeyi denetim. Döner: maske (geçerli), sayaçlar."""
    t, o, h, l, c, v = raw["t"], raw["o"], raw["h"], raw["l"], raw["c"], raw["v"]
    q = {}
    fin = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & np.isfinite(v)
    pos = (o > 0) & (h > 0) & (l > 0) & (c > 0)
    ohlc = (l <= np.minimum(o, c)) & (np.maximum(o, c) <= h)
    volok = v >= 0
    grid = (t % C.M5) == 0
    # makul aralık: 2015-01-01 .. 2035-01-01 ms — birim hatasını (s/us/ns) yakalar
    rng = (t >= 1_420_070_400_000) & (t <= 2_051_222_400_000)
    ok = fin & pos & ohlc & volok & grid & rng
    q.update(rows=int(len(t)), non_finite=int((~fin).sum()), non_positive=int((fin & ~pos).sum()),
             ohlc_inconsistent=int((fin & pos & ~ohlc).sum()), negative_volume=int((fin & ~volok).sum()),
             off_grid=int((~grid).sum()), out_of_range_time=int((~rng).sum()))
    # yinelenen damgalar: birebir aynı satır tekilleştirilebilir; çatışan iki satır kullanılamaz
    s = pd.DataFrame(dict(t=t, o=o, h=h, l=l, c=c, v=v))
    dup_exact = s.duplicated(keep="first")
    s2 = s[~dup_exact]
    conflict_t = set(s2.loc[s2.duplicated("t", keep=False), "t"].tolist())
    q.update(duplicate_exact=int(dup_exact.sum()), conflicting_timestamps=len(conflict_t))
    keep = ok & ~dup_exact.to_numpy() & ~np.isin(t, list(conflict_t))
    return keep, q


def to_grid(raw, keep, g0, n5):
    """Geçerli satırları [g0, g0+n5*5m) ızgarasına yerleştirir; eksik = NaN."""
    arrs = {k: np.full(n5, np.nan) for k in ("o", "h", "l", "c", "v")}
    t = raw["t"][keep]
    k = (t - g0) // C.M5
    m = (k >= 0) & (k < n5)
    for name in arrs:
        arrs[name][k[m]] = raw[name][keep][m]
    valid = np.isfinite(arrs["c"])
    return arrs, valid


def agg_valid(valid5, per):
    """Üst zaman dilimi bar geçerliliği: gruptaki TÜM alt barlar geçerli olmalı."""
    n = len(valid5) // per
    return valid5[: n * per].reshape(n, per).all(axis=1)


def resample(sd: SymbolData, per):
    """5m → per×5m OHLC; eksik alt bar varsa NaN (DATA_INVALID)."""
    n = sd.n5 // per
    sl = slice(0, n * per)
    o = sd.o[sl].reshape(n, per)[:, 0].copy()
    h = sd.h[sl].reshape(n, per).max(axis=1)
    l = sd.l[sl].reshape(n, per).min(axis=1)
    c = sd.c[sl].reshape(n, per)[:, -1].copy()
    v = agg_valid(sd.valid5, per)
    for a in (o, h, l, c):
        a[~v] = np.nan
    return o, h, l, c, v


def session_hl(sd: SymbolData):
    """Her UTC gün için [00:00,08:00) yüksek/düşük; 96 tam bar yoksa NaN."""
    nd = sd.n5 // C.GRID_PER_DAY
    hh = sd.h[: nd * C.GRID_PER_DAY].reshape(nd, C.GRID_PER_DAY)[:, : C.SESSION_BARS]
    ll = sd.l[: nd * C.GRID_PER_DAY].reshape(nd, C.GRID_PER_DAY)[:, : C.SESSION_BARS]
    vv = sd.valid5[: nd * C.GRID_PER_DAY].reshape(nd, C.GRID_PER_DAY)[:, : C.SESSION_BARS].all(axis=1)
    H = np.where(vv, hh.max(axis=1), np.nan)
    L = np.where(vv, ll.min(axis=1), np.nan)
    return H, L, vv


# ───────────────────────────── metadata ve funding ───────────────────────────
def contract_meta(detail: dict, symbol: str):
    """MEXC güncel sözleşme metadatası. Tarihsel değil (varsayım olarak raporlanır)."""
    d = detail.get(symbol) or {}
    try:
        tick = float(d["priceUnit"])
        cs = float(d["contractSize"])
        vu = float(d.get("volUnit") or 1)
        mv = float(d.get("minVol") or 1)
        if tick > 0 and cs > 0 and vu > 0 and mv > 0:
            return tick, cs, vu, mv, "MEXC contract/detail (güncel, tarihsel değil)"
    except (KeyError, TypeError, ValueError):
        pass
    return None


def load_funding(path_csv, g0, g1):
    """Binance fundingRate CSV (şema: calc_time ms, funding_interval_hours, last_funding_rate).
    Sıra: (1) ayrıştırılamayan satırlar SAYILIR ve atılır; (2) settlement zamanı 5m ızgarasına
    ±1 sn içinde ise o sınıra oturtulur (borsa titreşimi), değilse on_grid=False; (3) OTURTMADAN
    SONRA tekilleştirme: aynı sınırda aynı oran → yinelenen; farklı oran → ÇATIŞMA (o settlement
    kullanılmaz, sayılır); (4) kapsam: ardışık settlement'lar arası > aralık+1dk ise boşluk sayılır.
    Veri yoksa NOT_MODELED."""
    if not path_csv or not os.path.exists(path_csv):
        return np.zeros(0, "int64"), np.zeros(0), np.zeros(0, bool), "NOT_MODELED", {"rows": 0}
    d = pd.read_csv(path_csv)
    cols = {c.lower(): c for c in d.columns}
    tcol = next((cols[c] for c in ("calc_time", "fundingtime", "funding_time", "settletime") if c in cols), None)
    rcol = next((cols[c] for c in ("last_funding_rate", "fundingrate", "funding_rate") if c in cols), None)
    icol = next((cols[c] for c in ("funding_interval_hours", "collectcycle") if c in cols), None)
    if tcol is None or rcol is None:
        raise ValueError(f"funding şeması tanınmadı: {list(d.columns)}")
    t = pd.to_numeric(d[tcol], errors="coerce").to_numpy(dtype="float64")
    r = pd.to_numeric(d[rcol], errors="coerce").to_numpy(dtype="float64")
    iv = pd.to_numeric(d[icol], errors="coerce").to_numpy(dtype="float64") if icol else np.full(len(t), 8.0)
    ok = np.isfinite(t) & np.isfinite(r)
    q = dict(rows=int(len(t)), dropped_unparseable=int((~ok).sum()))
    t, r, iv = t[ok].astype("int64"), r[ok], iv[ok]
    if len(t) and t.max() > 10**14:
        raise ValueError("funding zaman birimi ms değil (şema: calc_time ms)")
    snapped = np.round(t / C.M5).astype("int64") * C.M5
    on_grid = np.abs(t - snapped) <= 1000
    t = np.where(on_grid, snapped, t)
    df = pd.DataFrame(dict(t=t, r=r, g=on_grid, iv=iv)).sort_values("t", kind="stable")
    dup = df.duplicated(["t", "r"], keep="first")
    df = df[~dup]
    conflict = df.duplicated("t", keep=False)
    q.update(duplicates_after_snap=int(dup.sum()), conflicting_settlements=int(conflict.sum() // 2 if conflict.any() else 0))
    df = df[~conflict]
    m = (df["t"] >= g0) & (df["t"] < g1)
    w = df[m]
    gaps = 0
    if len(w) > 1:
        dt = np.diff(w["t"].to_numpy())
        lim = (w["iv"].to_numpy()[1:] * C.H1 + C.MIN)
        gaps = int((dt > lim).sum())
    q.update(in_range=int(m.sum()), off_grid=int((~w["g"]).sum()), coverage_gaps=gaps,
             first=ms_to_str(int(w["t"].min())) if len(w) else None,
             last=ms_to_str(int(w["t"].max())) if len(w) else None)
    return (w["t"].to_numpy("int64"), w["r"].to_numpy(float), w["g"].to_numpy(bool),
            "BINANCE_UM_PROXY (gerçek settlement zamanları; MEXC değil)", q)


# ───────────────────────────── evren kurulumu ────────────────────────────────
def choose_source(veri_dir, symbols, end_ms):
    """Kaynak kuralı (PnL görmeden, MANIFEST): MEXC 5m TÜM semboller için 2023-01-08'den önce
    başlıyor, sona 1 gün içinde ulaşıyor ve eksik bar oranı <= %0.1 ise MEXC; aksi hâlde
    TÜM semboller Binance USDⓈ-M (venue vekili). Kaynaklar sembol bazında karıştırılmaz."""
    rapor = {}
    mexc_ok = True
    for s in symbols:
        p = os.path.join(veri_dir, "mexc_5m", f"{s}.npz")
        if not os.path.exists(p):
            rapor[s] = "mexc dosyası yok"
            mexc_ok = False
            continue
        raw = load_raw_npz(p)
        t = raw["t"]
        span = (end_ms - int(t.min())) // C.M5 if len(t) else 0
        miss = 1 - len(np.unique(t)) / max(span, 1)
        ok = len(t) > 0 and t.min() <= 1_673_136_000_000 and t.max() >= end_ms - C.DAY and miss <= 0.001
        rapor[s] = dict(ilk=str(pd.Timestamp(int(t.min()), unit="ms", tz="UTC")) if len(t) else None,
                        son=str(pd.Timestamp(int(t.max()), unit="ms", tz="UTC")) if len(t) else None,
                        eksik_oran=float(miss), uygun=bool(ok))
        mexc_ok &= bool(ok)
    return ("mexc_5m" if mexc_ok else "binance_5m"), rapor


def build_universe(veri_dir, symbols=None):
    symbols = list(symbols or C.UNIVERSE)
    with open(os.path.join(veri_dir, "indirme_ozeti.json")) as f:
        ozet = json.load(f)
    end_ms = int(pd.Timestamp(ozet["olusturma"]).floor("D").timestamp() * 1000)
    source, src_report = choose_source(veri_dir, symbols, end_ms)
    detail_p = os.path.join(veri_dir, "mexc_contract_detail.json")
    detail = json.load(open(detail_p)) if os.path.exists(detail_p) else {}
    raws, hashes, starts, ends = {}, {}, {}, {}
    if os.path.exists(detail_p):
        hashes[detail_p] = sha256_file(detail_p)
    for s in symbols:
        p = os.path.join(veri_dir, source, f"{s}.npz")
        if not os.path.exists(p):
            continue
        raws[s] = load_raw_npz(p)
        hashes[p] = sha256_file(p)
        starts[s], ends[s] = int(raws[s]["t"].min()), int(raws[s]["t"].max())
    g0 = (min(starts.values()) // C.DAY) * C.DAY
    g1 = ((max(ends.values()) + C.M5) // C.DAY) * C.DAY        # son tam gün sınırı (en geç sembol)
    n5 = (g1 - g0) // C.M5
    out, excluded, quality = {}, {}, {}
    for s in symbols:
        if s not in raws:
            excluded[s] = "DATA_MISSING: kaynak dosyası yok"
            continue
        meta = contract_meta(detail, s)
        if meta is None:
            excluded[s] = "METADATA_MISSING: tick/lot/sözleşme çarpanı yok"
            continue
        keep, q = validate_rows(raws[s])
        arrs, valid = to_grid(raws[s], keep, g0, n5)
        fpath = os.path.join(veri_dir, "binance_funding", f"{s}.csv")
        ft, fr, fg, fsrc, fq = load_funding(fpath, g0, g1)
        if os.path.exists(fpath):
            hashes[fpath] = sha256_file(fpath)
        sd = SymbolData(symbol=s, source=source, g0=g0, o=arrs["o"], h=arrs["h"], l=arrs["l"], c=arrs["c"],
                        v=arrs["v"], valid5=valid, tick=meta[0], contract_size=meta[1], vol_unit=meta[2],
                        min_vol=meta[3], meta_source=meta[4], funding_t=ft, funding_rate=fr,
                        funding_on_grid=fg, funding_source=fsrc)
        q["valid_5m"] = int(valid.sum())
        q["first_bar"] = str(pd.Timestamp(starts[s], unit="ms", tz="UTC"))
        q["last_bar"] = str(pd.Timestamp(ends[s], unit="ms", tz="UTC"))
        q["funding"] = fq
        sd.quality = q
        quality[s] = q
        out[s] = sd
    return dict(symbols=out, excluded=excluded, quality=quality, source=source, source_report=src_report,
                g0=g0, g1=g1, raw_hashes=hashes, download_summary_created=ozet.get("olusturma"))


# ───────────────────────────── tarihler ──────────────────────────────────────
def warmup_complete_ms(sd: SymbolData):
    """1000 tam 1H bar ve her alt TF'de (5m, 15m) en az 100 tam bar tamamlandığı ilk an."""
    v1h = agg_valid(sd.valid5, C.GRID_PER_1H)
    v15 = agg_valid(sd.valid5, C.GRID_PER_15M)
    def nth_close(valid, per, n):
        idx = np.flatnonzero(valid)
        if len(idx) < n:
            return None
        return sd.g0 + (int(idx[n - 1]) + 1) * per * C.M5
    a = nth_close(v1h, C.GRID_PER_1H, C.WARMUP_1H)
    b = nth_close(v15, C.GRID_PER_15M, C.WARMUP_LOWER_TF)
    c = nth_close(sd.valid5, 1, C.WARMUP_LOWER_TF)
    if None in (a, b, c):
        return None
    return max(a, b, c)


def last_complete_day_ms(sd: SymbolData):
    idx = np.flatnonzero(sd.valid5)
    if not len(idx):
        return None
    last_close = sd.g0 + (int(idx[-1]) + 1) * C.M5
    return (last_close // C.DAY) * C.DAY


def partition_dates(universe):
    syms = universe["symbols"]
    w = [warmup_complete_ms(sd) for sd in syms.values()]
    e = [last_complete_day_ms(sd) for sd in syms.values()]
    if not syms or None in w or None in e:
        return None
    t0 = int(math.ceil(max(w) / C.DAY)) * C.DAY
    t1 = min(e)
    n_days = (t1 - t0) // C.DAY
    b1 = t0 + int(math.floor(C.SPLIT_1 * n_days)) * C.DAY
    b2 = t0 + int(math.floor(C.SPLIT_2 * n_days)) * C.DAY
    return dict(T0=t0, T1=t1, B1=b1, B2=b2, N_days=n_days,
                DISCOVERY=(t0, b1), VALIDATION=(b1, b2), FINAL=(b2, t1))


def gaps_in(sd: SymbolData, a_ms, b_ms):
    """[a,b) içindeki eksik 5m bar aralıkları."""
    k0, k1 = (a_ms - sd.g0) // C.M5, (b_ms - sd.g0) // C.M5
    miss = np.flatnonzero(~sd.valid5[k0:k1]) + k0
    if not len(miss):
        return []
    runs, start, prev = [], miss[0], miss[0]
    for k in miss[1:]:
        if k != prev + 1:
            runs.append((start, prev))
            start = k
        prev = k
    runs.append((start, prev))
    return [(str(pd.Timestamp(sd.t_open(a), unit="ms", tz="UTC")),
             str(pd.Timestamp(sd.t_open(b) + C.M5, unit="ms", tz="UTC")), int(b - a + 1)) for a, b in runs]


def ms_to_str(ms):
    return None if ms is None else str(pd.Timestamp(int(ms), unit="ms", tz="UTC"))
