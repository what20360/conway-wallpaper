"""Fcitx5 controller + Rime ASCII mode; punctuation through real tray actions.

No synthetic key events, no input text capture, and no configuration rewriting.
Menu entries are accepted only when their punctuation semantics are recognizable.
"""
import json
import re
from PySide6.QtCore import QObject,QTimer
from .logging_setup import LOGGER

SERVICE='org.fcitx.Fcitx5';CONTROLLER='org.fcitx.Fcitx.Controller1'
CHINESE={'。，','，。','中文标点','中文標點','中式标点','中式標點'}
ENGLISH={'．，','，．','.,',',.','英文标点','英文標點','西文标点','西文標點'}

def unwrap(value):
    if isinstance(value,dict):
        if set(value)>={'type','data'}:return unwrap(value['data'])
        return {key:unwrap(item) for key,item in value.items()}
    if isinstance(value,list):return [unwrap(item) for item in value]
    return value

def bus_data(text):
    value=unwrap(json.loads(text))
    return value[0] if isinstance(value,list) and len(value)==1 else value

def all_strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,list):
        for item in value:yield from all_strings(item)

def menu_items(layout):
    if isinstance(layout,list):
        if len(layout)==3 and type(layout[0]) is int and isinstance(layout[1],dict):
            yield layout[0],layout[1]
        for item in layout:yield from menu_items(item)

def punctuation_action(layout):
    candidates=[]
    for identifier,props in menu_items(layout):
        if props.get('enabled') is False or props.get('visible') is False:continue
        icon=props.get('icon-name','')
        if icon in ('fcitx-punc-active','fcitx-punc-inactive'):
            candidates.append((identifier,icon=='fcitx-punc-active'));continue
        label=props.get('label','').replace('&','').strip()
        parts=[part.strip() for part in label.split('→')]
        if len(parts)==2 and ((parts[0] in CHINESE and parts[1] in ENGLISH) or (parts[0] in ENGLISH and parts[1] in CHINESE)):
            candidates.append((identifier,parts[0] in CHINESE))
    # Never guess when several actions match, or when a custom schema hides/renames it.
    return candidates[0] if len(candidates)==1 else None

def args(service,path,interface,method,signature='',*values):
    return ['busctl','--user','--json=short','--timeout=2','call',service,path,interface,method]+([signature,*map(str,values)] if signature else [])

class Fcitx(QObject):
    def __init__(self,system):
        super().__init__(system);self.system=system;self.polling=False;self.after=None;self.engine=None;self.menu=None;self.action=None
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.refresh)
        if system.enabled:self.timer.start();QTimer.singleShot(0,self.refresh)
    def call(self,argv,callback,key='ime-read'):
        def result(ok,text):
            if not self.system.enabled:return
            try:value=bus_data(text) if ok and text.strip() else None
            except (ValueError,TypeError):ok=False;value=None
            callback(ok,value)
        self.system.commands.run(key,argv,result)
    def refresh(self,after=None):
        if not self.system.enabled:return
        if not callable(after) and self.system.busy.intersection(('ime','punctuation')):return
        if callable(after):self.after=after
        if self.polling:return
        self.polling=True
        def done():
            self.polling=False;self.system.changed.emit()
            callback=self.after;self.after=None
            if callback:callback()
        def fail():
            self.system.state.update(ime=None,punctuation=None);self.system.errors['ime']='无法连接 Fcitx5；需要运行 Fcitx5 并提供会话 D-Bus 与 busctl'
            done()
        def engine_result(active):
            def result(ok,engine):
                if not ok or not isinstance(engine,str):fail();return
                self.engine=engine;self.system.errors.pop('ime',None)
                if active==0:self.system.state['ime']=None;self.system.errors['ime']='当前没有可用的输入上下文';self.read_punctuation(done)
                elif engine.startswith('keyboard-') or active==1:self.system.state['ime']=False;self.read_punctuation(done)
                elif engine=='rime':
                    def ascii_result(ok,value):
                        self.system.state['ime']=not value if ok and type(value) is bool else None
                        if self.system.state['ime'] is None:self.system.errors['ime']='当前 Rime 未提供 IsAsciiMode 接口'
                        self.read_punctuation(done)
                    self.call(args(SERVICE,'/rime','org.fcitx.Fcitx.Rime1','IsAsciiMode'),ascii_result)
                elif engine in ('pinyin','shuangpin'):self.system.state['ime']=True;self.read_punctuation(done)
                else:self.system.state['ime']=None;self.system.errors['ime']='当前输入法尚未支持中／英文状态识别';self.read_punctuation(done)
            return result
        def state_result(ok,value):
            if not ok or type(value) is not int or value not in (0,1,2):fail();return
            self.call(args(SERVICE,'/controller',CONTROLLER,'CurrentInputMethod'),engine_result(value))
        self.call(args(SERVICE,'/controller',CONTROLLER,'State'),state_result)
    def read_punctuation(self,done):
        self.action=None;self.system.state['punctuation']=None
        self.system.errors['punctuation']='未找到可识别的标点开关；需要 Fcitx5 托盘菜单和方案的标点选项'
        if self.menu:
            service,path=self.menu
            def result(ok,layout):
                if not ok:self.menu=None
                else:
                    self.action=punctuation_action(layout)
                    if self.action:
                        self.system.state['punctuation']=self.action[1];self.system.errors.pop('punctuation',None)
                done()
            self.call(args(service,path,'com.canonical.dbusmenu','GetLayout','iias',0,3,0),result);return
        def watcher(ok,items):
            candidates=[v for v in all_strings(items) if re.fullmatch(r'(?::[0-9]+\.[0-9]+|[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)+)/[A-Za-z0-9_/]+',v)][:64] if ok else []
            def discover():
                if not candidates:done();return
                service,tail=candidates.pop(0).split('/',1);path='/'+tail
                def identify(ok,value):
                    if ok and value=='Fcitx':self.menu=(service,'/MenuBar');self.read_punctuation(done)
                    else:discover()
                self.call(args(service,path,'org.freedesktop.DBus.Properties','Get','ss','org.kde.StatusNotifierItem','Id'),identify)
            discover()
        self.call(args('org.kde.StatusNotifierWatcher','/StatusNotifierWatcher','org.freedesktop.DBus.Properties','Get','ss',
                       'org.kde.StatusNotifierWatcher','RegisteredStatusNotifierItems'),watcher)
    def finish_control(self,key,target):
        def verify():
            self.system.busy.discard(key)
            LOGGER.info('Input control readback key=%s target=%s actual=%s',key,target,self.system.state[key])
            if self.system.state[key] is not target:self.system.notice.emit('输入法状态未进入目标值；输入焦点可能已变化，或当前方案不支持此操作。')
            self.system.changed.emit()
        QTimer.singleShot(200,lambda:self.refresh(after=verify))
    def control_failure(self,key):
        self.system.busy.discard(key);self.system.notice.emit('Fcitx5 操作失败，请确认输入法服务、托盘和当前输入方案。');self.system.changed.emit()
    def toggle_mode(self):
        key='ime'
        if self.system.busy.intersection(('ime','punctuation')) or not self.system.enabled:return
        self.system.busy.add(key);self.system.changed.emit()
        def perform():
            current=self.system.state[key]
            if current is None:self.control_failure(key);return
            target=not current
            LOGGER.info('Input mode requested chinese=%s engine=%s',target,self.engine)
            def complete(ok,_):
                if ok:self.finish_control(key,target)
                else:self.control_failure(key)
            if not target:
                argv=args(SERVICE,'/rime','org.fcitx.Fcitx.Rime1','SetAsciiMode','b','true') if self.engine=='rime' else args(SERVICE,'/controller',CONTROLLER,'Deactivate')
                self.call(argv,complete,'ime-control');return
            def activated(ok,_):
                if not ok:complete(False,None);return
                def selected(ok,engine):
                    if not ok:complete(False,None)
                    elif engine=='rime':self.call(args(SERVICE,'/rime','org.fcitx.Fcitx.Rime1','SetAsciiMode','b','false'),complete,'ime-control')
                    elif engine in ('pinyin','shuangpin'):complete(True,None)
                    else:complete(False,None)
                self.call(args(SERVICE,'/controller',CONTROLLER,'CurrentInputMethod'),selected,'ime-control')
            self.call(args(SERVICE,'/controller',CONTROLLER,'Activate'),activated,'ime-control')
        self.refresh(after=perform)
    def toggle_punctuation(self):
        key='punctuation'
        if self.system.busy.intersection(('ime','punctuation')) or not self.system.enabled:return
        self.system.busy.add(key);self.system.changed.emit()
        def perform():
            if not self.menu:self.control_failure(key);return
            service,path=self.menu
            def shown(ok,_):
                if not ok:self.control_failure(key);return
                def refreshed():
                    if not self.action:self.control_failure(key);return
                    identifier,current=self.action
                    LOGGER.info('Punctuation requested chinese=%s',not current)
                    def clicked(ok,_):
                        if not ok:self.control_failure(key);return
                        def close_menu():
                            self.call(args(service,path,'com.canonical.dbusmenu','Event','isvu',0,'closed','i',0,0),
                                      lambda ok,_:self.finish_control(key,not current),'ime-control')
                        QTimer.singleShot(100,close_menu)
                    self.call(args(service,path,'com.canonical.dbusmenu','Event','isvu',identifier,'clicked','i',0,0),clicked,'ime-control')
                self.read_punctuation(refreshed)
            self.call(args(service,path,'com.canonical.dbusmenu','AboutToShow','i',0),shown,'ime-control')
        self.refresh(after=perform)
    def stop(self):self.timer.stop();self.after=None
