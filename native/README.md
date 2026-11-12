# 生命场 · 原生应用实验版

先阅读 [方案与能力边界](docs/DESIGN.md)，再阅读 [操作手册](docs/MANUAL.md)。本目录是独立原生 Qt 应用，不加载 HTML 或 WebEngine；网页版本仍保留。

第一版面向 1920×1080 和 2560×1440。实现普通窗口和全屏，**暂不等于 Wayland 桌面背景层**。

## 安装与启动

在 Kubuntu 的项目根目录执行：

```bash
sudo apt install python3-venv libegl1 libgl1 libopengl0 libxcb-cursor0 libxkbcommon-x11-0
python3 -m venv .venv-native
.venv-native/bin/python -m pip install -r native/requirements.txt
.venv-native/bin/python native/run.py
```

已有系统 Qt/PySide 的用户也可使用发行版提供的 PySide6 和 NumPy，避免与系统 QML 模块混用。本版没有 Kirigami/QML 插件依赖。

系统控制需要相应服务和工具：`wpctl`（WirePlumber）、`nmcli`（NetworkManager）、`bluetoothctl`（BlueZ）、`plasma-apply-colorscheme`（Plasma）。缺少时仍能运行生命场，对应控制显示不可用。

```bash
# 以全屏启动；这是普通全屏应用，不会自动设置桌面壁纸
.venv-native/bin/python native/run.py --fullscreen
# 独立数据目录，便于测试，不影响常用数据
.venv-native/bin/python native/run.py --data-dir /tmp/conway-native-test
```

右上像素 X 关闭；最下排四角图标切换全屏。没有独立键盘快捷键；Shift＋左键作为擦除替代操作。

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
