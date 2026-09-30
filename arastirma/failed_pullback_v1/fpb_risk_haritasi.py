"""
B koşusu için adayın RİSK HARİTASI — koşudan ÖNCE üretilir ve kaydedilir.

Kural (deney tanımı): adayın işlem başı riski = A'daki AYNI sembol/yön için tanımlı
etkin stratejilerin POZİTİF risk yüzdelerinin EN KÜÇÜĞÜNÜN %25'i. Referans riski
olmayan sembol/yön (ör. hiçbir kolun işlem yapmadığı TRX) haritaya GİRMEZ.

A'nın ayarı = ikizin CANLI_ENV'i (ikiz/kos.py) → config.load_config() ile okunur;
elle kopyalanmaz. Kol ↔ sembol ↔ risk bağları (main.py / execution.py):
  donchian : DONCHIAN_SYMBOLS, risk donchian_risk_pct, long+short (EMA200 yönlü)
  squeeze  : SQUEEZE_SYMBOLS,  risk squeeze_risk_pct,  long+short (KC orta çizgi)
  BB (mean_rev): BB_SYMBOLS,   risk max_risk_per_trade (ATR yolu), long+short
Kullanım: python3 fpb_risk_haritasi.py  →  risk_haritasi.json
"""
import json
import os
import sys

BURA = os.path.dirname(os.path.abspath(__file__))
KOK = os.path.dirname(os.path.dirname(BURA))
sys.path.insert(0, KOK)
ADAY_PAY = 0.25


def haritayi_kur(risk_scale: str = "1.75") -> dict:
    from ikiz.kos import CANLI_ENV
    for k, v in CANLI_ENV.items():
        os.environ.setdefault(k, v)
    os.environ["RISK_SCALE"] = risk_scale
    os.environ["PAPER_MODE"] = "true"
    import config
    c = config.load_config()
    r, s = c.risk, c.strategy
    kollar = [
        ("donchian", s.donchian_symbols or [], r.donchian_risk_pct),
        ("squeeze", s.squeeze_symbols or [], r.squeeze_risk_pct),
        ("mean_rev", s.bb_symbols or [], r.max_risk_per_trade),
    ]
    harita, kaynak = {}, {}
    for sym in c.exchange.symbols:
        for yon, ad in ((1, "long"), (-1, "short")):
            adaylar = [(k, p) for k, semb, p in kollar if sym in semb and p > 0]
            if not adaylar:
                continue
            en_kucuk = min(p for _, p in adaylar)
            harita.setdefault(sym, {})[ad] = round(ADAY_PAY * en_kucuk, 10)
            kaynak.setdefault(sym, {})[ad] = {k: p for k, p in adaylar}
    haric = [s_ for s_ in c.exchange.symbols if s_ not in harita]
    return dict(kural="aday_risk = 0.25 x min(A'daki etkin kol risk%)",
                A_risk_scale=float(risk_scale), harita=harita, kaynak=kaynak,
                haric_semboller=haric)


if __name__ == "__main__":
    h = haritayi_kur()
    yol = os.path.join(BURA, "risk_haritasi.json")
    with open(yol, "w") as f:
        json.dump(h, f, indent=1, sort_keys=True)
    print(json.dumps(h, indent=1, sort_keys=True))
