import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QMouseEvent,QColor
from PySide6.QtWidgets import QApplication
from conway_desktop.model import Model
from conway_desktop.system import System,Commands,parse_volume,parse_wifi_devices,parse_wifi_state,parse_bluetooth
from conway_desktop.view import View,geometry

APP=QApplication.instance() or QApplication([])
class Native(unittest.TestCase):
    def setUp(self):self.model=Model();self.system=System(False);self.view=View(self.model,None,self.system)
    def tearDown(self):self.view.timer.stop();self.system.stop();self.view.deleteLater();APP.processEvents()
    def test_physical_layouts(self):
        for w,h,k in [(1920,1080,6),(2560,1440,8)]:
            self.assertEqual(geometry(w,h),(k,0,0))
            image=self.view.render_image(w,h)
            self.assertFalse(image.isNull())
            regions=self.view.regions
            for i,(rect,_,name) in enumerate(regions):
                self.assertTrue(0<=rect.x()<w and 0<=rect.y()<h,name)
                self.assertLessEqual(rect.right(),w);self.assertLessEqual(rect.bottom(),h)
                for other,_,other_name in regions[i+1:]:self.assertFalse(rect.intersects(other),name+' overlaps '+other_name)
            low=max(rect.bottom() for rect,_,_ in regions)
            self.assertGreaterEqual(h-low,h*.06)
            # Preview background remains panel-colored, rather than inheriting the life brush.
            box=next(r for r,_,name in regions if name=='load')
            self.assertEqual(image.pixelColor(box.x()+5,box.y()+5),QColor('#0d1820'))
    def test_continuous_speed_bar_mouse_selection(self):
        self.view.resize(1280,720);self.view.render_image(1280,720)
        bar=next(r for r,_,name in self.view.regions if name=='speed-bar')
        self.assertFalse(any(name.startswith('speed') and name!='speed-bar' for _,_,name in self.view.regions))
        from conway_desktop.model import SPEEDS
        for i,speed in enumerate(SPEEDS):
            point=QPointF(bar.x()+(i+.5)*bar.width()/8,bar.center().y())
            event=QMouseEvent(QMouseEvent.Type.MouseButtonPress,point,point,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            self.view.mousePressEvent(event);self.assertEqual(self.model.speed,speed)
    def test_shift_and_right_erase(self):
        self.view.resize(1280,720);self.view.render_image(1280,720)
        for button,modifier,alive in [(Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,1),(Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,0),(Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,0)]:
            self.model.cells.fill(1)
            event=QMouseEvent(QMouseEvent.Type.MouseButtonPress,QPointF(40,40),QPointF(40,40),button,button,modifier)
            self.view.mousePressEvent(event);self.assertEqual(self.model.cells[10,10],alive);self.view.stroke=None
    def test_adapters(self):
        self.assertEqual(parse_volume('Volume: 0.45 [MUTED]'),{'volume':.45,'muted':True})
        self.assertTrue(parse_wifi_devices('wlan0:wifi:connected\neth0:ethernet:connected'))
        self.assertFalse(parse_wifi_devices('eth0:ethernet:connected'))
        self.assertFalse(parse_bluetooth('Controller ABC\n Powered: no'))
        self.assertTrue(parse_wifi_state('enabled:enabled'))
        with self.assertRaises(ValueError):parse_wifi_state('disabled:disabled')
        for parser in (parse_volume,parse_bluetooth):
            with self.assertRaises(ValueError):parser('No default controller available')

    def test_command_parameters(self):
        calls=[]
        class Fake:
            def run(self,key,args,callback,**kwargs):calls.append((key,args));return True
        self.system.enabled=True;self.system.commands=Fake()
        self.system.state.update(volume=.5,muted=False,wifi=True,bluetooth=False)
        self.system.volume(2);self.assertEqual(calls[-1][1],['wpctl','set-volume','@DEFAULT_AUDIO_SINK@','1','-l','1'])
        self.system.busy.clear();self.system.mute();self.assertEqual(calls[-1][1][-1],'toggle')
        self.system.wifi();self.assertEqual(calls[-1][1],['nmcli','radio','wifi','off'])
        self.system.bluetooth();self.assertEqual(calls[-1][1],['bluetoothctl','--timeout','8','power','on'])
        self.system.commands=Commands(self.system)
    def test_async_commands(self):
        from PySide6.QtCore import QEventLoop,QTimer
        runner=Commands();loop=QEventLoop();result=[]
        runner.run('ok',[sys.executable,'-c',"print('ready')"],lambda ok,out:(result.append((ok,out.strip())),loop.quit()))
        QTimer.singleShot(4000,loop.quit);loop.exec()
        self.assertEqual(result,[(True,'ready')])
        result=[]
        runner.run('timeout',[sys.executable,'-c','import time; time.sleep(10)'],lambda ok,out:(result.append((ok,out)),loop.quit()))
        QTimer.singleShot(4500,loop.quit);loop.exec()
        self.assertTrue(result);self.assertFalse(result[0][0]);self.assertIn('超时',result[0][1]);runner.stop()

if __name__=='__main__':unittest.main()
