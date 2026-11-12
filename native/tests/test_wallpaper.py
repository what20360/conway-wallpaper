import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PySide6.QtCore import QEventLoop,QTimer,QUrl,QByteArray
from PySide6.QtGui import QImage
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply,QNetworkProxy
from PySide6.QtWidgets import QApplication
from conway_desktop.model import Model,default_cells,evolve
from conway_desktop.system import System,NetworkRates,network_counters,parse_connected_devices
from conway_desktop.view import View,rate_label,percent_label
from conway_desktop.wallpaper import WallpaperServer,install_plugin,private_token,set_autostart,autostart_file

APP=QApplication.instance() or QApplication([])

class TelemetryAndPatterns(unittest.TestCase):
    def test_units_and_percent(self):
        self.assertEqual([percent_label(x) for x in (None,0,5,99.6)],['--%','0%','5%','100%'])
        self.assertEqual([rate_label(x) for x in (None,0,999,1023,1024,2047,1048576,2621440)],['---','0B','999B','1023B','1K','1K','1M','2M'])
    def test_network_delta_resets_and_suspend(self):
        rates=NetworkRates()
        self.assertEqual(rates.sample({'wlan0':(100,200)},10),(None,None))
        self.assertEqual(rates.sample({'wlan0':(2148,1224)},12),(1024,512))
        self.assertEqual(rates.sample({'wlan0':(1,1)},14),(None,None))
        self.assertEqual(rates.sample({'eth0':(200,200)},16),(None,None))
        self.assertEqual(rates.sample({'eth0':(10000,10000)},100),(None,None))
        self.assertEqual(rates.sample({},102),(None,None))
    def test_tunnels_and_down_interfaces_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,physical,state in [('wlan0',True,'up'),('tun0',False,'up'),('eth0',True,'down'),('lo',False,'up')]:
                entry=root/name;entry.mkdir();(entry/'operstate').write_text(state)
                if physical:(entry/'device').mkdir()
                (entry/'statistics').mkdir()
                for key,value in [('rx_bytes','2000'),('tx_bytes','1000')]:(entry/'statistics'/key).write_text(value)
            self.assertEqual(network_counters(root),{'wlan0':(2000,1000)})
    def test_connection_count_is_unique_connected_devices(self):
        output='Device 01:02:03:04:05:06 Keyboard\nDevice 01:02:03:04:05:07 Headset\nDevice 01:02:03:04:05:06 Keyboard\n'
        self.assertEqual(parse_connected_devices(output),2)
        self.assertEqual(parse_connected_devices(''),0)
        with self.assertRaises(ValueError):parse_connected_devices('Invalid command in menu main: devices')
    def test_large_presets_and_true_downward_motion(self):
        from conway_desktop.presets import ship
        base=np.zeros((180,256),dtype=np.uint8);p=ship(0,1);h,w=p.shape;base[40:40+h,40:40+w]=p
        evolved=base.copy()
        for _ in range(4):evolved=evolve(evolved)
        np.testing.assert_array_equal(evolved,np.roll(base,2,axis=0))
        for n in range(8,20):
            c=default_cells(n);self.assertGreater(c.sum(),100)
            self.assertGreater(np.ptp(np.nonzero(c)[1]),140)
        meteor=default_cells(8);after=meteor.copy()
        for _ in range(4):after=evolve(after)
        np.testing.assert_array_equal(after,np.roll(meteor,2,axis=0))

class WallpaperBridge(unittest.TestCase):
    def setUp(self):
        self.model=Model();self.model.cells.fill(0);self.system=System(False);self.view=View(self.model,None,self.system)
        self.server=WallpaperServer(self.view,'a'*64,0)
        self.url=f'http://127.0.0.1:{self.server.server.serverPort()}'
        self.manager=QNetworkAccessManager();self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
    def tearDown(self):
        self.server.stop();self.view.timer.stop();self.system.stop();self.view.deleteLater();self.manager.deleteLater();APP.processEvents()
    def request(self,path,body=None,auth=True,origin=None):
        req=QNetworkRequest(QUrl(self.url+path));req.setTransferTimeout(4000)
        if auth:req.setRawHeader(b'Authorization',b'Bearer '+b'a'*64)
        if origin:req.setRawHeader(b'Origin',origin.encode())
        if body is None:reply=self.manager.get(req)
        else:
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
            reply=self.manager.post(req,QByteArray(json.dumps(body).encode()))
        loop=QEventLoop();reply.finished.connect(loop.quit)
        watchdog=QTimer(loop);watchdog.setSingleShot(True);watchdog.timeout.connect(loop.quit)
        watchdog.start(5000);loop.exec();watchdog.stop()
        result=(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute),bytes(reply.readAll()))
        reply.deleteLater();APP.processEvents();return result
    def test_auth_origin_png_and_dimensions(self):
        self.assertEqual(self.request('/frame?w=640&h=360',auth=False)[0],401)
        self.assertEqual(self.request('/frame?w=640&h=360&token='+'a'*64,origin='https://evil.example')[0],401)
        status,data=self.request('/frame?w=1920&h=1080&token='+'a'*64)
        self.assertEqual(status,200);image=QImage.fromData(data)
        self.assertEqual((image.width(),image.height()),(1920,1080))
        self.assertEqual(self.request('/frame?w=99999&h=1080&token='+'a'*64)[0],400)
    def test_physical_pointer_and_release(self):
        event={'kind':'press','w':1920,'h':1080,'x':60,'y':60,'shift':False}
        self.assertEqual(self.request('/input',event,auth=False)[0],401);self.assertFalse(self.model.cells.any())
        self.assertEqual(self.request('/input',event)[0],200);APP.processEvents();self.assertEqual(self.model.cells[10,10],1)
        event.update(kind='move',x=90);self.request('/input',event);APP.processEvents()
        self.assertTrue(self.model.cells[10,10:16].all())
        event['kind']='release';self.request('/input',event);APP.processEvents();self.assertIsNone(self.view.stroke)
        event.update(kind='press',x=60,shift=True);self.request('/input',event);APP.processEvents();self.assertEqual(self.model.cells[10,10],0)
        self.server.release_pointer();self.assertIsNone(self.view.stroke)
        event['x']=-1;self.assertEqual(self.request('/input',event)[0],400)
    def test_private_plugin_install_preserves_token_and_user_slots(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_DATA_HOME':folder}):
            data=Path(folder)/'app';token=private_token(data)
            package=install_plugin(data,False);self.assertTrue((package/'metadata.json').is_file())
            config=package/'contents/ui/Connection.qml';self.assertIn(token,config.read_text());self.assertEqual(config.stat().st_mode&0o777,0o600)
            self.assertEqual(private_token(data),token);install_plugin(data,False);self.assertIn(token,config.read_text())
    def test_autostart_preserves_custom_data_path(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder}):
            data=Path(folder)/'custom data'
            set_autostart(True,data);self.assertIn('"--data-dir" "'+str(data)+'"',autostart_file().read_text())
            set_autostart(False);self.assertFalse(autostart_file().exists())
    def test_closing_editor_keeps_wallpaper_engine_alive(self):
        self.view.wallpaper_mode=True;self.view.show();self.view.close()
        self.assertFalse(self.view.isVisible());self.assertTrue(self.view.timer.isActive())
        self.assertTrue(self.server.server.isListening())
    def test_qml_presentation_fetches_native_frame_and_forwards_controls(self):
        # Test actual QML presentation with an Item root. The Plasma-specific import
        # and containment/desktop input routing require a real Plasma 6 session.
        from PySide6.QtQml import QQmlEngine,QQmlComponent
        from PySide6.QtQuick import QQuickWindow
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=Path(__file__).parents[1]/'plasma-wallpaper/contents/ui'
            qml=(source/'main.qml').read_text().replace('import org.kde.plasma.plasmoid','').replace('WallpaperItem {','Item {',1)
            qml=qml.replace('import org.kde.plasma.core as PlasmaCore','import QtQuick.Controls as PlasmaCore').replace('contextualActions: [','property list<QtObject> contextualActions: [',1)
            (root/'main.qml').write_text(qml)
            (root/'Connection.qml').write_text('import QtQml\nQtObject { readonly property string token: "'+self.server.token+'"; readonly property string endpoint: "'+self.url+'" }')
            engine=QQmlEngine();component=QQmlComponent(engine,QUrl.fromLocalFile(str(root/'main.qml')))
            wait=QEventLoop();QTimer.singleShot(100,wait.quit);wait.exec()
            self.assertFalse(component.isError(),str(component.errors()))
            item=component.create();self.assertIsNotNone(item,str(component.errors()))
            window=QQuickWindow();item.setParentItem(window.contentItem());item.setWidth(640);item.setHeight(360)
            deadline=QTimer();deadline.setInterval(20);loop=QEventLoop()
            deadline.timeout.connect(lambda:loop.quit() if item.property('connected') else None)
            deadline.start();QTimer.singleShot(6000,loop.quit);loop.exec();deadline.stop()
            self.assertTrue(item.property('connected'))
            item.enqueue('press',20,20,False)
            loop=QEventLoop();QTimer.singleShot(200,loop.quit);loop.exec();self.assertEqual(self.model.cells[10,10],1)
            item.enqueue('release',20,20,False)
            loop=QEventLoop();QTimer.singleShot(100,loop.quit);loop.exec();self.assertIsNone(self.view.stroke)
            item.setVisible(False);item.setParentItem(None);item.deleteLater();window.deleteLater();engine.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
