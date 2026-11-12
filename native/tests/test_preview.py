import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage,QColor
from conway_desktop.preview import ActivityPreview

class ActivitySnapshots(unittest.TestCase):
    def test_one_private_file_refreshes_at_bounded_interval_and_busts_url_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0];preview=ActivityPreview(folder,clock=lambda:now[0]);image=QImage(1920,1080,QImage.Format.Format_RGB32);image.fill(QColor('green'))
            first=preview.update(image);self.assertTrue(first)
            self.assertEqual(Path(QUrl(first).toLocalFile()),preview.file)
            self.assertEqual(preview.file.stat().st_mode&0o777,0o600)
            data=preview.file.read_bytes();now[0]=10;image.fill(QColor('red'))
            self.assertEqual(preview.update(image),first);self.assertEqual(preview.file.read_bytes(),data)
            now[0]=31;second=preview.update(image);self.assertNotEqual(second,first)
            self.assertEqual(QUrl(first).toLocalFile(),QUrl(second).toLocalFile());self.assertEqual(len(list(Path(folder).iterdir())),1)
            self.assertEqual(QImage(str(preview.file)).pixelColor(320,180),QColor('red'))
    def test_write_failure_preserves_previous_url_and_waits_before_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[0];preview=ActivityPreview(folder,clock=lambda:now[0]);image=QImage(640,360,QImage.Format.Format_RGB32);image.fill(QColor('green'))
            first=preview.update(image);preview.file.unlink();preview.file.mkdir();now[0]=31
            self.assertEqual(preview.update(image),first);self.assertIsNotNone(preview.error)
            # Restoring the location must not cause a rapid retry loop.
            preview.file.rmdir();now[0]=32
            self.assertEqual(preview.update(image),first);self.assertFalse(preview.file.exists())
            now[0]=62;self.assertNotEqual(preview.update(image),first);self.assertIsNone(preview.error)
    def test_non_widescreen_input_is_letterboxed_without_stretch(self):
        with tempfile.TemporaryDirectory() as folder:
            preview=ActivityPreview(folder);image=QImage(300,300,QImage.Format.Format_RGB32);image.fill(QColor('blue'))
            # Different corners make the letterbox background observable.
            image.setPixelColor(0,0,QColor('black'));preview.update(image)
            thumb=QImage(str(preview.file));self.assertEqual((thumb.width(),thumb.height()),(640,360))
            self.assertEqual(thumb.pixelColor(0,180),QColor('black'));self.assertEqual(thumb.pixelColor(320,180),QColor('blue'))

if __name__=='__main__':unittest.main()
