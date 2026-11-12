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
import shutil
import urllib.error
ROOT=Path(__file__).resolve().parents[1]
code=(ROOT/'update.sh').read_text().split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
ns={'__name__':'installer_test'};exec(compile(code,'update.sh','exec'),ns)

class Installer(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'install with spaces';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def release(self,name):
        release=self.root/'releases'/name;release.mkdir(parents=True);(release/'READY').write_text('ready');return release
    def source_fixture(self,comment=b''):
        archive=self.root/'fixture.zip';self.archive(archive,'main')
        with zipfile.ZipFile(archive,'a') as zipped:zipped.comment=comment
        return archive
    def test_default_download_never_calls_api(self):
        sha='a'*40;fixture=self.source_fixture(sha.encode());folder=self.root/'download';folder.mkdir();urls=[]
        def download(url,target,**kwargs):
            urls.append(url);self.assertNotIn('api.github.com',url);shutil.copyfile(fixture,target)
        with patch.dict(ns,{'download':download}):revision,archive=ns['fetch_source']('main',folder)
        self.assertEqual(revision,sha);self.assertEqual(len(urls),1);self.assertIn('/zip/refs/heads/main',urls[0])
        destination=self.root/'unpack';destination.mkdir();ns['unpack'](archive,destination,revision)
        self.assertTrue((destination/'run.py').exists())
    def test_fixed_commit_download_needs_no_api(self):
        sha='b'*40;fixture=self.source_fixture(sha.encode());folder=self.root/'download';folder.mkdir();urls=[]
        def download(url,target,**kwargs):urls.append(url);shutil.copyfile(fixture,target)
        with patch.dict(ns,{'download':download}):revision,archive=ns['fetch_source'](sha,folder)
        self.assertEqual(revision,sha);self.assertEqual(urls,['https://codeload.github.com/what20360/conway-wallpaper/zip/'+sha])
    def test_missing_comment_uses_content_identity(self):
        fixture=self.source_fixture();folder=self.root/'download';folder.mkdir()
        with patch.dict(ns,{'download':lambda url,target:shutil.copyfile(fixture,target)}):revision,archive=ns['fetch_source']('main',folder)
        self.assertEqual(revision,'archive-'+hashlib.sha256(archive.read_bytes()).hexdigest())
        destination=self.root/'unpack';destination.mkdir();ns['unpack'](archive,destination,revision)
        self.assertTrue((destination/'run.py').exists())
    def test_branch_404_tries_tag_but_403_does_not_retry(self):
        fixture=self.source_fixture(b'a'*40);folder=self.root/'download';folder.mkdir();urls=[]
        def download(url,target):
            urls.append(url)
            if '/heads/' in url:raise urllib.error.HTTPError(url,404,'not found',{},None)
            shutil.copyfile(fixture,target)
        with patch.dict(ns,{'download':download}):ns['fetch_source']('v1',folder)
        self.assertIn('/tags/v1',urls[-1])
        error=urllib.error.HTTPError('https://codeload.github.com/test',403,'rate limit exceeded',{},None)
        with patch.dict(ns,{'download':lambda *args:(_ for _ in ()).throw(error)}):
            with self.assertRaises(urllib.error.HTTPError):ns['fetch_source']('main',folder)
        self.assertIn('网络／下载',ns['failure_message'](error))
    def test_wrong_commit_in_zip_is_rejected(self):
        fixture=self.source_fixture(b'a'*40)
        with self.assertRaises(RuntimeError):ns['archive_revision'](fixture,'b'*40)
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
