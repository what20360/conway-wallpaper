#!/usr/bin/env python3
import sys
from pathlib import Path
import shlex
try:
    from conway_desktop.app import main
except ModuleNotFoundError as exc:
    if exc.name and (exc.name.startswith('PySide6') or exc.name=='numpy'):
        print('当前 Python 环境缺少运行依赖。请执行：\n'+shlex.join([sys.executable,'-m','pip','install','-r',str(Path(__file__).with_name('requirements.txt'))]),file=sys.stderr)
        raise SystemExit(1)
    raise
if __name__ == '__main__':
    raise SystemExit(main())
