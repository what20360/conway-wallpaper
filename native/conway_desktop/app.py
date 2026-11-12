import argparse
from pathlib import Path
import sys
from PySide6.QtCore import QLockFile,QStandardPaths,Qt
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
    parser.add_argument('--render',type=Path,help='导出原生渲染图并退出，不加载用户数据或控制系统')
    args=parser.parse_args(argv)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication([sys.argv[0]])
    app.setApplicationName('ConwayDesktop');app.setOrganizationName('ConwayWallpaper')
    model=Model();store=None;lock=None
    if not args.render:
        path=args.data_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        path.mkdir(parents=True,exist_ok=True);lock=QLockFile(str(path/'app.lock'))
        if not lock.tryLock(0):print('已有实例使用这个数据目录。',file=sys.stderr);return 2
        store=Store(path/'state.sqlite3')
        try:store.restore(model)
        except Exception as exc:
            print('检查点损坏，已保留数据库并改用默认画面：',exc,file=sys.stderr)
    system=System(enabled=not args.no_system and not args.render)
    window=View(model,store,system)
    if args.render:
        w,h=map(int,args.resolution.split('x'));args.render.parent.mkdir(parents=True,exist_ok=True)
        ok=window.render_image(w,h).save(str(args.render));window.timer.stop()
        print('已输出原生渲染图：',args.render);return 0 if ok else 1
    if args.fullscreen:window.showFullScreen()
    else:window.show()
    result=app.exec()
    if store:store.close()
    if lock:lock.unlock()
    return result
