"""Strict, web-compatible LIF3/LBK3 codecs; no Qt dependency."""
import gzip
import io
import struct
import time
import zlib
import numpy as np
from .model import W,H
L=W*H

def crc(data): return zlib.crc32(data)&0xffffffff

def var(n):
    out=bytearray()
    while n>=128: out.append((n&127)|128); n>>=7
    out.append(n); return out

def readvar(data,offset,end=None):
    end=len(data) if end is None else end; value=0
    for shift in range(0,35,7):
        if offset>=end: raise ValueError('truncated varint')
        b=data[offset]; offset+=1; value|=(b&127)<<shift
        if not b&128: return value,offset
    raise ValueError('invalid varint')

def inflate(data,limit):
    # Bound decompression before allocating an untrusted expanded file.
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        out=stream.read(limit+1)
    if len(out)>limit: raise ValueError('expanded file too large')
    return out

def encode_life(cells,index,timestamp=None):
    if not 0<=index<=255: raise ValueError('index')
    flat=np.asarray(cells,dtype=np.uint8).reshape(-1)
    if flat.size!=L or not np.all((flat==0)|(flat==1)): raise ValueError('cells')
    sparse=bytearray(); last=-1
    for i in np.flatnonzero(flat): sparse.extend(var(int(i)-last)); last=int(i)
    rle=bytearray(); value=0; n=0
    for cell in flat:
        if cell==value: n+=1
        else: rle.extend(var(n)); value=int(cell); n=1
    rle.extend(var(n))
    candidates=[(0,np.packbits(flat,bitorder='little').tobytes()),(1,bytes(sparse)),(2,bytes(rle))]
    candidates += [(codec|128,gzip.compress(payload,mtime=0)) for codec,payload in candidates[:]]
    codec,payload=min(candidates,key=lambda p:len(p[1]))
    head=struct.pack('<4sHHBBI',b'LIF3',W,H,index,codec,int(time.time() if timestamp is None else timestamp)&0xffffffff)
    out=head+payload; return out+struct.pack('<I',crc(out))

def decode_life(data):
    if not 18<=len(data)<=200000: raise ValueError('file size')
    magic,w,h,index,codec,stamp=struct.unpack('<4sHHBBI',data[:14])
    if (magic,w,h)!=(b'LIF3',W,H) or crc(data[:-4])!=struct.unpack('<I',data[-4:])[0]: raise ValueError('checksum or dimensions')
    if codec not in (0,1,2,128,129,130): raise ValueError('codec')
    p=data[14:-4]
    if codec&128: p=inflate(p,L*5+16)
    mode=codec&127; flat=np.zeros(L,dtype=np.uint8)
    if mode==0:
        if len(p)!=(L+7)//8: raise ValueError('bitmap length')
        flat=np.unpackbits(np.frombuffer(p,dtype=np.uint8),bitorder='little')[:L].copy()
    elif mode==1:
        offset=0; last=-1
        while offset<len(p):
            delta,offset=readvar(p,offset); last+=delta
            if delta<1 or last>=L: raise ValueError('sparse index')
            flat[last]=1
    else:
        offset=0; pos=0; value=0; runs=0
        while offset<len(p):
            n,offset=readvar(p,offset)
            if pos+n>L or (runs>0 and n==0): raise ValueError('run length')
            if value: flat[pos:pos+n]=1
            pos+=n; value^=1; runs+=1
        if pos!=L: raise ValueError('incomplete runs')
    return index,stamp,flat.reshape(H,W)

def encode_bank(slots,backups):
    out=bytearray(b'LBK3'); out.extend(var(len(slots)))
    for index,file in sorted(slots.items()): out.extend(var(len(file))); out.extend(file)
    out.extend(var(len(backups)))
    for stamp,file in backups:
        out.extend(struct.pack('<I',int(stamp)&0xffffffff)); out.extend(var(len(file))); out.extend(file)
    out.extend(struct.pack('<I',crc(out))); raw=bytes(out); zipped=gzip.compress(raw,mtime=0)
    return zipped if len(zipped)<len(raw) else raw

def decode_bank(data):
    if len(data)>16*1024*1024: raise ValueError('file too large')
    if data[:2]==b'\x1f\x8b': data=inflate(data,32*1024*1024)
    if len(data)<10 or data[:4]!=b'LBK3' or crc(data[:-4])!=struct.unpack('<I',data[-4:])[0]: raise ValueError('bank checksum')
    end=len(data)-4; n,off=readvar(data,4,end)
    if n>256: raise ValueError('too many slots')
    slots={}; backups=[]
    def file_at(offset):
        length,offset=readvar(data,offset,end)
        if length<18 or offset+length>end: raise ValueError('file length')
        file=data[offset:offset+length]; decoded=decode_life(file)
        return offset+length,file,decoded
    for _ in range(n):
        off,file,decoded=file_at(off)
        if decoded[0] in slots: raise ValueError('duplicate slot')
        slots[decoded[0]]=file
    n,off=readvar(data,off,end)
    if n>50000: raise ValueError('too many backups')
    for _ in range(n):
        if off+4>end: raise ValueError('missing time')
        stamp=struct.unpack('<I',data[off:off+4])[0]; off+=4
        off,file,_=file_at(off); backups.append((stamp,file))
    if off!=end: raise ValueError('trailing data')
    return slots,backups
