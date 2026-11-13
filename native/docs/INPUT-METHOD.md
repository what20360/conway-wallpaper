# 输入法与标点状态

## 标点为何可能显示问号

Rime 的 ascii_punct 是标点模式开关：false 是中文标点，true 是 ASCII 标点。Fcitx5-Rime 从方案 switches 的 states 读取两段显示文字，并将当前值与目标值写成“当前 → 目标”的菜单标签。因此标签既可能是“。， → ．，”，也可能是“¥ → $”。只接受前一种会漏掉使用货币符号的常见配置；这属于本应用的识别兼容问题，不表示输入方案没有标点开关。

0.3.5 接受明确的货币和标点标签对，按照箭头左侧判断当前状态；英文标点时显示 $，中文标点时显示 ￥。全角／半角、简繁、emoji 等选项不属于本功能。遇到未知或多个候选时禁用而不猜测。

## 菜单读取与切换

Fcitx5 的菜单操作依赖最近的输入上下文。读取前 AboutToShow(0) 会更新该上下文引用，随后 GetLayout 才能得到相应动作。这个 D-Bus 方法不会弹出菜单或发送键盘事件。本应用从 StatusNotifierItem 的 Menu 属性获取实际对象路径，避免硬编码路径；失效后重新发现。

切换前再次读取菜单，使用最新动作 ID 发出 Event(clicked)，关闭该菜单交互后刷新并确认状态。发出命令不等于成功；未进入目标值时保留真实读数并提示。没有有效输入上下文、方案未公开该选项或托盘组件不可用时，无法保证从桌面直接切换。

原始依据：

- [Fcitx5-Rime ToggleAction](https://github.com/fcitx/fcitx5-rime/blob/master/src/rimeaction.cpp)：states 的当前／目标标签与选项切换。
- [Fcitx5-Rime RimeEngine](https://github.com/fcitx/fcitx5-rime/blob/master/src/rimeengine.cpp)：按方案 switches 创建动作。
- [Fcitx5 DBusMenu](https://github.com/fcitx/fcitx5/blob/master/src/modules/notificationitem/dbusmenu.cpp)：AboutToShow、输入上下文、菜单标签和事件路由。
- [Fcitx5 StatusNotifierItem](https://github.com/fcitx/fcitx5/blob/master/src/modules/notificationitem/notificationitem.cpp)：Id 与 Menu 属性。

## 诊断与显示

壁纸运行时，conway-desktop --wallpaper-info 的 inputMethod 字段返回中文模式、中文标点模式及 punctuationDiagnostic。stage 区分服务、托盘、路径、初始化、读取、候选识别等失败；菜单条目及候选数量帮助区分空菜单和不识别的标签。它不会返回原始菜单、方案名称或输入文本；日志只在诊断变化时记录。

信息页的放大状态与顶行常驻状态均使用无底色像素字形。中／英与￥／$ 表达模式差异，未知状态为问号；两个位置调用同一控制器。
