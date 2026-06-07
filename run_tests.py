"""
run_tests.py — tüm motor testlerini çalıştır.

Pytest gerekmez. Her test bağımsız çalışır ve hata varsa exit code != 0 verir.

Çalıştır:  python run_tests.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = [
    "tests/test_parity.py",      # üretim motoru == backtest
    "tests/test_data_feed.py",   # mum-kapanış tespiti (forming mumda tetiklenmez)
    "tests/test_multicoin.py",   # çoklu coin: coin başına fiyat + izole SL/TP
]


def main() -> int:
    root = Path(__file__).parent
    failed = []
    for t in TESTS:
        print(f"\n{'='*70}\nÇALIŞTIRILIYOR: {t}\n{'='*70}")
        r = subprocess.run([sys.executable, str(root / t)])
        if r.returncode != 0:
            failed.append(t)

    print(f"\n{'='*70}")
    if failed:
        print(f"✗ BAŞARISIZ: {', '.join(failed)}")
        return 1
    print(f"✓ TÜM TESTLER GEÇTİ ({len(TESTS)} dosya)")
    print("="*70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
