"""
oi_edge_audit.py — OI (open interest) Donchian kırılım kalitesini öngörüyor mu? SALT OKUR.

Önceden kayıtlı TEK hipotez (bkz. OI_EDGE_RAPORU.md; sonuçtan sonra DEĞİŞTİRİLMEZ):
  özellik : oi_change_4h = OI_T / OI_(T-4h) − 1   (T = canlı Donchian GİRİŞ zamanı)
  gruplar : OI_RISING  = oi_change_4h > 0
            OI_NOT_RISING = oi_change_4h <= 0
  etki    : delta_R = ort R_net(RISING) − ort R_net(NOT_RISING), hafta-kümeli bootstrap %95 GA
  kontrol : Spearman(oi_change_4h, R_net) — yalnız işaret kontrolü
Başka lookback, eşik, z-skor, yüzdelik, coin/yön seçimi YOK.

Veri: data/oi_log.csv (oi_collect.py, ~15 dk) + trades.db (mode=ro), yalnız is_paper=0 Donchian.
OI eşleşmesi GELECEĞİ KULLANMAZ: T anında/öncesindeki son kayıt, en fazla 30 dk bayat.
Outcome: erken_uyari.r_net (kanonik canlı net R). R yalnız stop güvenilirse sayılır
(sl0, ya da |giriş−sl_price| = 2.0×ATR ±%2 → stop hiç taşınmamış).

Kapılar (önceden sabit):
  OI takvim kapsamı < 30 gün  VEYA  geçerli Donchian n < 60  VEYA  veri kalitesi FAIL → D
  n < 30 → hiçbir edge tablosu üretilmez; 30 ≤ n < 60 → yalnız keşif tablosu, hüküm D
  lookahead assert ihlali → TEST INVALID

VPS:  cd /opt/bot2 && git pull && venv/bin/python arastirma/oi_edge_test/oi_edge_audit.py
Borsa API'si çağırmaz, emir göndermez, .env okumaz, bota dokunmaz. Yalnız işlem düzeyi CSV
--cikti klasörüne (varsayılan /tmp/oi_edge_audit) yazılır; repoya/data'ya yazmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOK)
import erken_uyari as EU  # noqa: E402  (kanonik r_net, kol_adi; yalnız stdlib kullanır)

DONCH_COINS = ("SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB")
GRID_DK = 15
BAYAT = pd.Timedelta(minutes=30)
LOOKBACK = pd.Timedelta(hours=4)
MIN_GUN = 30
MIN_N_KARAR = 60
MIN_N_KESIF = 30
N_BOOT = 5000
TOHUM = 20260928
SL_ATR = 2.0            # donchian sl_atr (strategies/donchian.py:184; canlı config 2.0)
ATR_TOL = 0.02
SICRAMA = 10.0          # ardışık iki kayıt arasında ×10 / ÷10 = ölçek kırılması
# Kalite FAIL eşikleri (önceden sabit)
MAX_BOZUK_ORAN = 0.01   # null/bozuk/≤0 OI oranı
MIN_DONCH_KAPSAM = 0.80  # Donchian coinlerinde 15dk ızgara kapsamı


# ─────────────────────────── OI verisi ───────────────────────────
def oi_oku(yol):
    ham = pd.read_csv(yol, dtype=str, keep_default_na=False)
    n_ham = len(ham)
    ts = pd.to_datetime(ham["ts"], utc=True, errors="coerce")
    oi = pd.to_numeric(ham["oi"], errors="coerce")
    d = pd.DataFrame({"ts": ts, "symbol": ham["symbol"].str.strip().str.upper(), "oi": oi,
                      "oi_usd": pd.to_numeric(ham.get("oi_usd"), errors="coerce"),
                      "price": pd.to_numeric(ham.get("price"), errors="coerce")})
    bozuk_ts = int(d["ts"].isna().sum())
    null_oi = int(d["oi"].isna().sum())
    sifir_alti = int((d["oi"] <= 0).sum())
    dup = int(d.duplicated(["ts", "symbol"]).sum())
    temiz = d.dropna(subset=["ts", "oi"])
    temiz = temiz[temiz["oi"] > 0].drop_duplicates(["ts", "symbol"], keep="first")
    temiz = temiz.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return temiz, dict(n_ham=n_ham, bozuk_ts=bozuk_ts, null_oi=null_oi,
                       sifir_alti=sifir_alti, dup=dup)


def kapsam(d, sayim):
    """Genel + coin başına kapsam; kalite bulguları."""
    out = {}
    if d.empty:
        return dict(bos=True)
    out["ilk"], out["son"] = d["ts"].min(), d["ts"].max()
    out["gun"] = (out["son"] - out["ilk"]).total_seconds() / 86400
    out["satir"] = sayim["n_ham"]
    anlar = d["ts"].drop_duplicates().sort_values()
    aralik = anlar.diff().dt.total_seconds().div(60).dropna()
    out["aralik_medyan_dk"] = float(aralik.median()) if len(aralik) else float("nan")
    ızgara = pd.date_range(out["ilk"].floor(f"{GRID_DK}min"), out["son"].floor(f"{GRID_DK}min"),
                           freq=f"{GRID_DK}min")
    out["kapsam_pct"] = anlar.dt.floor(f"{GRID_DK}min").nunique() / max(len(ızgara), 1) * 100
    if len(aralik):
        i = aralik.idxmax()
        out["en_buyuk_bosluk_dk"] = float(aralik.max())
        out["en_buyuk_bosluk_bitis"] = anlar.loc[i]
    coin = {}
    for s, g in d.groupby("symbol"):
        t = g["ts"]
        iz = pd.date_range(t.min().floor(f"{GRID_DK}min"), t.max().floor(f"{GRID_DK}min"),
                           freq=f"{GRID_DK}min")
        bos = t.diff().dt.total_seconds().div(60)
        oran = g["oi"].div(g["oi"].shift(1))
        coin[s] = dict(n=len(g), ilk=t.min(), son=t.max(),
                       gun=(t.max() - t.min()).total_seconds() / 86400,
                       kapsam_pct=t.dt.floor(f"{GRID_DK}min").nunique() / max(len(iz), 1) * 100,
                       en_buyuk_bosluk_dk=float(bos.max()) if len(g) > 1 else float("nan"),
                       sicrama=int(((oran > SICRAMA) | (oran < 1 / SICRAMA)).sum()),
                       max_log_oran=float(np.nanmax(np.abs(np.log(oran)))) if len(g) > 1 else 0.0)
    out["coin"] = coin
    return out


def kalite(kap, sayim):
    """(PASS/FAIL, gerekçeler) — önceden sabit kurallar."""
    neden = []
    n = max(sayim["n_ham"], 1)
    bozuk = sayim["bozuk_ts"] + sayim["null_oi"] + sayim["sifir_alti"]
    if bozuk / n > MAX_BOZUK_ORAN:
        neden.append(f"null/bozuk/≤0 oranı %{bozuk / n * 100:.2f} > %{MAX_BOZUK_ORAN * 100:.0f}")
    for c in DONCH_COINS:
        k = kap.get("coin", {}).get(c)
        if k is None:
            neden.append(f"{c}: OI verisi yok")
            continue
        if k["kapsam_pct"] < MIN_DONCH_KAPSAM * 100:
            neden.append(f"{c}: 15dk ızgara kapsamı %{k['kapsam_pct']:.1f} < %{MIN_DONCH_KAPSAM * 100:.0f}")
        if k["sicrama"]:
            neden.append(f"{c}: {k['sicrama']} açıklanamayan ölçek sıçraması (×10/÷10)")
    return ("FAIL" if neden else "PASS"), neden


# ─────────────────────────── işlemler ───────────────────────────
def islemler(db):
    con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, symbol, side, entry_price, exit_price, quantity, sl_price, entry_time, "
        "exit_time, pnl_usdt, exit_reason, strategy_scores FROM trades WHERE is_paper=0 "
        "ORDER BY entry_time")]
    con.close()
    return [r for r in rows if EU.kol_adi(r.get("strategy_scores")) == "donchian"]


def stop_guvenilir(t):
    """erken_uyari.r_net'in kullandığı stop güvenilir mi: sl0 VAR, ya da sl_price hiç taşınmamış."""
    ss = EU._skor(t)
    if ss.get("sl0"):
        return True, "sl0"
    try:
        atr, sp, ep = float(ss.get("atr")), float(t["sl_price"]), float(t["entry_price"])
        niyet = float(ss.get("intended_entry") or ep)
    except (TypeError, ValueError):
        return False, "stop doğrulanamadı"
    if atr > 0 and abs(abs(niyet - sp) / (SL_ATR * atr) - 1) <= ATR_TOL:
        return True, "sl_price(ATR doğrulandı)"
    return False, "stop taşınmış/doğrulanamadı"


def son_kayit(g_ts, g_oi, an):
    """an'da veya ÖNCESİNDEKİ son kayıt (asla sonrası). (ts, oi) ya da (None, None)."""
    i = g_ts.searchsorted(an, side="right") - 1
    if i < 0:
        return None, None
    return g_ts[i], g_oi[i]


def eslestir(trades, d):
    idx = {s: (g["ts"].dt.tz_convert(None).to_numpy(), g["oi"].to_numpy())
           for s, g in d.groupby("symbol")}   # tz-naive UTC datetime64
    satir, sayim = [], {}

    def say(k):
        sayim[k] = sayim.get(k, 0) + 1

    for t in trades:
        coin = str(t["symbol"]).split("/")[0].upper()
        T = pd.Timestamp(t["entry_time"])
        T = T.tz_localize("UTC") if T.tzinfo is None else T.tz_convert("UTC")
        if t.get("pnl_usdt") is None or not t.get("exit_time"):
            say("açık işlem (sonuç yok)")
            continue
        ok, kaynak = stop_guvenilir(t)
        R = EU.r_net(t) if ok else None
        if R is None:
            say(f"R güvenilmez: {kaynak if not ok else 'risk=0'}")
            continue
        if coin not in idx:
            say("coin için OI yok")
            continue
        ts_arr, oi_arr = idx[coin]
        T64 = np.datetime64(T.tz_convert(None))
        ts0, oi0 = son_kayit(ts_arr, oi_arr, T64)
        tsl, oil = son_kayit(ts_arr, oi_arr, np.datetime64((T - LOOKBACK).tz_convert(None)))
        if ts0 is None or tsl is None:
            say("OI kaydı yok (işlem OI başlangıcından önce)")
            continue
        ts0, tsl = pd.Timestamp(ts0, tz="UTC"), pd.Timestamp(tsl, tz="UTC")
        if T - ts0 > BAYAT or (T - LOOKBACK) - tsl > BAYAT:
            say("OI bayat (>30 dk)")
            continue
        satir.append(dict(trade_id=t["id"], symbol=coin, side=str(t["side"]).lower(),
                          entry_time=T, oi_t_ts=ts0, oi_t=float(oi0),
                          oi_t_minus_4h_ts=tsl, oi_t_minus_4h=float(oil),
                          oi_change_4h=float(oi0) / float(oil) - 1.0, R_net=float(R),
                          exit_reason=t.get("exit_reason"), stop_kaynak=kaynak))
    return pd.DataFrame(satir), sayim


def lookahead_denetim(m):
    if m.empty:
        return 0
    ihlal = (m["oi_t_ts"] > m["entry_time"]) | (m["oi_t_minus_4h_ts"] > m["entry_time"] - LOOKBACK)
    return int(ihlal.sum())


# ─────────────────────────── istatistik ───────────────────────────
def grup_ozet(R, cikis):
    R = np.asarray(R, float)
    if len(R) == 0:
        return dict(n=0)
    kaz, kay = R[R > 0].sum(), -R[R < 0].sum()
    c = pd.Series(cikis).fillna("?").astype(str)
    return dict(n=len(R), ort=R.mean(), medyan=float(np.median(R)), wr=(R > 0).mean() * 100,
                pf=(kaz / kay) if kay > 0 else float("inf"),
                tp=int(c.str.contains("tp").sum()), sl=int(c.str.contains("sl").sum()),
                max_hold=int(c.str.contains("max_hold|hold").sum()),
                diger=int((~c.str.contains("tp|sl|hold")).sum()))


def delta(m):
    a = m.loc[m["oi_change_4h"] > 0, "R_net"]
    b = m.loc[m["oi_change_4h"] <= 0, "R_net"]
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    return a.mean() - b.mean()


def hafta_boot(m):
    rng = np.random.default_rng(TOHUM)
    hafta = m["entry_time"].dt.tz_convert(None).dt.to_period("W").astype(str)
    gruplar = [g for _, g in m.groupby(hafta)]
    k = len(gruplar)
    out, bos = [], 0
    for _ in range(N_BOOT):
        sec = rng.integers(0, k, k)
        o = pd.concat([gruplar[i] for i in sec])
        d = delta(o)
        if np.isfinite(d):
            out.append(d)
        else:
            bos += 1
    out = np.array(out)
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)), k, bos) \
        if len(out) else (float("nan"), float("nan"), k, bos)


def islem_boot(m):
    rng = np.random.default_rng(TOHUM)
    a = m.loc[m["oi_change_4h"] > 0, "R_net"].to_numpy()
    b = m.loc[m["oi_change_4h"] <= 0, "R_net"].to_numpy()
    if len(a) == 0 or len(b) == 0:
        return float("nan"), float("nan")
    d = rng.choice(a, (N_BOOT, len(a))).mean(1) - rng.choice(b, (N_BOOT, len(b))).mean(1)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return float("nan"), float("nan")
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(TOHUM)
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(N_BOOT)])
    return rho, float((np.abs(perm) >= abs(rho) - 1e-12).mean())


def gs(o):
    if not o.get("n"):
        return "n=0"
    return (f"n={o['n']:>3d}  ort R {o['ort']:+.3f}  medyan {o['medyan']:+.3f}  WR %{o['wr']:.1f}  "
            f"PF {o['pf']:.2f}  TP/SL/max-hold/diğer {o['tp']}/{o['sl']}/{o['max_hold']}/{o['diger']}")


def _t(x):
    return x.strftime("%Y-%m-%d %H:%M") if isinstance(x, pd.Timestamp) else str(x)


# ─────────────────────────── ana akış ───────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="OI → Donchian kırılım kalitesi (salt okur)")
    ap.add_argument("--oi", default=os.path.join("data", "oi_log.csv"))
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--cikti", default="/tmp/oi_edge_audit")
    ap.add_argument("--yalniz-kapsam", action="store_true", help="yalnız OI veri kapsamı")
    a = ap.parse_args(argv)

    if not os.path.exists(a.oi):
        sys.exit(f"OI dosyası yok: {a.oi}")
    d, sayim = oi_oku(a.oi)
    kap = kapsam(d, sayim)
    kal, kal_neden = kalite(kap, sayim) if not kap.get("bos") else ("FAIL", ["OI verisi boş"])

    print(f"== OI VERİ KAPSAMI ({a.oi})")
    if kap.get("bos"):
        print("  boş")
    else:
        print(f"  ilk {_t(kap['ilk'])} · son {_t(kap['son'])} · {kap['gun']:.1f} gün · "
              f"satır {kap['satir']} · 15dk ızgara kapsamı %{kap['kapsam_pct']:.1f}")
        print(f"  toplama aralığı medyan {kap['aralik_medyan_dk']:.2f} dk · en büyük boşluk "
              f"{kap.get('en_buyuk_bosluk_dk', float('nan')):.1f} dk (biten {_t(kap.get('en_buyuk_bosluk_bitis'))})")
        print(f"  duplicate (ts,coin) {sayim['dup']} · bozuk ts {sayim['bozuk_ts']} · "
              f"null OI {sayim['null_oi']} · OI≤0 {sayim['sifir_alti']}")
        print(f"  {'coin':<5s} {'satır':>6s} {'ilk':>16s} {'son':>16s} {'gün':>6s} {'kapsam':>7s} "
              f"{'maxboşluk':>9s} {'sıçrama':>7s} {'max|ln|':>7s}")
        for c in list(DONCH_COINS) + sorted(set(kap["coin"]) - set(DONCH_COINS)):
            k = kap["coin"].get(c)
            if k is None:
                print(f"  {c:<5s} VERİ YOK")
                continue
            isaret = " *" if c in DONCH_COINS else ""
            print(f"  {c:<5s} {k['n']:>6d} {_t(k['ilk']):>16s} {_t(k['son']):>16s} {k['gun']:>6.1f} "
                  f"%{k['kapsam_pct']:>5.1f} {k['en_buyuk_bosluk_dk']:>8.1f}dk {k['sicrama']:>7d} "
                  f"{k['max_log_oran']:>7.3f}{isaret}")
        print("  (* = Donchian coini)")
        print("  OI alanı: oi_collect.py ilk bulunan alanı yazar, önce 'holdVol' (kontrat adedi).")
        print("  CSV alan adını kaydetmez; ölçek tutarlılığı yukarıdaki sıçrama sütunuyla denetlenir.")
        print("  ⚠ oi_usd = kontrat × fiyat → contractSize≠1 coinlerde USD DEĞİLDİR; bu test")
        print("    yalnız oran (oi_change_4h) kullanır, birim sabit kaldıkça etkilenmez.")
    print(f"  VERİ KALİTESİ: {kal}" + ("" if kal == "PASS" else " — " + "; ".join(kal_neden)))

    if a.yalniz_kapsam:
        return "KAPSAM"

    trades = islemler(a.db) if os.path.exists(a.db) else []
    if not os.path.exists(a.db):
        print(f"\n  trades.db yok: {a.db}")
    m, esl = eslestir(trades, d) if not kap.get("bos") else (pd.DataFrame(), {})
    ihlal = lookahead_denetim(m)
    os.makedirs(a.cikti, exist_ok=True)
    csv_yol = os.path.join(a.cikti, "oi_donchian_eslesme.csv")
    m.to_csv(csv_yol, index=False)

    print(f"\n== CANLI DONCHIAN EŞLEŞMESİ (is_paper=0; {a.db}, salt okur)")
    print(f"  toplam Donchian işlemi {len(trades)} · geçerli OI eşleşmesi {len(m)}")
    for k, v in sorted(esl.items()):
        print(f"    geçersiz — {k}: {v}")
    print(f"  lookahead ihlali: {ihlal}  (OI_T ≤ giriş ve OI_T−4h ≤ giriş−4h, otomatik assert)")
    print(f"  işlem düzeyi CSV: {csv_yol}")

    gun = kap.get("gun", 0.0) if not kap.get("bos") else 0.0
    n = len(m)
    gecersiz = len(trades) - n

    def kapanis(hukum, durum=None, gerekce=None):
        print("\n" + "=" * 60)
        print("OI COVERAGE:")
        print(f"first: {_t(kap.get('ilk'))}")
        print(f"last: {_t(kap.get('son'))}")
        print(f"days: {gun:.1f}")
        print(f"rows: {kap.get('satir', 0)}")
        print(f"coverage %: {kap.get('kapsam_pct', 0.0):.1f}")
        print()
        print(f"DONCHIAN trades total: {len(trades)}")
        print(f"valid OI matched: {n}")
        print(f"invalid/stale: {gecersiz}")
        print()
        print("DATA QUALITY:")
        print(kal)
        if durum:
            print()
            print("STATUS:")
            print(durum)
            if gerekce:
                print()
                print("gerekçe:")
                for g in gerekce:
                    print(g)
        return hukum

    if ihlal:
        kapanis("INVALID", "TEST INVALID", [f"{ihlal} lookahead ihlali — sonuç kullanılamaz"])
        print("\nHÜKÜM:\nTEST INVALID")
        return "INVALID"

    yetersiz = gun < MIN_GUN or n < MIN_N_KARAR or kal != "PASS"
    if n < MIN_N_KESIF or kal != "PASS" or yetersiz:
        if MIN_N_KESIF <= n and kal == "PASS":
            # 30 ≤ n < 60 (ya da gün < 30): YALNIZ keşif tablosu, karar YOK
            print("\n== KEŞİF TABLOSU (karar değildir; n veya gün kapısı karşılanmadı)")
            print("  OI_RISING      " + gs(grup_ozet(m.loc[m.oi_change_4h > 0, "R_net"],
                                                     m.loc[m.oi_change_4h > 0, "exit_reason"])))
            print("  OI_NOT_RISING  " + gs(grup_ozet(m.loc[m.oi_change_4h <= 0, "R_net"],
                                                     m.loc[m.oi_change_4h <= 0, "exit_reason"])))
        g = [f"days {gun:.1f} / required {MIN_GUN}", f"trades {n} / required {MIN_N_KARAR}"]
        if kal != "PASS":
            g.append("data quality FAIL: " + "; ".join(kal_neden))
        kapanis("D", "DATA INSUFFICIENT", g)
        print("\nHÜKÜM:\nD")
        return "D"

    # ── PRIMARY TEST (kapılar geçti) ──
    up, dn = m[m.oi_change_4h > 0], m[m.oi_change_4h <= 0]
    gu, gd = grup_ozet(up.R_net, up.exit_reason), grup_ozet(dn.R_net, dn.exit_reason)
    dR = delta(m)
    lo, hi, hafta_n, bos = hafta_boot(m)
    tlo, thi = islem_boot(m)
    rho, p = spearman(m.oi_change_4h, m.R_net)
    print("\n== PRIMARY TEST (önceden kayıtlı)")
    print("  OI_RISING      " + gs(gu))
    print("  OI_NOT_RISING  " + gs(gd))
    print(f"  delta_R {dR:+.4f} · hafta-kümeli %95 GA [{lo:+.4f}, {hi:+.4f}] ({hafta_n} hafta, "
          f"{N_BOOT} tekrar, boş grup {bos}) · işlem-düzeyi GA [{tlo:+.4f}, {thi:+.4f}]")
    print(f"  Spearman(oi_change_4h, R_net) rho {rho:+.3f} p {p:.3f}  (yalnız kontrol)")
    print("\n  Betimsel (karar DEĞİL, filtre önerisi DEĞİL):")
    for yon in ("long", "short"):
        g = m[m.side == yon]
        print(f"    {yon:<5s} n={len(g):>3d} ort R {g.R_net.mean() if len(g) else float('nan'):+.3f}")
    for c, g in m.groupby("symbol"):
        print(f"    {c:<5s} n={len(g):>3d} ort oi_change_4h {g.oi_change_4h.mean():+.4f} "
              f"ort R {g.R_net.mean():+.3f}")

    if not (dR > 0):
        hukum = "C"
    elif rho < 0 and p < 0.05:
        hukum = "C"
    elif lo > 0 and rho >= 0:
        hukum = "A"
    else:
        hukum = "B"

    kapanis(hukum)
    print()
    print("OI RISING:")
    print(f"n {gu['n']}\nmean R {gu['ort']:+.4f}\nPF {gu['pf']:.2f}\nWR %{gu['wr']:.1f}")
    print()
    print("OI NOT RISING:")
    print(f"n {gd['n']}\nmean R {gd['ort']:+.4f}\nPF {gd['pf']:.2f}\nWR %{gd['wr']:.1f}")
    print()
    print(f"DELTA R: {dR:+.4f}")
    print(f"95% week-cluster CI: [{lo:+.4f}, {hi:+.4f}]")
    print()
    print("SPEARMAN:")
    print(f"rho {rho:+.3f}")
    print(f"p {p:.3f}")
    print()
    print("HÜKÜM:")
    print(hukum + ("  (HISTORICAL / FORWARD-DATA CANDIDATE — production'a uygulanmaz)"
                   if hukum == "A" else ""))
    return hukum


if __name__ == "__main__":
    main()
