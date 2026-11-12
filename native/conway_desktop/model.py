"""Pure model and clock: independent of Qt and OS controls."""
import time
import numpy as np

W, H = 256, 180
SPEEDS = (.125, .25, .5, 1, 2, 4, 8, 16)
SPEED_LABELS = ('1/8', '1/4', '1/2', '1', '2', '4', '8', '16')
PALETTES = ('night', 'ice', 'violet', 'day', 'sand', 'forest')

def evolve(cells):
    neighbors = np.zeros_like(cells, dtype=np.uint8)
    for y, x in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
        neighbors += np.roll(cells, (y,x), (0,1))
    return ((neighbors == 3) | ((cells != 0) & (neighbors == 2))).astype(np.uint8)

def default_cells(index):
    c = np.zeros((H,W), dtype=np.uint8)
    pulsar = [(a,b) for a in (2,3,4,8,9,10) for b in (0,5,7,12)]
    pulsar += [(b,a) for a,b in list(pulsar)]
    gun = ['........................O...........', '......................O.O...........',
           '............OO......OO............OO', '...........O...O....OO............OO',
           'OO........O.....O...OO..............', 'OO........O...O.OO....O.O...........',
           '..........O.....O.......O...........', '...........O...O....................',
           '............OO......................']
    patterns = [[], [(1,0),(2,1),(0,2),(1,2),(2,2)],
                [(1,0),(4,0),(0,1),(0,2),(4,2),(0,3),(1,3),(2,3),(3,3)], pulsar,
                [(x,y) for y,row in enumerate(gun) for x,ch in enumerate(row) if ch=='O'],
                [(1,0),(2,0),(0,1),(1,1),(1,2)],
                [(1,0),(3,1),(0,2),(1,2),(4,2),(5,2),(6,2)],
                [(6,0),(0,1),(1,1),(1,2),(5,2),(6,2),(7,2)]]
    pts = patterns[index] if 0 <= index < len(patterns) else []
    if pts:
        ox=(W-max(x for x,y in pts)-1)//2; oy=(H-max(y for x,y in pts)-1)//2
        for x,y in pts: c[oy+y,ox+x]=1
    return c

def random_cells(seed):
    if not 0 <= seed <= 255: raise ValueError('seed')
    # Same LCG and row-major order as the web edition, not NumPy's RNG.
    s=seed+1; c=np.empty(W*H,dtype=np.uint8)
    for i in range(W*H):
        s=(s*1664525+1013904223)&0xffffffff; c[i]=s/4294967296 < .18
    return c.reshape(H,W)

class Model:
    def __init__(self):
        self.cells=default_cells(1); self.generation=0; self.running=False
        self.speed=8; self.brush=1; self.palette='night'; self.mode='preset'
        self.preset=1; self.seed=42; self.trails=True
        self.fade=np.zeros((H,W),dtype=np.float32)
    @property
    def index(self): return self.preset if self.mode=='preset' else self.seed
    def select(self,n):
        if self.mode=='preset': self.preset=n%256
        else: self.seed=n%256
    def step(self):
        new=evolve(self.cells)
        self.fade=np.where((self.cells!=0)&(new==0),1,self.fade)
        self.cells=new; self.generation+=1
    def load(self,cells):
        self.cells=np.asarray(cells,dtype=np.uint8).reshape(H,W).copy()
        self.generation=0; self.running=False; self.fade.fill(0)
    def paint(self,x,y,erase):
        r=self.brush//2
        for yy in range(y-r,y+r+1):
            for xx in range(x-r,x+r+1):
                self.cells[yy%H,xx%W]=0 if erase else 1; self.fade[yy%H,xx%W]=0
    def settings(self):
        return {k:getattr(self,k) for k in ('generation','running','speed','brush','palette','mode','preset','seed','trails')}
    def restore(self,cells,settings):
        self.cells=cells.copy()
        n=settings.get('generation',0)
        self.generation=n if isinstance(n,int) and 0<=n<2**63 else 0
        self.running=settings.get('running') is True
        old_speed=settings.get('speed',8)
        self.speed=max((s for s in SPEEDS if s<=old_speed),default=SPEEDS[0]) if isinstance(old_speed,(int,float)) and old_speed>0 else 8
        self.brush=settings.get('brush') if settings.get('brush') in (1,3,5) else 1
        self.palette=settings.get('palette') if settings.get('palette') in PALETTES else 'night'
        self.mode='random' if settings.get('mode')=='random' else 'preset'
        for key,default in (('preset',1),('seed',42)):
            n=settings.get(key,default); setattr(self,key,n if isinstance(n,int) and 0<=n<=255 else default)
        self.trails=settings.get('trails') is not False

class Clock:
    def __init__(self): self.reset()
    def reset(self,wall=None,mono=None,speed=8):
        self.last_mono=time.monotonic() if mono is None else mono
        self.last_wall=time.time() if wall is None else wall
        self.bucket=int(self.last_wall*speed)
        self.speed=speed
    def due(self,speed,active,wall=None,mono=None):
        wall=time.time() if wall is None else wall; mono=time.monotonic() if mono is None else mono
        bucket=int(wall*speed)
        wall_gap=wall-self.last_wall;self.last_wall=wall
        if speed!=self.speed or not active or mono-self.last_mono>2 or mono<self.last_mono or abs(wall_gap)>2:
            self.reset(wall,mono,speed); return False
        if speed<=1:
            result=bucket>self.bucket; self.bucket=bucket
            # Track the last event-loop visit separately, even for an 8-second period.
            self.last_mono=mono; return result
        if mono-self.last_mono>=1/speed:
            self.last_mono=mono; return True
        return False
