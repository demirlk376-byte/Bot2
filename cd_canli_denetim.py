"""
cd_canli_denetim.py — CANLI tarafta cooldown celiskisini olcer. SALT OKUR.

VPS'te kosulur:  cd /opt/bot2 && venv/bin/python cd_canli_denetim.py

Olcer:
 1) (strateji:sembol) anahtar basina islem dagilimi  -> anahtar yogunlugu
 2) BITISIK KAYIP-KAYIP cifti sayisi = ratchet semantiginde BEKLENEN cooldown
    TETIKLEME sayisi (execution._record_trade_outcome ile birebir replay)
 3) Her tetiklemeden sonra AYNI anahtarda 240 dk icinde bir GIRIS olmus mu?
    -> cooldown fiilen bir sey engelledi mi (engellemesi gerekirken engellemedi mi)
 4) _record_trade_outcome'u ATLAYAN kapanislar (exit_reason halted_entry /
    no_stop_safety) — bunlar streak sayacini hic artirmaz
 5) Ayni anahtarda onceki CIKIS -> sonraki GIRIS bosluk dagilimi
    (cooldown 240dk'nin baglayici olup olmadigini bu belirler)

Not: bu script yalnizca trades.db'yi okur; hicbir sey yazmaz.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta

DB = sys.argv[1] if len(sys.argv) > 1 else "/opt/bot2/data/trades.db"
LIMIT = 2          # CONSECUTIVE_LOSS_LIMIT
CD_DK = 240        # COOLDOWN_MINUTES

if not os.path.exists(DB):
    sys.exit(f"trades.db bulunamadi: {DB}  (yol arg olarak verilebilir)")

con = sqlite3.connect(DB)
rows = con.execute(
    "SELECT id, symbol, entry_time, exit_time, pnl_usdt, exit_reason, strategy_scores "
    "FROM trades WHERE is_paper=0 AND exit_time IS NOT NULL AND exit_time<>'' "
    "ORDER BY exit_time").fetchall()

T = []
for _id, sym, et, xt, pnl, xr, ss in rows:
    try:
        sc = json.loads(ss) if ss else {}
    except Exception:
        sc = {}
    strat = sc.get("strategy", "all")
    T.append(dict(id=_id, sym=sym, kol=strat, anahtar=f"{strat}:{sym}",
                  giris=datetime.fromisoformat(et), cikis=datetime.fromisoformat(xt),
                  pnl=float(pnl or 0.0), neden=xr or ""))

print("=" * 92)
print(f"CANLI COOLDOWN DENETIMI · {DB}")
print(f"kapanan gercek islem: {len(T)}")
if not T:
    sys.exit(0)
bas, son = min(x["giris"] for x in T), max(x["cikis"] for x in T)
gun = (son - bas).total_seconds() / 86400
print(f"donem: {bas:%Y-%m-%d} -> {son:%Y-%m-%d}  = {gun:.0f} gun  = {len(T)/gun:.2f} islem/gun")
print("=" * 92)

# ── 4) sayaci ATLAYAN kapanislar ──
atlar = [x for x in T if x["neden"] in ("halted_entry", "no_stop_safety")]
print(f"\n### 4) _record_trade_outcome'u ATLAYAN kapanislar: {len(atlar)}")
print(f"     exit_reason dagilimi: {dict(Counter(x['neden'] for x in T))}")
if atlar:
    print("     (bu satirlar DB'ye yaziliyor ama streak sayacini ARTIRMIYOR)")

# sayaca giren islemler
S = [x for x in T if x["neden"] not in ("halted_entry", "no_stop_safety")]

# ── 1) anahtar yogunlugu ──
dag = Counter(x["anahtar"] for x in S)
print(f"\n### 1) ANAHTAR YOGUNLUGU")
print(f"     aktif (kol:coin) anahtar = {len(dag)} · islem = {len(S)}"
      f" · anahtar basina ort {len(S)/max(len(dag),1):.2f}")
tek = sum(1 for v in dag.values() if v == 1)
print(f"     TEK islemli anahtar = {tek}/{len(dag)}  (%{tek/max(len(dag),1)*100:.0f})"
      f" — bunlar cooldown'i ASLA tetikleyemez")
print(f"     dagilim: " + ", ".join(f"{a}={n}" for a, n in dag.most_common()))
print(f"     islem sayisi histogrami: {dict(sorted(Counter(dag.values()).items()))}")

# ── 2) TETIKLEME replay (execution._record_trade_outcome birebir) ──
seri = defaultdict(int)
tetik = []
for x in sorted(S, key=lambda z: z["cikis"]):
    a = x["anahtar"]
    if x["pnl"] < 0:
        seri[a] += 1
        if seri[a] >= LIMIT:
            tetik.append((x["cikis"], a, seri[a]))   # streak SIFIRLANMAZ (uretimde de)
    else:
        seri[a] = 0
print(f"\n### 2) BEKLENEN COOLDOWN TETIKLEMESI (kod replay'i, kesinti YOK)")
print(f"     tetikleme = {len(tetik)}  (islem basina %{len(tetik)/max(len(S),1)*100:.1f})")
print(f"     kol dagilimi: {dict(Counter(a.split(':')[0] for _t, a, _s in tetik))}")
for t, a, s in tetik[:40]:
    print(f"       {t:%Y-%m-%d %H:%M} {a:<26s} streak={s}")
if len(tetik) > 40:
    print(f"       ... +{len(tetik)-40} tane daha")
print(f"     >>> journalctl'de gozlenen 2 ile KIYASLA. Fark = restart/kesinti/log kaybi.")

# ── 3) tetikleme BAGLAYICI miydi? ──
gir = defaultdict(list)
for x in S:
    gir[x["anahtar"]].append(x["giris"])
for a in gir:
    gir[a].sort()
bagl = 0
for t, a, _s in tetik:
    if any(t < g <= t + timedelta(minutes=CD_DK) for g in gir[a]):
        bagl += 1
print(f"\n### 3) TETIKLEMEDEN SONRAKI {CD_DK} DK ICINDE AYNI ANAHTARDA GIRIS")
print(f"     {bagl} / {len(tetik)} tetikleme icin BOYLE BIR GIRIS VAR.")
print(f"     0 ise: cooldown tetiklense de engelleyecek bir sey yok (BAGLAYICI DEGIL).")
print(f"     >0 ise: cooldown tetiklendi ama giris yine de olmus -> durum KAYBOLMUS")
print(f"             (restart) ya da kapi kacirilmis demektir.")

# ── 5) ayni anahtarda cikis -> sonraki giris boslugu ──
print(f"\n### 5) AYNI ANAHTARDA: onceki CIKIS -> sonraki GIRIS boslugu")
bos = []
for a, g in defaultdict(list, {k: [x for x in S if x["anahtar"] == k] for k in dag}).items():
    g.sort(key=lambda z: z["giris"])
    for i in range(1, len(g)):
        bos.append(((g[i]["giris"] - g[i - 1]["cikis"]).total_seconds() / 60.0,
                    g[i - 1]["pnl"] < 0, a))
print(f"     ardisik cift = {len(bos)}")
if bos:
    v = sorted(b for b, _k, _a in bos)
    import statistics
    print(f"     medyan bosluk = {statistics.median(v):.0f} dk"
          f" · <= {CD_DK}dk olan = {sum(1 for b in v if b <= CD_DK)}"
          f" (%{sum(1 for b in v if b <= CD_DK)/len(v)*100:.1f})")
    print(f"     en kucuk 10 bosluk (dk): {[round(x) for x in v[:10]]}")
    print(f"     <= {CD_DK}dk VE onceki islem KAYIP: "
          f"{sum(1 for b, k, _a in bos if b <= CD_DK and k)}")
print("\n" + "=" * 92)
