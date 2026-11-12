"""Small asynchronous adapters. Never uses shell=True or arbitrary command text."""
import configparser
import os
from pathlib import Path
import re
import shutil
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,QTimer,Signal


def parse_volume(text):
    match=re.search(r'Volume:\s*([0-9.]+)',text)
    if not match: raise ValueError('no default audio output')
    return {'volume':float(match[1]),'muted':'[MUTED]' in text}

def parse_wifi_devices(text):
    return any('wifi' in line.split(':')[1:2] for line in text.splitlines())

def parse_wifi_state(text):
    parts=text.strip().split(':')
    if len(parts)!=2 or any(v not in ('enabled','disabled') for v in parts):raise ValueError('无法读取无线开关状态')
    if parts[0]=='disabled':raise ValueError('Wi-Fi 硬件开关已禁用，请先解除硬件禁用')
    return parts[1]=='enabled'

def parse_bluetooth(text):
    m=re.search(r'Powered:\s*(yes|no)',text)
    if not m: raise ValueError('no Bluetooth controller')
    return m[1]=='yes'

class Commands(QObject):
    def __init__(self,parent=None): super().__init__(parent); self.active={}
    def run(self,key,args,callback):
        if key in self.active: return False
        program=shutil.which(args[0])
        if not program: callback(False,'缺少工具 '+args[0]); return False
        process=QProcess(self); env=QProcessEnvironment.systemEnvironment();env.insert('LC_ALL','C');process.setProcessEnvironment(env);timer=QTimer(process); timer.setSingleShot(True)
        self.active[key]=process; done=False
        def finish(ok,error=''):
            nonlocal done
            if done:return
            done=True; timer.stop()
            output=bytes(process.readAllStandardOutput()).decode(errors='replace')
            stderr=bytes(process.readAllStandardError()).decode(errors='replace')
            def cleanup():
                if self.active.get(key) is process:self.active.pop(key,None)
                process.deleteLater()
            if process.state()!=QProcess.ProcessState.NotRunning:
                process.finished.connect(cleanup);process.kill()
            else:cleanup()
            callback(ok,output if ok else (error or stderr or output or '命令执行失败'))
        def process_error(error):
            if not done:finish(False,process.errorString())
        process.finished.connect(lambda code,status:finish(code==0 and status==QProcess.ExitStatus.NormalExit))
        process.errorOccurred.connect(process_error)
        timer.timeout.connect(lambda:finish(False,'命令超时'))
        process.start(program,args[1:]); timer.start(3000); return True
    def stop(self):
        for process in list(self.active.values()): process.kill(); process.waitForFinished(500)

class System(QObject):
    changed=Signal(); notice=Signal(str)
    def __init__(self,enabled=True,parent=None):
        super().__init__(parent); self.enabled=enabled; self.commands=Commands(self)
        self.state={'volume':None,'muted':None,'wifi':None,'bluetooth':None,'theme':None,'cpu':None,'memory':None}
        self.errors={}; self.busy=set(); self._cpu=None; self.wifi_device=False
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.refresh)
        if enabled: self.timer.start(); QTimer.singleShot(0,self.refresh)
    def _read(self,key,args,parser):
        if key in self.busy:return
        def result(ok,out):
            try:
                if not ok:raise ValueError(out.strip())
                value=parser(out)
                if key=='audio':self.state.update(value)
                else:self.state[key]=value
                self.errors.pop(key,None)
            except (ValueError,TypeError) as exc:
                self.errors[key]=str(exc)
                if key=='audio':self.state.update(volume=None,muted=None)
                else:self.state[key]=None
            self.changed.emit()
        self.commands.run('read-'+key,args,result)
    def refresh(self):
        if not self.enabled:return
        try:
            numbers=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            total=sum(numbers); idle=numbers[3]+numbers[4]
            if self._cpu and total>self._cpu[0]:self.state['cpu']=max(0,min(100,100*(1-(idle-self._cpu[1])/(total-self._cpu[0]))))
            self._cpu=(total,idle)
            memory={p[0].rstrip(':'):int(p[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(p:=line.split())>=2}
            self.state['memory']=100*(1-memory['MemAvailable']/memory['MemTotal'])
        except (OSError,ValueError,KeyError):pass
        self._read('audio',['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],parse_volume)
        def wifi_devices(out):
            self.wifi_device=parse_wifi_devices(out)
            if not self.wifi_device:self.state['wifi']=None;self.errors['wifi']='没有无线网卡';self.changed.emit()
            else:self._read('wifi',['nmcli','-t','-f','WIFI-HW,WIFI','general','status'],parse_wifi_state)
        self.commands.run('devices',['nmcli','-t','-f','DEVICE,TYPE,STATE','device','status'],lambda ok,out:wifi_devices(out) if ok else self._wifi_error(out))
        self._read('bluetooth',['bluetoothctl','show'],parse_bluetooth)
        cfg=configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'kdeglobals')
            name=cfg.get('General','ColorScheme',fallback='BreezeLight') if shutil.which('plasma-apply-colorscheme') else ''
            self.state['theme']=('night' if 'dark' in name.lower() else 'day') if name else None
        except (OSError,configparser.Error):self.state['theme']=None
        self.changed.emit()
    def _wifi_error(self,out):
        self.state['wifi']=None;self.errors['wifi']=out;self.changed.emit()
    def _action(self,key,args):
        if not self.enabled or key in self.busy:return
        self.busy.add(key);self.changed.emit()
        def result(ok,out):
            self.busy.discard(key)
            if not ok:self.notice.emit(out.strip() or '操作失败')
            self.refresh();self.changed.emit()
        self.commands.run('set-'+key,args,result)
    def volume(self,value):
        if self.state['volume'] is not None:self._action('audio',['wpctl','set-volume','@DEFAULT_AUDIO_SINK@',str(max(0,min(1,value))),'-l','1'])
    def mute(self):
        if self.state['muted'] is not None:self._action('audio',['wpctl','set-mute','@DEFAULT_AUDIO_SINK@','toggle'])
    def wifi(self):
        if self.state['wifi'] is not None:self._action('wifi',['nmcli','radio','wifi','off' if self.state['wifi'] else 'on'])
    def bluetooth(self):
        if self.state['bluetooth'] is not None:self._action('bluetooth',['bluetoothctl','power','off' if self.state['bluetooth'] else 'on'])
    def theme(self):
        target='BreezeDark' if self.state['theme']!='night' else 'BreezeLight'
        roots=[Path('/usr/share/color-schemes'),Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'color-schemes']
        if not any((root/(target+'.colors')).exists() for root in roots):
            self.notice.emit('未找到系统配色方案 '+target);return
        self._action('theme',['plasma-apply-colorscheme',target])
    def stop(self):self.timer.stop();self.commands.stop()
