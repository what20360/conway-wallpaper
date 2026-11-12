# 生命场 · 原生应用实验版

先阅读 [方案与能力边界](docs/DESIGN.md)，再阅读 [操作手册](docs/MANUAL.md)。本目录是独立原生 Qt 应用，不加载 HTML 或 WebEngine；网页版本仍保留。

第一版面向 1920×1080 和 2560×1440。实现普通窗口和全屏，**暂不等于 Wayland 桌面背景层**。

## 推荐：一键下载／更新

先安装一次系统运行依赖：

```bash
sudo apt install python3-venv libegl1 libgl1 libopengl0 libxcb-cursor0 libxkbcommon-x11-0
```

下载脚本并运行（无需在原有源码目录中执行）：

```bash
curl -fL https://raw.githubusercontent.com/what20360/conway-wallpaper/main/native/update.sh -o /tmp/conway-update.sh
bash /tmp/conway-update.sh
```

脚本会直接下载完整源码快照（不查询 GitHub API），从 ZIP 注释读取提交号；没有注释时用内容摘要标识版本。随后创建／复用虚拟环境、安装 Python 依赖并验证原生 Qt 绘制，成功后才启用新版，同时添加应用菜单入口。已有预设与检查点不会迁移或删除，仍使用原来的 Qt 用户数据目录。原先带自定义 `--data-dir` 启动的用户，之后也应继续传同一个目录。

```bash
# 启动；支持继续追加 --fullscreen、--data-dir 等原生应用参数
~/.local/bin/conway-desktop
# 后续一条命令更新
~/.local/bin/conway-desktop-update
# 离线回退到上一个已准备版本
~/.local/bin/conway-desktop-update --rollback
# 依赖损坏时建立新运行环境，保留旧版
~/.local/bin/conway-desktop-update --repair
```

更新不会强制结束正在运行的窗口；请关闭旧窗口后重新启动。安装日志在 `~/.local/share/conway-desktop-install/update.log`，运行日志请点击应用左上角状态点。脚本支持 `--install-dir`、`--ref` 和 `--run`。下载会沿用标准 `https_proxy` / `http_proxy` 环境变量；没有内置第三方镜像。

旧版源码目录和 `.venv-native` 不会被脚本删除。托管版本放在 `~/.local/share/conway-desktop-install/releases/`，依赖环境单独缓存，代码版本保留便于回退；长期不用的旧版可在关闭应用后自行清理。

## 手动从源码启动

在仓库根目录执行：

```bash
python3 -m venv .venv-native
.venv-native/bin/python -m pip install -r native/requirements.txt
.venv-native/bin/python native/run.py
```

如果只下载／复制了 native/ 内部文件，入口是当前目录的 `run.py`，依赖文件也是当前目录的 `requirements.txt`。

系统控制需要 `wpctl`、`nmcli`、`bluetoothctl`、`rfkill` 和 `plasma-apply-colorscheme`；缺少时对应控制不可用。单纯运行应用不需要 sudo。

```bash
.venv-native/bin/python native/run.py --fullscreen
.venv-native/bin/python native/run.py --data-dir /tmp/conway-native-test
# 详细日志与只读诊断
.venv-native/bin/python native/run.py --debug
.venv-native/bin/python native/run.py --diagnose
```

右上 X 关闭；最下排四角图标切换全屏。没有独立键盘快捷键；Shift＋左键擦除保留。

## 校验与原生渲染

```bash
.venv-native/bin/python -m unittest discover -s native/tests -v
QT_QPA_PLATFORM=offscreen .venv-native/bin/python native/run.py --render /tmp/conway-1080.png --resolution 1920x1080 --no-system
QT_QPA_PLATFORM=offscreen .venv-native/bin/python native/run.py --render /tmp/conway-1440.png --resolution 2560x1440 --no-system
```

渲染模式不加载用户数据库，不发出系统控制命令。可在无桌面环境中验证绘制；不能代替真实 KDE 桌面、缩放、权限与休眠测试。

## 原生渲染预览

下图由本程序通过 Qt offscreen 绘制，系统控制因无 KDE 会话而显示不可用。

![1080p 原生界面](docs/preview-1080.png)


### 旧脚本提示 HTTP 403: rate limit exceeded

旧版默认会调用 GitHub API 查询版本，可能被公共出口 IP 的限额阻止。新版不再依赖该 API，直接下载源码快照。请重新下载 update.sh 再执行，不要继续运行缓存的旧 `/tmp/conway-update.sh`。无需修改 Qt 图形库，也无需提供 GitHub Token。若下载服务本身仍返回 403／429，新版会明确打印网络地址与错误类型。
