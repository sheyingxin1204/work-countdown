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

首次运行会自动创建本机配置文件 `config.json`。

## 构建独立 EXE

```powershell
python -m pip install -r requirements-build.txt
.\build_exe.ps1
```

生成文件：`dist\班时钟.exe`。它可以在没有 Python 环境的 Windows 电脑上直接运行。

## 设置上下班时间

在悬浮窗上右键，选择“打开设置中心”，可以集中配置：

- 上午上班
- 午休开始
- 下午上班
- 下午下班
- 周末、节假日和调休工作日
- 透明度、始终置顶和右下角边距

时间使用 24 小时制，例如 `09:00`。保存后立即生效。

右键菜单还可重新加载配置、隐藏到系统托盘或退出程序；直接拖动窗口会保存当前位置。

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

## 配置说明

`config.json` 是本机个人配置，不会提交到 Git。可参考 `config.example.json` 手动配置周末、节假日、调休、透明度和窗口置顶等选项。
