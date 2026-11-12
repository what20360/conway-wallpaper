"""Read-only diagnostic bundle; never changes service or radio state."""
import os
import platform
import shutil
import subprocess
import json
import re
from pathlib import Path
from urllib.request import Request,ProxyHandler,build_opener
from PySide6.QtCore import qVersion
from .logging_setup import LOGGER,redact,log_dir,log_file
from .system import read_rfkill

def read_wallpaper_info(path,port=17832):
    # Read only: do not create credentials, acquire the app lock, or touch SQLite.
    token=(Path(path)/'wallpaper-token').read_text().strip()
    request=Request(f'http://127.0.0.1:{port}/display-info',headers={'Authorization':'Bearer '+token})
    with build_opener(ProxyHandler({})).open(request,timeout=5) as response:return json.load(response)

def summarize_outputs(text):
    clean=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',text);lines=[]
    for line in clean.splitlines():
        value=line.strip()
        if value.startswith(('Geometry:','Scale:','Rotation:')):lines.append(value)
        elif value.startswith('Output:'):lines.append(' '.join(value.split()[:3]))
        elif value.startswith('Modes:'):
            selected=re.search(r'\b[0-9]+:([0-9]+x[0-9]+@[0-9.]+)\*',value)
            if selected:lines.append('Current mode: '+selected[1])
    return '\n'.join(lines) or 'No display geometry parsed'

def collect(path=None):
    LOGGER.info('Diagnostic begin Qt=%s kernel=%s session=%s',qVersion(),platform.release(),os.environ.get('XDG_SESSION_TYPE','unknown'))
    LOGGER.info('Bluetooth rfkill=%s',read_rfkill())
    if path:
        try:LOGGER.info('Wallpaper display info=%s',read_wallpaper_info(path))
        except Exception as exc:LOGGER.warning('Wallpaper display info unavailable: %s',exc)
    commands=[['plasmashell','--version'],['kscreen-doctor','-o'],['bluetoothctl','--version'],['bluetoothctl','show'],['rfkill','list','bluetooth'],
              ['systemctl','is-active','bluetooth'],['journalctl','-u','bluetooth','-b','-n','40','--no-pager'],
              ['nmcli','--version'],['wpctl','--version']]
    env={**os.environ,'LC_ALL':'C.UTF-8','NO_COLOR':'1','TERM':'dumb'}
    for args in commands:
        if not shutil.which(args[0]):LOGGER.warning('Diagnostic missing tool=%s',args[0]);continue
        try:
            result=subprocess.run(args,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=5,check=False)
            output=summarize_outputs(result.stdout) if args[0]=='kscreen-doctor' else result.stdout
            LOGGER.info('Diagnostic argv=%s code=%s output=%s',args,result.returncode,redact(output))
        except (OSError,subprocess.TimeoutExpired) as exc:LOGGER.warning('Diagnostic argv=%s error=%s',args,redact(exc))
    LOGGER.info('Diagnostic end');print('诊断已写入：',log_file())
