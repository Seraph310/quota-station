新增“检查更新”和“一键升级”：以后可直接在小站里下载新版本，校验后自动重启，保留现有设置。

| 下载包 | 使用方法 |
| --- | --- |
| Windows x64 ZIP | 完整解压后打开 QuotaStation/QuotaStation.exe，无需 Python |
| macOS arm64 DMG | Apple 芯片 Mac，拖入 Applications |
| macOS x64 DMG | Intel Mac，拖入 Applications |

- 卡片或托盘右键 → 检查更新 → 一键升级，自动选择 Windows、Apple 芯片 Mac 或 Intel Mac 安装包。
- 每天静默检查一次新版本，不自动安装、不弹窗打断工作或游戏。
- 校验安装包 SHA-256；下载失败保留当前程序，新版启动失败自动回退。
- 保留显示来源、窗口大小、吸附位置和余额缓存。
- 源码运行可一键安装桌面版，保留源码目录，并在 Windows 更新本项目的桌面快捷方式。
- 保留侧边额度条、Magpie 同步、双向卷角翻页等功能。
- 下载版将设置保存在用户目录，更新或移动程序不影响设置。
- Windows 支持 Codex、Qoder、WorkBuddy 和 Magpie；macOS 支持 Codex CLI 和 Magpie。macOS 的 Qoder、WorkBuddy 原生登录读取尚未适配。

Windows 包面向 Windows 10/11 x64；两种 Mac 包在 macOS 15 上构建和验证。所有平台均执行离线测试，并实际运行打包后的升级助手，在隔离目录验证替换程序、保留设置和启动新版。卡片、翻页、侧边吸附、更新窗口和来源选择页也经过打包启动检查；演示与测试使用虚构账号。尚未对实体 Mac 上各平台真实账号逐一验证。

旧版首次需安装一次 v0.4.0，后续即可在小站内升级。Mac 请先把应用移出 DMG；安装目录需要当前用户有写入权限。

换电脑后，先在新电脑登录对应客户端或设置 Magpie。包内不包含任何真实账号或登录凭证。

当前 Windows 包未做商业代码签名，Mac 包使用临时签名且未经 Apple 公证。首次打开可能需要系统确认；Mac 可按 [Apple 官方说明](https://support.apple.com/en-us/102445) 为这一个应用允许打开，无需关闭系统安全功能。

SHA256SUMS.txt 提供各安装包的校验值。详细使用说明见 [下载版说明](https://github.com/Seraph310/quota-station/blob/main/docs/DOWNLOAD.md)。
