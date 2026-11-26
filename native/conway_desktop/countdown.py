"""A countdown that charges only time spent in a known unlocked session."""
import math
import time

MAX_SECONDS=999*3600+59*60+59

class Countdown:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.stamp=clock();self.duration=25*60;self.remaining=0.
        self.state='idle';self.locked=None;self.pending=False
        self.repeat=False;self.rounds=0;self.unacknowledged=0
    def update(self):
        now=self.clock();elapsed=max(0,now-self.stamp);self.stamp=now
        if self.state=='running' and self.locked is False:
            if elapsed>=self.remaining:
                excess=elapsed-self.remaining
                completed=1+int(excess//self.duration) if self.repeat else 1
                self.remaining=self.duration-excess%self.duration if self.repeat else 0.
                if not self.repeat:self.state='finished'
                self.rounds+=completed;self.unacknowledged+=completed;self.pending=True
            else:self.remaining-=elapsed
    def set_locked(self,value):
        if value is not None and type(value) is not bool:raise ValueError('lock state')
        self.update();self.locked=value
    def start(self,seconds):
        if type(seconds) is not int or not 1<=seconds<=MAX_SECONDS:raise ValueError('countdown duration')
        self.duration=seconds;self.remaining=float(seconds);self.state='running';self.pending=False;self.stamp=self.clock()
        self.rounds=0;self.unacknowledged=0
    def set_repeat(self,value):
        if type(value) is not bool:raise ValueError('countdown repeat')
        self.update();self.repeat=value
    def pause(self):
        self.update()
        if self.state=='running':self.state='paused'
    def resume(self):
        if self.state=='paused':self.state='running';self.stamp=self.clock()
    def cancel(self):
        self.remaining=0.;self.state='idle';self.pending=False;self.stamp=self.clock()
        self.rounds=0;self.unacknowledged=0
    def acknowledge(self):self.unacknowledged=0;self.pending=False
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
        return dict(duration=self.duration,remaining=self.remaining,state=self.state,pending=self.pending,
                    repeat=self.repeat,rounds=self.rounds,unacknowledged=self.unacknowledged)
    def restore(self,data):
        duration=data['duration'];remaining=data['remaining'];state=data['state'];pending=data['pending']
        repeat=data.get('repeat',False);rounds=data.get('rounds',1 if state=='finished' else 0)
        unacknowledged=data.get('unacknowledged',1 if pending else 0)
        if type(duration) is not int or not 1<=duration<=MAX_SECONDS:raise ValueError('countdown duration')
        if type(remaining) not in (int,float) or not math.isfinite(remaining) or not 0<=remaining<=duration:raise ValueError('countdown remaining')
        if state not in ('idle','running','paused','finished') or type(pending) is not bool:raise ValueError('countdown state')
        if (state in ('running','paused') and remaining<=0) or (state in ('idle','finished') and remaining!=0):raise ValueError('countdown state')
        if type(repeat) is not bool or type(rounds) is not int or type(unacknowledged) is not int or not 0<=unacknowledged<=rounds:raise ValueError('countdown rounds')
        if (pending and not unacknowledged) or (state=='idle' and rounds) or (state=='finished' and not rounds):raise ValueError('countdown reminder')
        self.duration=duration;self.remaining=float(remaining);self.state=state;self.pending=pending or bool(unacknowledged);self.stamp=self.clock()
        self.repeat=repeat;self.rounds=rounds;self.unacknowledged=unacknowledged
