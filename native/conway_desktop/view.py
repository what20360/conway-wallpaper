"""Native physical-pixel renderer and mouse control surface."""
import datetime as dt
import json
import math
from pathlib import Path
import time
import numpy as np
from PySide6.QtCore import Qt,QTimer,QPoint,QRect,QRectF,QUrl
from PySide6.QtGui import QColor,QImage,QPainter,QPen,QFont,QDesktopServices
from PySide6.QtWidgets import QWidget,QFileDialog,QMessageBox
from .model import W,H,SPEEDS,SPEED_LABELS,PALETTES,random_cells,default_cells,Clock
from .formats import encode_life,decode_life
from .logging_setup import LOGGER,log_dir

PIXELS=json.loads(Path(__file__).with_name('pixels.json').read_text())
GLYPHS=PIXELS['glyphs']; ICONS=PIXELS['icons']
GLYPHS['%']={'w':5,'r':[25,26,2,4,8,11,19]}
GLYPHS.update({'中':{'w':9,'r':[16,16,511,273,273,511,16,16,16]},
               '英':{'w':9,'r':[68,511,68,16,254,146,254,40,68,387]},
               '，':{'w':3,'r':[0,0,0,3,3,2,4]},
               '。':{'w':5,'r':[0,0,0,14,17,17,14]},
               ',':{'w':3,'r':[0,0,0,0,3,2,4]}})
DATE_GLYPHS=json.loads(Path(__file__).with_name('date-pixels.json').read_text())
ICONS.update({
 'close':['1000001','0100010','0010100','0001000','0010100','0100010','1000001'],
 'wifi':['0111110','1000001','0011100','0100010','0000000','0001000'],
 'bluetooth':['0001000','0001100','0101010','0011100','0011100','0101010','0001100'],
 'volume':['0001000','0011001','1111010','1111010','1111010','0011001','0001000'],
 'mute':['0001000','0011000','1111011','1111000','1111011','0011000','0001000']})
THEMES={
 'night':dict(bg='#0a1218',panel='#0d1820',grid='#14232b',line='#29404a',muted='#67818e',text='#b9cbd0',life='#a2dfb8',clock='#91bbd6',speed='#d5b789',archive='#b5a2cc',off='#1b303a',danger='#dc9b8c'),
 'day':dict(bg='#e7eae0',panel='#dce2d9',grid='#d6ddd2',line='#b3c1b5',muted='#687e73',text='#334d48',life='#3e7960',clock='#4e7086',speed='#98713d',archive='#796382',off='#c5d0c3',danger='#a35e4a')}
THEMES['ice']={**THEMES['night'],'life':'#9dcbe6','clock':'#c4d6f2'}
THEMES['violet']={**THEMES['night'],'life':'#c7b0e6','clock':'#a9cae0'}
THEMES['sand']={**THEMES['day'],'bg':'#eee5d2','panel':'#e6dac3','life':'#996b49'}
THEMES['forest']={**THEMES['day'],'bg':'#dfe9df','panel':'#d0dfd2','life':'#386c50'}

def speed_from_position(position,width):
    return max(0,min(7,int(position*8/max(1,width))))

def percent_label(value):return '--%' if value is None else f'{max(0,min(100,round(value)))}%'

def rate_label(value):
    if value is None:return '---'
    value=max(0,int(value))
    for divisor,unit in ((1024*1024,'M'),(1024,'K'),(1,'B')):
        if value>=divisor or divisor==1:return str(value//divisor)+unit

def wifi_label(state):
    if not state.get('wifi'):return '---'
    name=state.get('ssid')
    return name if name else ('[隐藏网络]' if name=='' else '---')

def ssid_bitmap(name,width,height,color):
    # Rasterize Unicode glyphs once at low resolution, then use exact 2x blocks.
    scale=2;w=max(1,width//scale);h=max(1,height//scale)
    image=QImage(w,h,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.TextAntialiasing,False)
    font=QFont('Sans Serif');font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    clean=''.join(ch if ch.isprintable() else ' ' for ch in name)
    for size in (8,7,6):
        font.setPixelSize(size);painter.setFont(font)
        if painter.fontMetrics().boundingRect(QRect(0,0,w,10000),Qt.TextFlag.TextWrapAnywhere,clean).height()<=h:break
    painter.setPen(color)
    painter.drawText(QRect(0,0,w,h),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWrapAnywhere,clean)
    painter.end();return image.scaled(w*scale,h*scale,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.FastTransformation)

def geometry(width,height):
    k=max(1,min(width//320,height//180))
    return k,(width-320*k)//2,(height-180*k)//2

class View(QWidget):
    def __init__(self,model,store,system):
        super().__init__();self.m=model;self.store=store;self.system=system
        self.clock=Clock();self.stroke=None;self.hover=None;self.regions=[];self.last_save=0;self.wallpaper_mode=False
        self.page='bank';self.deck='patterns';self.backup_index=0;self.preview=None;self._grid_cache=None
        self._ssid_cache=None;self._ssid_rect=None;self.feedback=False;self.storage_failed=False;self.last_frame=time.monotonic();self.wall_time=time.time()
        self.setWindowTitle('生命场 · 原生实验版');self.setMinimumSize(640,360)
        self.setMouseTracking(True);self.resize(1280,720)
        self.timer=QTimer(self);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16);self.timer.timeout.connect(self.tick);self.timer.start()
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.setInterval(200)
        self.debounce.timeout.connect(self.checkpoint)
        self.system.changed.connect(self.system_changed);self.system.notice.connect(self.error)
        self._system_theme=None;self.refresh_preview()
    def system_changed(self):
        value=self.system.state['theme']
        if value and value!=self._system_theme:
            initial=self._system_theme is None;self._system_theme=value
            if not initial:self.m.palette=value;self.debounce.start()
        self.update()
    def unavailable(self,name):
        key='audio' if name in ('volume','mute','volume-bar') else 'theme' if name in ('sun','moon') else name
        message=self.system.errors.get(key)
        if name=='save' and self.m.mode=='random':message='请先切换到 P 预设模式再保存。'
        if not self.system.enabled:message='当前以 --no-system 或渲染模式运行，系统控制已禁用。'
        self.error(message or '这个功能当前不可用，请检查对应工具、服务和设备。')
    def open_logs(self):
        directory=log_dir()
        if directory:QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        else:self.error('当前渲染／测试模式没有启用文件日志。')
    def error(self,message):
        LOGGER.error('UI notice: %s',message)
        print(message,flush=True)
        QMessageBox.warning(self,'生命场',message[:1600])
    def checkpoint(self):
        if not self.store:return
        try:self.store.checkpoint(self.m);self.last_save=time.monotonic();self.storage_failed=False;LOGGER.debug('Checkpoint saved generation=%s',self.m.generation)
        except Exception as exc:
            self.storage_failed=True
            LOGGER.exception('Checkpoint save failed')
            print('检查点保存失败:',exc,flush=True)
        self.update()
    def changed(self):self.debounce.start();self.update()
    def tick(self):
        now=time.monotonic();self.wall_time=time.time();active=self.m.running and self.stroke is None
        if self.clock.due(self.m.speed,active,wall=self.wall_time,mono=now):self.m.step()
        elapsed=min(.2,max(0,now-self.last_frame));self.last_frame=now
        if self.m.trails:self.m.fade*=math.exp(-elapsed*6)
        if self.store and now-self.last_save>=10:self.checkpoint()
        self.update()
    def refresh_preview(self):
        try:
            if self.page=='backups':
                backups=self.store.backups() if self.store else []
                self.backup_index=min(self.backup_index,max(0,len(backups)-1))
                self.preview=decode_life(backups[self.backup_index][1])[2] if backups else np.zeros((H,W),dtype=np.uint8)
            elif self.m.mode=='random':self.preview=random_cells(self.m.seed)
            else:self.preview=self.store.slot(self.m.preset) if self.store else default_cells(self.m.preset)
        except Exception as exc:self.error(str(exc))
        self.update()
    def select(self,n):self.m.select(n);self.refresh_preview();self.changed()
    def toggle_mode(self):
        self.m.mode='random' if self.m.mode=='preset' else 'preset';self.refresh_preview();self.changed()
    def run_toggle(self):self.m.running=not self.m.running;self.clock.reset(speed=self.m.speed);self.changed()
    def single_step(self):self.m.running=False;self.m.step();self.clock.reset(speed=self.m.speed);self.changed()
    def speed(self,i):self.m.speed=SPEEDS[i];self.clock.reset(speed=self.m.speed);self.changed()
    def palette(self):self.m.palette=PALETTES[(PALETTES.index(self.m.palette)+1)%len(PALETTES)];self.changed()
    def load_selected(self):
        if self.page!='bank':return
        self.m.load(self.preview);self.clock.reset(speed=self.m.speed);self.changed()
    def save_slot(self):
        if not self.store or self.m.mode!='preset':return
        try:self.store.save(self.m.preset,self.m.cells);self.refresh_preview();self.feedback=True;self.changed()
        except Exception as exc:self.error('预设保存失败：'+str(exc))
    def clear(self):self.m.cells.fill(0);self.m.fade.fill(0);self.m.generation=0;self.changed()
    def brush(self):self.m.brush={1:3,3:5,5:1}[self.m.brush];self.changed()
    def trails(self):self.m.trails=not self.m.trails;self.m.fade.fill(0);self.changed()
    def fullscreen(self):self.showNormal() if self.isFullScreen() else self.showFullScreen()
    def backups(self):
        self.page='bank' if self.page=='backups' else 'backups';self.backup_index=0;self.refresh_preview()
    def switch_deck(self):
        self.deck='information' if self.deck=='patterns' else 'patterns';self.update()
    def backup_move(self,n):
        items=self.store.backups() if self.store else []
        if items:self.backup_index=(self.backup_index+n)%len(items);self.refresh_preview()
    def export(self,bank=False):
        if not self.store:return
        try:
            if bank:data=self.store.export_bank();name='life-bank.lifebank'
            elif self.page=='backups':
                items=self.store.backups()
                if not items:return
                data=items[self.backup_index][1];name='replaced.life'
            else:data=encode_life(self.preview,self.m.index);name=f'{self.m.index:03}.life'
            file,_=QFileDialog.getSaveFileName(self,'导出',name,'生命场文件 (*.life *.lifebank)')
            if file:
                # Temporary file + atomic replacement, so failed writes preserve prior file.
                import os,tempfile
                target=Path(file);temp=None
                try:
                    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as out:
                        temp=Path(out.name);out.write(data);out.flush();os.fsync(out.fileno())
                    os.replace(temp,target)
                finally:
                    if temp and temp.exists():temp.unlink()
        except Exception as exc:self.error('导出失败：'+str(exc))
    def import_file(self):
        file,_=QFileDialog.getOpenFileName(self,'导入预设或预设库','','生命场文件 (*.life *.lifebank)')
        if not file:return
        try:
            if Path(file).stat().st_size>16*1024*1024:raise ValueError('文件超过 16 MiB')
            data=Path(file).read_bytes()
            if data[:4]==b'LIF3':
                index,_,cells=decode_life(data);self.m.mode='preset';self.m.preset=index;self.m.load(cells)
            else:self.store.import_bank(data)
            self.page='bank';self.refresh_preview();self.changed()
        except Exception as exc:self.error('导入失败，原有预设未改变：'+str(exc))
    def draw_scene(self,p,width,height):
        k,ox,oy=geometry(width,height);self.frame=(k,ox,oy)
        t={key:QColor(value) for key,value in THEMES[self.m.palette].items()}
        p.setRenderHint(QPainter.RenderHint.Antialiasing,False)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False);p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(0,0,width,height,t['bg']);world=QRect(ox,oy,W*k,H*k)
        cache_key=(k,self.m.palette)
        if not self._grid_cache or self._grid_cache[0]!=cache_key:
            grid=QImage(W*k,H*k,QImage.Format.Format_RGB32);grid.fill(t['bg']);g=QPainter(grid)
            g.setPen(Qt.PenStyle.NoPen);g.setBrush(t['grid'])
            g.drawRects([QRect(x*k+k//2,y*k+k//2,1,1) for y in range(H) for x in range(W)])
            g.end();self._grid_cache=(cache_key,grid)
        p.drawImage(QPoint(ox,oy),self._grid_cache[1])
        if self.m.trails:
            for level in (1,2,3):
                yy,xx=np.nonzero((self.m.fade>level*.15)&(self.m.fade<=(level+1)*.15)&(self.m.cells==0))
                color=QColor(t['life']);color.setAlpha(15*level);p.setBrush(color)
                p.drawRects([QRect(ox+int(x)*k+1,oy+int(y)*k+1,k-1,k-1) for y,x in zip(yy,xx)])
        yy,xx=np.nonzero(self.m.cells);p.setBrush(t['life'])
        p.drawRects([QRect(ox+int(x)*k,oy+int(y)*k,max(1,k-1),max(1,k-1)) for y,x in zip(yy,xx)])
        side=ox+W*k;sw=64*k;sh=180*k
        p.fillRect(side,oy,sw,sh,t['panel'])
        unit=min(sw/320,(sh-max(48,sh*.06))/850);left=side+(sw-320*unit)/2;top=oy
        self.regions=[]
        def rect(x,y,w,h):return QRect(round(left+x*unit),round(top+y*unit),round(w*unit),round(h*unit))
        def dot(x,y,size,color):p.fillRect(rect(x,y,size,size),color)
        def text(x,y,value,size,color,right=False,font=None):
            font=font or GLYPHS
            size=max(1,round(size*unit));value=str(value)
            length=sum((font.get(ch,GLYPHS['?'])['w']+1)*size for ch in value)-size
            px=round(left+x*unit)-(length if right else 0);py=round(top+y*unit)
            for ch in value:
                glyph=font.get(ch,GLYPHS['?'])
                for row,bits in enumerate(glyph['r']):
                    for col in range(glyph['w']):
                        if bits&(1<<(glyph['w']-col-1)):p.fillRect(px+col*size,py+row*size,max(1,size-1),max(1,size-1),color)
                px+=(glyph['w']+1)*size
        def icon(x,y,name,color,size=3):
            for yy,row in enumerate(ICONS[name]):
                for xx,ch in enumerate(row):
                    if ch=='1':dot(x+xx*size,y+yy*size,size*.8,color)
        def region(name,x,y,w,h,action,enabled=True):
            r=rect(x,y,w,h)
            self.regions.append((r,action if enabled else lambda:self.unavailable(name),name))
            if self.hover and r.contains(self.hover):
                for px,py in ((r.left(),r.top()),(r.right()-5,r.top()),(r.left(),r.bottom()-5),(r.right()-5,r.bottom()-5)):
                    p.fillRect(px,py,5,2,t['line']);p.fillRect(px,py,2,5,t['line'])
        def button(name,x,y,action,on=False,color='life',enabled=True):
            region(name,x,y,48,48,action,enabled);icon(x+13,y+13,name,t[color] if on and enabled else t['muted'] if enabled else t['off'])
        def toggle(x,y,value,action,name):
            region(name,x,y,58,48,lambda:action() if name not in self.system.busy else None,value is not None)
            # Large tile + thumb position distinguish power even without relying on hue.
            p.fillRect(rect(x,y,58,43),t['life'] if value else t['off'])
            ink=t['panel'] if value else t['muted']
            icon(x+19,y+3,name,ink,3)
            p.fillRect(rect(x+7,y+29,44,10),t['panel'] if value else t['line'])
            p.fillRect(rect(x+(35 if value else 9),y+31,14,6),t['life'] if value else t['muted'])
            if name in self.system.busy:p.fillRect(rect(x,y,58,4),t['speed'])
            if value is None:text(x+25,y+8,'?',2,t['muted'])
            if name=='bluetooth' and value:
                count=self.system.state.get('connected')
                if count is None:text(x+24,y+46,'?',1,t['muted'])
                elif count>8:text(x+12,y+46,str(count),1.5,t['clock'])
                else:
                    for i in range(count):dot(x+6+i*6,y+46,4,t['clock'])
        def separator(y):
            for x in range(24,296,8):dot(x,y,2,t['line'])
        now=dt.datetime.fromtimestamp(self.wall_time)
        region('logs',20,0,32,28,self.open_logs)
        dot(25,9,4,t['danger'] if self.storage_failed else t['life'])
        region('page-switch',258,0,40,28,self.switch_deck)
        text(270,3,'P' if self.deck=='patterns' else 'I',2.5,t['clock'])
        text(24,32,now.strftime('%H:%M'),7,t['clock']);text(296,67,now.strftime('%S'),3,t['clock'],True)
        text(24,104,now.strftime('%Y.%m.%d'),3,t['text'],font=DATE_GLYPHS);text(296,104,now.isoweekday(),3,t['clock'],True)
        generation=str(self.m.generation).zfill(10)
        text(24,145,'G',3,t['life']);text(296,145,generation,min(3,240/(6*len(generation))),t['life'],True)
        for x,label,key in ((24,'C','cpu'),(174,'M','memory')):
            text(x,176,label,2.5,t['muted']);text(x+30,176,percent_label(self.system.state[key]),2.5,t['clock'])
        for x,name,key in ((24,'down','download'),(174,'up','upload')):
            icon(x,194,name,t['muted'],1.2);text(x+30,194,rate_label(self.system.state.get(key)),2.1,t['clock'])
        separator(213)
        region('run',24,220,48,48,self.run_toggle)
        for y in range(7):
            for x in range(7):
                if self.m.running or x in (0,6) or y in (0,6):dot(31+x*5,227+y*5,4,t['life'] if self.m.running else t['line'])
        button('step',99,220,self.single_step)
        theme=self.system.state['theme'];button('sun' if theme=='day' else 'moon',174,220,self.system.theme,True,'clock',theme is not None)
        region('palette',249,220,48,48,self.palette)
        for y in range(6):
            for x in range(6):dot(258+x*5,229+y*5,4,t[('life','clock','speed','archive')[(x//3+2*(y//3))%4]])
        text(24,282,SPEED_LABELS[SPEEDS.index(self.m.speed)],2.5,t['speed'])
        bar=rect(24,313,272,28)
        region('speed-bar',24,313,272,28,lambda:self.speed(speed_from_position(self.hover.x()-bar.x(),bar.width())))
        p.fillRect(bar,t['off']);selected=SPEEDS.index(self.m.speed)
        for column in range(40):
            x1=bar.x()+column*bar.width()//40;x2=bar.x()+(column+1)*bar.width()//40
            for row in range(3):
                y1=bar.y()+row*bar.height()//3;y2=bar.y()+(row+1)*bar.height()//3
                p.fillRect(x1,y1,max(1,x2-x1-1),max(1,y2-y1-1),t['speed'] if column//5<=selected else t['off'])
        separator(374)
        if self.deck=='information':
            state=self.system.state
            text(24,392,'IME',3,t['clock']);text(296,399,'FCITX5',2,t['muted'],True)
            for x,key,label,action in ((24,'ime','IME',self.system.ime.toggle_mode),(174,'punctuation','PUNC',self.system.ime.toggle_punctuation)):
                value=state[key];busy=bool(self.system.busy.intersection(('ime','punctuation')))
                enabled=value is not None
                region(key,x,437,122,94,lambda action=action:action() if not self.system.busy.intersection(('ime','punctuation')) else None,enabled)
                p.fillRect(rect(x,437,122,94),t['life'] if value else t['clock'] if value is False else t['off'])
                color=t['panel'] if value is not None else t['muted']
                text(x+10,443,label,1.8,color)
                symbols=('中' if value else '英') if key=='ime' else ('，。' if value else ',.')
                text(x+(42 if key=='ime' else 38),466,symbols if value is not None else '?',4,color)
                if busy:p.fillRect(rect(x,437,122,5),t['speed'])
            for y,name,key in ((563,'down','download'),(607,'up','upload')):
                icon(24,y,name,t['clock'],3)
                text(296,y,rate_label(state.get(key)),3,t['clock'],True)
        else:
            if self.page=='bank':
                region('mode',24,388,48,48,self.toggle_mode)
                if self.m.mode=='preset':text(36,397,'P',4,t['life'])
                else:icon(34,399,'dice',t['speed'],3)
                button('left',92,388,lambda:self.select(self.m.index-1));text(150,398,f'{self.m.index:03}',4,t['life'])
                button('right',249,388,lambda:self.select(self.m.index+1))
                for i in range(8):
                    bit=128>>i;x=24+i*34;region('bit'+str(bit),x,451,28,27,lambda bit=bit:self.select(self.m.index^bit))
                    for y in range(4):
                        for xx in range(4):dot(x+xx*6,451+y*6,4,t['life'] if self.m.index&bit else t['off'])
            else:
                button('stack',24,388,self.backups,True,'archive');items=self.store.backups() if self.store else []
                text(105,399,f'{self.backup_index+1 if items else 0}/{len(items)}',3,t['archive'])
                button('left',24,445,lambda:self.backup_move(-1));button('right',249,445,lambda:self.backup_move(1))
            box=rect(24,493,272,106);p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(t['line'],1));p.drawRect(box);p.setPen(Qt.PenStyle.NoPen)
            if self.preview is not None and self.preview.any():
                ys,xs=np.nonzero(self.preview);bw=int(xs.max()-xs.min()+1);bh=int(ys.max()-ys.min()+1)
                ps=max(1,min(box.width()//(bw+4),box.height()//(bh+4),12))
                # Large patterns are sampled only in preview; stored grid remains full-size.
                if bw*ps>box.width() or bh*ps>box.height():
                    img=QImage(W,H,QImage.Format.Format_RGB32);img.fill(t['panel']);ip=QPainter(img);ip.setPen(Qt.PenStyle.NoPen);ip.setBrush(t['life']);ip.drawRects([QRect(int(x),int(y),1,1) for y,x in zip(ys,xs)]);ip.end()
                    p.drawImage(box,img)
                else:
                    bx=box.x()+(box.width()-bw*ps)//2;by=box.y()+(box.height()-bh*ps)//2;p.setBrush(t['life'])
                    p.drawRects([QRect(bx+(int(x)-int(xs.min()))*ps,by+(int(y)-int(ys.min()))*ps,max(1,ps-1),max(1,ps-1)) for y,x in zip(ys,xs)])
            region('load',24,493,272,106,self.load_selected,self.page=='bank')
            if self.page=='bank':
                button('save',24,612,self.save_slot,self.store.custom(self.m.preset) if self.store else False,'life',self.m.mode=='preset')
                button('down',99,612,self.export,False,'archive');button('up',174,612,self.import_file,False,'clock');button('stack',249,612,self.backups,True,'archive')
            else:
                button('down',174,612,self.export,False,'archive');button('save',249,612,lambda:self.export(True),True,'archive')
        separator(671)
        state=self.system.state;volume=state['volume']
        muted=state['muted'] is True
        if muted:p.fillRect(rect(24,682,48,48),t['danger'])
        region('mute' if muted else 'volume',24,682,48,48,self.system.mute,volume is not None)
        icon(37,695,'volume',t['panel'] if muted else t['clock'] if volume is not None else t['off'])
        if muted:
            # A broad diagonal crosses the entire speaker tile, not a few icon pixels.
            for i in range(9):p.fillRect(rect(29+i*4,687+i*4,6,6),t['panel'])
        region('volume-bar',90,685,206,36,lambda:self.system.volume(max(0,min(1,(self.hover.x()-rect(90,685,206,36).x())/rect(90,685,206,36).width()))),volume is not None)
        for i in range(20):dot(92+i*10,696,7,t['line'] if muted else t['clock'] if volume is not None and i<round(volume*20) else t['off'])
        toggle(24,737,state['wifi'],self.system.wifi,'wifi');toggle(99,737,state['bluetooth'],self.system.bluetooth,'bluetooth')
        label=wifi_label(state);self._ssid_rect=rect(174,737,122,46)
        key=(label,self._ssid_rect.width(),self._ssid_rect.height(),self.m.palette)
        if not self._ssid_cache or self._ssid_cache[0]!=key:
            self._ssid_cache=(key,ssid_bitmap(label,self._ssid_rect.width(),self._ssid_rect.height(),t['clock']))
        p.drawImage(self._ssid_rect.topLeft(),self._ssid_cache[1])
        if self.system.busy:dot(159,760,4,t['speed'])
        separator(789)
        button('clear',24,800,self.clear,False,'danger');button('brush',92,800,self.brush,self.m.brush>1)
        text(155,812,self.m.brush,3,t['life']);button('trail',190,800,self.trails,self.m.trails);button('full',249,800,self.fullscreen)
    def paintEvent(self,event):
        p=QPainter(self);ratio=self.devicePixelRatioF();p.scale(1/ratio,1/ratio)
        self.draw_scene(p,round(self.width()*ratio),round(self.height()*ratio));p.end()
    def render_image(self,width,height):
        image=QImage(width,height,QImage.Format.Format_RGB32);p=QPainter(image);self.draw_scene(p,width,height);p.end();return image
    def _physical(self,event):
        ratio=self.devicePixelRatioF();return QPoint(round(event.position().x()*ratio),round(event.position().y()*ratio))
    def _cell(self,point):
        k,ox,oy=getattr(self,'frame',geometry(round(self.width()*self.devicePixelRatioF()),round(self.height()*self.devicePixelRatioF())))
        x=(point.x()-ox)//k;y=(point.y()-oy)//k
        return (x,y) if 0<=x<W and 0<=y<H else None
    def mousePressEvent(self,event):
        point=self._physical(event);self.hover=point
        for rect,action,name in self.regions:
            if rect.contains(point):
                if event.button()==Qt.MouseButton.LeftButton:action()
                return
        cell=self._cell(point)
        if cell and event.button() in (Qt.MouseButton.LeftButton,Qt.MouseButton.RightButton):
            erase=event.button()==Qt.MouseButton.RightButton or bool(event.modifiers()&Qt.KeyboardModifier.ShiftModifier)
            self.stroke=(cell,erase);self.m.paint(*cell,erase);self.update()
    def mouseMoveEvent(self,event):
        point=self._physical(event);self.hover=point
        if self._ssid_rect and self._ssid_rect.contains(point):self.setToolTip(wifi_label(self.system.state))
        else:self.setToolTip('')
        if self.stroke:
            cell=self._cell(point)
            if cell:
                old,erase=self.stroke;n=max(abs(old[0]-cell[0]),abs(old[1]-cell[1]),1)
                for i in range(n+1):self.m.paint(round(old[0]+(cell[0]-old[0])*i/n),round(old[1]+(cell[1]-old[1])*i/n),erase)
                self.stroke=(cell,erase)
        self.update()
    def mouseReleaseEvent(self,event):
        if self.stroke:self.stroke=None;self.clock.reset(speed=self.m.speed);self.checkpoint()
    def focusOutEvent(self,event):
        if self.stroke:self.stroke=None;self.clock.reset(speed=self.m.speed);self.checkpoint()
        super().focusOutEvent(event)
    def closeEvent(self,event):
        self.checkpoint()
        if self.wallpaper_mode:self.hide();event.ignore();return
        self.system.stop();self.timer.stop();event.accept()
