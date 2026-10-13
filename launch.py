"""Fixed isolated launcher. No user-site imports or developer-runtime fallback."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
if Path(sys.executable).resolve() != (RUNTIME / 'python/python.exe').resolve():
    raise SystemExit('BUNDLED_PYTHON_REQUIRED: 请通过包内 start.cmd 启动；运行环境缺失时请查阅 REQUIREMENTS.md。')
sys.dont_write_bytecode = True
sys.path[:] = [str(RUNTIME / 'python/Lib'), str(RUNTIME / 'python/DLLs'),
               str(RUNTIME / 'python' / f'python{sys.version_info.major}{sys.version_info.minor}.zip'),
               str(RUNTIME / 'python'), str(RUNTIME / 'vendor'), str(RUNTIME / 'pdf-text-v1'), str(ROOT)]
from app.cli import main
raise SystemExit(main(ROOT))
