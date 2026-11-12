import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import logging
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from conway_desktop.system import System,Commands,read_rfkill,parse_active_ssid,split_nmcli,bluez_error
from conway_desktop.model import Model,SPEEDS
from conway_desktop.view import speed_from_position,wifi_label,ssid_bitmap
from conway_desktop.logging_setup import configure,LOGGER
from PySide6.QtGui import QColor
APP=QApplication.instance() or QApplication([])

class Fake:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def run(self,key,args,callback,**kwargs):
        self.calls.append((key,args,kwargs))
        answer=self.responses.get(key,(True,''))
        if isinstance(answer,list):answer=answer.pop(0)
        callback(*answer);return True
    def stop(self):pass

class SystemFeatures(unittest.TestCase):
    def setUp(self):
        self.system=System(False);self.system.enabled=True;self.system.refresh=lambda:None
        self.system.state['bluetooth']=False;self.notices=[];self.system.notice.connect(self.notices.append)
        self.timer=patch('conway_desktop.system.QTimer.singleShot',side_effect=lambda ms,fn:fn());self.timer.start()
    def tearDown(self):self.timer.stop();self.system.stop()
    def test_rfkill_sysfs(self):
        with tempfile.TemporaryDirectory() as directory:
            entry=Path(directory)/'rfkill0';entry.mkdir()
            for name,value in [('type','bluetooth'),('name','hci0'),('soft','1'),('hard','0')]:
                (entry/name).write_text(value)
            self.assertEqual(read_rfkill(Path(directory)),[{'name':'hci0','soft':True,'hard':False}])
    def test_soft_block_unblocked_before_power_and_verified(self):
        self.system.commands=Fake({'bt-unblock':(True,''),'bt-power':(True,'Changing power on succeeded'),'bt-verify':(True,'Powered: yes')})
        with patch('conway_desktop.system.read_rfkill',side_effect=[[{'name':'hci0','soft':True,'hard':False}],[]]):self.system.bluetooth()
        calls=self.system.commands.calls
        self.assertEqual([x[0] for x in calls],['bt-unblock','bt-power','bt-verify','read-connected'])
        self.assertEqual(calls[0][1],['rfkill','unblock','bluetooth'])
        self.assertEqual(calls[1][2]['timeout_ms'],10000)
        self.assertTrue(self.system.state['bluetooth']);self.assertNotIn('bluetooth',self.system.busy);self.assertEqual(self.notices,[])
    def test_hard_block_never_unblocks_or_powers_on(self):
        self.system.commands=Fake({})
        with patch('conway_desktop.system.read_rfkill',return_value=[{'name':'hci0','soft':False,'hard':True}]):self.system.bluetooth()
        self.assertFalse(any(x[0] in ('bt-power','bt-unblock') for x in self.system.commands.calls))
        self.assertIn('硬件',self.notices[0]);self.assertFalse(self.system.state['bluetooth'])
    def test_bluez_error_even_with_zero_exit_is_failure(self):
        self.system.commands=Fake({'bt-power':(True,'Failed to set power on: org.bluez.Error.Failed')})
        with patch('conway_desktop.system.read_rfkill',return_value=[]):self.system.bluetooth()
        self.assertTrue(self.notices);self.assertFalse(self.system.state['bluetooth'])
        self.assertFalse(any(x[0]=='bt-verify' for x in self.system.commands.calls))
    def test_unblock_permission_failure_keeps_radio_off(self):
        self.system.commands=Fake({'bt-unblock':(False,'Permission denied')})
        with patch('conway_desktop.system.read_rfkill',return_value=[{'soft':True,'hard':False,'name':'hci0'}]):self.system.bluetooth()
        self.assertIn('Permission denied',self.notices[0]);self.assertFalse(self.system.state['bluetooth'])
        self.assertFalse(any(x[0]=='bt-power' for x in self.system.commands.calls))
    def test_command_success_without_readback_is_not_success(self):
        self.system.commands=Fake({'bt-power':(True,'Changing power on succeeded'),'bt-verify':(True,'Powered: no')})
        with patch('conway_desktop.system.read_rfkill',return_value=[]):self.system.bluetooth()
        self.assertFalse(self.system.state['bluetooth']);self.assertTrue(self.notices)
        self.assertEqual(sum(x[0]=='bt-verify' for x in self.system.commands.calls),4)
    def test_power_off_does_not_unblock(self):
        self.system.state['bluetooth']=True
        self.system.commands=Fake({'bt-power':(True,'Changing power off succeeded'),'bt-verify':(True,'Powered: no')})
        with patch('conway_desktop.system.read_rfkill',return_value=[{'soft':True,'hard':False,'name':'hci0'}]):self.system.bluetooth()
        self.assertFalse(self.system.state['bluetooth']);self.assertFalse(any(x[0]=='bt-unblock' for x in self.system.commands.calls))
    def test_fast_refresh_reads_connected_count_after_current_power_state(self):
        self.assertEqual(self.system.bluetooth_timer.interval(),500)
        self.system.commands=Fake({'read-bluetooth':(True,'Powered: yes'),
                                  'read-connected':(True,'Device 01:02:03:04:05:06 Headset\n')})
        self.system.refresh_bluetooth()
        self.assertIs(self.system.state['bluetooth'],True);self.assertEqual(self.system.state['connected'],1)
        self.assertEqual([call[0] for call in self.system.commands.calls],['read-bluetooth','read-connected'])
        self.system.commands=Fake({'read-bluetooth':(True,'Powered: no')});self.system.refresh_bluetooth()
        self.assertIs(self.system.state['bluetooth'],False);self.assertEqual(self.system.state['connected'],0)
        self.assertEqual([call[0] for call in self.system.commands.calls],['read-bluetooth'])
    def test_old_poll_cannot_overwrite_new_bluetooth_action(self):
        callbacks=[]
        class Delayed:
            def run(self,key,args,callback,**kwargs):callbacks.append(callback)
            def stop(self):pass
        self.system.commands=Delayed();self.system.state.update(bluetooth=False,connected=0)
        self.system.refresh_bluetooth();self.system._bluetooth_token+=1
        callbacks[0](True,'Powered: yes')
        self.assertIs(self.system.state['bluetooth'],False);self.assertEqual(self.system.state['connected'],0)

class DisplayAndLogging(unittest.TestCase):
    def test_ssid_escaping_case_and_unicode(self):
        self.assertEqual(parse_active_ssid('no:Other\nyes:Home\\:WiFi\\\\5G'), 'Home:WiFi\\5G')
        self.assertEqual(parse_active_ssid('yes:中文网络'), '中文网络')
        self.assertEqual(parse_active_ssid('yes:'),'')
        self.assertIsNone(parse_active_ssid('no:Other'))
        self.assertEqual(wifi_label({'wifi':True,'ssid':'MyHome'}),'MyHome')
        self.assertEqual(wifi_label({'wifi':False,'ssid':'Old'}),'---')
        image=ssid_bitmap('Home:WiFi\\5G',146,54,QColor('white'))
        self.assertLessEqual(image.width(),146);self.assertLessEqual(image.height(),54)
    def test_speed_defaults_and_old_checkpoint_migration(self):
        self.assertEqual(SPEEDS,(.125,.25,.5,1,2,4,8,16))
        m=Model();self.assertIn(m.speed,SPEEDS)
        for old,new in [(6,4),(12,8),(24,16),(40,16)]:
            m.restore(m.cells,{'speed':old});self.assertEqual(m.speed,new)
        self.assertEqual([speed_from_position(x,272) for x in (0,33,34,68,271,272)],[0,0,1,2,7,7])
    def test_debug_command_output_omits_ssid(self):
        from PySide6.QtCore import QEventLoop,QTimer
        old_hook=sys.excepthook
        with tempfile.TemporaryDirectory() as directory:
            try:
                configure(directory,True)
                script=Path(directory)/'fixture.py';script.write_text("print('PrivateNetworkName')")
                loop=QEventLoop();runner=Commands()
                runner.run('read-ssid',[sys.executable,str(script)],lambda ok,out:loop.quit())
                QTimer.singleShot(4000,loop.quit);loop.exec();runner.stop()
                content=(Path(directory)/'conway.log').read_text()
                self.assertNotIn('PrivateNetworkName',content);self.assertIn('SSID output omitted',content)
            finally:
                for handler in list(LOGGER.handlers):handler.close();LOGGER.removeHandler(handler)
                LOGGER.addHandler(logging.NullHandler());sys.excepthook=old_hook
    def test_logs_rotate_and_mask_addresses(self):
        old_hook=sys.excepthook
        with tempfile.TemporaryDirectory() as directory:
            try:
                configure(directory,True)
                LOGGER.info('adapter AA:BB:CC:DD:EE:FF')
                text=(Path(directory)/'conway.log').read_text()
                self.assertNotIn('AA:BB:CC:DD:EE:FF',text);self.assertIn('<MAC>',text)
                handler=LOGGER.handlers[0];handler.maxBytes=256
                for _ in range(30):LOGGER.info('x'*100)
                self.assertLessEqual(len(list(Path(directory).glob('conway.log*'))),4)
                self.assertEqual((Path(directory)/'conway.log').stat().st_mode&0o777,0o600)
            finally:
                for handler in list(LOGGER.handlers):handler.close();LOGGER.removeHandler(handler)
                LOGGER.addHandler(logging.NullHandler());sys.excepthook=old_hook

if __name__=='__main__':unittest.main()
