"""One bounded local thumbnail for Plasma's file-based activity switcher."""
from pathlib import Path
import secrets
import time
from PySide6.QtCore import QSaveFile,QFileDevice,QIODevice,Qt,QUrl
from PySide6.QtGui import QImage,QImageWriter,QPainter
from .logging_setup import LOGGER

class ActivityPreview:
    def __init__(self,directory,interval=30,clock=time.monotonic):
        self.file=Path(directory)/'activity-preview.png';self.interval=interval;self.clock=clock
        self.last_attempt=None;self.revision=0;self.session=secrets.token_hex(6);self.url='';self.error=None
    def update(self,image):
        now=self.clock()
        if self.last_attempt is not None and now-self.last_attempt<self.interval:return self.url
        self.last_attempt=now
        try:
            self.file.parent.mkdir(parents=True,exist_ok=True)
            # Always 16:9: Plasma 6.6's activity cards otherwise stretch images.
            thumbnail=QImage(640,360,QImage.Format.Format_RGB32);thumbnail.fill(image.pixelColor(0,0))
            scaled=image.scaled(640,360,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation)
            painter=QPainter(thumbnail);painter.drawImage((640-scaled.width())//2,(360-scaled.height())//2,scaled);painter.end()
            output=QSaveFile(str(self.file));output.setDirectWriteFallback(False)
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):raise OSError(output.errorString())
            if not output.setPermissions(QFileDevice.Permission.ReadOwner|QFileDevice.Permission.WriteOwner):
                output.cancelWriting();raise OSError(output.errorString())
            writer=QImageWriter(output,b'PNG');writer.setCompression(20)
            if not writer.write(thumbnail):output.cancelWriting();raise OSError(writer.errorString())
            if not output.commit():raise OSError(output.errorString())
            self.revision+=1
            self.url=QUrl.fromLocalFile(str(self.file.resolve())).toString()+'#conway-'+self.session+'-'+str(self.revision)
            if self.error:LOGGER.info('Activity preview recovered')
            self.error=None
        except Exception as exc:
            message=str(exc)
            if message!=self.error:LOGGER.warning('Activity preview failed: %s',message)
            self.error=message
        return self.url
