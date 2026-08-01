"""
trail_exit_diag2.py — SAF KONTROL: "notp" = TP'yi kaldır, BAŞKA HİÇBİR ŞEYE DOKUNMA.
Stop ilk 2xATR'de SABİT kalır, maxhold korunur. Kaybedenlere dokunulmadığı için
"örtük erken çıkış" bulaşması YOKTUR → tezin (kazananı serbest bırak) EN TEMİZ testi.
Ayrıca donchian için maxhold'u uzatmanın (30→45/60 bar) etkisi: TP'siz kol kısa pencerede
boğuluyor mu?
"""
import numpy as np
import trail_exit_test as T

P = T.build_cache("local")
basef = T.stats(T.portfolio(P, {}), funding=True)
print(T.line("TABAN (funding düşülmüş)", basef))
print()
for slv in ("donchian", "squeeze", "bb"):
    st = T.stats(T.portfolio(P, {slv: ("notp", None)}), funding=True)
    d = {y: st["by_year"].get(y, 0) - basef["by_year"].get(y, 0) for y in (2023, 2024, 2025, 2026)}
    print(T.line(f"notp (TP YOK, stop sabit) {slv}", st))
    print(f"      delta yıl-yıl: 2023{d[2023]:+.0f} 2024{d[2024]:+.0f} 2025{d[2025]:+.0f} 2026{d[2026]:+.0f}"
          f"  | TRAIN {d[2023]+d[2024]:+.0f} TEST {d[2025]+d[2026]:+.0f}")
    m = st["slv"] == slv; r = st["R"][m]
    print(f"      {slv} bacakları: n{m.sum()} ort {r.mean():+.3f}R | kazanan {r[r>0].mean():+.2f}R (%{(r>0).mean()*100:.0f})"
          f" | KAYBEDEN {r[r<0].mean():+.3f}R | maxR {r.max():+.1f} | R>5: {(r>5).sum()}")
st = T.stats(T.portfolio(P, {s: ("notp", None) for s in ("donchian", "squeeze", "bb")}), funding=True)
print(T.line("notp HEPSİ", st))
