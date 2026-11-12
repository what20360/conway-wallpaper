# Plasma 活动切换器预览

## 核实的生成路径

针对用户的 Plasma 6.6.6，活动切换器没有直接抓取自定义 WallpaperItem。plasma-desktop 的 BackgroundCache 从桌面容器读取 wallpaperplugin，再读取该插件的 `Wallpaper/<插件>/General/Image`；非空时将其作为背景 URI。ActivityItem 将 URI 交给 `image://wallpaperthumbnail/`；SwitcherBackend 使用 KIO 文件缩略图生成器加载。因此动态插件没有 Image 配置时，实时壁纸正常绘制也可能没有活动卡片预览。

依据均为 KDE 原始源码：

- [6.6.6 SortedActivitiesModel / BackgroundCache](https://github.com/KDE/plasma-desktop/blob/v6.6.6/imports/activitymanager/sortedactivitiesmodel.cpp)：读取 Image、监听 applet 配置变化并刷新模型。
- [6.6.6 ActivityItem.qml](https://github.com/KDE/plasma-desktop/blob/v6.6.6/desktoppackage/contents/activitymanager/ActivityItem.qml)：wallpaperthumbnail 图像源。
- [6.6.6 SwitcherBackend](https://github.com/KDE/plasma-desktop/blob/v6.6.6/imports/activitymanager/switcherbackend.cpp)：将 URI 交给 KIO::filePreview。
- [KConfigPropertyMap](https://github.com/KDE/kconfig/blob/master/src/qml/kconfigpropertymap.cpp)：属性更新与 writeConfig 的落盘职责不同。
- [Plasma 6.6.6 标准图片壁纸](https://github.com/KDE/plasma-workspace/blob/v6.6.6/wallpapers/image/imagepackage/contents/ui/main.qml)：显式 writeConfig 的使用方式。
- [KIO 6.20 FilePreviewJob](https://github.com/KDE/kio/blob/v6.20.0/src/gui/filepreviewjob.cpp)：本地 URL 转为 toLocalFile、canonicalFilePath 后生成缓存键，URL 片段不成为新的本地缩略图缓存文件名。

## 本项目实现

后台从已经渲染的壁纸帧生成 640×360 PNG，保持比例，不抓取屏幕或其他窗口。只原子覆盖数据目录内的 `activity-preview.png`，权限 0600，每 30 秒至多写一次。插件新增 General/Image 配置项，收到新快照 URL 时更新该项并 writeConfig，让 KDE 的配置监听触发刷新。其他壁纸插件和活动设置不被修改。

URL 增加每次不同的片段，使 Qt 图像源发生变化；实际本地路径固定，KIO 本地缓存也按固定规范路径索引。后台重启增加会话标识，避免重启后命中上次 Qt 图像缓存。不积累历史快照或逐帧图片。若生成失败，保留最近有效快照、记录日志并在下一周期重试。

活动切换器取得的是最近静态画面，不是视频。后台没有收到帧请求时不更新；未激活活动保留最近配置。多个活动共用此后台的同一世界，因此不会得到独立的每活动图案。16:9 缩略图也避免旧版活动卡片直接拉伸不同宽高比的图片。

## 验证与安装

自动测试覆盖原子单文件、权限、限频、比例、像素更新及 QML 配置写入调用。当前测试环境没有 Plasma 会话，真实活动切换器的最终显示尚未验证；代码路径与用户版本源码相符。

更新后先重启后台，再重载 plasmashell，以加载新增的配置结构。运行 `conway-desktop --wallpaper-info` 查看 activityPreview 的文件地址与错误。如已有图片而卡片仍空，应进一步检查宿主是否加载 0.3.3、Image 是否已经写入，以及该环境的 KIO PNG 缩略图支持，不能直接认定是截图权限问题。
