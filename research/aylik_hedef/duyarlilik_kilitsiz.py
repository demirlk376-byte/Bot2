"""Bilgi amaçlı duyarlılık (karar dışı): kilitsiz kural — her adımda (değer/ay başı − 1) ≥ eşik ise o adım engelli,
değer eşiğin altına düşerse girişler yeniden serbest (bot-yalnız ön kaydındaki 'girişte kontrol' biçimine benzer)."""
import json, os, sys
import pandas as pd
sys.path.insert(0, "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/aylik_hedef_T")
import trend_aylik as TA

bot = TA.bot_islemleri(TA.DB)
veri, _ = TA.yukle(TA.BOT12)
out = {}
for ad, esik in (("H10_kilitsiz", 0.10), ("H15_kilitsiz", 0.15)):
    m = TA.MotorAylikHedef(veri, "ETH", "B0", TA.MAL["NORMAL"], t_bas=TA.BL.A, t_bit=TA.SON, bot=bot, esik=esik, kilit=False).kos()
    seri = pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
    s = TA.ay_sonu(seri)
    _, tab = TA.aylik_tablo(s)
    out[ad] = dict(son_carpan=float(seri.deger.iloc[-1] / TA.C0), mdd_ay_sonu_pct=TA.mdd(s), tetik_ay=len(m.tetik_ilk),
                   bot_atlanan_hedef=len(m.hedef_bot_atlanan), R_toplam=float(sum(x[1] for x in m.hedef_bot_atlanan)),
                   yillik={int(k): round(float(v), 1) for k, v in tab["YIL"].items()})
    print(ad, out[ad])
json.dump(out, open(os.path.join(TA.OUT, "duyarlilik_kilitsiz.json"), "w"), indent=1)
