"""Deterministic large compositions, all on the same toroidal B3/S23 board.

The meteor shower is a fleet of downward LWSS, not a new cellular rule.
Existing user slots take precedence over these built-ins in Store.slot().
"""
import numpy as np
from .model import W,H,evolve,default_cells

NAMES={8:'流星雨',9:'密集流星雨',10:'横向舰队',11:'交汇舰队',12:'四座滑翔机枪',
       13:'脉冲星阵列',14:'橡实花园',15:'R 五连块星群',16:'四向滑翔机枪',
       17:'振荡器走廊',18:'混合实验场',19:'雨与灯塔'}

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
    if index in (8,9,19):
        # np.rot90 turns left-moving LWSS into vertically descending spaceships.
        cols,rows=(12,4) if index==8 else (16,5) if index==9 else (8,3)
        for column in range(cols):
            for row in range(rows):
                put(ship((column+row)%4,1),8+column*(240//cols),8+row*30+(column*7)%19)
        if index==19:
            for x in (30,100,170):put(basic(3),x,140)
    elif index in (10,11):
        for row in range(8):
            for column in range(5):
                put(ship((row+column)%4,2 if index==11 and row%2 else 0),12+column*47,8+row*21)
    elif index in (12,16):
        gun=basic(4)
        for i,(x,y) in enumerate(((20,20),(160,20),(20,105),(160,105))):
            put(np.rot90(gun,i if index==16 else 0).copy(),x,y)
    elif index in (13,14,15,17):
        n={13:3,14:6,15:5,17:3}[index]
        for row in range(4):
            for column in range(6 if index!=17 else 9):
                put(np.rot90(basic(n),(row+column)%4).copy(),8+column*(40 if index!=17 else 27),10+row*40)
    elif index==18:
        for row in range(3):
            for column in range(5):
                n=(3,4,5,6,7)[(row+column)%5]
                put(basic(n),8+column*49,12+row*54)
    return result
