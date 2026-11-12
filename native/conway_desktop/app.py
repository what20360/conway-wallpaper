import argparse
from pathlib import Path
import sys
import platform
from .logging_setup import configure,LOGGER
from PySide6.QtCore import QLockFile,QStandardPaths,Qt,QCoreApplication
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from .model import Model
from .storage import Store
from .system import System
from .view import View

def main(argv=None):
    parser=argparse.ArgumentParser(description='生命场原生实验版')
    parser.add_argument('--fullscreen',action='store_true')
    parser.add_argument('--resolution',choices=['1920x1080','2560x1440'],default='1920x1080')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--no-system',action='store_true')
    parser.add_argument('--debug',action='store_true',help='记录详细命令诊断，不记录 SSID')
    parser.add_argument('--log-dir',type=Path,help='指定日志目录')
    parser.add_argument('--diagnose',action='store_true',help='收集只读系统诊断后退出')
    parser.add_argument('--render',type=Path,help='导出原生渲染图并退出，不加载用户数据或控制系统')
    args=parser.parse_args(argv)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=(QCoreApplication if args.diagnose else QApplication)([sys.argv[0]])
    app.setApplicationName('ConwayDesktop');app.setOrganizationName('ConwayWallpaper')
    path=args.data_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    lock=None
    if not args.render and not args.diagnose:
        path.mkdir(parents=True,exist_ok=True);lock=QLockFile(str(path/'app.lock'))
        if not lock.tryLock(0):print('已有实例使用这个数据目录。',file=sys.stderr);return 2
    if not args.render or args.log_dir:
        directory=configure(args.log_dir or path/'logs',args.debug,'diagnostics.log' if args.diagnose else 'conway.log')
        print('日志目录：',directory,flush=True)
        LOGGER.info('Version=%s system=%s session=%s',Path(__file__).parents[1].joinpath('VERSION').read_text().strip(),platform.release(),__import__('os').environ.get('XDG_SESSION_TYPE','unknown'))
        from PySide6.QtCore import qInstallMessageHandler
        def qt_message(kind,context,message):LOGGER.warning('Qt: %s',message)
        qInstallMessageHandler(qt_message)
    if args.diagnose:
        from .diagnostics import collect
        collect();return 0
    model=Model();store=None
    if not args.render:
        store=Store(path/'state.sqlite3')
        try:
            restored=store.restore(model);LOGGER.info('Checkpoint restored=%s generation=%s',restored,model.generation)
        except Exception as exc:
            LOGGER.exception('Checkpoint restore failed')
            print('检查点损坏，已保留数据库并改用默认画面：',exc,file=sys.stderr)
    system=System(enabled=not args.no_system and not args.render)
    window=View(model,store,system)
    if args.render:
        w,h=map(int,args.resolution.split('x'));args.render.parent.mkdir(parents=True,exist_ok=True)
        ok=window.render_image(w,h).save(str(args.render));window.timer.stop()
        print('已输出原生渲染图：',args.render);return 0 if ok else 1
    if args.fullscreen:window.showFullScreen()
    else:window.show()
    LOGGER.info('Window started fullscreen=%s system_controls=%s',args.fullscreen,not args.no_system)
    result=app.exec()
    LOGGER.info('Application exited code=%s',result)
    if store:store.close()
    if lock:lock.unlock()
    return result
