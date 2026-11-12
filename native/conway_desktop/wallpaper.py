"""Plasma 6 wallpaper bridge. Native QPainter frames; authenticated loopback only.

There is no HTML engine. The same model, controls and SQLite store serve both
the hidden native application and the Plasma WallpaperItem presentation.
"""
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import struct
import zlib
import numpy as np
from urllib.parse import urlsplit,parse_qs
from PySide6.QtCore import QObject,QTimer,QPointF,Qt
from PySide6.QtGui import QImage,QMouseEvent,QIcon,QPixmap,QPainter,QColor
from PySide6.QtNetwork import QTcpServer,QHostAddress
from PySide6.QtWidgets import QSystemTrayIcon,QMenu,QApplication
from .logging_setup import LOGGER

PLUGIN_ID='org.what20360.conway'
PORT=17832

def encode_frame(image):
    """Lossless RGB PNG with filter 0 and level 1; avoid costly adaptive filtering."""
    rgb=image.convertToFormat(QImage.Format.Format_RGB888);w,h=rgb.width(),rgb.height()
    raw=np.frombuffer(rgb.bits(),np.uint8).reshape(h,rgb.bytesPerLine())
    rows=np.zeros((h,w*3+1),np.uint8);rows[:,1:]=raw[:,:w*3]
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows.tobytes(),1))+chunk(b'IEND',b'')

def private_token(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    file=directory/'wallpaper-token'
    if not file.exists():
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as out:out.write(secrets.token_hex(32))
    file.chmod(0o600);token=file.read_text().strip()
    if len(token)!=64 or any(c not in '0123456789abcdef' for c in token):raise ValueError('壁纸连接凭据损坏；请关闭应用后删除 wallpaper-token 并重新安装壁纸插件')
    return token

def install_plugin(data,check_plasma=True):
    if check_plasma:
        program=shutil.which('plasmashell')
        if not program:raise RuntimeError('未找到 Plasma；壁纸插件需要 Plasma 6，普通窗口仍可独立使用')
        result=subprocess.run([program,'--version'],capture_output=True,text=True,timeout=10)
        import re
        if not re.search(r'plasmashell\s+6\.',result.stdout+'\n'+result.stderr):raise RuntimeError('当前壁纸插件需要 Plasma 6；Plasma 5 尚未支持')
    root=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'plasma/wallpapers'
    root.mkdir(parents=True,exist_ok=True);destination=root/PLUGIN_ID
    source=Path(__file__).parents[1]/'plasma-wallpaper'
    token=private_token(data)
    stage=Path(tempfile.mkdtemp(prefix=PLUGIN_ID+'-',dir=root));backup=None
    try:
        shutil.copytree(source,stage,dirs_exist_ok=True)
        connection=stage/'contents/ui/Connection.qml'
        connection.write_text('import QtQml\nQtObject {\n    readonly property string token: '+json.dumps(token)+'\n    readonly property string endpoint: "http://127.0.0.1:'+str(PORT)+'"\n}\n')
        connection.chmod(0o600)
        if destination.exists():
            backup=root/(PLUGIN_ID+'.old-'+secrets.token_hex(4));destination.rename(backup)
        try:stage.rename(destination)
        except BaseException:
            if backup:backup.rename(destination);backup=None
            raise
        if backup:shutil.rmtree(backup)
    finally:
        if stage.exists():shutil.rmtree(stage)
    LOGGER.info('Plasma wallpaper plugin installed id=%s',PLUGIN_ID)
    return destination

class WallpaperServer(QObject):
    def __init__(self,view,token,port=PORT,parent=None):
        super().__init__(parent);self.view=view;self.token=token;self.pending={};self.sockets=set();self.cache=None
        self._signature=None;self._revision=0
        self.server=QTcpServer(self)
        if not self.server.listen(QHostAddress('127.0.0.1'),port):raise RuntimeError('壁纸后台端口被占用：'+self.server.errorString())
        self.server.newConnection.connect(self.accept)
        self.release_timer=QTimer(self);self.release_timer.setSingleShot(True);self.release_timer.setInterval(3000)
        self.release_timer.timeout.connect(self.release_pointer)
        LOGGER.info('Wallpaper bridge listening on loopback port=%s',self.server.serverPort())
    def accept(self):
        while self.server.hasPendingConnections():
            socket=self.server.nextPendingConnection()
            if len(self.sockets)>=16:socket.abort();socket.deleteLater();continue
            self.sockets.add(socket);self.pending[socket]=bytearray()
            timer=QTimer(socket);timer.setSingleShot(True);timer.setInterval(5000)
            timer.timeout.connect(lambda s=socket:s.abort());timer.start()
            socket.readyRead.connect(lambda s=socket:self.read(s))
            def disconnected(s=socket,t=timer):
                self.pending.pop(s,None);self.sockets.discard(s);t.stop()
                s.readyRead.disconnect();s.disconnected.disconnect();t.timeout.disconnect();s.deleteLater()
            socket.disconnected.connect(disconnected)
    def reply(self,socket,status,body=b'',mime='application/json'):
        self.pending.pop(socket,None)
        reason={200:'OK',400:'Bad Request',401:'Unauthorized',404:'Not Found',413:'Too Large',503:'Unavailable'}[status]
        headers=f'HTTP/1.1 {status} {reason}\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n'
        socket.write(headers.encode()+body);socket.disconnectFromHost()
    def read(self,socket):
        if socket not in self.pending:return
        data=self.pending[socket];data.extend(bytes(socket.readAll()))
        if len(data)>32768:self.reply(socket,413);return
        marker=data.find(b'\r\n\r\n')
        if marker<0:return
        try:
            lines=bytes(data[:marker]).decode('ascii').split('\r\n')
            method,target,version=lines[0].split(' ')
            if version!='HTTP/1.1':raise ValueError('version')
            headers={}
            for line in lines[1:]:
                name,value=line.split(':',1);name=name.lower()
                if name in headers:raise ValueError('duplicate header')
                headers[name]=value.strip()
            length=int(headers.get('content-length','0'))
            if not 0<=length<=16384 or 'transfer-encoding' in headers:raise ValueError('length')
            if len(data)<marker+4+length:return
            url=urlsplit(target);query=parse_qs(url.query)
            supplied=headers.get('authorization','').removeprefix('Bearer ')
            # Images have no custom-header API; the frame-only token can also be a query.
            if method=='GET' and url.path=='/frame':supplied=query.get('token',[''])[0]
            if headers.get('origin','') not in ('','null') or not hmac.compare_digest(supplied,self.token):
                self.reply(socket,401);return
            if method=='GET' and url.path=='/status':
                self.reply(socket,200,json.dumps({'revision':self.revision()}).encode())
            elif method=='GET' and url.path=='/frame':
                w=int(query.get('w',['1920'])[0]);h=int(query.get('h',['1080'])[0]);self.dimensions(w,h)
                # Coalesce simultaneous consumers, without keeping historical images.
                key=(w,h,self.revision())
                if not self.cache or self.cache[0]!=key:self.cache=(key,encode_frame(self.view.render_image(w,h)))
                self.reply(socket,200,self.cache[1],'image/png')
            elif method=='POST' and url.path=='/input':
                event=json.loads(bytes(data[marker+4:marker+4+length]))
                self.validate_input(event)
                self.reply(socket,200,b'{}')
                # Respond before native file dialogs enter their own event loop.
                QTimer.singleShot(0,lambda e=event:self.input(e))
            else:self.reply(socket,404)
        except (ValueError,KeyError,TypeError,UnicodeError):self.reply(socket,400)
        except Exception:LOGGER.exception('Wallpaper request failed');self.reply(socket,503)
    def revision(self):
        view=self.view;m=view.m
        fade=zlib.crc32((m.fade/.15).astype(np.uint8).tobytes()) if m.trails else 0
        signature=(tuple(m.settings().items()),zlib.crc32(m.cells.tobytes()),fade,int(view.wall_time),
                   tuple(view.system.state.items()),frozenset(view.system.busy),view.deck,view.page,view.backup_index,
                   zlib.crc32(view.preview.tobytes()) if view.preview is not None else 0,
                   view.hover.x() if view.hover else None,view.hover.y() if view.hover else None,
                   view.storage_failed)
        if signature!=self._signature:self._signature=signature;self._revision+=1
        return self._revision
    @staticmethod
    def dimensions(w,h):
        if type(w) is not int or type(h) is not int or not 640<=w<=2560 or not 360<=h<=1440:raise ValueError('dimensions')
    def validate_input(self,event):
        if not isinstance(event,dict):raise ValueError('event')
        if event.get('kind')=='command':
            if event.get('name') not in ('window','run','logs'):raise ValueError('command')
            return
        if event.get('kind') not in ('press','move','release','cancel'):raise ValueError('kind')
        self.dimensions(event['w'],event['h'])
        if type(event.get('x')) is not int or type(event.get('y')) is not int or not 0<=event['x']<event['w'] or not 0<=event['y']<event['h']:raise ValueError('position')
        if type(event.get('shift',False)) is not bool:raise ValueError('shift')
    def input(self,event):
        try:
            self.cache=None;view=self.view
            if event['kind']=='command':
                if event['name']=='window':view.showNormal();view.raise_();view.activateWindow()
                elif event['name']=='run':view.run_toggle()
                elif event['name']=='logs':view.open_logs()
                return
            # Rebuild hit regions for this screen, including when several screens share a model.
            view.render_image(event['w'],event['h'])
            ratio=view.devicePixelRatioF();point=QPointF(event['x']/ratio,event['y']/ratio)
            kind=event['kind'];button=Qt.MouseButton.LeftButton
            modifier=Qt.KeyboardModifier.ShiftModifier if event.get('shift') else Qt.KeyboardModifier.NoModifier
            if kind in ('release','cancel'):self.release_pointer();return
            event_type=QMouseEvent.Type.MouseButtonPress if kind=='press' else QMouseEvent.Type.MouseMove
            mouse=QMouseEvent(event_type,point,point,button if kind=='press' else Qt.MouseButton.NoButton,button,modifier)
            if kind=='press':view.mousePressEvent(mouse)
            else:view.mouseMoveEvent(mouse)
            if view.stroke:self.release_timer.start()
        except Exception:LOGGER.exception('Wallpaper input failed');self.release_pointer()
    def release_pointer(self):
        self.release_timer.stop()
        if self.view.stroke:
            self.view.stroke=None;self.view.clock.reset(speed=self.view.m.speed);self.view.checkpoint()
    def stop(self):
        self.release_pointer();self.server.close()
        for socket in list(self.sockets):socket.abort()

def desktop_command(data=None):
    launcher=Path.home()/'.local/bin/conway-desktop'
    command=[str(launcher),'--wallpaper'] if launcher.is_file() else [sys.executable,str(Path(__file__).parents[1]/'run.py'),'--wallpaper']
    return command+(['--data-dir',str(data)] if data else [])

def autostart_file():return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'autostart/conway-wallpaper.desktop'

def set_autostart(enabled,data=None):
    file=autostart_file()
    if not enabled:file.unlink(missing_ok=True);return
    # Desktop Entry Exec quoting, not shell quoting.
    command=' '.join('"'+arg.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"' for arg in desktop_command(data))
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text('[Desktop Entry]\nType=Application\nName=生命场壁纸后台\nExec='+command+'\nIcon=applications-graphics\nTerminal=false\nX-KDE-autostart-after=panel\n')

def create_tray(view,data=None):
    if not QSystemTrayIcon.isSystemTrayAvailable():LOGGER.warning('System tray unavailable');return None
    icon=QIcon.fromTheme('applications-graphics')
    if icon.isNull():
        pixmap=QPixmap(24,24);pixmap.fill(QColor('#0a1218'));p=QPainter(pixmap)
        for x,y in ((1,0),(2,1),(0,2),(1,2),(2,2)):p.fillRect(3+x*6,3+y*6,5,5,QColor('#a2dfb8'))
        p.end();icon=QIcon(pixmap)
    tray=QSystemTrayIcon(icon,view);menu=QMenu(view)
    menu.addAction('打开控制窗口',lambda:(view.showNormal(),view.raise_(),view.activateWindow()))
    menu.addAction('暂停／继续',view.run_toggle);menu.addAction('打开日志目录',view.open_logs)
    if view.wallpaper_mode:
        auto=menu.addAction('登录时启动壁纸后台');auto.setCheckable(True);auto.setChecked(autostart_file().exists())
        def toggle(value):
            try:set_autostart(value,data)
            except OSError as exc:auto.setChecked(not value);view.error('设置自动启动失败：'+str(exc))
        auto.triggered.connect(toggle)
    menu.addSeparator()
    def quit_app():view.wallpaper_mode=False;view.close();QApplication.quit()
    menu.addAction('退出生命场',quit_app);tray.setContextMenu(menu);tray.setToolTip('生命场 · 壁纸后台' if view.wallpaper_mode else '生命场')
    tray.activated.connect(lambda reason:view.showNormal() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show();return tray
