"""Asynchronous OS controls, verified state and Bluetooth failure diagnostics."""
import configparser
import os
from pathlib import Path
import re
import shutil
import time
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,QTimer,Signal
from .logging_setup import LOGGER,redact


def split_nmcli(line):
    fields=[];current=[];escaped=False
    for ch in line:
        if escaped:current.append(ch);escaped=False
        elif ch=='\\':escaped=True
        elif ch==':':fields.append(''.join(current));current=[]
        else:current.append(ch)
    if escaped:current.append('\\')
    fields.append(''.join(current));return fields

def parse_active_ssid(text):
    for line in text.splitlines():
        fields=split_nmcli(line)
        if len(fields)==2 and fields[0]=='yes':return fields[1]
    return None

def parse_volume(text):
    match=re.search(r'Volume:\s*([0-9.]+)',text)
    if not match:raise ValueError('没有默认音频输出')
    return {'volume':float(match[1]),'muted':'[MUTED]' in text}

def parse_wifi_devices(text):
    return any(split_nmcli(line)[1:2]==['wifi'] for line in text.splitlines())

def parse_wifi_state(text):
    parts=text.strip().split(':')
    if len(parts)!=2 or any(v not in ('enabled','disabled') for v in parts):raise ValueError('无法读取无线开关状态')
    if parts[0]=='disabled':raise ValueError('Wi-Fi 硬件开关已禁用，请先解除硬件禁用')
    return parts[1]=='enabled'

def parse_bluetooth(text):
    m=re.search(r'Powered:\s*(yes|no)',text)
    if not m:raise ValueError('未找到蓝牙适配器')
    return m[1]=='yes'

def bluez_error(text):
    return bool(re.search(r'Failed to (?:set|connect)|org\.bluez\.Error\.|No default controller|No controller available',text,re.I))

def parse_connected_devices(text):
    if bluez_error(text) or re.search(r'Invalid command|Invalid argument|Missing',text,re.I):
        raise ValueError('当前 BlueZ 无法读取已连接设备')
    return len(set(re.findall(r'^Device ([0-9A-Fa-f:]{17})\s',text,re.M)))

def network_counters(root=Path('/sys/class/net')):
    """Count physical, up interfaces, excluding duplicated tunnel/bridge traffic."""
    result={}
    for entry in Path(root).iterdir():
        try:
            if not (entry/'device').exists() or (entry/'operstate').read_text().strip()!='up':continue
            result[entry.name]=tuple(int((entry/'statistics'/name).read_text()) for name in ('rx_bytes','tx_bytes'))
        except (OSError,ValueError):continue
    return result

class NetworkRates:
    def __init__(self):self.previous=None
    def sample(self,counters,now):
        old=self.previous;self.previous=(now,counters)
        if old is None or not counters or set(old[1])!=set(counters):return None,None
        elapsed=now-old[0]
        if not 0<elapsed<=6:return None,None
        if any(counters[n][i]<old[1][n][i] for n in counters for i in (0,1)):return None,None
        return tuple(sum(counters[n][i]-old[1][n][i] for n in counters)/elapsed for i in (0,1))

def read_rfkill(root=Path('/sys/class/rfkill')):
    result=[]
    try:
        for entry in sorted(Path(root).glob('rfkill*')):
            try:
                if (entry/'type').read_text().strip()!='bluetooth':continue
                result.append({'name':(entry/'name').read_text().strip(),
                               'soft':(entry/'soft').read_text().strip()=='1',
                               'hard':(entry/'hard').read_text().strip()=='1'})
            except OSError:continue
    except OSError:pass
    return result

class Commands(QObject):
    def __init__(self,parent=None):super().__init__(parent);self.active={}
    def run(self,key,args,callback,timeout_ms=3000):
        if key in self.active:return False
        program=shutil.which(args[0])
        if not program:
            LOGGER.debug('Command unavailable key=%s program=%s',key,args[0]);callback(False,'缺少工具 '+args[0]);return False
        process=QProcess(self);env=QProcessEnvironment.systemEnvironment()
        # Keep UTF-8 for network names while making command keywords predictable.
        env.insert('LC_ALL','C.UTF-8');env.insert('TERM','dumb');env.insert('NO_COLOR','1')
        process.setProcessEnvironment(env);timer=QTimer(process);timer.setSingleShot(True)
        self.active[key]=process;done=False;timed_out=False;process_failure='';started=time.monotonic()
        LOGGER.debug('Command start key=%s argv=%s timeout_ms=%s',key,redact(args),timeout_ms)
        def finish(ok,error=''):
            nonlocal done
            if done:return
            done=True;timer.stop()
            output=bytes(process.readAllStandardOutput()).decode('utf-8',errors='replace')
            stderr=bytes(process.readAllStandardError()).decode('utf-8',errors='replace')
            logged='<SSID output omitted>' if key=='read-ssid' else '<device aliases omitted>' if key=='read-connected' else '<input method metadata omitted>' if key.startswith('ime-') else redact(output or stderr or error)
            LOGGER.debug('Command end key=%s ok=%s elapsed_ms=%d output=%s',key,ok,int((time.monotonic()-started)*1000),logged)
            self.active.pop(key,None)
            timer.timeout.disconnect();process.finished.disconnect();process.errorOccurred.disconnect()
            process.deleteLater()
            callback(ok,output if ok else (error or stderr or output or '命令执行失败'))
        def process_error(error):
            nonlocal process_failure
            process_failure=process.errorString()
            if error==QProcess.ProcessError.FailedToStart:finish(False,process_failure)
        def timeout():
            nonlocal timed_out
            timed_out=True;timer.stop();process.kill()
            # Deliver the callback only after finished; callers may immediately close
            # the owning window/runner. Never destroy a live process during its signal.
        process.finished.connect(lambda code,status:finish(not timed_out and code==0 and status==QProcess.ExitStatus.NormalExit,
                                                            '命令超时' if timed_out else process_failure))
        process.errorOccurred.connect(process_error);timer.timeout.connect(timeout)
        process.start(program,args[1:]);timer.start(timeout_ms);return True

    def stop(self):
        for process in list(self.active.values()):process.kill();process.waitForFinished(500)

class System(QObject):
    changed=Signal();notice=Signal(str)
    def __init__(self,enabled=True,parent=None):
        super().__init__(parent);self.enabled=enabled;self.commands=Commands(self)
        self.state={'volume':None,'muted':None,'wifi':None,'ssid':None,'bluetooth':None,'connected':None,'theme':None,'cpu':None,'memory':None,'download':None,'upload':None,'ime':None,'punctuation':None}
        self.network=NetworkRates();self._network_wall=None
        self.errors={};self.busy=set();self._cpu=None;self.wifi_device=False;self._bluetooth_token=0
        from .ime import Fcitx
        self.ime=Fcitx(self)
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.refresh)
        self.bluetooth_timer=QTimer(self);self.bluetooth_timer.setInterval(500);self.bluetooth_timer.timeout.connect(self.refresh_bluetooth)
        if enabled:
            self.timer.start();self.bluetooth_timer.start()
            QTimer.singleShot(0,self.refresh);QTimer.singleShot(0,self.refresh_bluetooth)
    def _set_error(self,key,error):
        if self.errors.get(key)!=error:LOGGER.warning('Read failure key=%s error=%s',key,'<SSID read failed>' if key=='ssid' else redact(error))
        self.errors[key]=error
    def _read(self,key,args,parser,after=None):
        if key in self.busy:return
        bluetooth_token=self._bluetooth_token if key in ('bluetooth','connected') else None
        def result(ok,out):
            if not self.enabled:return
            if bluetooth_token is not None and (bluetooth_token!=self._bluetooth_token or 'bluetooth' in self.busy):return
            previous=self.state.get(key) if key!='audio' else (self.state['volume'],self.state['muted'])
            try:
                if not ok:raise ValueError(out.strip())
                value=parser(out)
                if key=='audio':self.state.update(value)
                else:self.state[key]=value
                if key in self.errors:LOGGER.info('Read recovered key=%s',key)
                self.errors.pop(key,None)
                current=self.state.get(key) if key!='audio' else (self.state['volume'],self.state['muted'])
                if current!=previous:LOGGER.info('State changed key=%s value=%s',key,'<SSID changed>' if key=='ssid' else current)
            except (ValueError,TypeError) as exc:
                self._set_error(key,str(exc))
                if key=='audio':self.state.update(volume=None,muted=None)
                else:self.state[key]=None
            self.changed.emit()
            if after:after()
        self.commands.run('read-'+key,args,result)
    def _refresh_connected(self):
        if self.state['bluetooth'] is True:self._read('connected',['bluetoothctl','devices','Connected'],parse_connected_devices)
        else:
            self.state['connected']=0 if self.state['bluetooth'] is False else None
            self.changed.emit()
    def refresh_bluetooth(self):
        if not self.enabled or 'bluetooth' in self.busy:return
        self._read('bluetooth',['bluetoothctl','show'],parse_bluetooth,after=self._refresh_connected)
    def refresh(self):
        if not self.enabled:return
        try:
            numbers=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            total=sum(numbers);idle=numbers[3]+numbers[4]
            if self._cpu and total>self._cpu[0]:self.state['cpu']=max(0,min(100,100*(1-(idle-self._cpu[1])/(total-self._cpu[0]))))
            self._cpu=(total,idle)
            memory={p[0].rstrip(':'):int(p[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(p:=line.split())>=2}
            self.state['memory']=100*(1-memory['MemAvailable']/memory['MemTotal'])
        except (OSError,ValueError,KeyError):pass
        wall=time.time()
        if self._network_wall is not None and not 0<wall-self._network_wall<=6:self.network.previous=None
        self._network_wall=wall
        try:self.state['download'],self.state['upload']=self.network.sample(network_counters(),time.monotonic())
        except OSError:self.state.update(download=None,upload=None);self.network.previous=None
        self._read('audio',['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],parse_volume)
        def wifi_devices(out):
            if not self.enabled:return
            self.wifi_device=parse_wifi_devices(out)
            if not self.wifi_device:self.state.update(wifi=None,ssid=None);self._set_error('wifi','没有无线网卡');self.changed.emit()
            else:
                self._read('wifi',['nmcli','-t','-f','WIFI-HW,WIFI','general','status'],parse_wifi_state)
                self._read('ssid',['nmcli','-t','-e','yes','-f','ACTIVE,SSID','device','wifi','list','--rescan','no'],parse_active_ssid)
        self.commands.run('devices',['nmcli','-t','-f','DEVICE,TYPE,STATE','device','status'],lambda ok,out:wifi_devices(out) if ok else self._wifi_error(out))
        cfg=configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'kdeglobals')
            name=cfg.get('General','ColorScheme',fallback='BreezeLight') if shutil.which('plasma-apply-colorscheme') else ''
            self.state['theme']=('night' if 'dark' in name.lower() else 'day') if name else None
        except (OSError,configparser.Error):self.state['theme']=None
        self.changed.emit()
    def _wifi_error(self,out):
        self.state.update(wifi=None,ssid=None);self._set_error('wifi',out);self.changed.emit()
    def _action(self,key,args):
        if not self.enabled or key in self.busy:return
        self.busy.add(key);self.changed.emit();LOGGER.info('Control requested key=%s argv=%s',key,redact(args))
        def result(ok,out):
            if not self.enabled:return
            self.busy.discard(key)
            LOGGER.info('Control result key=%s command_ok=%s detail=%s',key,ok,redact(out))
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
        if not self.enabled or self.state['bluetooth'] is None or 'bluetooth' in self.busy:return
        target=not self.state['bluetooth'];self._bluetooth_token+=1;token=self._bluetooth_token
        self.busy.add('bluetooth');self.changed.emit()
        blocks=read_rfkill();LOGGER.info('Bluetooth requested target=%s rfkill=%s',target,blocks)
        def live():return token==self._bluetooth_token
        def fail(reason):
            if not live():return
            LOGGER.error('Bluetooth failed target=%s error=%s rfkill=%s',target,redact(reason),read_rfkill())
            self.errors['bluetooth-action']=reason;self.busy.discard('bluetooth');self.refresh();self.changed.emit()
            # Extra diagnostics run once on failure, not every two-second poll.
            self.commands.run('bt-diagnostic',['bluetoothctl','show'],lambda ok,out:LOGGER.warning('Bluetooth adapter diagnostic ok=%s output=%s',ok,redact(out)))
            self.notice.emit(reason+'\n\n已记录到日志；可点击左上角状态点打开日志目录。')
        def verify(attempt=0):
            if not live():return
            def result(ok,out):
                if not live():return
                try:actual=parse_bluetooth(out) if ok else None
                except ValueError:actual=None
                LOGGER.info('Bluetooth readback target=%s actual=%s attempt=%s',target,actual,attempt)
                if actual is target:
                    self.state['bluetooth']=actual;self.errors.pop('bluetooth-action',None);self.busy.discard('bluetooth');self.changed.emit();LOGGER.info('Bluetooth confirmed powered=%s',actual)
                    self._refresh_connected()
                elif attempt<3:QTimer.singleShot(400,lambda:verify(attempt+1))
                else:fail('蓝牙命令已返回，但适配器没有进入目标状态。\n'+redact(out))
            self.commands.run('bt-verify',['bluetoothctl','show'],result,timeout_ms=5000)
        def power():
            if not live():return
            def result(ok,out):
                if not live():return
                LOGGER.info('Bluetooth power result command_ok=%s output=%s',ok,redact(out))
                if not ok or bluez_error(out):fail(redact(out) or 'BlueZ 操作失败')
                else:QTimer.singleShot(250,verify)
            self.commands.run('bt-power',['bluetoothctl','--timeout','8','power','on' if target else 'off'],result,timeout_ms=10000)
        if target and blocks and all(b['hard'] for b in blocks):
            fail('蓝牙被硬件开关禁用，软件无法解除。请检查机身开关、飞行模式或 BIOS。');return
        if target and any(b['soft'] for b in blocks):
            def unblocked(ok,out):
                if not live():return
                LOGGER.info('Bluetooth rfkill unblock ok=%s output=%s',ok,redact(out))
                if not ok:fail('蓝牙处于软件禁用状态，解除失败：\n'+redact(out)+'\n可先在 KDE 蓝牙设置中打开蓝牙，再重试。')
                elif any(b['hard'] or b['soft'] for b in read_rfkill()):fail('蓝牙的无线禁用状态尚未解除，请检查系统蓝牙设置。')
                else:power()
            self.commands.run('bt-unblock',['rfkill','unblock','bluetooth'],unblocked)
        else:power()
    def theme(self):
        target='BreezeDark' if self.state['theme']!='night' else 'BreezeLight'
        roots=[Path('/usr/share/color-schemes'),Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'color-schemes']
        if not any((root/(target+'.colors')).exists() for root in roots):self.notice.emit('未找到系统配色方案 '+target);return
        self._action('theme',['plasma-apply-colorscheme',target])
    def stop(self):
        self.enabled=False;self._bluetooth_token+=1;self.timer.stop();self.bluetooth_timer.stop();self.ime.stop();self.commands.stop()
