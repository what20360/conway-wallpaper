"""Install a per-user Plasma service; activation is an explicit systemctl step."""
import os
from pathlib import Path
import tempfile

NAME='conway-wallpaper.service'
MARKER='# Managed by ConwayDesktop'

def service_file():return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'systemd/user'/NAME

def unit_argument(value):
    value=str(value)
    if any(ch in value for ch in ('\n','\r','\0')):raise ValueError('服务参数不能包含换行或 NUL')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'

def service_text(launcher,data):
    command=' '.join(unit_argument(v) for v in (launcher,'--wallpaper','--data-dir',data))
    return f'''{MARKER}
[Unit]
Description=Conway wallpaper and desktop controls
PartOf=graphical-session.target
After=plasma-plasmashell.service
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=5
RestartPreventExitStatus=2
TimeoutStopSec=10

[Install]
WantedBy=plasma-workspace.target
'''

def install_service(data):
    launcher=Path.home()/'.local/bin/conway-desktop'
    if not launcher.is_file() or not os.access(launcher,os.X_OK):raise RuntimeError('请先使用一键更新脚本安装稳定启动器 ~/.local/bin/conway-desktop')
    file=service_file()
    if file.exists() and not file.read_text().startswith(MARKER):raise RuntimeError('同名服务已有自定义内容，未覆盖：'+str(file))
    text=service_text(launcher,Path(data).resolve());file.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=file.parent,delete=False) as out:
            temporary=Path(out.name);out.write(text)
        temporary.replace(file)
    finally:
        if temporary:temporary.unlink(missing_ok=True)
    from .wallpaper import set_autostart
    set_autostart(False)
    return file
