"""
fvg_arsiv_denetim.py — ARSIV DENETIMI olcumu: "Fair Value Gap / Imbalance" ailesi.
URETIM KODUNA DOKUNMAZ. Sadece okur + olcer.

NEDEN BU OLCUM:
  Aile 2026-08-12'de `kapali_kollar.py` ile ORTAK 7 KOLTUK altinda olculdu ve
  reddedildi (DURUM.md:375 -> fvg n=7672, kendi ortR +0.0091, PF 1.02,
  portfoy D$ -245, maxDD 125.4, en kotu ay -120.2).
  O olcum harness'inda IKI SAPMA var:
   (1) win=120 bar penceresi ile EMA200 -> ewm(span=200, adjust=False) her
       cagrida yeniden tohumlanir; 120 barda tohum agirligi (1-2/201)^120 = %30.
       Yani "EMA200 trend filtresi" aslinda %30 oraninda 120-bar-onceki tek
       kapanistan olusuyordu. CANLI 250 bar veriyor (main.py:528) -> tohum %8.
   (2) Giris cl[i] (piyasa emri, mum kapanisi) modellendi. Ama CANLI post-only
       limit'i sinyalin ep SEVIYESINE koyar (execution.py:592-636, structure-
       based -> fallback YOK). Ailenin tum cazibesi bu: giris kaymasi = 0.
       kapali_kollar hem yanlis fiyattan girer hem sld'yi close'dan yeniden
       hesaplar -> stratejinin RR 2.5'i bozulur.

BU DOSYA NE OLCER:
  A) REPLIKASYON: kapali_kollar.py birebir (win=120, giris=close) -> arsiv sayisi
     tutuyor mu?
  B) SADIK: win=1000 (EMA200 tohumu ihmal edilebilir) + limit-at-level giris
     + post-only gecerlilik kapisi + dolum kapisi. R stratejinin kendi sl/tp'sinden.
  K1: stop mesafesi dagilimi -> kayma R bedeli (giris MAKER=0, cikis market)
  K2: LONG / SHORT bacaklari AYRI
  K5: TRAIN(<2025-01-01) / TEST(>=2025-01-01)

Kullanim:  python3 fvg_arsiv_denetim.py [local]
"""
from __future__ import annotations
import sys, time
import numpy as np, pandas as pd

sys.path.insert(0, "/home/user/Bot2")
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn
from strategies.fvg import FvgStrategy

KAYMA = 15.85 / 1e4                 # olculmus GIRIS kaymasi (donchian, n=54)
SPLIT = pd.Timestamp("2025-01-01")
FEE = DB.FEE
MAXHOLD = 48                        # kapali_kollar.py ile ayni
COINS = DB.DONCH + DB.SQZ + DB.BB_COINS


def _naive(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tz is not None else ts


def kol_uret(m, win, giris_mod, fill_bars=1):
    """FVG sinyalleri. giris_mod: 'close' (arsiv) | 'level' (canli-sadik).

    'level': post-only gecerlilik -> long icin close[i] > ep olmali (aksi halde
    limit marketable, post-only REDDEDILIR -> canli atlar). Dolum -> sonraki
    fill_bars bar icinde fiyat ep'ye deger mi. Cikis taramasi dolum barindan
    baslar; ayni barda hem SL hem TP varsa SL sayilir (muhafazakar).
    """
    d = m
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    idx = d.index; n = len(cl)
    s = FvgStrategy()
    out = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        try:
            sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a))
        except Exception:
            continue
        dd = getattr(sg, "direction", 0)
        if dd == 0 or i <= occ:
            continue
        slp = float(getattr(sg, "sl_price", 0.0) or 0.0)
        tpp = float(getattr(sg, "tp_price", 0.0) or 0.0)
        epv = float(getattr(sg, "entry_price", 0.0) or 0.0)
        if slp <= 0 or tpp <= 0:
            continue

        if giris_mod == "close":
            e = cl[i]; start = i + 1
        else:
            if epv <= 0:
                continue
            # post-only gecerlilik kapisi
            if dd == 1 and not (cl[i] > epv):
                continue
            if dd == -1 and not (cl[i] < epv):
                continue
            f = None
            for k in range(i + 1, min(i + 1 + fill_bars, n)):
                if (dd == 1 and lo[k] <= epv) or (dd == -1 and hi[k] >= epv):
                    f = k; break
            if f is None:
                continue
            e = epv; start = f

        sld = abs(e - slp)
        if sld <= 0 or sld / e > 0.20:
            continue
        ep_out = None; j = start; cikis = "sure"
        for j in range(start, min(start + MAXHOLD, n)):
            if dd == 1:
                if lo[j] <= slp: ep_out = slp; cikis = "sl"; break
                if hi[j] >= tpp: ep_out = tpp; cikis = "tp"; break
            else:
                if hi[j] >= slp: ep_out = slp; cikis = "sl"; break
                if lo[j] <= tpp: ep_out = tpp; cikis = "tp"; break
        if ep_out is None:
            j = min(start + MAXHOLD, n - 1); ep_out = cl[j]; cikis = "sure"
        # ucret: maker giris (0) + taker cikis (1bp) 'level'; iki taraf taker 'close'
        ucret = (2 * FEE if giris_mod == "close" else FEE) * e / sld
        R = dd * (ep_out - e) / sld - ucret
        out.append(dict(giris=_naive(idx[i]), cikis_t=_naive(idx[j]), R=R,
                        sp=sld / e, yon=dd, cikis=cikis))
        occ = j
    return out


def ozet(tr, ad, kayma_mod):
    """kayma_mod: 'giris' (piyasa emri) | 'cikis' (maker giris, sadece SL/sure kayar) | 'yok'"""
    if not tr:
        print(f"  {ad:<34s} sinyal YOK"); return None
    R = np.array([t["R"] for t in tr]); sp = np.array([t["sp"] for t in tr])
    if kayma_mod == "giris":
        R = R - KAYMA / sp
    elif kayma_mod == "cikis":
        mask = np.array([t["cikis"] != "tp" for t in tr])
        R = R - np.where(mask, KAYMA / sp, 0.0)
    z = R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 1 else 0.0
    te = np.array([t["giris"] >= SPLIT for t in tr])
    Rte = R[te]
    zte = (Rte.mean() / Rte.std(ddof=1) * np.sqrt(len(Rte))) if len(Rte) > 1 else 0.0
    print(f"  {ad:<34s} n={len(R):>5d}  ortR {R.mean():+.4f}  z {z:+5.2f}  "
          f"stop%med {np.median(sp)*100:5.2f}  kaymaR {KAYMA/np.median(sp):.4f}  "
          f"| TEST n={te.sum():>5d} ortR {Rte.mean() if te.sum() else 0:+.4f} z {zte:+5.2f}")
    return dict(R=R, sp=sp, tr=tr)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    t0 = time.time()

    # ── ANKOR ──
    ham = []
    for c in DB.DONCH:
        ham += [(t[0], t[1].value, t[2], t[3]) for t in DB.gen("donchian", fast_bt.load(c, source=src))]
    for c in DB.SQZ:
        ham += [(t[0], t[1].value, t[2], t[3]) for t in DB.gen("squeeze", fast_bt.load(c, source=src))]
    for c in DB.BB_COINS:
        ham += [(t[0], t[1].value, t[2], t[3]) for t in DB.gen_bb(fast_bt.load(c, source=src))]
    import heapq
    ev = sorted(ham, key=lambda z: z[0]); oh = []; ctr = 0; al = []
    for e, x, R, slp in ev:
        while oh and oh[0][0] <= e: heapq.heappop(oh)
        if len(oh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr)); al.append((x, R, slp))
    print(f"\n{'='*118}\n=== FVG ARSIV DENETIMI ===")
    print(f"  ANKOR: {len(al)} islem  {'✓ 1579 BIREBIR' if len(al)==1579 else '✗ SAPMA — kiyas gecersiz'}")
    if len(al) != 1579:
        sys.exit(1)

    dfs = {c: fast_bt.load(c, source=src) for c in COINS}

    for etiket, win, mod in (("A) ARSIV REPLIKASYON (win=120, giris=close)", 120, "close"),
                             ("B) SADIK (win=1000 EMA200, limit-at-level)", 1000, "level")):
        tr = []
        for c in COINS:
            tr += kol_uret(dfs[c], win, mod)
        print(f"\n  {etiket}   [{time.time()-t0:.0f}s]")
        km = "giris" if mod == "close" else "cikis"
        ozet(tr, "TUM (kaymasiz)", "yok")
        ozet(tr, f"TUM (kayma: {km})", km)
        ozet([t for t in tr if t["yon"] == 1], f"LONG  (kayma: {km})", km)
        ozet([t for t in tr if t["yon"] == -1], f"SHORT (kayma: {km})", km)
        if tr:
            sp = np.array([t["sp"] for t in tr])
            ck = pd.Series([t["cikis"] for t in tr]).value_counts(normalize=True)
            print(f"    stop%  p25 {np.percentile(sp,25)*100:.2f}  med {np.median(sp)*100:.2f}  "
                  f"p75 {np.percentile(sp,75)*100:.2f}   cikis: "
                  + " ".join(f"{k}%{v*100:.0f}" for k, v in ck.items()))
    print(f"\n  kitap referansi: kaymali ortR +0.1764 · kaymasiz +0.2373 · donchian stop %4.96")
    print(f"{'='*118}\n  toplam {time.time()-t0:.0f}s")




# ── EK OLCUM: BTC (orijinal iddianin coini, deploy 12'sinde YOK) + IFVG kardesi ──
def ek():
    """py fvg_arsiv_denetim.py ek local"""
    import strategies.ifvg as IF
    src = sys.argv[2] if len(sys.argv) > 2 else "local"
    print(f"\n{'='*118}\n=== EK: BTC + IFVG ===")

    def uret(m, win, mod, cls):
        """kol_uret ile ayni, ama strateji sinifi parametrik."""
        d = m
        a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
        hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
        idx = d.index; n = len(cl); s = cls(); out = []; occ = -1
        for i in range(260, n - 1):
            a = a_ser[i]
            if not np.isfinite(a) or a <= 0: continue
            try: sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a))
            except Exception: continue
            dd = getattr(sg, "direction", 0)
            if dd == 0 or i <= occ: continue
            slp = float(getattr(sg, "sl_price", 0.0) or 0.0)
            tpp = float(getattr(sg, "tp_price", 0.0) or 0.0)
            epv = float(getattr(sg, "entry_price", 0.0) or 0.0)
            if slp <= 0 or tpp <= 0: continue
            if mod == "close":
                e = cl[i]; start = i + 1
            else:
                if epv <= 0: continue
                if dd == 1 and not (cl[i] > epv): continue
                if dd == -1 and not (cl[i] < epv): continue
                f = None
                for k in range(i + 1, min(i + 2, n)):
                    if (dd == 1 and lo[k] <= epv) or (dd == -1 and hi[k] >= epv): f = k; break
                if f is None: continue
                e = epv; start = f
            sld = abs(e - slp)
            if sld <= 0 or sld / e > 0.20: continue
            ep_out = None; j = start; ck = "sure"
            for j in range(start, min(start + MAXHOLD, n)):
                if dd == 1:
                    if lo[j] <= slp: ep_out = slp; ck = "sl"; break
                    if hi[j] >= tpp: ep_out = tpp; ck = "tp"; break
                else:
                    if hi[j] >= slp: ep_out = slp; ck = "sl"; break
                    if lo[j] <= tpp: ep_out = tpp; ck = "tp"; break
            if ep_out is None:
                j = min(start + MAXHOLD, n - 1); ep_out = cl[j]; ck = "sure"
            ucret = (2 * FEE if mod == "close" else FEE) * e / sld
            out.append(dict(giris=_naive(idx[i]), cikis_t=_naive(idx[j]),
                            R=dd * (ep_out - e) / sld - ucret, sp=sld / e, yon=dd, cikis=ck))
            occ = j
        return out

    btc = fast_bt.load("BTC", source=src)
    print("\n  [1] FVG @ BTC — orijinal iddia: PF 1.37 / 646 islem / HER YIL pozitif")
    for et, w, mo in (("BTC arsiv-repl (win120,close)", 120, "close"),
                      ("BTC sadik   (win1000,level)", 1000, "level")):
        tr = uret(btc, w, mo, FvgStrategy)
        ozet(tr, et + " kaymasiz", "yok")
        ozet(tr, et + " kaymali ", "giris" if mo == "close" else "cikis")

    print("\n  [2] IFVG (kardes kol, gap>=0.75 rr=2.0) — arsiv iddiasi PF 1.43 TR1.43/TE1.45")
    tri = []
    for c in COINS:
        tri += uret(fast_bt.load(c, source=src), 1000, "level", IF.IfvgStrategy)
    ozet(tri, "IFVG deploy-12 sadik kaymasiz", "yok")
    ozet(tri, "IFVG deploy-12 sadik kaymali ", "cikis")
    trb = uret(btc, 1000, "level", IF.IfvgStrategy)
    ozet(trb, "IFVG @BTC sadik kaymasiz", "yok")
    ozet(trb, "IFVG @BTC sadik kaymali ", "cikis")
    print(f"{'='*118}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ek":
        ek()
    else:
        main()
