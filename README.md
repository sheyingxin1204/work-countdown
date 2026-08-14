# 班时钟

一个 Windows 桌面悬浮倒计时工具，会根据当前时间显示距离上班、午休、下午上班或下班的剩余时间。支持周末、法定节假日和调休工作日，并驻留在系统托盘中。

## 环境要求

- Windows 10 / 11
- Python 3（安装时勾选“Add Python to PATH”）

首次运行前安装托盘图标所需依赖：

```powershell
python -m pip install -r requirements.txt
```

## 运行

在项目目录打开 PowerShell：

```powershell
.\run.ps1
```

首次运行会自动在用户配置目录创建配置文件。已存在项目目录下旧版 `config.json` 时，程序会自动迁移一份到新目录。

## 构建独立 EXE

```powershell
python -m pip install -r requirements-build.txt
.\build_exe.ps1
```

生成文件：`dist\班时钟.exe`。它可以在没有 Python 环境的 Windows 电脑上直接运行。

如果安装了 Inno Setup 6，可继续生成一键安装器：

```powershell
.\build_installer.ps1
```

安装器会提供开始菜单、桌面快捷方式和开机自启选项，默认按当前用户安装，不需要管理员权限。

生成发布校验和：

```powershell
.\create_checksums.ps1
```

运行自动化测试：

```powershell
python -m unittest discover -s tests -v
```

开发依赖和 CI 检查：

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check work_core.py tests
python -m mypy work_core.py
```

GitHub Actions 会在 Windows 环境中自动执行测试、类型检查、EXE 构建和启动烟测。

## 设置上下班时间

在悬浮窗上右键，选择“打开设置中心”，可以集中配置：

- 上午上班
- 午休开始
- 下午上班
- 下午下班
- 周末、节假日和调休工作日
- 年度日历 JSON 导入/导出和日期冲突校验
- 一键同步国务院公告的年度节假日/调休日历，网络不可用时自动使用本地缓存
- 自定义多工作时段和可选加班结束时间
- 透明度、始终置顶和右下角边距
- 午休、下班 Windows 通知，以及可选提示音
- 提前提醒、免打扰时段和测试提醒按钮
- 工作时长/加班时长统计、近 7 天和本月概览及 CSV 导出
- 紧凑/详细显示模式、秒数显示和工作日进度条
- 深色、浅色和海洋蓝主题

时间使用 24 小时制，例如 `09:00`。保存后立即生效。

年度日历可在设置中心导入或导出 JSON 文件，格式可参考 `calendar.example.json`。同一日期不能同时出现在节假日和调休工作日列表中。

点击“同步官方日历”会从开源的国务院公告数据镜像获取所选年份，并与当前手动日期合并；如果同一日期冲突，调休工作日优先。同步结果会缓存到 `%APPDATA%\\BanClock\\holiday-cache`，离线时可继续使用最近一次缓存。同步后仍需点击“保存设置”。

在设置中心勾选“使用自定义工作时段”后，可按行填写 `开始 - 结束`，最多 4 段；加班结束时间留空时不显示加班倒计时。

启用提醒后，状态从上午上班切换到午休、或从下午上班切换到已下班时各提醒一次；程序启动时不会重复提醒当前状态。提示音需要在设置中心单独开启。

“提前提醒分钟”可设置 0 到 120 分钟，0 表示关闭；免打扰时段会暂停所有自动提醒，但“发送测试提醒”仍然可用。

右键菜单还可重新加载配置、隐藏到系统托盘或退出程序；直接拖动窗口会保存当前位置。

快捷键：`Ctrl+Shift+B` 显示/隐藏悬浮窗，`Ctrl+Shift+S` 打开设置中心；设置中心还可恢复默认窗口位置。

右键菜单中的“工作统计”会显示今日、近 7 天和本月的实际工作时长，并可导出 CSV。统计数据保存在 `%APPDATA%\\BanClock\\stats.json`，只记录程序运行期间的工作时段。

班时钟首次启动会定位到当前显示器的右下角工作区域，并自动避开任务栏；如果电脑连接了多个显示器，会使用鼠标所在的显示器。重复启动时只保留一个实例。

## 系统托盘

启动后，班时钟会在 Windows 右下角通知区域显示 Logo。托盘图标支持：

- 左键或双击：显示/隐藏悬浮窗
- 右键：设置上下班时间、重新加载配置、退出程序
- 关闭悬浮窗：隐藏到系统托盘，不会结束程序

## 开机自启

安装开机自启：

```powershell
.\install_startup.ps1
```

取消开机自启：

```powershell
.\uninstall_startup.ps1
```

创建桌面快捷方式：

```powershell
.\install_desktop.ps1
```

删除桌面快捷方式：

```powershell
.\uninstall_desktop.ps1
```

桌面端菜单中的“检查更新”会连接 GitHub Release 页面检查新版本；如果 Release 提供 EXE，程序可以下载到用户目录并校验 SHA-256。已安装版会调用更新助手，在退出旧进程后自动替换并重启；开发模式仍会打开下载目录供手动运行。“关于班时钟”可查看当前版本号和配置目录。

## 配置说明

配置文件位于 `%APPDATA%\BanClock\config.json`，是本机个人配置，不会提交到 Git。可参考 `config.example.json` 手动配置周末、节假日、调休、透明度、窗口置顶、提醒和显示模式等选项。

运行日志位于 `%APPDATA%\BanClock\ban_clock.log`。如果配置文件损坏，程序会先保留 `config.broken.*.json` 备份，再恢复默认配置。
