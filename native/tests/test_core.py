import base64
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conway_desktop.model import Model,Clock,evolve,default_cells,random_cells,W,H
from conway_desktop.formats import encode_life,decode_life,encode_bank,decode_bank,inflate
from conway_desktop.storage import Store

class Rules(unittest.TestCase):
    def test_rules(self):
        c=np.zeros((H,W),dtype=np.uint8);c[10:12,10:12]=1
        np.testing.assert_array_equal(evolve(c),c)
        c.fill(0);c[0,[255,0,1]]=1
        expected=np.zeros_like(c);expected[[179,0,1],0]=1
        np.testing.assert_array_equal(evolve(c),expected)
        np.testing.assert_array_equal(evolve(evolve(c)),c)
        c=default_cells(1);old=c.copy()
        for _ in range(4):c=evolve(c)
        np.testing.assert_array_equal(c,np.roll(old,(1,1),(0,1)))
    def test_brush_and_counter(self):
        m=Model();m.cells.fill(0);m.brush=3;m.paint(0,0,False)
        self.assertEqual(int(m.cells.sum()),9);m.paint(0,0,True);self.assertEqual(m.cells.sum(),0)
        m.generation=2**32-1;m.step();self.assertEqual(m.generation,2**32)
    def test_suspend_when_monotonic_excludes_sleep(self):
        clock=Clock();clock.reset(wall=.2,mono=.2,speed=1)
        self.assertFalse(clock.due(1,True,wall=3600.2,mono=.3))
        self.assertTrue(clock.due(1,True,wall=3601,mono=.4))
    def test_seeds(self):
        self.assertEqual(len({random_cells(i).tobytes() for i in range(256)}),256)
        np.testing.assert_array_equal(random_cells(42),random_cells(42))
    def test_clock(self):
        for speed in (.125,.25,.5,1):
            clock=Clock();period=1/speed
            clock.reset(wall=.1,mono=0,speed=speed)
            count=0
            for i in range(1,int(period*100)+1):
                count+=clock.due(speed,True,wall=i/100,mono=i/100)
            self.assertEqual(count,1)
            self.assertFalse(clock.due(speed,True,wall=period+.01,mono=period+.01))
            self.assertFalse(clock.due(speed,True,wall=period+100,mono=period+100))
            self.assertFalse(clock.due(speed,False,wall=period+101,mono=period+100.1))

class Formats(unittest.TestCase):
    def test_roundtrip(self):
        for c in [np.zeros((H,W),dtype=np.uint8),np.ones((H,W),dtype=np.uint8),default_cells(1),random_cells(255)]:
            file=encode_life(c,255,42);index,stamp,result=decode_life(file)
            self.assertEqual((index,stamp),(255,42));np.testing.assert_array_equal(result,c)
            for damaged in (file[:-1],file[:12]+bytes([file[12]^1])+file[13:]):
                with self.assertRaises(ValueError):decode_life(damaged)
        self.assertEqual(len(encode_life(np.zeros((H,W),dtype=np.uint8),0)),18)
    def test_bank(self):
        file=encode_life(default_cells(1),255,42)
        for data in (encode_bank({255:file},[(123,file)]),):
            slots,backups=decode_bank(data);self.assertEqual(slots,{255:file});self.assertEqual(backups,[(123,file)])
            with self.assertRaises((ValueError,EOFError,OSError)):decode_bank(data[:-1])
    def test_limit(self):
        import gzip
        with self.assertRaises(ValueError):inflate(gzip.compress(b'x'*1024),100)
    def test_web_fixtures(self):
        path=Path(__file__).with_name('web-fixtures.json')
        fixtures=json.loads(path.read_text())
        for row in fixtures['files']:
            index,stamp,cells=decode_life(base64.b64decode(row['file']))
            self.assertEqual(index,row['index']);self.assertEqual(int(cells.sum()),row['population'])
            if row['random']:
                np.testing.assert_array_equal(cells,random_cells(index))
            else:np.testing.assert_array_equal(cells,default_cells(index))
        slots,backups=decode_bank(base64.b64decode(fixtures['bank']))
        self.assertEqual(len(slots),2);self.assertEqual(len(backups),1)

class Persistence(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.sqlite3';self.store=Store(self.path)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def test_checkpoint_separate_from_presets(self):
        m=Model();m.cells=random_cells(42);m.generation=600000000;m.running=True
        self.store.checkpoint(m);self.store.close();self.store=Store(self.path)
        restored=Model();self.assertTrue(self.store.restore(restored));np.testing.assert_array_equal(m.cells,restored.cells)
        self.assertEqual(restored.settings(),m.settings());self.assertFalse(self.store.custom(1));self.assertEqual(self.store.backups(),[])
    def test_backup(self):
        c=default_cells(1);self.store.save(255,c);self.assertEqual(len(self.store.backups()),0)
        self.store.save(255,c);self.assertEqual(len(self.store.backups()),0)
        self.store.save(255,np.zeros((H,W),dtype=np.uint8));self.assertEqual(len(self.store.backups()),1)
        np.testing.assert_array_equal(decode_life(self.store.backups()[0][1])[2],c)
    def test_failed_import_rolls_back(self):
        original=default_cells(1);self.store.save(255,original)
        incoming=encode_bank({255:encode_life(random_cells(42),255)},[])
        self.store.db.execute("CREATE TRIGGER deny BEFORE INSERT ON presets BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.import_bank(incoming)
        np.testing.assert_array_equal(self.store.slot(255),original);self.assertEqual(self.store.backups(),[])
    def test_import_explicit_empty_keeps_slot_identity(self):
        c=np.zeros((H,W),dtype=np.uint8)
        self.store.import_bank(encode_bank({255:encode_life(c,255)},[]))
        self.assertTrue(self.store.custom(255))
        self.store.save(255,default_cells(1));self.assertEqual(len(self.store.backups()),1)
    def test_bad_checkpoint_does_not_partially_restore(self):
        m=Model();self.store.checkpoint(m)
        with self.store.db:self.store.db.execute("UPDATE checkpoint SET settings='[]'")
        other=Model();other.generation=123
        with self.assertRaises(ValueError):self.store.restore(other)
        self.assertEqual(other.generation,123)

if __name__=='__main__':unittest.main()
