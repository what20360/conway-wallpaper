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
    parser.add_argument('--wallpaper',action='store_true',help='运行 Plasma 6 原生壁纸后台；右键菜单和图标由 Plasma 管理')
    parser.add_argument('--install-wallpaper',action='store_true',help='安装当前用户的 Plasma 6 壁纸插件后退出')
    parser.add_argument('--resolution',choices=['1920x1080','2560x1440'],default='1920x1080')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--no-system',action='store_true')
    parser.add_argument('--debug',action='store_true',help='记录详细命令诊断，不记录 SSID')
    parser.add_argument('--log-dir',type=Path,help='指定日志目录')
    parser.add_argument('--diagnose',action='store_true',help='收集只读系统诊断后退出')
    parser.add_argument('--wallpaper-info',action='store_true',help='读取正在运行的壁纸前端版本、宿主尺寸与 DPI 后退出')
    parser.add_argument('--render',type=Path,help='导出原生渲染图并退出，不加载用户数据或控制系统')
    args=parser.parse_args(argv)
    if args.wallpaper_info and (args.render or args.wallpaper or args.install_wallpaper or args.diagnose):parser.error('--wallpaper-info 必须单独运行')
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if args.render and (args.wallpaper or args.install_wallpaper):parser.error('--render 不能与壁纸模式同时使用')
    app=(QCoreApplication if args.diagnose or args.install_wallpaper or args.wallpaper_info else QApplication)([sys.argv[0]])
    app.setApplicationName('ConwayDesktop');app.setOrganizationName('ConwayWallpaper')
    path=args.data_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    if args.wallpaper_info:
        import json
        from .diagnostics import read_wallpaper_info
        try:
            report=read_wallpaper_info(path)
            print(json.dumps(report,ensure_ascii=False,indent=2));return 0
        except Exception as exc:print('无法读取壁纸后台显示信息：',exc,file=sys.stderr);return 1
    if args.install_wallpaper:
        from .wallpaper import install_plugin
        try:print('已安装壁纸插件：',install_plugin(path));return 0
        except Exception as exc:print('壁纸安装失败：',exc,file=sys.stderr);return 1
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
        collect(path);return 0
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
    from .wallpaper import create_tray,WallpaperServer,install_plugin,private_token
    server=None
    if args.wallpaper:
        try:
            install_plugin(path)
            window.wallpaper_mode=True;server=WallpaperServer(window,private_token(path))
        except Exception as exc:
            LOGGER.exception('Wallpaper startup failed');print('壁纸后台启动失败：',exc,file=sys.stderr)
            window.wallpaper_mode=False;window.close();store.close();lock.unlock();return 1
        app.setQuitOnLastWindowClosed(False)
        print('壁纸后台已启动。桌面右键 → 配置桌面和壁纸 → 壁纸类型 → 生命场 · 原生。',flush=True)
        app.aboutToQuit.connect(server.stop)
    elif args.fullscreen:window.showFullScreen()
    else:window.show()
    tray=create_tray(window,path)
    # Desktop logout/SIGTERM must save the newest state as well as the periodic checkpoint.
    import signal
    signal.signal(signal.SIGTERM,lambda *_:app.quit());signal.signal(signal.SIGINT,lambda *_:app.quit())
    app.aboutToQuit.connect(window.checkpoint)
    LOGGER.info('Window started fullscreen=%s system_controls=%s',args.fullscreen,not args.no_system)
    result=app.exec()
    window.system.stop();window.timer.stop()
    LOGGER.info('Application exited code=%s',result)
    if store:store.close()
    if lock:lock.unlock()
    return result
