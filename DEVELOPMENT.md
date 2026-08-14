# 开发说明

这份文档给维护项目的人看，普通用户不需要阅读。普通用户请直接从 [Releases](https://github.com/sheyingxin1204/work-countdown/releases) 下载。

## 本地运行

需要 Windows、Python 3 和项目依赖：

```powershell
python -m pip install -r requirements.txt
.\run.ps1
```

## 检查代码

```powershell
python -m py_compile work_countdown.py work_core.py holiday_sync.py work_stats.py app_updates.py desktop_hotkeys.py
python -m unittest discover -s tests -v
ruff check work_core.py holiday_sync.py work_stats.py app_updates.py desktop_hotkeys.py work_countdown.py tests
mypy work_core.py holiday_sync.py work_stats.py app_updates.py desktop_hotkeys.py
```

## 构建发布文件

```powershell
python -m pip install -r requirements-build.txt
.\build_exe.ps1
.\smoke_exe.ps1
.\build_installer.ps1
.\create_checksums.ps1
.\verify_release.ps1
```

有代码签名证书时，设置 `BAN_CLOCK_CERT` 和可选的 `BAN_CLOCK_CERT_PASSWORD`，然后运行 `.\sign_exe.ps1`。没有证书时脚本只提示待签名，不会伪造签名结果。

发布前请查看 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)。

## 代码结构

- `work_countdown.py`：窗口、托盘、设置和用户交互。
- `work_core.py`：工作日历、工作时段和倒计时状态。
- `holiday_sync.py`：年度节假日同步和缓存。
- `work_stats.py`：工作时长统计和 CSV 导出。
- `app_updates.py`：Release 检查、下载和 SHA-256 校验。
- `desktop_hotkeys.py`：Windows 全局快捷键。

## 写代码的约定

- 名称简短、直接，优先使用现有项目里的叫法，不为了显得复杂而增加层级。
- 注释只说明原因和容易踩坑的地方，不把代码重新翻译一遍。
- 用户能看到的文字保持自然、简洁，不出现“AI 助手”之类的产品化措辞。

## 配置和数据

用户配置不在仓库中，默认位于 `%APPDATA%/BanClock`。仓库里的 `config.example.json` 只用于说明配置格式，不要把个人 `config.json` 提交到 Git。
