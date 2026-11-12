import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from conway_desktop.system import System
from conway_desktop.ime import bus_data,punctuation_action
from conway_desktop.model import Model
from conway_desktop.view import View

APP=QApplication.instance() or QApplication([])

class FakeBus:
    def __init__(self):self.ascii=False;self.punctuation=True;self.engine='rime';self.calls=[];self.failed=False
    def run(self,key,argv,callback,**kwargs):
        self.calls.append(argv);method=argv[8];signature=argv[9] if len(argv)>9 else '';values=argv[10:]
        if self.failed:callback(False,'no session bus');return True
        value=None;kind=''
        if method=='State':kind='i';value=1 if self.engine.startswith('keyboard-') else 2
        elif method=='CurrentInputMethod':kind='s';value=self.engine
        elif method=='IsAsciiMode':kind='b';value=self.ascii
        elif method=='SetAsciiMode':self.ascii=values[0]=='true'
        elif method=='Activate':self.engine='rime'
        elif method=='Deactivate':self.engine='keyboard-us'
        elif method=='Get':
            if values[-1]=='RegisteredStatusNotifierItems':kind='v';value={'type':'as','data':[':1.55/StatusNotifierItem']}
            else:kind='v';value={'type':'s','data':'Fcitx'}
        elif method=='GetLayout':
            label='。， → ．，' if self.punctuation else '．， → 。，'
            kind='u(ia{sv}av)';data=[42,[0,{},[{'type':'(ia{sv}av)','data':[77,{'label':{'type':'s','data':label}},[]]}]]]
            callback(True,json.dumps({'type':kind,'data':data}));return True
        elif method=='AboutToShow':kind='b';value=True
        elif method=='Event' and values[1]=='clicked':self.punctuation=not self.punctuation
        callback(True,json.dumps({'type':kind,'data':[value]}) if kind else '');return True
    def stop(self):pass

class InputMethods(unittest.TestCase):
    def setUp(self):
        self.system=System(False);self.system.enabled=True;self.bus=FakeBus();self.system.commands=self.bus
        self.messages=[];self.system.notice.connect(self.messages.append)
    def tearDown(self):self.system.stop()
    def test_primitive_and_nested_busctl_json(self):
        self.assertIs(bus_data('{"type":"b","data":[false]}'),False)
        self.assertEqual(bus_data('{"type":"v","data":[{"type":"s","data":"Fcitx"}]}'),'Fcitx')
        self.assertEqual(bus_data('{"type":"v","data":[{"type":"as","data":[":1.55/StatusNotifierItem"]}]}'),[':1.55/StatusNotifierItem'])
    def test_read_rime_internal_ascii_mode_and_menu_state(self):
        self.system.ime.refresh();self.assertIs(self.system.state['ime'],True);self.assertIs(self.system.state['punctuation'],True)
        self.bus.ascii=True;self.bus.punctuation=False;self.system.ime.refresh()
        self.assertIs(self.system.state['ime'],False);self.assertIs(self.system.state['punctuation'],False)
    def test_toggles_and_readback_use_real_methods(self):
        with patch('conway_desktop.ime.QTimer.singleShot',side_effect=lambda _,callback:callback()):
            self.system.ime.refresh();self.system.ime.toggle_mode();self.assertTrue(self.bus.ascii);self.assertIs(self.system.state['ime'],False)
            self.system.ime.toggle_mode();self.assertFalse(self.bus.ascii);self.assertIs(self.system.state['ime'],True)
            self.system.ime.toggle_punctuation();self.assertFalse(self.bus.punctuation);self.assertIs(self.system.state['punctuation'],False)
        self.assertFalse(self.messages);self.assertFalse(self.system.busy)
        self.assertTrue(any(argv[-3:]==['SetAsciiMode','b','true'] for argv in self.bus.calls))
        event=next(argv for argv in self.bus.calls if argv[8]=='Event')
        self.assertEqual(event[9:],['isvu','77','clicked','i','0','0'])
    def test_keyboard_to_rime_activates_then_exits_rime_ascii(self):
        self.bus.engine='keyboard-us';self.bus.ascii=True
        with patch('conway_desktop.ime.QTimer.singleShot',side_effect=lambda _,callback:callback()):self.system.ime.toggle_mode()
        self.assertEqual(self.bus.engine,'rime');self.assertFalse(self.bus.ascii);self.assertIs(self.system.state['ime'],True)
    def test_unknown_punctuation_never_guesses_or_clicks(self):
        layout=[0,{},[[1,{'label':'全角 → 半角'},[]],[2,{'label':'繁體 → 简体'},[]]]]
        self.assertIsNone(punctuation_action(layout))
        self.assertEqual(punctuation_action([0,{},[[10,{'icon-name':'fcitx-punc-active'},[]]]]),(10,True))
        self.assertIsNone(punctuation_action([0,{},[[10,{'label':'。， → ．，'},[]],[11,{'label':'。， → ．，'},[]]]]))
    def test_missing_service_has_unknown_states(self):
        self.bus.failed=True;self.system.ime.refresh()
        self.assertIsNone(self.system.state['ime']);self.assertIsNone(self.system.state['punctuation']);self.assertIn('ime',self.system.errors)
    def test_information_page_layout_and_no_canvas_close(self):
        view=View(Model(),None,self.system);view.deck='information'
        try:
            for w,h in ((1920,1080),(2560,1440)):
                view.render_image(w,h);names={name for _,_,name in view.regions}
                self.assertNotIn('close',names);self.assertIn('ime',names);self.assertIn('punctuation',names);self.assertNotIn('load',names)
                for i,(r,_,name) in enumerate(view.regions):
                    for s,_,other in view.regions[i+1:]:self.assertFalse(r.intersects(s),(name,other))
        finally:view.timer.stop();view.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
