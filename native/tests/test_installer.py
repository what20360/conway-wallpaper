"""Exercise the standalone updater without touching the real home or network."""
from pathlib import Path
import hashlib
import os
import platform
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
code=(ROOT/'update.sh').read_text().split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
ns={'__name__':'installer_test'};exec(compile(code,'update.sh','exec'),ns)

class Installer(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'install with spaces';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def release(self,name):
        release=self.root/'releases'/name;release.mkdir(parents=True);(release/'READY').write_text('ready');return release
    def test_fixed_commit_needs_no_api_lookup(self):
        self.assertEqual(ns['remote_commit']('a'*40,self.root),'a'*40)
        self.assertFalse((self.root/'commit.json').exists())
    def test_activation_and_offline_rollback(self):
        a=self.release('a');b=self.release('b');ns['activate'](self.root,a);ns['activate'](self.root,b)
        self.assertEqual((self.root/'previous').resolve(),a)
        ns['activate'](self.root,(self.root/'previous').resolve())
        self.assertEqual((self.root/'current').resolve(),a);self.assertEqual((self.root/'previous').resolve(),b)
    def test_incomplete_release_cannot_replace_current(self):
        old=self.release('old');ns['activate'](self.root,old)
        broken=self.root/'releases'/'broken';broken.mkdir()
        with self.assertRaises(RuntimeError):ns['activate'](self.root,broken)
        self.assertEqual((self.root/'current').resolve(),old)
    def test_repaired_release_is_kept_for_same_commit(self):
        sha='d'*40;repaired=self.release(sha+'-repair-1234');(repaired/'REVISION').write_text(sha)
        ns['activate'](self.root,repaired)
        self.assertEqual(ns['prepared_release'](self.root,sha),repaired)
    def test_archive_traversal_rejected(self):
        sha='a'*40;archive=self.root/'bad.zip';destination=self.root/'out';destination.mkdir()
        with zipfile.ZipFile(archive,'w') as zipped:zipped.writestr('conway-wallpaper-'+sha+'/native/../outside','bad')
        with self.assertRaises(RuntimeError):ns['unpack'](archive,destination,sha)
        self.assertFalse((self.root/'outside').exists())
    def test_dependency_failure_keeps_old_version(self):
        old=self.release('old');ns['activate'](self.root,old);sha='b'*40;archive=self.root/'source.zip'
        self.archive(archive,sha)
        with patch.object(ns['venv'].EnvBuilder,'create',side_effect=RuntimeError('simulated dependency failure')):
            with self.assertRaises(RuntimeError):ns['prepare'](self.root,sha,archive)
        self.assertEqual((self.root/'current').resolve(),old);self.assertFalse((self.root/'releases'/sha).exists())
    def archive(self,archive,sha):
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as zipped:
            for path in ROOT.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.png','.pyc'):
                    zipped.write(path,'conway-wallpaper-'+sha+'/native/'+path.relative_to(ROOT).as_posix())
    def test_prepare_runs_real_qt_smoke_before_activation(self):
        sha='c'*40;archive=self.root/'source.zip';self.archive(archive,sha)
        requirements=(ROOT/'requirements.txt').read_bytes()
        key=hashlib.sha256(requirements+f'{sys.version_info[:2]}-{platform.machine()}'.encode()).hexdigest()[:20]
        environment=self.root/'environments'/key;(environment/'bin').mkdir(parents=True)
        (environment/'bin/python').symlink_to(sys.executable);(environment/'READY').write_text('ready')
        release=ns['prepare'](self.root,sha,archive)
        self.assertTrue((release/'READY').exists());self.assertFalse((self.root/'current').exists())
        ns['activate'](self.root,release);self.assertEqual((self.root/'current').resolve(),release)
        ns['launchers'](self.root,self.root/'fake-home')
        launcher=self.root/'fake-home/.local/bin/conway-desktop'
        self.assertTrue(os.access(launcher,os.X_OK));self.assertIn('"$@"',launcher.read_text())

if __name__=='__main__':unittest.main()
