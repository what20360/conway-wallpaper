"""Deterministic large compositions, all on the same toroidal B3/S23 board.

The meteor shower is a fleet of downward LWSS, not a new cellular rule.
Existing user slots take precedence over these built-ins in Store.slot().
"""
import numpy as np
import json
from pathlib import Path
from .model import W,H,evolve,default_cells

NAMES={8:'流星雨',9:'密集流星雨',10:'对称横向舰队',11:'交汇舰队',12:'四座滑翔机枪',
       13:'脉冲星阵列',14:'橡实花园',15:'R 五连块星群',16:'四向滑翔机枪',
       17:'振荡器走廊',18:'混合实验场',19:'雨与灯塔',20:'Schick 引擎阵列',21:'Weekender 舰队',
       22:'双蜂穿梭阵列',23:'十五周期振荡器阵列',24:'Puffer 喷射器阵列'}
LEXICON=json.loads(Path(__file__).with_name('lexicon-patterns.json').read_text())['patterns']

def lexicon_pattern(name):
    return np.array([[ch=='O' for ch in row] for row in LEXICON[name]['rows']],dtype=np.uint8)

def crop(cells):
    yy,xx=np.nonzero(cells)
    return cells[yy.min():yy.max()+1,xx.min():xx.max()+1].copy()

def ship(phase=0,turns=0):
    cells=default_cells(2)
    for _ in range(phase%4):cells=evolve(cells)
    return np.rot90(crop(cells),turns).copy()

def large_preset(index):
    result=np.zeros((H,W),dtype=np.uint8)
    def put(pattern,x,y):
        h,w=pattern.shape
        if x<0 or y<0 or x+w>W or y+h>H:raise ValueError('preset outside board')
        result[y:y+h,x:x+w]|=pattern
    def basic(n):return crop(default_cells(n))
    def quartet(pattern,x,y):
        h,w=pattern.shape
        put(pattern,x,y);put(np.fliplr(pattern),W-x-w,y)
        put(np.flipud(pattern),x,H-y-h);put(np.flip(pattern),W-x-w,H-y-h)
    def symmetric_grid(pattern,cols,rows,dx,dy):
        h,w=pattern.shape
        # Even counts and matching pitch parity center the lattice exactly, with
        # both mirror axes between cells on the even-sized world.
        dx+=((w-dx)%2);dy+=((h-dy)%2)
        x0=(W-w-(cols-1)*dx)//2;y0=(H-h-(rows-1)*dy)//2
        for iy in range(rows//2):
            for ix in range(cols//2):quartet(pattern,x0+ix*dx,y0+iy*dy)
    if 20<=index<=24:
        name,cols,rows,dx,dy={20:('Schick_engine',4,4,60,41),21:('weekender',4,4,60,41),
                            22:('twin_bees_shuttle',4,4,61,41),23:('pentadecathlon',8,6,30,27),
                            24:('puffer',4,4,61,41)}[index]
        symmetric_grid(lexicon_pattern(name),cols,rows,dx,dy)
    elif index in (8,9,19):
        # A 9-row period is the smallest divisor of H that preserves independent
        # LWSS flight. Repeat through the seam: no separate groups or large gaps.
        pattern=ship(0,1);h,w=pattern.shape;cols=6 if index==9 else 4;dx=40 if cols==6 else 60
        x0=(W-w-(cols-1)*dx)//2
        for column in range(cols//2):
            x=x0+column*dx
            for y in range(0,H,9):
                put(pattern,x,y);put(np.fliplr(pattern),W-x-w,y)
        if index==19:
            quartet(basic(3),61,41)
    elif index in (10,11):
        symmetric_grid(ship(0,0 if index==10 else 1),8 if index==10 else 6,8,31 if index==10 else 40,22 if index==10 else 21)
    elif index in (12,16):
        gun=np.rot90(basic(4),1 if index==16 else 0).copy()
        symmetric_grid(gun,2,2,141 if index==16 else 128,90 if index==16 else 91)
    elif index in (13,14,15,17):
        n={13:3,14:6,15:5,17:3}[index]
        symmetric_grid(basic(n),8 if index==17 else 6,6 if index==17 else 4,31 if index==17 else 40,31 if index==17 else 40)
    elif index==18:
        for iy in range(2):
            for ix in range(2):
                p=basic((3,4,6,7)[iy*2+ix]);h,w=p.shape
                tile=np.zeros((36,40),np.uint8);tile[(36-h)//2:(36-h)//2+h,(40-w)//2:(40-w)//2+w]=p
                quartet(tile,18+ix*60,6+iy*44)
    return result
