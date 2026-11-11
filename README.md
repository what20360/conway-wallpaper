# 生命场 256 · Conway Wallpaper

基于康威生命游戏的交互式像素动态壁纸。按 16:9 铺满游戏区与右侧控制区，所有可见控件、日期和时间均由像素块组成。

## 使用

[在线预览](https://what20360.github.io/conway-wallpaper/) · [自动构建状态](https://github.com/what20360/conway-wallpaper/actions/workflows/pages.yml)

下载并解压仓库后直接打开：

- [`dist/index.html`](dist/index.html)：编辑版，启动时暂停。
- [`dist/wallpaper.html`](dist/wallpaper.html)：壁纸版，启动时运行。
- [`project.json`](project.json)：供支持网页项目格式的壁纸宿主加载，主文件是 `dist/wallpaper.html`。

无需安装依赖或构建。设置为实际桌面背景还需要支持本地 HTML、鼠标交互、文件导入导出和持久化存储的壁纸宿主；浏览器全屏本身不会修改系统桌面设置。

**先阅读完整的 [使用手册](MANUAL.md)。** 界面没有常驻文字说明；另提供可直接在浏览器打开的 [HTML 手册](dist/manual.html)。

## 功能

- B3/S23 生命规则，256×180 网格，四边环绕。
- 游戏区占宽度 80%，信息区占 20%；16:9 下完整铺满，非 16:9 下游戏区中心裁切且控件完整显示。
- 256 个可写预设槽位，256 个可复现随机种子，八位填充选择编号。
- 左键绘制，右键擦除，1×1／3×3／5×5 笔刷。
- 精细像素日期、时间、演化代数、底部面板避让留白、八挡速度（含每 8／4／2 秒一代的慢速）、运行／暂停、单步、六套循环配色、单图标昼夜切换、残影。
- 只在预设被覆盖时保留旧预设；不记录初始帧、绘制过程、普通修改或演化历史。
- 自适应位图、稀疏差分、游程与 Gzip 编码，支持单个 `.life` 文件和整个 `.lifebank` 预设库。
- 浏览器本地保存预设库，无外部资源或数据上传。重要预设可导出文件备份。

切换模式或编号只更新预览；点击预览才载入。修改后需点击软盘保存到选中的 P 槽。完整交互及文件格式行为见手册。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `dist/index.html` | 单文件应用源码，无外部运行依赖 |
| `dist/wallpaper.html` | 由编辑版生成的自动运行入口 |
| `dist/manual.html` | HTML 操作手册 |
| `MANUAL.md` | Markdown 操作手册 |
| `checks/` | 规则、界面约束与紧凑存档校验 |
| `scripts/build.mjs` | 更新自动运行入口、HTML 手册与项目描述 |
| `.github/workflows/pages.yml` | 自动构建、校验并部署 GitHub Pages |

## 修改与验证

使用 Node.js 20 或更新版本，无需 `npm install`：

```sh
npm test
npm run build
```

修改 `dist/index.html` 或 `MANUAL.md` 后运行构建命令更新壁纸入口和 HTML 手册。推送至 main 后自动部署在线预览；Pull Request 只构建和校验，不发布。校验覆盖生命规则、16:9 布局、256 个种子、紧凑文件往返、损坏文件拒绝、预设覆盖备份和保存失败回滚。

本项目尚未在真实 KDE 桌面壁纸宿主中实机验证；宿主的鼠标转发、文件选择、下载与浏览器存储策略会影响功能。
