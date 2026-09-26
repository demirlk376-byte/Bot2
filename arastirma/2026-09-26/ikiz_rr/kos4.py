import os, sys, subprocess, time
KOK = "/home/user/Bot2"; BURA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KOK)
import ikiz_paralel as P
S3 = dict(SQUEEZE_SYMBOLS="XRP,DOGE,XLM")
KOSULAR = [
    ("k20_cap25", dict(P.MALIYET, **P.KAZANAN, **S3, POSITION_CAP_FRACTION="2.5")),               # kopru: c_cap25 birebir
    ("k25_cap25", dict(P.MALIYET, **P.KAZANAN, **S3, POSITION_CAP_FRACTION="2.5", DONCHIAN_RR="2.5")),  # CANLI
    ("k25_cap15", dict(P.MALIYET, **P.KAZANAN, **S3, DONCHIAN_RR="2.5")),                          # CAP yeniden
    ("k25_eski",  dict(P.MALIYET, DONCHIAN_RR="2.5")),                                             # 09-22 oncesi canli
]
ps = []
for ad, ek in KOSULAR:
    env = dict(os.environ); env.update(ek)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1",
               IKIZ_IZLE=",".join(sorted(ek)), REPLAY_DB=os.path.join(BURA, f"ikiz_{ad}.db"), IKIZ_ETIKET=ad)
    f = open(os.path.join(BURA, f"ikiz_{ad}.log"), "w", encoding="utf-8")
    ps.append((ad, subprocess.Popen([sys.executable, os.path.join(KOK, "ikiz_tam.py")], env=env, cwd=KOK,
                                    stdout=f, stderr=subprocess.STDOUT), time.time()))
for ad, p, t0 in ps:
    rc = p.wait(); print(f"{ad}: rc={rc}  {(time.time()-t0)/60:.1f} dk", flush=True)
