"""Run the public synthetic mechanism tests with this package runtime only."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'runtime'
if Path(sys.executable).resolve()!=(RUNTIME/'python/python.exe').resolve():
    raise SystemExit('BUNDLED_PYTHON_REQUIRED: use runtime\\python\\python.exe with -X utf8 -I -S -B.')
sys.dont_write_bytecode=True
sys.path[:]=[str(RUNTIME/'python/Lib'),str(RUNTIME/'python/DLLs'),
    str(RUNTIME/'python'/f'python{sys.version_info.major}{sys.version_info.minor}.zip'),str(RUNTIME/'python'),
    str(RUNTIME/'vendor'),str(RUNTIME/'pdf-text-v1'),str(ROOT),str(ROOT/'tests')]
import unittest
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
raise SystemExit(0 if result.wasSuccessful() else 1)
