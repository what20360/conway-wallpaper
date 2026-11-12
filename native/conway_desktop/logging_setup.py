"""Bounded local diagnostics: no SSIDs, passwords or complete Bluetooth addresses."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys

LOGGER = logging.getLogger('conway')
LOGGER.addHandler(logging.NullHandler());LOGGER.propagate=False
LOG_DIR = None
LOG_FILE = None

def redact(value):
    value = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', str(value))
    value = re.sub(r'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b', '<MAC>', value)
    value = re.sub(r'(?i)(token=|Bearer )[a-z0-9]+',r'\1<redacted>',value)
    return value[:2000]

class PrivateHandler(RotatingFileHandler):
    def _open(self):
        fd=os.open(self.baseFilename, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        return os.fdopen(fd, 'a', encoding='utf-8')

class RedactedFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))

def configure(directory, debug=False, filename='conway.log'):
    global LOG_DIR,LOG_FILE
    LOG_DIR=Path(directory);LOG_DIR.mkdir(parents=True,exist_ok=True)
    try:LOG_DIR.chmod(0o700)
    except OSError:pass
    for handler in list(LOGGER.handlers):handler.close();LOGGER.removeHandler(handler)
    LOGGER.setLevel(logging.DEBUG if debug else logging.INFO);LOGGER.propagate=False
    LOG_FILE=LOG_DIR/filename
    handler=PrivateHandler(LOG_FILE,maxBytes=1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(RedactedFormatter('%(asctime)s %(levelname)s %(message)s'))
    LOGGER.addHandler(handler)
    try:LOG_FILE.chmod(0o600)
    except OSError:pass
    def uncaught(kind,value,tb):
        LOGGER.critical('Uncaught exception',exc_info=(kind,value,tb))
        sys.__excepthook__(kind,value,tb)
    sys.excepthook=uncaught
    LOGGER.info('Starting native application; Python=%s platform=%s',sys.version.split()[0],sys.platform)
    return LOG_DIR

def log_dir():return LOG_DIR
def log_file():return LOG_FILE
