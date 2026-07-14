# 上班倒计时

一个 Windows 桌面悬浮倒计时工具，会根据当前时间显示距离上班、午休、下午上班或下班的剩余时间。支持周末、法定节假日和调休工作日。

## 环境要求

- Windows 10 / 11
- Python 3（安装时勾选“Add Python to PATH”）

项目只使用 Python 标准库，不需要安装额外依赖。

## 运行

在项目目录打开 PowerShell：

```powershell
.\run.ps1
```

首次运行会自动创建本机配置文件 `config.json`。

## 设置上下班时间

在悬浮窗上右键，选择“设置上下班时间”，填写：

- 上午上班
- 午休开始
- 下午上班
- 下午下班

时间使用 24 小时制，例如 `09:00`。保存后立即生效。

右键菜单还可重新加载配置或退出程序；直接拖动窗口会保存当前位置。

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
