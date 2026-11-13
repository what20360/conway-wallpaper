"""A countdown that charges only time spent in a known unlocked session."""
import math
import time

MAX_SECONDS=999*3600+59*60+59

class Countdown:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.stamp=clock();self.duration=25*60;self.remaining=0.
        self.state='idle';self.locked=None;self.pending=False
    def update(self):
        now=self.clock();elapsed=max(0,now-self.stamp);self.stamp=now
        if self.state=='running' and self.locked is False:
            self.remaining=max(0.,self.remaining-elapsed)
            if self.remaining==0:self.state='finished';self.pending=True
    def set_locked(self,value):
        if value is not None and type(value) is not bool:raise ValueError('lock state')
        self.update();self.locked=value
    def start(self,seconds):
        if type(seconds) is not int or not 1<=seconds<=MAX_SECONDS:raise ValueError('countdown duration')
        self.duration=seconds;self.remaining=float(seconds);self.state='running';self.pending=False;self.stamp=self.clock()
    def pause(self):
        self.update()
        if self.state=='running':self.state='paused'
    def resume(self):
        if self.state=='paused':self.state='running';self.stamp=self.clock()
    def cancel(self):self.remaining=0.;self.state='idle';self.pending=False;self.stamp=self.clock()
    def take_reminder(self):
        if self.pending and self.locked is False:self.pending=False;return True
        return False
    @property
    def status(self):
        if self.state=='running':return 'WAIT' if self.locked is None else 'LOCK' if self.locked else 'RUN'
        return {'idle':'SET','paused':'PAUSE','finished':'DONE'}[self.state]
    @property
    def label(self):
        if self.state=='idle':return '--:--:--'
        seconds=math.ceil(self.remaining);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
        return f'{hours:02}:{minutes:02}:{seconds:02}'
    def snapshot(self):
        self.update()
        return dict(duration=self.duration,remaining=self.remaining,state=self.state,pending=self.pending)
    def restore(self,data):
        duration=data['duration'];remaining=data['remaining'];state=data['state'];pending=data['pending']
        if type(duration) is not int or not 1<=duration<=MAX_SECONDS:raise ValueError('countdown duration')
        if type(remaining) not in (int,float) or not math.isfinite(remaining) or not 0<=remaining<=duration:raise ValueError('countdown remaining')
        if state not in ('idle','running','paused','finished') or type(pending) is not bool:raise ValueError('countdown state')
        if (state in ('running','paused') and remaining<=0) or (state in ('idle','finished') and remaining!=0) or (pending and state!='finished'):raise ValueError('countdown state')
        self.duration=duration;self.remaining=float(remaining);self.state=state;self.pending=pending;self.stamp=self.clock()
