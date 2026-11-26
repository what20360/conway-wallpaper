"""Replaceable, persistent critical desktop notices, with bounded async work."""
from collections import deque
import json
from .logging_setup import LOGGER

class CountdownNotification:
    def __init__(self,commands,fallback):
        self.commands=commands;self.fallback=fallback;self.identifier=0
        self.generation=0;self.latest=None;self.closing=deque();self.busy=False
    def show(self,title,body):
        self.latest=(self.generation,title,body);self._dispatch()
    def clear(self):
        self.generation+=1;self.latest=None
        if self.identifier:self.closing.append(self.identifier);self.identifier=0
        self._dispatch()
    def _dispatch(self):
        if self.busy:return
        if self.closing:
            identifier=self.closing.popleft();generation=None
            method=['CloseNotification','u',str(identifier)]
        elif self.latest:
            generation,title,body=self.latest;self.latest=None
            method=['Notify','susssasa{sv}i','生命场',str(self.identifier),'alarm-symbolic',title,body,
                    '0','3','urgency','y','2','sound-name','s','complete','transient','b','false','0']
        else:return
        self.busy=True;called=False
        def finished(ok,output):
            nonlocal called
            if called:return
            called=True;self.busy=False
            if generation is not None:
                identifier=0
                if ok:
                    try:
                        reply=json.loads(output);value=reply['data'][0]
                        if reply['type']=='u' and type(value) is int and 0<value<2**32:identifier=value
                    except (ValueError,KeyError,TypeError,IndexError):pass
                if identifier:
                    if generation==self.generation:self.identifier=identifier
                    else:self.closing.append(identifier)
                elif generation==self.generation:
                    LOGGER.warning('Countdown desktop notification failed: %s',output[:400])
                    self.fallback(title,body)
            elif not ok:LOGGER.debug('Countdown notification close failed: %s',output[:400])
            self._dispatch()
        accepted=self.commands.run('countdown-notification',
            ['busctl','--user','--json=short','--timeout=2','call','org.freedesktop.Notifications',
             '/org/freedesktop/Notifications','org.freedesktop.Notifications',*method],finished)
        if not accepted and not called:finished(False,'Notification command is busy')
