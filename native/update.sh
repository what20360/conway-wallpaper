#!/usr/bin/env bash
# Download this file and run with bash. App data is kept outside managed releases.
set -Eeuo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  echo '需要 Python 3.10 或更新版本。Kubuntu 可安装 python3 和 python3-venv。' >&2
  exit 1
fi
exec python3 - "$@" <<'PY'
import argparse
import contextlib
import fcntl
import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path,PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import venv
import zipfile

REPO='what20360/conway-wallpaper'
LOG=logging.getLogger('update')

def download(url,target,limit=64*1024*1024):
    LOG.info('Download source url=%s',url)
    request=urllib.request.Request(url,headers={'User-Agent':'ConwayDesktopUpdater/0.3.5','Accept':'application/zip, */*'})
    with urllib.request.urlopen(request,timeout=30) as response,open(target,'wb') as out:
        size=0
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>limit:raise RuntimeError('下载文件超过大小限制')
            out.write(chunk)

def archive_revision(archive,expected=None):
    with zipfile.ZipFile(archive) as zipped:
        comment=zipped.comment.decode('ascii',errors='ignore').strip()
    if re.fullmatch('[0-9a-f]{40}',comment):
        if expected and comment!=expected:raise RuntimeError('归档提交号与请求不符')
        return comment
    if expected:return expected
    # A coherent downloaded snapshot remains identifiable without any API lookup.
    return 'archive-'+hashlib.sha256(archive.read_bytes()).hexdigest()

def fetch_source(ref,folder):
    archive=folder/'source.zip'
    if re.fullmatch('[0-9a-f]{40}',ref):
        download(f'https://codeload.github.com/{REPO}/zip/{ref}',archive)
        return archive_revision(archive,ref),archive
    quoted=urllib.parse.quote(ref,safe='/')
    try:download(f'https://codeload.github.com/{REPO}/zip/refs/heads/{quoted}',archive)
    except urllib.error.HTTPError as exc:
        if exc.code!=404:raise
        download(f'https://codeload.github.com/{REPO}/zip/refs/tags/{quoted}',archive)
    return archive_revision(archive),archive

def unpack(archive,destination,sha):
    total=0;count=0
    with zipfile.ZipFile(archive) as zipped:
        roots={member.filename.split('/')[0] for member in zipped.infolist() if member.filename}
        if len(roots)!=1:raise RuntimeError('归档必须只有一个仓库根目录')
        root=roots.pop()
        if not root.startswith('conway-wallpaper-'):raise RuntimeError('归档不是预期仓库')
        if sha.startswith('archive-'):
            if 'archive-'+hashlib.sha256(archive.read_bytes()).hexdigest()!=sha:raise RuntimeError('归档内容标识不符')
        else:archive_revision(archive,sha)
        prefix=root+'/native/'
        for member in zipped.infolist():
            path=PurePosixPath(member.filename)
            if path.is_absolute() or '..' in path.parts:raise RuntimeError('归档路径不安全')
            if not member.filename.startswith(prefix):continue
            relative=PurePosixPath(member.filename[len(prefix):])
            if not relative.parts or member.is_dir():continue
            if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):raise RuntimeError('归档路径不安全')
            if (member.external_attr>>16)&0o170000==0o120000:raise RuntimeError('归档含符号链接')
            total+=member.file_size;count+=1
            if total>32*1024*1024 or count>5000:raise RuntimeError('归档解压超过限制')
            target=destination.joinpath(*relative.parts);target.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(member) as source,target.open('wb') as out:shutil.copyfileobj(source,out)
    for name in ('run.py','requirements.txt','VERSION','conway_desktop/app.py','update.sh'):
        if not (destination/name).is_file():raise RuntimeError('下载内容缺少 '+name)

def link_replace(link,target):
    if link.exists() and not link.is_symlink():raise RuntimeError(str(link)+' 已存在且不是本安装器管理的符号链接')
    temp=link.with_name(link.name+'.new')
    if temp.is_symlink():temp.unlink()
    elif temp.exists():raise RuntimeError('临时激活路径已被占用：'+str(temp))
    temp.symlink_to(target,target_is_directory=True);os.replace(temp,link)

def activate(root,release):
    if not (release/'READY').is_file():raise RuntimeError('版本未通过准备／自检，拒绝激活')
    current=root/'current';previous=root/'previous'
    old=current.resolve() if current.is_symlink() else None
    if old==release:return
    if old and old.exists():link_replace(previous,old)
    link_replace(current,release)

def command(args,**kwargs):
    LOG.info('Run %s',shlex.join(map(str,args)))
    try:subprocess.run(list(map(str,args)),check=True,**kwargs)
    except subprocess.CalledProcessError as exc:
        stage='Qt 启动／绘制验证失败，请查看前面的具体错误和 README 图形依赖' if '--render' in list(map(str,args)) else 'Python 依赖安装失败，请查看前面的 pip 输出'
        raise RuntimeError(stage+'；命令：'+shlex.join(map(str,args))) from exc

def prepared_release(root,sha):
    current=root/'current'
    if current.is_symlink():
        candidate=current.resolve()
        if (candidate/'READY').is_file() and (candidate/'REVISION').is_file() and (candidate/'REVISION').read_text().strip()==sha:return candidate
    return root/'releases'/sha

def prepare(root,sha,archive,repair=False):
    release=prepared_release(root,sha)
    if (release/'READY').is_file() and not repair:return release
    if release.exists():
        # Never delete an active version, including during a repair attempt.
        if (release/'READY').is_file() or ((root/'current').is_symlink() and (root/'current').resolve()==release):
            release=release.with_name(sha+'-repair-'+os.urandom(4).hex())
        else:shutil.rmtree(release)
    release.mkdir(parents=True)
    created_env=None
    try:
        unpack(archive,release,sha)
        requirements=(release/'requirements.txt').read_bytes()
        key=hashlib.sha256(requirements+f'{sys.version_info[:2]}-{platform.machine()}'.encode()).hexdigest()[:20]
        if repair:key+='-'+os.urandom(4).hex()
        environment=root/'environments'/key
        current=root/'current'
        if not repair and current.is_symlink():
            candidate=current.resolve()
            if (candidate/'requirements.txt').is_file() and (candidate/'requirements.txt').read_bytes()==requirements:
                previous_env=(candidate/'.venv-native').resolve()
                if previous_env.name.startswith(key) and (previous_env/'READY').is_file():environment=previous_env
        if not (environment/'READY').is_file():
            if environment.exists():shutil.rmtree(environment)
            environment.parent.mkdir(parents=True,exist_ok=True);created_env=environment
            print('正在创建运行环境并安装依赖……',flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
            command([environment/'bin/python','-m','pip','install','-r',release/'requirements.txt'])
            (environment/'READY').write_text('ready\n')
        (release/'.venv-native').symlink_to(environment,target_is_directory=True)
        print('正在验证原生 Qt 启动和绘制……',flush=True)
        env={**os.environ,'QT_QPA_PLATFORM':'offscreen'}
        command([environment/'bin/python',release/'run.py','--render',release/'smoke.png','--no-system'],env=env)
        (release/'smoke.png').unlink(missing_ok=True)
        (release/'REVISION').write_text(sha+'\n');(release/'READY').write_text('ready\n')
        return release
    except BaseException:
        shutil.rmtree(release,ignore_errors=True)
        if created_env:shutil.rmtree(created_env,ignore_errors=True)
        raise

def launchers(root,home):
    directory=home/'.local/bin';directory.mkdir(parents=True,exist_ok=True)
    for name,body in (
        ('conway-desktop','exec '+shlex.quote(str(root/'current/.venv-native/bin/python'))+' '+shlex.quote(str(root/'current/run.py'))+' "$@"'),
        ('conway-desktop-update','exec bash '+shlex.quote(str(root/'current/update.sh'))+' --install-dir '+shlex.quote(str(root))+' "$@"')):
        file=directory/name;file.write_text('#!/bin/sh\n'+body+'\n');file.chmod(0o755)
    apps=home/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    executable=str(directory/'conway-desktop').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
    (apps/'conway-desktop.desktop').write_text('[Desktop Entry]\nType=Application\nName=生命场\nComment=像素生命场与系统控制\nExec="'+executable+'"\nIcon=applications-graphics\nTerminal=false\nCategories=Utility;\n')
    (apps/'conway-wallpaper.desktop').write_text('[Desktop Entry]\nType=Application\nName=生命场壁纸后台\nComment=启动 Plasma 6 原生壁纸服务\nExec="'+executable+'" --wallpaper\nIcon=preferences-desktop-wallpaper\nTerminal=false\nCategories=Utility;\n')

def main(argv=None):
    parser=argparse.ArgumentParser(description='生命场一键安装／更新；不修改应用数据')
    parser.add_argument('--install-dir',type=Path,default=Path.home()/'.local/share/conway-desktop-install')
    parser.add_argument('--ref',default='main',help='分支、标签或提交，默认 main')
    parser.add_argument('--rollback',action='store_true',help='切回上一个已准备版本，无需联网')
    parser.add_argument('--repair',action='store_true',help='创建新环境修复依赖，保留正在运行的旧版')
    parser.add_argument('--run',action='store_true',help='成功后启动应用')
    args=parser.parse_args(argv)
    if sys.version_info<(3,10):raise RuntimeError('需要 Python 3.10 或更新版本')
    root=args.install_dir.expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    (root/'releases').mkdir(exist_ok=True)
    handler=RotatingFileHandler(root/'update.log',maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));LOG.addHandler(handler);LOG.setLevel(logging.INFO)
    with (root/'update.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('另一个下载／更新任务正在运行')
        if args.rollback:
            previous=root/'previous'
            if not previous.is_symlink():raise RuntimeError('没有可回退的旧版本')
            release=previous.resolve()
        else:
            with tempfile.TemporaryDirectory(prefix='download-',dir=root) as temporary:
                folder=Path(temporary)
                print('正在直接下载源码归档（不查询 GitHub API）……',flush=True)
                sha,archive=fetch_source(args.ref,folder);release=prepared_release(root,sha)
                if not (release/'READY').is_file() or args.repair:
                    print('正在准备版本 '+sha[:16]+'……',flush=True)
                    release=prepare(root,sha,archive,args.repair)
        launchers(root,Path.home());activate(root,release);LOG.info('Activated release=%s',release.name)
    print('已准备版本：'+release.name+'\n启动：'+str(Path.home()/'.local/bin/conway-desktop')+'\n再次更新：'+str(Path.home()/'.local/bin/conway-desktop-update')+'\n安装日志：'+str(root/'update.log'))
    print('预设和检查点未改动。普通窗口需关闭后重开；壁纸模式须从托盘退出后台再启动，才使用新版。')
    if args.run:subprocess.Popen([str(Path.home()/'.local/bin/conway-desktop')],start_new_session=True)
    return 0

def failure_message(exc):
    if isinstance(exc,urllib.error.HTTPError):
        if exc.code in (403,429):return f'下载服务拒绝请求或限流（HTTP {exc.code}）：{exc.url}。这是网络／下载错误，与 Qt 图形库无关。'
        if exc.code==404:return f'未找到指定分支、标签或提交（HTTP 404）：{exc.url}'
        return f'下载服务返回 HTTP {exc.code}：{exc.url}'
    if isinstance(exc,urllib.error.URLError):return '网络连接失败：'+str(exc.reason)
    return str(exc)

if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        LOG.exception('Update failed')
        print('下载／更新失败：'+failure_message(exc)+'\n用户预设和检查点未被修改。',file=sys.stderr)
        for handler in LOG.handlers:
            if hasattr(handler,'baseFilename'):print('安装日志：'+handler.baseFilename,file=sys.stderr)
        raise SystemExit(1)
PY
