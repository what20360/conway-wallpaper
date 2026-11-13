# 可选用户服务方案

已有程序登录自启可以保持原样，本轮不会自动新增任何启动项。服务安装入口已实现，作为备用保留；以下操作仅在明确想改用 systemd 管理时执行，不必与现有自启并用。

## 注册与登录启动

使用一键更新器安装过的稳定启动器：

```bash
~/.local/bin/conway-desktop --install-service
```

该命令仅注册当前用户的 conway-wallpaper.service，并关闭本程序旧 XDG 登录启动项，不自动启用服务。不会覆盖同名的自定义服务。若一直使用自定义数据目录，应在安装命令后加 `--data-dir /原来的数据目录`。

先从托盘退出旧后台，再执行：

```bash
systemctl --user daemon-reload
systemctl --user enable --now conway-wallpaper.service
systemctl --user restart plasma-plasmashell.service
```

这是登录 Plasma 后自动启动，不是登录前运行的系统服务。不使用 sudo，不需要开启用户 linger。服务跟随图形会话退出，启动次序在 plasmashell 之后，使用稳定启动器，异常退出可重启；正常托盘退出不会被强行拉起。单实例锁的退出码 2 不触发反复重启。

## 管理与更新

```bash
systemctl --user status conway-wallpaper.service
journalctl --user -u conway-wallpaper.service -b -n 80 --no-pager
systemctl --user restart conway-wallpaper.service
systemctl --user stop conway-wallpaper.service
```

已改用服务时，后续更新：

```bash
~/.local/bin/conway-desktop-update
systemctl --user restart conway-wallpaper.service
systemctl --user restart plasma-plasmashell.service
```

保留原自启方式时，继续从托盘退出、更新并重新启动后台即可，无须执行这些服务命令。

## 停用和恢复原自启

```bash
systemctl --user disable --now conway-wallpaper.service
rm "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/conway-wallpaper.service"
systemctl --user daemon-reload
```

重新正常启动壁纸后台后，可再次勾选托盘的登录自启。注册服务时托盘显示“登录自启由用户服务管理”，防止额外添加另一份启动项。

## 实现依据

生成的单位使用 PartOf=graphical-session.target、After=plasma-plasmashell.service、WantedBy=plasma-workspace.target；不设置 After=plasma-workspace.target，以免与 target 的隐式启动次序产生环。ExecStart 中的路径、空格、引号、百分号与美元符号按 systemd 语法处理，不经 shell 执行。

依据：[systemd 图形会话服务](https://www.freedesktop.org/software/systemd/man/latest/systemd.special.html)、[Plasma 6.6.6 工作区目标](https://github.com/KDE/plasma-workspace/blob/v6.6.6/startkde/systemd/plasma-workspace.target)、[plasmashell 单位](https://github.com/KDE/plasma-workspace/blob/v6.6.6/shell/plasma-plasmashell.service.in)。本地 systemd-analyze --user verify 已通过生成单位的语法检查；真实登录生命周期尚需 Plasma 实机确认。
