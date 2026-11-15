新增侧边吸附和额度窄条：把小站拖过屏幕左、右边缘后松手，即可收成窄条，在屏幕边缘查看额度。

| 下载包 | 使用方法 |
| --- | --- |
| Windows x64 ZIP | 完整解压后打开 QuotaStation/QuotaStation.exe，无需 Python |
| macOS arm64 DMG | Apple 芯片 Mac，拖入 Applications |
| macOS x64 DMG | Intel Mac，拖入 Applications |

- 侧边条显示当前来源的剩余百分比和竖向进度；只有余额的来源显示简短金额或积分，暂无数据时显示“—”。
- 悬停 0.35 秒展开卡片，移开 0.6 秒自动收回；悬停查看不主动激活窗口。
- 窄条可以沿屏幕边缘上下拖动，向屏幕内拖动恢复卡片；右键菜单可取消吸附。
- 自动保存吸附位置，跨显示器接缝拖动不触发收起。
- 保留显示来源选择、Magpie 一键同步、双向卷角翻页和卡片缩放。
- 下载版将设置保存在用户目录，更新或移动程序不影响设置。
- Windows 支持 Codex、Qoder、WorkBuddy 和 Magpie；macOS 支持 Codex CLI 和 Magpie。macOS 的 Qoder、WorkBuddy 原生登录读取尚未适配。

Windows 包面向 Windows 10/11 x64；两种 Mac 包在 macOS 15 上构建和验证。所有平台均执行离线测试，并实际启动打包后的程序验证卡片、翻页、侧边吸附和来源选择页；演示与测试使用虚构账号。Windows 另外验证了侧边条收起、展开时前台焦点保持不变。尚未对实体 Mac 上各平台真实账号逐一验证。

换电脑后，先在新电脑登录对应客户端或设置 Magpie。包内不包含任何真实账号或登录凭证。

当前 Windows 包未做商业代码签名，Mac 包使用临时签名且未经 Apple 公证。首次打开可能需要系统确认；Mac 可按 [Apple 官方说明](https://support.apple.com/en-us/102445) 为这一个应用允许打开，无需关闭系统安全功能。

SHA256SUMS.txt 提供各安装包的校验值。详细使用说明见 [下载版说明](https://github.com/Seraph310/quota-station/blob/main/docs/DOWNLOAD.md)。
