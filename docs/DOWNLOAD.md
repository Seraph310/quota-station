# 额度小站 · 下载版

无需安装 Python。下载地址：https://github.com/Seraph310/quota-station/releases/latest

Windows 10/11（64 位）：解压完整 ZIP，打开 QuotaStation 文件夹，双击 QuotaStation.exe。请保留旁边的 _internal 文件夹，可给 exe 创建桌面快捷方式。

macOS：Apple 芯片选 arm64，Intel 选 x64。打开 DMG，把 Quota Station.app 拖到 Applications 后启动。本版在 macOS 15 上构建并测试。

换电脑后先安装并登录要查询的客户端。Windows 支持 Codex、Qoder、WorkBuddy 本机直连，以及 Magpie；macOS 支持 Codex CLI 和 Magpie。本版未实现 macOS 上 Qoder、WorkBuddy 的原生登录读取。

双击卡片展开，点击“显示来源”勾选账号；“一键同步 Magpie”读取这台电脑已有的 Magpie 来源。左侧上一页、右侧下一页，拖右下折角调整大小。

设置、显示选择和缓存保存在当前用户目录，更新程序会保留它们：
- Windows：%LOCALAPPDATA%\QuotaStation
- macOS：~/Library/Application Support/QuotaStation

程序不会携带作者的账号、登录凭证或真实余额。不同电脑需要各自登录；不复制客户端的登录文件。

当前下载包没有购买商业代码签名证书；macOS 使用临时签名，尚未经过 Apple 公证。首次打开可能遇到系统提示。确认下载自上面的项目 Release 后，可按系统界面为这一个应用允许打开，无需关闭系统安全功能。macOS 官方说明：https://support.apple.com/en-us/102445

若 macOS 提示开发者无法验证，可在尝试打开后进入“系统设置 → 隐私与安全性”查看这一个应用的“仍要打开”。

升级时先从托盘菜单退出小站，再替换完整程序文件夹或 .app。无需移动用户目录里的设置。

第三方库许可证随程序放在 licenses 目录（Windows：_internal/licenses；macOS：应用包内 Contents/Resources/licenses）。对应源码和许可证链接见 THIRD_PARTY_NOTICES.txt。
