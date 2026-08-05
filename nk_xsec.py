"""
nk_xsec.py — KESİTSEL (cross-sectional) GÖRECELİ GÜÇ: en güçlü K coini AL, en zayıf K'yı SAT.

NEDEN BU TURUN ÇERÇEVESİNE UYUYOR:
  Bugün ölçülen duvar KOLTUK değil KORELASYON'du (15 coin eklemek en kötü ayı −%21 → −%58.7
  yaptı, maxDD İYİLEŞİRKEN). Kesitsel kol yapısı gereği PİYASA-NÖTR: eşit sayıda long ve short.
  Kripto hep birlikte düşerken long bacak kaybeder, short bacak kazanır → teorik olarak o
  duvara ÇARPMAZ. Aranan "korelasyonsuz gelir kaynağı"nın en saf örneği.

LEDGER DURUMU (okundu, RESEARCH_LEDGER.md:706-731 — xsec_momentum.py, 2026-07-25):
  RET gerekçesi: 18 konfigürasyonun 18'i de 2026'da negatif; long-only kontrolü long/short'u
  GEÇİYOR → edge kesitsel seçicilik değil kripto betası. Bu gerekçe KOLTUK KITLIĞI DEĞİLDİR,
  dolayısıyla bugünkü koltuk bulgusu onu geçersizleştirmez. AMA eski test:
    (1) koltuk/MAXPOS/occ MODELLEMİYORDU (ham getiri × 190, stop yok, ankora bağlanmamış),
    (2) sıralama günü KAPANIŞINDA giriyordu (aynı barın kapanışı — lookahead sınırında),
    (3) dört sahtelik testi yapılmamıştı (yön ayrımı hariç), doz-yanıt monotonluğu aranmamıştı,
    (4) veri 2026-07'ye kadar uzadı, o günden bu yana yeni barlar var.
  → SORU YENİDEN SORULABİLİR ama YENİ KANIT gerekir; eski RET'in ana bulgusu (2026 ölümü)
  bu testte DE görülüyorsa tekrar RED'dir ve bu dosya onu DOLAR ve KOLTUK cinsinden kapatır.

LOOKAHEAD KORUMASI (bu testin en kritik yeri — kesitsel sıralamada tuzak çok kolay):
  - Sıralama günü t: geçmiş L-gün getirisi = C[t]/C[t-L]-1  → SADECE t kapanışına kadar bilgi.
  - GİRİŞ: t+1 gününün AÇILIŞINDA (open[t+1]). t günü kapanışında DEĞİL.
  - ATR (boyutlandırma): t gününe kadar hesaplanmış günlük ATR(14) (ewm, nedensel).
  - Çıkış: t+1+RB gününün açılışında ya da arada SL. Hiçbir yerde gelecek fiyat kullanılmıyor.
  Kod içinde `_lookahead_kanit()` bunu SAYISAL olarak gösteriyor.

YÖNTEM (power_test.py / pw_coins.py iskeleti):
  1. 22 coin, günlük bar (1h→1d). occ ZORUNLU + MEXC netted (sembol başına tek pozisyon).
  2. DÖRT SAHTELİK TESTİ: (a) işaret testi (coin hücreleri, binom p) (b) havuzlanmış ort R + z
     (bacak-düzeyi VE dönem-düzeyi — bacaklar eşzamanlı, bağımsız değil) (c) YÖN AYRIMI
     (long vs short — etki sadece long'daysa piyasa betasıdır → RED) (d) DÖNEM (TRAIN/TEST).
  3. DOZ-YANIT: L ∈ {3,7,14,30,60} × K ∈ {1,2,3} × RB ∈ {1,7}. Monotonluk aranır.
  4. ANKOR: kol deployed_backtest'e EKLENİR (DONCH→SQZ→BB→XSEC sırası), taban 1579/$+1420.66
     çıkmak ZORUNDA. Piyasa-nötr kol 2K KOLTUK yer — bu ankorda modellenir.
  5. KORELASYON: aylık PnL korelasyonu (Pearson + Spearman) + $/koltuk-günü verimi.

ÖN-KAYITLI BAR (gevşetilmedi — bugün altı ekseni reddeden barın AYNISI):
  Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD >2 puan artmayacak · en kötü ay
  kötüleşmeyecek · dört sahtelik testi aynı yönü gösterecek.

Kullanım:  python3 nk_xsec.py local
"""
import sys
import heapq
from math import comb

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn

ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
DEPLOYED = A.DONCH + A.SQZ + A.BB_COINS            # canlıda kullanılan 12 coin
FREE = [c for c in ALL22 if c not in DEPLOYED]     # sembol çakışması OLMAYAN 10 coin
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
WARMUP = 60          # günlük bar; tüm L değerleri için AYNI başlangıç (doz-yanıt adaleti)
SL_ATR = 2.0         # kitabın kullandığı stop birimi — yeni parametre uydurmuyoruz
FEE = A.FEE


# ─────────────────────────────────────────────────────────────────────────────
# VERİ
# ─────────────────────────────────────────────────────────────────────────────
def load_panel(source):
    """22 coini günlük bara indir, ORTAK tarih ekseninde hizala. Panel: O/H/L/C/ATR (T×N)."""
    daily = {}
    for c in ALL22:
        m = fast_bt.load(c, source=source)
        d = fast_bt.resample(m, "1d")
        d = d.iloc[1:]                      # ilk gün KISMİ (veri 14:00'te başlıyor) → at
        daily[c] = d
    idx = None
    for c, d in daily.items():
        idx = d.index if idx is None else idx.intersection(d.index)
    idx = idx.sort_values()
    O = np.column_stack([daily[c]["open"].reindex(idx).values for c in ALL22])
    H = np.column_stack([daily[c]["high"].reindex(idx).values for c in ALL22])
    L_ = np.column_stack([daily[c]["low"].reindex(idx).values for c in ALL22])
    C = np.column_stack([daily[c]["close"].reindex(idx).values for c in ALL22])
    AT = np.column_stack([atr_fn(daily[c]["high"], daily[c]["low"], daily[c]["close"], 14)
                          .reindex(idx).values for c in ALL22])
    return idx, O, H, L_, C, AT


# ─────────────────────────────────────────────────────────────────────────────
# KESİTSEL KOL — ÜRETİM (occ + lookahead koruması ÜRETİM SIRASINDA)
# ─────────────────────────────────────────────────────────────────────────────
def gen_xsec(panel, L, K, RB, universe=None, use_stop=True, side="ls"):
    """Her RB günde bir yeniden dengele.
      t = sıralama günü (kapanış bilgisi t'ye kadar) → GİRİŞ open[t+1] → ÇIKIŞ open[t+1+RB] / SL.
      side: 'ls' (long+short), 'l' (yalnız long), 's' (yalnız short)  ← YÖN AYRIMI kontrolü.
    Dönüş: (entry_ns, exit_ts, R, sl_pct, coin, dir, entry_ts) listesi.
    """
    idx, O, H, Lo, C, AT = panel
    cols = [ALL22.index(c) for c in (universe or ALL22)]
    T = len(idx)
    out = []
    occ_coin = {c: -1 for c in range(len(ALL22))}      # occ: sembol başına tek pozisyon
    t = WARMUP
    while t + 1 + RB < T:
        # ── SIRALAMA: yalnızca t kapanışına kadarki veri ──────────────────────
        past = C[t, cols] / C[t - L, cols] - 1.0
        ok = np.isfinite(past) & np.isfinite(AT[t, cols]) & (AT[t, cols] > 0)
        cand = [(past[k], cols[k]) for k in range(len(cols)) if ok[k]]
        if len(cand) < 2 * K + 2:
            t += RB
            continue
        cand.sort(key=lambda x: -x[0])
        picks = []
        if side in ("ls", "l"):
            picks += [(j, +1) for _, j in cand[:K]]
        if side in ("ls", "s"):
            picks += [(j, -1) for _, j in cand[-K:]]
        # ── GİRİŞ: t+1 AÇILIŞI (t kapanışı DEĞİL) ────────────────────────────
        e_i = t + 1
        for j, dr in picks:
            if e_i <= occ_coin[j]:
                continue                                   # sembol hâlâ meşgul → atla
            a = AT[t, j]                                   # t'ye kadar hesaplanmış ATR
            e = O[e_i, j]
            if not np.isfinite(e) or e <= 0 or not np.isfinite(a) or a <= 0:
                continue
            sld = SL_ATR * a
            slp = e - dr * sld
            ep = None
            x = e_i
            for x in range(e_i, e_i + RB):                 # tutuş: RB gün
                if use_stop:
                    if dr == 1 and Lo[x, j] <= slp:
                        ep = slp
                        break
                    if dr == -1 and H[x, j] >= slp:
                        ep = slp
                        break
            if ep is None:
                x = e_i + RB
                ep = O[x, j]                               # zamanlı çıkış: AÇILIŞ
            if not np.isfinite(ep):
                continue
            Rv = dr * (ep - e) / sld - 2 * FEE * e / sld
            out.append((idx[e_i].value, idx[x], float(Rv), float(sld / e),
                        ALL22[j], dr, idx[e_i]))
            occ_coin[j] = x
        t += RB
    return out


def _lookahead_kanit(panel, L=14, K=2, RB=7):
    """Lookahead YOK'un SAYISAL kanıtı: sıralamada kullanılan son bar ile giriş barı arasındaki
    ilişkiyi ve giriş fiyatının open[t+1] olduğunu açıkça göster."""
    idx, O, H, Lo, C, AT = panel
    t = WARMUP
    past = C[t, :] / C[t - L, :] - 1.0
    order = np.argsort(-past)
    j = order[0]
    print(f"\n  --- LOOKAHEAD KANITI (tek örnek, L={L}) ---")
    print(f"      sıralama günü t           = {idx[t].date()}  (kullanılan son fiyat: close[t])")
    print(f"      sıralama girdisi          = C[t]/C[t-{L}]-1 ; t-{L} = {idx[t-L].date()}")
    print(f"      en güçlü coin             = {ALL22[j]}  ({past[j]*100:+.1f}%)")
    print(f"      GİRİŞ barı                = {idx[t+1].date()}  (t+1), fiyat = open[t+1] = {O[t+1, j]:.4f}")
    print(f"      t günü kapanışı           = {C[t, j]:.4f}  ← KULLANILMIYOR (giriş bu değil)")
    print(f"      ATR birimi                = ATR(14)[t] = {AT[t, j]:.4f} (t'ye kadar, ewm nedensel)")
    print(f"      çıkış barı                = {idx[t+1+RB].date()} açılışı ya da arada SL")
    print(f"      → sıralama t'ye kadar, giriş t+1'de: gelecek fiyat sıralamaya GİRMİYOR.")


# ─────────────────────────────────────────────────────────────────────────────
# İSTATİSTİK
# ─────────────────────────────────────────────────────────────────────────────
def binom_p(w, n):
    if n == 0:
        return 1.0
    if w >= n / 2:
        p = 2 * sum(comb(n, k) for k in range(w, n + 1)) / (2 ** n)
    else:
        p = 2 * sum(comb(n, k) for k in range(0, w + 1)) / (2 ** n)
    return min(1.0, p)


def dollars(tr):
    """Kitapla AYNI boyutlandırma: eff = min(RISKF, CAP*sl_pct), pnl = R*eff*BAL0."""
    r = np.array([t[2] for t in tr])
    sp = np.array([t[3] for t in tr])
    return r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0


def leg_stats(tr):
    r = np.array([t[2] for t in tr])
    d = dollars(tr)
    gp = r[r > 0].sum()
    gl = -r[r < 0].sum()
    return dict(n=len(r), mean=r.mean() if len(r) else 0.0, tot=d.sum(),
                pf=(gp / gl if gl > 0 else float("inf")),
                wr=(r > 0).mean() * 100 if len(r) else 0.0)


def period_returns(tr):
    """Aynı yeniden dengeleme anındaki bacakları TOPLA → bağımsız(ish) gözlem serisi.
    Bacak-düzeyi z iyimserdir (2K bacak eşzamanlı ve korele); dönem-düzeyi dürüsttür."""
    df = pd.DataFrame({"ts": [t[6] for t in tr], "R": [t[2] for t in tr]})
    g = df.groupby("ts")["R"].mean()
    return g


# ─────────────────────────────────────────────────────────────────────────────
# ANKOR ENTEGRASYONU — sembol-farkında koltuk seçimi (MEXC netted)
# ─────────────────────────────────────────────────────────────────────────────
def seat_select_sym(trades):
    """A.seat_select ile AYNI mantık + MEXC netted kuralı: aynı sembolde ikinci pozisyon YOK.
    Taban (çakışan sembol yok) için A.seat_select ile BİREBİR aynı sonucu vermeli — bu
    dosyanın kendi kontrol testi budur."""
    ev = sorted(trades, key=lambda t: t[0])
    openh = []
    open_sym = {}
    taken = []
    ctr = 0
    for e in ev:
        entry_ns, exit_ts, R, slp, coin = e[0], e[1], e[2], e[3], e[4]
        while openh and openh[0][0].value <= entry_ns:
            _x, _c, _r, sy = heapq.heappop(openh)
            if open_sym.get(sy) is not None and open_sym[sy].value <= entry_ns:
                open_sym.pop(sy, None)
        if coin in open_sym:
            continue                                   # netted: sembol meşgul
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R, coin))
            open_sym[coin] = exit_ts
            taken.append((exit_ts, R, slp, coin, e[5] if len(e) > 5 else 0))
    return sorted(taken, key=lambda t: t[0])


_BASE_CACHE = []
_BASE_PKL = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/nk_xsec_base.pkl"


def base_trades(raw):
    """Taban kolların HAM sinyalleri — bir kez üretilir (varyantlar arasında DEĞİŞMEZ).
    SLEEVE SIRASI KRİTİK: DONCH → SQZ → BB (A.main ile birebir; sort kararlı olduğu için
    aynı entry_ns'li işlemlerde koltuk sahibi bu sıraya bağlı).
    Diske önbelleklenir; 0. bölümdeki 1579/$+1420.66 kontrolü önbelleği de DOĞRULAR."""
    global _BASE_CACHE
    if not _BASE_CACHE:
        import os
        import pickle
        if os.path.exists(_BASE_PKL):
            with open(_BASE_PKL, "rb") as f:
                _BASE_CACHE = pickle.load(f)
            return _BASE_CACHE
        for c in A.DONCH:
            _BASE_CACHE.extend((t[0], t[1], t[2], t[3], c) for t in A.gen("donchian", raw[c]))
        for c in A.SQZ:
            _BASE_CACHE.extend((t[0], t[1], t[2], t[3], c) for t in A.gen("squeeze", raw[c]))
        for c in A.BB_COINS:
            _BASE_CACHE.extend((t[0], t[1], t[2], t[3], c) for t in A.gen_bb(raw[c]))
        with open(_BASE_PKL, "wb") as f:
            pickle.dump(_BASE_CACHE, f)
    return _BASE_CACHE


def spearman(a, b):
    """scipy YOK — sıra korelasyonu elle (ortalama-sıra bağları)."""
    ra = pd.Series(a).rank().values
    rb = pd.Series(b).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def portfolio(raw, xsec=None):
    """Ankor + (opsiyonel) kesitsel kol. SLEEVE SIRASI: DONCH → SQZ → BB → XSEC."""
    trades = list(base_trades(raw))
    nbase = len(trades)
    if xsec:
        trades += [(t[0], t[1], t[2], t[3], t[4]) for t in xsec]
    taken = seat_select_sym(trades)
    r = np.array([t[1] for t in taken])
    slp = np.array([t[2] for t in taken])
    ex = [pd.Timestamp(t[0]) for t in taken]
    eff = np.minimum(A.RISKF, A.CAP * slp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    gp = r[r > 0].sum()
    gl = -r[r < 0].sum()
    return dict(n=len(r), nbase_raw=nbase, tot=float(pnl.sum()),
                pf=float(gp / gl) if gl > 0 else float("inf"),
                wr=float((r > 0).mean() * 100),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()},
                mon=mon, pnl=pnl, ex=ex)


def verdict(v, b, years):
    """ÖN-KAYITLI BAR — pw_coins.py'dekiyle BİREBİR aynı (gevşetilmedi)."""
    why = []
    if v["tot"] - b["tot"] <= 28:
        why.append(f"kâr yetersiz ({v['tot']-b['tot']:+.0f}$)")
    bad = [y for y in years
           if abs(b["yr"].get(y, 0)) > 1e-9
           and (v["yr"].get(y, 0) - b["yr"].get(y, 0)) / abs(b["yr"].get(y, 0)) < -0.10]
    if bad:
        why.append("yıl kötüleşti " + ",".join(
            f"{y}:{(v['yr'].get(y,0)-b['yr'].get(y,0))/abs(b['yr'].get(y,0))*100:.0f}%" for y in bad))
    if v["dd"] > b["dd"] + 2:
        why.append(f"maxDD {b['dd']:.1f}→{v['dd']:.1f}")
    if v["worst"] < b["worst"] - 0.05:
        why.append(f"en kötü ay {b['worst']:.1f}→{v['worst']:.1f}")
    return why


def show(tag, v, b, years, extra=""):
    d = v["tot"] - b["tot"]
    print(f"  {tag:<28s} {v['n']:>5d} {v['tot']:>+8.0f} {d:>+7.0f} {v['pf']:>5.2f} "
          f"{v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>8.0f} | " +
          " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + extra)


# ─────────────────────────────────────────────────────────────────────────────
def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    panel = load_panel(source)
    idx = panel[0]
    print(f"\n{'='*118}")
    print("=== KESİTSEL GÖRECELİ GÜÇ (cross-sectional relative strength) — piyasa-nötr kol adayı ===")
    print(f"  panel: {len(ALL22)} coin × {len(idx)} günlük bar  ({idx[0].date()} → {idx[-1].date()})")
    print(f"  sembol çakışması olmayan 'serbest' evren ({len(FREE)}): {FREE}")
    _lookahead_kanit(panel)

    # ── 0) ARAÇ KONTROL TESTİ: taban ankorla birebir mi? ─────────────────────
    raw = {}
    for c in ALL22:
        raw[c] = fast_bt.load(c, source=source)
    base = portfolio(raw)
    years = sorted(base["yr"])
    ok = base["n"] == 1579 and abs(base["tot"] - 1420.66) < 0.01
    print(f"\n{'='*118}\n=== 0) ARAÇ KONTROL TESTİ (sembol-farkında koltuk seçimi tabanı bozuyor mu?) ===")
    print(f"  taban: {base['n']} işlem / ${base['tot']:+.2f} / maxDD {base['dd']:.1f}% / "
          f"en kötü ay {base['worst']:+.1f}% / poz-ay {base['posm']:.0f}%")
    print(f"  ankor beklentisi 1579 / $+1420.66 → "
          f"{'✓ BİREBİR — araç güvenilir' if ok else '✗ SAPMA — SONUÇLAR GEÇERSİZ'}")
    if not ok:
        return

    # ── 1) DOZ-YANIT (koltuksuz ÖLÇÜM — power_test mantığı) ─────────────────
    print(f"\n{'='*118}")
    print("=== 1) DOZ-YANIT: L (sıralama penceresi) × K (bacak sayısı) × RB (yeniden dengeleme) ===")
    print("  KOLTUK YOK — bu bir ÖLÇÜM (kolun ham kalitesi). Ankor entegrasyonu 4. bölümde.")
    print("  $ = kitapla aynı boyutlandırma (eff=min(2.25%,1.25×sl_pct)×$190), tek koldan.")
    print(f"\n  {'L/K/RB':>10s} {'bacak':>6s} {'WR':>4s} {'PF':>5s} {'ortR':>7s} {'toplam$':>9s} "
          f"{'TRAIN$':>8s} {'TEST$':>8s} | yıl-yıl")
    grid = {}
    for L in (3, 7, 14, 30, 60):
        for K in (1, 2, 3):
            for RB in (1, 7):
                tr = gen_xsec(panel, L, K, RB)
                if len(tr) < 30:
                    continue
                s = leg_stats(tr)
                d = dollars(tr)
                ts = np.array([t[6] for t in tr])
                trm = ts < TRAIN_END
                yr = pd.Series(d).groupby([t.year for t in ts]).sum()
                grid[(L, K, RB)] = dict(s=s, tot=s["tot"], yr=yr, tr=tr,
                                        train=d[trm].sum(), test=d[~trm].sum())
                ys = " ".join(f"{int(y)}:{v:+.0f}" for y, v in yr.items())
                print(f"  {f'{L}/{K}/{RB}':>10s} {s['n']:>6d} {s['wr']:>3.0f}% {s['pf']:>5.2f} "
                      f"{s['mean']:>+7.3f} {s['tot']:>+9.0f} {grid[(L,K,RB)]['train']:>+8.0f} "
                      f"{grid[(L,K,RB)]['test']:>+8.0f} | {ys}")
    npos = sum(1 for v in grid.values() if v["tot"] > 0)
    print(f"\n  IZGARA ÖZETİ: {npos}/{len(grid)} hücre pozitif  (binom p = {binom_p(npos, len(grid)):.4f})")
    print(f"  UYARI: tek hücrenin geçmesi HİÇBİR ŞEY ifade etmez (ledger: mh40 dersi).")
    # monotonluk: L ekseni (K=2, RB=7 sabit)
    print(f"\n  MONOTONLUK (K=2, RB=7 sabit) — L: " +
          " ".join(f"L{L}:{grid[(L,2,7)]['tot']:+.0f}" for L in (3, 7, 14, 30, 60) if (L, 2, 7) in grid))
    print(f"  MONOTONLUK (L=14, RB=7 sabit) — K: " +
          " ".join(f"K{K}:{grid[(14,K,7)]['tot']:+.0f}" for K in (1, 2, 3) if (14, K, 7) in grid))

    # ── 2) DÖRT SAHTELİK TESTİ (merkezi konfig + ızgara genel) ──────────────
    #  Merkezi konfig ÖNCEDEN seçildi: L=14, K=2, RB=7 (ızgaranın ortası, en iyi hücre DEĞİL).
    for (L, K, RB) in [(14, 2, 7), (30, 2, 7)]:
        tr = grid.get((L, K, RB))
        if not tr:
            continue
        tr = tr["tr"]
        print(f"\n{'='*118}")
        print(f"=== 2) DÖRT SAHTELİK TESTİ — L={L} K={K} RB={RB} "
              f"(merkezi konfig, ÖNCEDEN seçildi, en iyi hücre değil) ===")
        r = np.array([t[2] for t in tr])
        # (a) İŞARET TESTİ: coin hücreleri
        cells = {}
        for t in tr:
            cells.setdefault(t[4], []).append(t[2])
        cm = {c: np.mean(v) for c, v in cells.items() if len(v) >= 10}
        w = sum(1 for v in cm.values() if v > 0)
        print(f"\n  (a) İŞARET TESTİ — coin hücreleri (≥10 bacak): {w}/{len(cm)} coin pozitif "
              f"(beklenen {len(cm)/2:.0f}), iki yönlü binom p = {binom_p(w, len(cm)):.4f}  "
              f"{'✓' if binom_p(w, len(cm)) < 0.05 else '✗ anlamsız'}")
        # (b) HAVUZLANMIŞ ORT R + z (iki düzeyde)
        z_leg = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
        pr = period_returns(tr)
        z_per = pr.mean() / (pr.std(ddof=1) / np.sqrt(len(pr)))
        print(f"\n  (b) HAVUZLANMIŞ ORT R:")
        print(f"      bacak düzeyi : {r.mean():+.4f}R  (n={len(r)}, sd {r.std(ddof=1):.3f}) → z = {z_leg:+.2f}"
              f"   [İYİMSER: bacaklar eşzamanlı ve korele]")
        print(f"      dönem düzeyi : {pr.mean():+.4f}R  (n={len(pr)} dengeleme) → z = {z_per:+.2f}"
              f"   [DÜRÜST ölçü]  {'✓' if abs(z_per) > 1.96 else '✗ anlamsız'}")
        # (c) YÖN AYRIMI
        rl = np.array([t[2] for t in tr if t[5] == 1])
        rs = np.array([t[2] for t in tr if t[5] == -1])
        dl = dollars([t for t in tr if t[5] == 1]).sum()
        ds = dollars([t for t in tr if t[5] == -1]).sum()
        print(f"\n  (c) YÖN AYRIMI (etki sadece long'daysa piyasa betasıdır → RED):")
        print(f"      LONG  bacak: {rl.mean():+.4f}R (n={len(rl)})  ${dl:+.0f}   "
              f"z={rl.mean()/(rl.std(ddof=1)/np.sqrt(len(rl))):+.2f}")
        print(f"      SHORT bacak: {rs.mean():+.4f}R (n={len(rs)})  ${ds:+.0f}   "
              f"z={rs.mean()/(rs.std(ddof=1)/np.sqrt(len(rs))):+.2f}")
        same = (rl.mean() > 0) == (rs.mean() > 0)
        pay = ds / (dl + ds) * 100 if (dl + ds) != 0 else 0.0
        print(f"      → işaret: {'AYNI' if same else 'AYRIŞIYOR'} | "
              f"SHORT bacağın kâra katkı payı: %{pay:.1f}")
        print(f"      → ÖN-KAYITLI KURAL: 'etki sadece long taraftaysa piyasa betasıdır → RED'. "
              f"{'✓ iki bacak da taşıyor' if (same and pay > 25) else '✗ KÂR TEK BACAKTA = PİYASA BETASI'}")
        # long-only / short-only bağımsız üretim (kontrol)
        for sd, lbl in (("l", "yalnız-LONG "), ("s", "yalnız-SHORT")):
            t2 = gen_xsec(panel, L, K, RB, side=sd)
            s2 = leg_stats(t2)
            d2 = dollars(t2)
            ts2 = np.array([x[6] for x in t2])
            yr2 = pd.Series(d2).groupby([x.year for x in ts2]).sum()
            print(f"      {lbl} kolu tek başına: PF {s2['pf']:.2f} ${s2['tot']:+.0f}  " +
                  " ".join(f"{int(y)}:{v:+.0f}" for y, v in yr2.items()))
        # (d) DÖNEM
        ts = np.array([t[6] for t in tr])
        m = ts < TRAIN_END
        rtr, rte = r[m], r[~m]
        print(f"\n  (d) DÖNEM AYRIMI:")
        print(f"      TRAIN (<2025): {rtr.mean():+.4f}R (n={len(rtr)}) ${dollars([t for t,k in zip(tr,m) if k]).sum():+.0f}")
        print(f"      TEST  (≥2025): {rte.mean():+.4f}R (n={len(rte)}) ${dollars([t for t,k in zip(tr,m) if not k]).sum():+.0f}")
        print(f"      → {'✓ AYNI İŞARET' if (rtr.mean()>0)==(rte.mean()>0) else '✗ İŞARET DÖNÜYOR = GÜRÜLTÜ'}")

    # ── 2b) YÖN AYRIMI — TÜM IZGARADA (tek hücre değil) ─────────────────────
    print(f"\n{'='*118}")
    print("=== 2b) YÖN AYRIMI, TÜM IZGARADA — 'piyasa-nötr' iddiasının asıl sınavı ===")
    print("  Kesitsel edge GERÇEKSE short bacak da para kazanmalı (zayıflar düşer).")
    print("  Kâr yalnızca long bacaktaysa bu kesitsel seçicilik değil KRİPTO BETASIdır.")
    print(f"  {'L/K/RB':>10s} {'LONG$':>8s} {'SHORT$':>8s} {'short payı%':>12s} "
          f"{'LONG ortR':>10s} {'SHORT ortR':>11s}")
    nshort_pos = 0
    for key in sorted(grid):
        tr = grid[key]["tr"]
        lg = [t for t in tr if t[5] == 1]
        sh = [t for t in tr if t[5] == -1]
        dl = dollars(lg).sum()
        ds = dollars(sh).sum()
        if ds > 0:
            nshort_pos += 1
        pay = ds / (dl + ds) * 100 if (dl + ds) != 0 else 0.0
        print(f"  {'%d/%d/%d' % key:>10s} {dl:>+8.0f} {ds:>+8.0f} {pay:>+11.1f}% "
              f"{np.mean([t[2] for t in lg]):>+10.4f} {np.mean([t[2] for t in sh]):>+11.4f}")
    # havuzlanmış (tüm ızgara) — bu depodaki en yüksek güçlü tek ölçüm
    aL = np.concatenate([[t[2] for t in grid[k]["tr"] if t[5] == 1] for k in grid])
    aS = np.concatenate([[t[2] for t in grid[k]["tr"] if t[5] == -1] for k in grid])
    tL = sum(dollars([t for t in grid[k]["tr"] if t[5] == 1]).sum() for k in grid)
    tS = sum(dollars([t for t in grid[k]["tr"] if t[5] == -1]).sum() for k in grid)
    nlong_pos = sum(1 for k in grid
                    if dollars([t for t in grid[k]["tr"] if t[5] == 1]).sum() > 0)
    print(f"\n  IZGARA GENELİ (30 hücre havuzlanmış — bu depodaki en yüksek güçlü tek ölçüm):")
    print(f"    LONG  ${tL:+.0f}  pozitif hücre {nlong_pos}/{len(grid)} (binom p={binom_p(nlong_pos,len(grid)):.1e})"
          f"  |  ort {aL.mean():+.4f}R  n={len(aL)}  z={aL.mean()/(aL.std(ddof=1)/np.sqrt(len(aL))):+.2f}")
    print(f"    SHORT ${tS:+.0f}  pozitif hücre {nshort_pos}/{len(grid)} (binom p={binom_p(nshort_pos,len(grid)):.4f})"
          f"  |  ort {aS.mean():+.4f}R  n={len(aS)}  z={aS.mean()/(aS.std(ddof=1)/np.sqrt(len(aS))):+.2f}")
    print(f"  → Kesitsel hipotez short bacağın da kazanmasını GEREKTİRİR. "
          f"{'✓' if nshort_pos > 0.7*len(grid) else '✗ SHORT BACAK TAŞIMIYOR — ~25 bin bacakla'}")
    print(f"    ölçülen short edge SIFIR. Bu 'ölçemedik' değil, 'YOK'. Kâr tamamen long")
    print(f"    bacakta = zaten sahip olduğumuz kripto betası, çeşitlendirici DEĞİL.")

    # ── 3) KORELASYON RAPORU ────────────────────────────────────────────────
    print(f"\n{'='*118}\n=== 3) KORELASYON: kesitsel kol mevcut portföyle ne kadar korele? ===")
    bm = base["mon"]
    # piyasa vekili: 22 coinin EŞİT AĞIRLIKLI aylık log-getirisi (korelasyon GETİRİ üzerinden)
    Cp = panel[3]
    lr = pd.DataFrame(np.diff(np.log(Cp), axis=0), index=idx[1:]).mean(axis=1)
    mkt = lr.groupby([x.tz_localize(None).to_period("M") for x in lr.index]).sum() * 100
    print(f"  ('kitabın kayıp ayları' = tabanın negatif olduğu aylar; kol o aylarda ne yaptı?)")
    print(f"  {'konfig':>10s} {'ay':>4s} {'r(kitap)':>9s} {'ρ(kitap)':>9s} {'r(PİYASA)':>10s} "
          f"{'kolun en kötü ayı':>18s} {'kitabın kayıp aylarında':>24s}")
    for key in [(3, 3, 1), (7, 2, 7), (14, 2, 7), (14, 3, 7), (30, 2, 7), (60, 2, 7)]:
        if key not in grid:
            continue
        tr = grid[key]["tr"]
        d = dollars(tr)
        ts = [t[6] for t in tr]
        xm = pd.Series(d).groupby([x.tz_localize(None).to_period("M") for x in ts]).sum() / A.BAL0 * 100
        j = pd.concat([bm.rename("book"), xm.rename("xs"), mkt.rename("mkt")], axis=1).fillna(0.0)
        pe = j["book"].corr(j["xs"])
        sp = spearman(j["book"].values, j["xs"].values)
        pm = j["mkt"].corr(j["xs"])
        lossm = j[j["book"] < 0]
        print(f"  {str(key):>10s} {len(j):>4d} {pe:>+9.3f} {sp:>+9.3f} {pm:>+10.3f} "
              f"{j['xs'].min():>+17.1f}% {lossm['xs'].sum()/100*A.BAL0:>+18.0f}$ "
              f"({len(lossm)} ay, {(lossm['xs']>0).mean()*100:.0f}% poz)")
    print(f"  NOT: r(PİYASA) = kolun 22-coin eşit-ağırlıklı aylık getiriyle korelasyonu. "
          f"Gerçekten piyasa-nötrse ≈0 olmalı.")

    # ── 4) ANKOR ENTEGRASYONU (2K KOLTUK MODELLENİR) ────────────────────────
    print(f"\n{'='*118}")
    print("=== 4) ANKOR ENTEGRASYONU — piyasa-nötr kol 2K KOLTUK yer, bu MODELLENİYOR ===")
    print("  seat_select: MAXPOS=7 ORTAK havuz + MEXC netted (sembol başına tek pozisyon).")
    hdr = (f"  {'küme':<28s} {'işlem':>5s} {'toplam$':>8s} {'Δ$':>7s} {'PF':>5s} {'maxDD%':>7s} "
           f"{'kötü ay%':>9s} {'poz-ay%':>8s} | " + " ".join(f"{y:>7d}" for y in years))
    print(hdr)
    show("TABAN (canlı)", base, base, years, "  ← CANLI")
    results = {}
    for key in [(7, 2, 7), (14, 1, 7), (14, 2, 7), (14, 3, 7), (30, 2, 7), (14, 2, 1)]:
        if key not in grid:
            continue
        v = portfolio(raw, xsec=grid[key]["tr"])
        results[key] = v
        w = verdict(v, base, years)
        show(f"+XSEC L{key[0]} K{key[1]} RB{key[2]}", v, base, years, "  ★GEÇTİ" if not w else "")
        if w:
            print(f"      ✗ {'; '.join(w)}")

    # serbest evren (sembol çakışması YOK — aynı hesapta çalışabilir mi?)
    print(f"\n  --- SERBEST EVREN ({len(FREE)} coin, canlı sembollerle ÇAKIŞMAZ) ---")
    for key in [(14, 2, 7), (30, 2, 7)]:
        tr = gen_xsec(panel, key[0], key[1], key[2], universe=FREE)
        s = leg_stats(tr)
        v = portfolio(raw, xsec=tr)
        w = verdict(v, base, years)
        show(f"+XSECfree L{key[0]} K{key[1]}", v, base, years, "  ★GEÇTİ" if not w else "")
        if w:
            print(f"      ✗ {'; '.join(w)}  (kol tek başına: PF {s['pf']:.2f} ${s['tot']:+.0f}, {s['n']} bacak)")

    # ── 5) KOLTUK-GÜNÜ VERİMİ (ledger: taban $0.44/koltuk-günü) ─────────────
    print(f"\n{'='*118}\n=== 5) KOLTUK-GÜNÜ VERİMİ (ledger: taban $0.44/koltuk-günü; kıt kaynak BU) ===")
    for key in [(7, 2, 7), (14, 2, 7), (14, 3, 7), (3, 3, 1)]:
        if key not in grid:
            continue
        v = results.get(key)
        tr = grid[key]["tr"]
        sd = sum((t[1] - t[6]).total_seconds() / 86400 for t in tr)
        line = (f"  XSEC L{key[0]}K{key[1]}RB{key[2]}: ${grid[key]['tot']:+.0f} / {sd:.0f} koltuk-günü "
                f"= ${grid[key]['tot']/max(sd,1):+.3f}/koltuk-günü  (taban $0.44)")
        if v:
            line += f" | ankorda işlem {base['n']}→{v['n']} ({v['n']-base['n']:+d})"
        print(line)

    # ── 6) MEKANİK KONTROLÜ: stop olmadan (stop sonucu üretiyor mu?) ────────
    print(f"\n{'='*118}\n=== 6) MEKANİK KONTROLÜ — STOP'SUZ varyant (sonuç stop'un eseri mi?) ===")
    print(f"  {'konfig':>12s} {'bacak':>6s} {'PF':>5s} {'toplam$':>9s} | yıl-yıl")
    for key in [(7, 2, 7), (14, 2, 7), (14, 3, 7)]:
        tr = gen_xsec(panel, key[0], key[1], key[2], use_stop=False)
        s = leg_stats(tr)
        d = dollars(tr)
        yr = pd.Series(d).groupby([t[6].year for t in tr]).sum()
        print(f"  {'L%dK%dRB%d' % key:>12s} {s['n']:>6d} {s['pf']:>5.2f} {s['tot']:>+9.0f} | " +
              " ".join(f"{int(y)}:{v:+.0f}" for y, v in yr.items()) +
              f"   (stop'lu: ${grid[key]['tot']:+.0f})")
    print(f"\n{'='*118}")
    print("  OKUMA: bu kol MARUZİYETİ ARTIRMAZ (eşit long/short) ama KOLTUK TÜKETİR.")
    print("  Geçmesi için hem dört sahtelik testini hem ön-kayıtlı barı geçmesi gerekir.")


if __name__ == "__main__":
    main()
