"""Atomic SQLite checkpoints and explicitly overwritten presets."""
import json
import sqlite3
import time
import numpy as np
from .model import Model,default_cells,W,H
from .formats import encode_life,decode_life,decode_bank,encode_bank

class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path)); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),data BLOB NOT NULL,settings TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS presets(slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 0 AND 255),data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS app_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS backups(id INTEGER PRIMARY KEY,stamp INTEGER NOT NULL,data BLOB NOT NULL);
        ''')
    def checkpoint(self,model,countdown=None):
        blob=encode_life(model.cells,model.preset)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES(1,?,?)',(blob,json.dumps(model.settings())))
            if countdown is not None:self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',('countdown',json.dumps(countdown.snapshot())))
    def restore(self,model):
        row=self.db.execute('SELECT data,settings FROM checkpoint WHERE id=1').fetchone()
        if not row: return False
        _,_,cells=decode_life(row[0]); settings=json.loads(row[1])
        if not isinstance(settings,dict): raise ValueError('checkpoint settings')
        model.restore(cells,settings); return True
    def save_countdown(self,countdown):
        with self.db:self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',('countdown',json.dumps(countdown.snapshot())))
    def restore_countdown(self,countdown):
        row=self.db.execute('SELECT value FROM app_state WHERE key=?',('countdown',)).fetchone()
        if row:countdown.restore(json.loads(row[0]));return True
        return False
    def slot(self,index):
        row=self.db.execute('SELECT data FROM presets WHERE slot=?',(index,)).fetchone()
        return decode_life(row[0])[2] if row else default_cells(index)
    def custom(self,index): return self.db.execute('SELECT 1 FROM presets WHERE slot=?',(index,)).fetchone() is not None
    def save(self,index,cells):
        previous=self.slot(index)
        if np.array_equal(previous,cells): return False
        old=self.db.execute('SELECT data FROM presets WHERE slot=?',(index,)).fetchone()
        with self.db:
            if old or previous.any(): self.db.execute('INSERT INTO backups(stamp,data) VALUES(?,?)',(int(time.time()),old[0] if old else encode_life(previous,index,0)))
            self.db.execute('INSERT OR REPLACE INTO presets VALUES(?,?)',(index,encode_life(cells,index)))
        return True
    def backups(self): return self.db.execute('SELECT stamp,data FROM backups ORDER BY id').fetchall()
    def export_bank(self):
        return encode_bank(dict(self.db.execute('SELECT slot,data FROM presets')),self.backups())
    def import_bank(self,data):
        slots,backups=decode_bank(data)  # Entire file verified before any writes.
        changes=[]
        for index,file in slots.items():
            previous=self.slot(index); new=decode_life(file)[2]
            if np.array_equal(previous,new):
                if not self.custom(index):changes.append((index,file,None))
                continue
            old=self.db.execute('SELECT data FROM presets WHERE slot=?',(index,)).fetchone()
            backup=old[0] if old else encode_life(previous,index,0) if previous.any() else None
            changes.append((index,file,backup))
        with self.db:
            for index,file,backup in changes:
                if backup: self.db.execute('INSERT INTO backups(stamp,data) VALUES(?,?)',(int(time.time()),backup))
                self.db.execute('INSERT OR REPLACE INTO presets VALUES(?,?)',(index,file))
            existing=set(self.backups())
            for stamp,file in backups:
                if (stamp,file) not in existing:
                    self.db.execute('INSERT INTO backups(stamp,data) VALUES(?,?)',(stamp,file)); existing.add((stamp,file))
    def close(self): self.db.close()
