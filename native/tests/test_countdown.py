import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,Signal,QTimer,Qt
from PySide6.QtWidgets import QApplication,QSpinBox,QPushButton
from PySide6.QtDBus import QDBusMessage
from conway_desktop.countdown import Countdown,MAX_SECONDS
from conway_desktop.storage import Store
from conway_desktop.model import Model
from conway_desktop.system import System
from conway_desktop.view import View,PALETTE_SWATCHES
from conway_desktop import session_lock

APP=QApplication.instance() or QApplication([])

class CountdownRules(unittest.TestCase):
    def setUp(self):self.now=0.;self.timer=Countdown(lambda:self.now)
    def test_unlock_lock_and_unknown_charge_only_active_time(self):
        t=self.timer;t.start(60);self.now=10;t.update();self.assertEqual(t.remaining,60);self.assertEqual(t.status,'WAIT')
        t.set_locked(False);self.now=25;t.set_locked(True);self.assertEqual(t.remaining,45)
        self.now=1000;t.update();self.assertEqual(t.remaining,45);self.assertEqual(t.status,'LOCK')
        t.set_locked(None);self.now=2000;t.set_locked(False);self.now=2005;t.update();self.assertEqual(t.remaining,40)
    def test_manual_pause_and_resume_during_lock(self):
        t=self.timer;t.set_locked(False);t.start(10);self.now=3;t.pause();self.now=10;t.update();self.assertEqual(t.remaining,7)
        t.set_locked(True);t.resume();self.now=100;t.update();self.assertEqual(t.remaining,7)
        t.set_locked(False);self.now=107;t.update();self.assertTrue(t.take_reminder());self.assertFalse(t.take_reminder())
    def test_expiration_at_lock_is_deferred_until_unlock_once(self):
        t=self.timer;t.set_locked(False);t.start(1);self.now=2;t.set_locked(True)
        self.assertEqual(t.state,'finished');self.assertFalse(t.take_reminder())
        self.now=100;t.set_locked(False);self.assertTrue(t.take_reminder());self.assertFalse(t.take_reminder())
    def test_restart_cancel_rounding_and_duration_limits(self):
        t=self.timer;t.set_locked(False);t.start(3661);self.assertEqual(t.label,'01:01:01')
        self.now=.4;t.update();self.assertEqual(t.label,'01:01:01')
        t.start(MAX_SECONDS);self.assertEqual(t.label,'999:59:59');t.cancel();self.assertEqual(t.label,'--:--:--');self.assertFalse(t.pending)
        for seconds in (0,-1,1.5,True,MAX_SECONDS+1):
            with self.assertRaises(ValueError):t.start(seconds)
    def test_sqlite_restart_does_not_consume_offline_time_or_world(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'state.sqlite3';store=Store(db);m=Model();m.generation=123;store.checkpoint(m)
            t=self.timer;t.set_locked(False);t.start(90);self.now=15;store.checkpoint(m,t);store.close()
            self.now=100000;restored=Countdown(lambda:self.now);store=Store(db)
            self.assertTrue(store.restore_countdown(restored));self.assertIsNone(restored.locked)
            restored.set_locked(False);self.assertEqual(restored.remaining,75)
            other=Model();self.assertTrue(store.restore(other));self.assertEqual(other.generation,123);store.close()
    def test_corrupt_checkpoint_rejected_before_changing_timer(self):
        for data in ({'duration':10,'remaining':float('nan'),'state':'running','pending':False},
                     {'duration':10,'remaining':0,'state':'running','pending':False},
                     {'duration':10,'remaining':5,'state':'paused','pending':True}):
            with self.assertRaises(ValueError):self.timer.restore(data)
            self.assertEqual(self.timer.state,'idle')

class CountdownUI(unittest.TestCase):
    def setUp(self):
        self.system=System(False);self.view=View(Model(),None,self.system);self.view.timer.stop()
    def tearDown(self):self.system.stop();self.view.deleteLater();APP.processEvents()
    def test_notification_once_even_on_pattern_page_and_lock_deferral(self):
        now=[0];self.view.countdown=Countdown(lambda:now[0]);self.view.countdown.set_locked(False)
        self.view.countdown.start(1);self.view.deck='patterns';now[0]=2
        self.view.lock_changed(True)
        with patch.object(self.view,'remind_countdown') as alert:
            self.view.tick();alert.assert_not_called();self.view.lock_changed(False)
            self.view.tick();self.view.tick();alert.assert_called_once()
    def test_click_settings_start_then_cancel_does_not_affect_world(self):
        self.view.countdown.set_locked(False)
        def set_time():
            dialog=APP.activeModalWidget()
            dialog.findChild(QSpinBox,'hours').setValue(0);dialog.findChild(QSpinBox,'minutes').setValue(2);dialog.findChild(QSpinBox,'seconds').setValue(3)
            dialog.findChild(QPushButton,'start').click()
        watchdog=QTimer();watchdog.setSingleShot(True);watchdog.timeout.connect(lambda:APP.activeModalWidget().reject() if APP.activeModalWidget() else None)
        watchdog.start(3000);QTimer.singleShot(0,set_time);self.view.configure_countdown();watchdog.stop()
        self.assertEqual(self.view.countdown.duration,123);self.assertEqual(self.view.countdown.state,'running')
        QTimer.singleShot(0,lambda:APP.activeModalWidget().findChild(QPushButton,'cancel').click())
        watchdog.start(3000);self.view.configure_countdown();watchdog.stop();self.assertEqual(self.view.countdown.state,'idle')
        self.assertEqual(self.view.m.generation,0)
    def test_layout_hit_area_and_color_icon_in_both_resolutions(self):
        from PySide6.QtGui import QColor
        import numpy as np
        self.view.deck='information';self.view.countdown.start(3661)
        for w,h in ((1920,1080),(2560,1440)):
            image=self.view.render_image(w,h);regions=self.view.regions
            self.assertIn('countdown',{name for _,_,name in regions})
            for i,(r,_,name) in enumerate(regions):
                for box,_,other in regions[i+1:]:self.assertFalse(r.intersects(box),(name,other))
            box=next(r for r,_,name in regions if name=='palette')
            pixels=np.frombuffer(image.bits(),np.uint32).reshape(h,image.bytesPerLine()//4)[box.y():box.y()+box.height(),box.x():box.x()+box.width()]
            for color in PALETTE_SWATCHES:self.assertGreater((pixels==QColor(color).rgba()).sum(),30)

class FakeWatcher(QObject):
    serviceOwnerChanged=Signal(str,str,str)
    def __init__(self,*args,**kwargs):super().__init__(kwargs.get('parent'))

class FakeReply:
    def __init__(self,value,error=False):self.value=value;self.error=error
    def type(self):return QDBusMessage.MessageType.ErrorMessage if self.error else QDBusMessage.MessageType.ReplyMessage
    def arguments(self):return [self.value]

class FakePending(QObject):
    finished=Signal(object)
    def __init__(self,reply,parent):super().__init__(parent);self.result=reply
    def reply(self):return self.result

class FakeBus:
    def __init__(self):self.connected=True;self.response=FakeReply(False)
    def isConnected(self):return self.connected
    def connect(self,*args):return True
    def disconnect(self,*args):return True
    def asyncCall(self,message,timeout):return self.response

class LockMonitoring(unittest.TestCase):
    def setUp(self):
        self.bus=FakeBus()
        self.patches=[patch.object(session_lock.QDBusConnection,'sessionBus',return_value=self.bus),
                      patch.object(session_lock,'QDBusServiceWatcher',FakeWatcher),patch.object(session_lock,'QDBusPendingCallWatcher',FakePending)]
        for p in self.patches:p.start()
        self.monitor=session_lock.SessionLock();self.monitor.timer.stop()
    def tearDown(self):
        self.monitor.stop();self.monitor.deleteLater();APP.processEvents()
        for p in reversed(self.patches):p.stop()
    def finish(self):p=self.monitor.pending;p.finished.emit(p)
    def test_initial_read_lock_signal_and_stale_reply_are_ordered(self):
        self.monitor.refresh();self.assertIsNone(self.monitor.state)
        self.monitor.active_changed(True);self.finish();self.assertIs(self.monitor.state,True)
        self.bus.response=FakeReply(False);self.monitor.refresh();self.finish();self.assertIs(self.monitor.state,False)
    def test_service_disappearance_and_read_failure_never_assume_unlocked(self):
        self.monitor.active_changed(False);self.monitor.owner_changed('service','old','');self.assertIsNone(self.monitor.state)
        self.bus.response=FakeReply(None,True);self.finish()
        self.monitor.refresh();self.finish();self.assertIsNone(self.monitor.state);self.assertTrue(self.monitor.error)
