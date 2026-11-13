"""Observe KDE's screen locker without taking focus or inhibiting locking."""
from PySide6.QtCore import QObject,QTimer,Signal,Slot,SLOT
from PySide6.QtDBus import QDBusConnection,QDBusMessage,QDBusPendingCallWatcher,QDBusServiceWatcher
from .logging_setup import LOGGER

SERVICE='org.freedesktop.ScreenSaver';PATH='/ScreenSaver';INTERFACE=SERVICE

class SessionLock(QObject):
    changed=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.state=None;self.error=None;self.serial=0;self.pending=None;self.subscribed=False
        self.bus=QDBusConnection.sessionBus();self.stopped=False
        self.watcher=QDBusServiceWatcher(SERVICE,self.bus,parent=self)
        self.watcher.serviceOwnerChanged.connect(self.owner_changed)
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.refresh)
        self.timer.start();QTimer.singleShot(0,self.refresh)
    def publish(self,value,error=None):
        if self.stopped:return
        if (value,error)!=(self.state,self.error):
            self.state=value;self.error=error;LOGGER.info('Session lock state=%s error=%s',value,error);self.changed.emit(value)
    @Slot(bool)
    def active_changed(self,value):
        self.serial+=1;self.publish(value)
    @Slot(str,str,str)
    def owner_changed(self,service,old,new):
        self.serial+=1;self.publish(None,'等待锁屏服务重新确认');self.refresh()
    def refresh(self):
        if self.stopped or self.pending:return
        if not self.bus.isConnected():self.publish(None,'会话 D-Bus 不可用');return
        if not self.subscribed:
            self.subscribed=self.bus.connect(SERVICE,PATH,INTERFACE,'ActiveChanged',self,SLOT('active_changed(bool)'))
        if not self.subscribed:self.publish(None,'无法订阅锁屏状态');return
        serial=self.serial;message=QDBusMessage.createMethodCall(SERVICE,PATH,INTERFACE,'GetActive')
        watcher=QDBusPendingCallWatcher(self.bus.asyncCall(message,1500),self);self.pending=watcher
        def finished(*_):
            reply=watcher.reply();self.pending=None;watcher.deleteLater()
            if self.stopped or serial!=self.serial:return
            values=reply.arguments()
            if reply.type()==QDBusMessage.MessageType.ReplyMessage and len(values)==1 and type(values[0]) is bool:self.publish(values[0])
            else:self.publish(None,'无法读取锁屏状态')
        watcher.finished.connect(finished)
    def stop(self):
        self.stopped=True;self.timer.stop()
        if self.subscribed:self.bus.disconnect(SERVICE,PATH,INTERFACE,'ActiveChanged',self,SLOT('active_changed(bool)'))
