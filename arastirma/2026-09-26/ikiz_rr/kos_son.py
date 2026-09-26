"""Canli (RR 2.5, CAP 2.5) uzerinde: tek-tek cikarma (ablasyon) + O/N taramalari. 4'lu havuz."""
import os, sys, subprocess, time
from concurrent.futures import ThreadPoolExecutor
KOK = "/home/user/Bot2"; BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)
import ikiz_paralel as P
L = dict(P.MALIYET, **P.KAZANAN, SQUEEZE_SYMBOLS="XRP,DOGE,XLM", POSITION_CAP_FRACTION="2.5", DONCHIAN_RR="2.5")
def cikar(**k):
    d = dict(L); d.update(k); return d
KOSULAR_ESKI = [
    ("a_filtresiz", cikar(DONCHIAN_VOL_MULT="0")),             # canli - hacim filtresi
    ("a_risk14",    cikar(RISK_SCALE="1.4")),                   # canli - risk artisi
    ("a_trxli",     cikar(SQUEEZE_SYMBOLS="XRP,DOGE,TRX,XLM")), # canli - TRX cikarma
    ("p_st07",  cikar(PORTFOY_STOP="0.07")),
    ("p_st12",  cikar(PORTFOY_STOP="0.12")),
    ("p_st18",  cikar(PORTFOY_STOP="0.18")),
    ("p_st12s", cikar(PORTFOY_STOP="0.12", PORTFOY_SOGUMA_SAAT="24")),
    ("p_st12y", cikar(PORTFOY_STOP="0.12", MAX_SAME_DIRECTION="5")),
    ("n_ayni5", cikar(MAX_SAME_DIRECTION="5")),
    ("n_ayni4", cikar(MAX_SAME_DIRECTION="4")),
    ("n_ayni3", cikar(MAX_SAME_DIRECTION="3")),
    ("n_korel3", cikar(MAX_SAME_DIRECTION="5", MAX_CORRELATED_DIRECTION="3")),
]
M = dict(P.MALIYET)
KOSULAR = [
    ("y_taban",    dict(M)),                                          # yeni CANLI_ENV = canli; k25_cap25'i uretmeli
    ("p_st12s2",   dict(M, PORTFOY_STOP="0.12", PORTFOY_SOGUMA_SAAT="24")),  # saat hatasi duzeltildi
    ("p_st10y",    dict(M, PORTFOY_STOP="0.10", MAX_SAME_DIRECTION="5")),
    ("p_st15y",    dict(M, PORTFOY_STOP="0.15", MAX_SAME_DIRECTION="5")),
]
def kos(ad_ek):
    ad, ek = ad_ek
    env = dict(os.environ); env.update(ek)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
               IKIZ_IZLE=",".join(sorted(ek)), REPLAY_DB=os.path.join(BURA, f"ikiz_{ad}.db"), IKIZ_ETIKET=ad)
    t0 = time.time()
    with open(os.path.join(BURA, f"ikiz_{ad}.log"), "w", encoding="utf-8") as f:
        rc = subprocess.run([sys.executable, os.path.join(KOK, "ikiz_tam.py")], env=env, cwd=KOK,
                            stdout=f, stderr=subprocess.STDOUT).returncode
    print(f"{ad}: rc={rc} {(time.time()-t0)/60:.1f} dk", flush=True)
with ThreadPoolExecutor(4) as ex:
    list(ex.map(kos, KOSULAR))
