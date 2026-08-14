# 班时钟发布检查清单

## 构建前

- [ ] 确认 APP_VERSION、installer.iss 的版本号和 Git tag 一致。
- [ ] 确认 CHANGELOG.md（或 Release 描述）列出功能、已知限制和回滚方式。
- [ ] 在干净的 Windows 用户目录中确认配置迁移、托盘、开机自启和桌面快捷方式。

## 自动检查

运行以下命令：

    python -m unittest discover -s tests -v
    ruff check work_core.py holiday_sync.py work_stats.py app_updates.py desktop_hotkeys.py work_countdown.py tests
    mypy work_core.py holiday_sync.py work_stats.py app_updates.py desktop_hotkeys.py
    .\build_exe.ps1
    .\smoke_exe.ps1
    .\build_installer.ps1
    .\create_checksums.ps1
    .\test_update_helper.ps1
    .\verify_release.ps1

## 签名

证书准备好后设置 BAN_CLOCK_CERT 和可选的 BAN_CLOCK_CERT_PASSWORD，再运行 .\sign_exe.ps1。

没有证书时脚本只报告“待签名”并返回成功；正式稳定版不能把未签名状态当作完成。

## 发布后

- [ ] GitHub Release 同时上传 班时钟.exe、安装包和 SHA256SUMS.txt。
- [ ] 在全新 Windows 账户安装，验证右下角定位、日历同步、统计、更新助手和卸载。
- [ ] 下载一个旧版本可用的更新包，验证更新助手会备份旧文件；故意提供损坏包，验证回滚后旧版本仍可启动。
- [ ] 至少连续运行 2 个工作日，确认休眠/唤醒、跨午夜、网络离线和多显示器场景无异常，再把 RC 标记为稳定版。
