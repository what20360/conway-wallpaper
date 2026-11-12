import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from pathlib import Path
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
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
    def test_presets_are_mirrored_and_rain_is_uniform_through_vertical_seam(self):
        for index in range(8,25):
            cells=default_cells(index)
            np.testing.assert_array_equal(cells,np.fliplr(cells),err_msg=str(index))
            if index not in (8,9,19):np.testing.assert_array_equal(cells,np.flipud(cells),err_msg=str(index))
        for index,columns in ((8,4),(9,6)):
            cells=default_cells(index)
            np.testing.assert_array_equal(cells,np.roll(cells,9,axis=0))
            alive_columns=np.flatnonzero(cells.any(axis=0))
            starts=alive_columns[np.r_[True,np.diff(alive_columns)>1]]
            self.assertEqual(len(starts),columns)
            self.assertTrue((np.diff(starts)==np.diff(starts)[0]).all())
    def test_lexicon_patterns_keep_documented_period_or_motion(self):
        from conway_desktop.presets import lexicon_pattern
        for name,period,shift in (('Schick_engine',12,(0,-6)),('weekender',7,(-2,0)),('twin_bees_shuttle',46,(0,0)),('pentadecathlon',15,(0,0))):
            p=lexicon_pattern(name);h,w=p.shape;cells=np.zeros((180,256),np.uint8);cells[70:70+h,100:100+w]=p
            evolved=cells.copy()
            for _ in range(period):evolved=evolve(evolved)
            np.testing.assert_array_equal(evolved,np.roll(cells,shift,(0,1)))
        for index,period in ((22,46),(23,15)):
            cells=default_cells(index);evolved=cells.copy()
            for _ in range(period):evolved=evolve(evolved)
            np.testing.assert_array_equal(evolved,cells)

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
    def test_five_segment_bluetooth_bar_is_readable_from_zero_to_five(self):
        from conway_desktop.view import THEMES
        from PySide6.QtGui import QColor
        self.system.state['bluetooth']=True
        for width,height in ((1920,1080),(2560,1440)):
            for count in range(6):
                self.system.state['connected']=count;image=self.view.render_image(width,height)
                box=next(r for r,_,name in self.view.regions if name=='bluetooth');unit=box.width()/48
                for i in range(5):
                    x=round(box.x()+(1+i*11)*unit);y=round(box.y()+51*unit)
                    color=QColor(THEMES[self.model.palette]['clock' if i<count else 'panel'])
                    self.assertEqual(image.pixelColor(x,y),color,(width,count,i))
    def test_status_icons_share_color_states_without_solid_backgrounds(self):
        from conway_desktop.view import THEMES
        from PySide6.QtGui import QColor
        palette=THEMES[self.model.palette]
        for active in (True,False):
            self.system.state.update(volume=.5,muted=not active,wifi=active,bluetooth=active,connected=0)
            image=self.view.render_image(2560,1440)
            pixels=np.frombuffer(image.bits(),np.uint32).reshape(image.height(),image.bytesPerLine()//4)
            for name in ('volume' if active else 'mute','wifi','bluetooth'):
                box=next(r for r,_,n in self.view.regions if n==name);unit=box.width()/48
                # No colored tile at the button corner; the whole glyph carries state.
                self.assertEqual(image.pixelColor(round(box.x()+3*unit),round(box.y()+3*unit)),QColor(palette['panel']))
                ink=QColor(palette['life' if active else 'danger']).rgba()
                body=pixels[box.y():box.y()+round(45*unit),box.x():box.x()+box.width()]
                self.assertGreater(np.count_nonzero(body==ink),100)
        self.system.pending['bluetooth']=True;self.system.busy.add('bluetooth')
        image=self.view.render_image(2560,1440);box=next(r for r,_,n in self.view.regions if n=='bluetooth')
        pixels=np.frombuffer(image.bits(),np.uint32).reshape(image.height(),image.bytesPerLine()//4)
        self.assertGreater(np.count_nonzero(pixels[box.y():box.y()+60,box.x():box.x()+box.width()]==QColor(palette['life']).rgba()),100)
        self.assertIs(self.system.state['bluetooth'],False)
    def wait_until(self,predicate,timeout=6000):
        if predicate():return
        loop=QEventLoop();poll=QTimer(loop);poll.setInterval(10)
        poll.timeout.connect(lambda:loop.quit() if predicate() else None)
        watchdog=QTimer(loop);watchdog.setSingleShot(True);watchdog.timeout.connect(loop.quit)
        poll.start();watchdog.start(timeout);loop.exec();poll.stop();watchdog.stop()
        self.assertTrue(predicate(),'QML operation timed out')
    @contextmanager
    def presentation(self,width,height,ratio):
        from PySide6.QtCore import QObject
        from PySide6.QtQml import QQmlEngine,QQmlComponent
        from PySide6.QtQuick import QQuickWindow
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=Path(__file__).parents[1]/'plasma-wallpaper/contents/ui'
            qml=(source/'main.qml').read_text().replace('import org.kde.plasma.plasmoid','').replace('WallpaperItem {','Item {\n property var configuration: ({Image: \"\", writeCount: 0, writeConfig: function() { this.writeCount += 1 }})',1)
            qml=qml.replace('import org.kde.plasma.core as PlasmaCore','import QtQuick.Controls as PlasmaCore').replace('contextualActions: [','property list<QtObject> contextualActions: [',1)
            qml=qml.replace('readonly property real ratio: Screen.devicePixelRatio || 1','readonly property real ratio: '+str(ratio))
            (root/'main.qml').write_text(qml)
            (root/'Connection.qml').write_text('import QtQml\nQtObject { readonly property string token: "'+self.server.token+'"; readonly property string endpoint: "'+self.url+'" }')
            engine=QQmlEngine();component=QQmlComponent(engine,QUrl.fromLocalFile(str(root/'main.qml')))
            self.wait_until(lambda:component.status()!=QQmlComponent.Status.Loading)
            self.assertFalse(component.isError(),str(component.errors()));item=component.create()
            self.assertIsNotNone(item,str(component.errors()))
            window=QQuickWindow();window.resize(width,height);item.setParentItem(window.contentItem());item.setWidth(width);item.setHeight(height)
            def front():return item.findChild(QObject,'frameA' if item.property('frontIsA') else 'frameB')
            self.wait_until(lambda:item.property('connected') and front().property('frameWidth')==item.property('pixelWidth') and front().property('frameHeight')==item.property('pixelHeight'))
            try:yield item,front()
            finally:
                item.setVisible(False);item.setParentItem(None);item.deleteLater();window.deleteLater();engine.deleteLater();APP.processEvents()
    def test_capped_dpi_frame_fills_surface_without_aspect_distortion(self):
        for width,height,ratio in ((2560,1440,2),(2560,1440,1.5),(2048,1152,1.25),(1280,720,2),(1920,1080,1),(2700,1440,2)):
            with self.subTest(width=width,height=height,dpr=ratio),self.presentation(width,height,ratio) as (item,frame):
                self.assertEqual(frame.property('width'),width);self.assertEqual(frame.property('height'),height)
                fw,fh=frame.property('frameWidth'),frame.property('frameHeight')
                pw,ph=frame.property('paintedWidth'),frame.property('paintedHeight')
                self.assertAlmostEqual(pw/fw,ph/fh,places=5)
                self.assertGreaterEqual(pw,width-2);self.assertGreaterEqual(ph,height-2)
                self.assertLessEqual(fw,2560);self.assertLessEqual(fh,1440)
                item.setProperty('sending',True)
                item.enqueue('press',width*.6,height*.8,False)
                event=item.property('inputQueue').toVariant()[0]
                self.assertEqual(event['w'],fw);self.assertEqual(event['h'],fh)
                self.assertAlmostEqual(event['x'],fw*.6,delta=1);self.assertAlmostEqual(event['y'],fh*.8,delta=1)
    def test_dpi_capped_right_panel_mouse_hits_correct_control(self):
        with self.presentation(2560,1440,2) as (item,frame):
            self.view.render_image(frame.property('frameWidth'),frame.property('frameHeight'))
            button=next(rect for rect,_,name in self.view.regions if name=='page-switch')
            item.enqueue('press',button.center().x(),button.center().y(),False)
            self.wait_until(lambda:self.view.deck=='information')
            item.enqueue('release',button.center().x(),button.center().y(),False)
    def test_user_130_percent_rounding_keeps_full_2k_canvas(self):
        from conway_desktop.view import geometry
        for width,height,ratio in ((1970,1107,2),(1969,1107,2),(1970,1108,1.3)):
            with self.subTest(width=width,height=height,dpr=ratio),self.presentation(width,height,ratio) as (item,frame):
                self.assertEqual((frame.property('frameWidth'),frame.property('frameHeight')),(2560,1440))
                self.assertEqual(geometry(frame.property('frameWidth'),frame.property('frameHeight')),(8,0,0))
    def test_real_mouse_delivery_above_desktop_and_opt_in_drawing(self):
        from PySide6.QtCore import Qt,QPoint,QObject
        from PySide6.QtQml import QQmlEngine,QQmlComponent
        from PySide6.QtTest import QTest
        self.view.wallpaper_mode=True
        with self.presentation(1280,720,2) as (item,frame):
            overlay=item.findChild(QObject,'wallpaperInput');self.assertIsNotNone(overlay);self.assertIs(overlay.parent(),item)
            window=item.window();engine=QQmlEngine.contextForObject(item).engine()
            component=QQmlComponent(engine)
            component.setData(b'import QtQuick\nMouseArea { property int pressCount: 0; acceptedButtons: Qt.LeftButton | Qt.RightButton; onPressed: pressCount += 1 }',QUrl())
            desktop=component.create();self.assertIsNotNone(desktop,str(component.errors()))
            desktop.setParentItem(window.contentItem());desktop.setWidth(1280);desktop.setHeight(720);desktop.setZ(100)
            item.setZ(-1000);window.show();APP.processEvents()
            self.view.render_image(2560,1440)
            button=next(rect for rect,_,name in self.view.regions if name=='page-switch')
            QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(button.center().x()//2,button.center().y()//2))
            self.wait_until(lambda:self.view.deck=='information')
            self.assertEqual(desktop.property('pressCount'),0)
            QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(100,100))
            self.assertEqual(desktop.property('pressCount'),1);self.assertFalse(self.model.cells.any())
            # The pixel pencil button enables drawing without taking desktop icons
            # away from users when drawing mode is off.
            pencil=next(rect for rect,_,name in self.view.regions if name=='desktop-edit')
            QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(pencil.center().x()//2,pencil.center().y()//2))
            self.wait_until(lambda:item.property('editing'))
            QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(100,100))
            self.wait_until(lambda:self.model.cells[25,25]==1 and self.view.stroke is None)
            self.assertEqual(desktop.property('pressCount'),1)
            QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,QPoint(100,100))
            self.wait_until(lambda:self.model.cells[25,25]==0 and self.view.stroke is None)
            QTest.mouseClick(window,Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,QPoint(100,100))
            self.assertEqual(desktop.property('pressCount'),2)
            desktop.setParentItem(None);desktop.deleteLater()
    def test_frontend_version_and_layout_report_are_read_only_and_authenticated(self):
        from conway_desktop.wallpaper import VERSION
        status,data=self.request('/display-info',auth=False);self.assertEqual(status,401)
        status,data=self.request('/status');self.assertEqual(status,200);self.assertTrue(json.loads(data)['reloadRequired'])
        path='/status?frontend='+VERSION+'&logicalW=1970&logicalH=1107&screenDpr=2&sourceW=2560&sourceH=1440&imageW=1970&imageH=1107'
        status,data=self.request(path);self.assertEqual(status,200);self.assertFalse(json.loads(data)['reloadRequired'])
        status,data=self.request('/display-info');info=json.loads(data)
        self.assertEqual(info['backendVersion'],VERSION);self.assertEqual(info['clients'][-1]['logicalW'],1970)
        self.assertEqual(info['clients'][-1]['sourceH'],1440);self.assertNotIn(self.server.token,data.decode())
        self.assertEqual(self.request('/status?frontend='+VERSION+'&logicalW=nan')[0],400)
    def test_activity_snapshot_path_is_published_to_own_wallpaper_config(self):
        from conway_desktop.preview import ActivityPreview
        with tempfile.TemporaryDirectory() as folder:
            now=[0];self.server.preview=ActivityPreview(folder,clock=lambda:now[0])
            with self.presentation(1280,720,2) as (item,frame):
                def configured():return item.property('configuration').property('Image').toString()
                self.wait_until(lambda:bool(configured()))
                first=configured();url=QUrl(first)
                self.assertEqual(QImage(url.toLocalFile()).size().width(),640)
                self.assertEqual(QImage(url.toLocalFile()).size().height(),360)
                self.assertGreaterEqual(item.property('configuration').property('writeCount').toInt(),1)
                now[0]=31;self.server.preview.update(self.view.render_image(2560,1440))
                self.wait_until(lambda:configured()!=first)
                self.assertEqual(len(list(Path(folder).glob('*.png'))),1)
    def test_qml_presentation_fetches_native_frame_and_forwards_controls(self):
        # Test actual QML presentation with an Item root. The Plasma-specific import
        # and containment/desktop input routing require a real Plasma 6 session.
        from PySide6.QtQml import QQmlEngine,QQmlComponent
        from PySide6.QtQuick import QQuickWindow
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=Path(__file__).parents[1]/'plasma-wallpaper/contents/ui'
            qml=(source/'main.qml').read_text().replace('import org.kde.plasma.plasmoid','').replace('WallpaperItem {','Item {\n property var configuration: ({Image: \"\", writeCount: 0, writeConfig: function() { this.writeCount += 1 }})',1)
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
