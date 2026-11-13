from pathlib import Path
import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conway_desktop.service import install_service,service_file,unit_argument,service_text
from conway_desktop.wallpaper import autostart_file,set_autostart

class UserService(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)/'home with spaces';self.home.mkdir()
        self.env=patch.dict(os.environ,{'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'.config')});self.env.start()
        self.launcher=self.home/'.local/bin/conway-desktop';self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('#!/bin/sh\nexit 0\n');self.launcher.chmod(0o755)
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_registration_moves_autostart_to_service_without_enabling_it(self):
        data=self.home/'custom data';set_autostart(True,data);self.assertTrue(autostart_file().exists())
        file=install_service(data);text=file.read_text()
        self.assertFalse(autostart_file().exists());self.assertIn(unit_argument(data),text)
        self.assertIn('WantedBy=plasma-workspace.target',text);self.assertNotIn('After=plasma-workspace.target',text)
        self.assertIn('RestartPreventExitStatus=2',text);self.assertFalse((file.parent/'plasma-workspace.target.wants').exists())
        with self.assertRaises(RuntimeError):set_autostart(True,data)
    def test_custom_units_are_preserved_with_old_autostart(self):
        set_autostart(True);file=service_file();file.parent.mkdir(parents=True);file.write_text('# custom\n')
        with self.assertRaises(RuntimeError):install_service(self.home/'data')
        self.assertEqual(file.read_text(),'# custom\n');self.assertTrue(autostart_file().exists())
    def test_unit_arguments_escape_specifiers_and_variables_not_shell(self):
        text=service_text('/tmp/a %$"/launcher','/tmp/data %$"')
        self.assertIn('%%$$\\"',text)
        with self.assertRaises(ValueError):unit_argument('/tmp/data\nExecStart=bad')
    def test_install_cli_needs_no_display_or_database(self):
        data=self.home/'data'
        result=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'run.py'),'--install-service','--data-dir',str(data)],
                              env={**os.environ,'QT_QPA_PLATFORM':'invalid-plugin-for-headless-check',
                                   'PYTHONPATH':os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)},capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertTrue(service_file().exists())
        self.assertFalse((data/'state.sqlite3').exists());self.assertFalse((data/'app.lock').exists())
