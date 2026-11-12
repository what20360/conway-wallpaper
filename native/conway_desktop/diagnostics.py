"""Read-only diagnostic bundle; never changes service or radio state."""
import os
import platform
import shutil
import subprocess
from PySide6.QtCore import qVersion
from .logging_setup import LOGGER,redact,log_dir,log_file
from .system import read_rfkill

def collect():
    LOGGER.info('Diagnostic begin Qt=%s kernel=%s session=%s',qVersion(),platform.release(),os.environ.get('XDG_SESSION_TYPE','unknown'))
    LOGGER.info('Bluetooth rfkill=%s',read_rfkill())
    commands=[['bluetoothctl','--version'],['bluetoothctl','show'],['rfkill','list','bluetooth'],
              ['systemctl','is-active','bluetooth'],['journalctl','-u','bluetooth','-b','-n','40','--no-pager'],
              ['nmcli','--version'],['wpctl','--version']]
    env={**os.environ,'LC_ALL':'C.UTF-8','NO_COLOR':'1','TERM':'dumb'}
    for args in commands:
        if not shutil.which(args[0]):LOGGER.warning('Diagnostic missing tool=%s',args[0]);continue
        try:
            result=subprocess.run(args,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=5,check=False)
            LOGGER.info('Diagnostic argv=%s code=%s output=%s',args,result.returncode,redact(result.stdout))
        except (OSError,subprocess.TimeoutExpired) as exc:LOGGER.warning('Diagnostic argv=%s error=%s',args,redact(exc))
    LOGGER.info('Diagnostic end');print('诊断已写入：',log_file())
