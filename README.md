# 额度小站 · Quota Station

**留一点余量，从容做事。**

一个便签风格的 Windows 桌面小组件，把 **Codex、Qoder、WorkBuddy** 的剩余额度放在手边。收起是一张小卡片或悬浮球，展开是一张三平台额度便签。

![额度小站：小卡片、悬浮球与展开便签；数值为演示数据](docs/images/overview.png)

> 上图由真实程序渲染，全部使用虚构演示数值，不对应任何真实账号。各平台单位不同，分别展示，不跨平台相加。

**培训实践案例：** [在线阅读图文说明](docs/case-study.md) · [下载作业 PDF](output/pdf/额度小站-AI工作辅助实践案例.pdf)

## 从一个真实的小需求开始

在使用多种 AI 工具辅助生物信息学分析及日常工作时，频繁切换客户端查看额度会打断正在进行的操作。这个项目借助 Codex，把“在桌面上看一眼剩余额度”的想法做成一个实际可用的小工具。

需求和审美取舍由使用者提出，Codex 辅助实现、调试与测试。便签外观、单击轮换、双击展开和可拖动的书页折角，都来自实际使用中的迭代。Qoder 与 WorkBuddy 在这个案例中是被监测的平台。

## 可以做什么

| 操作 | 效果 |
| --- | --- |
| 单击卡片或球 | Codex → Qoder → WorkBuddy 轮换 |
| 双击 | 展开三平台额度便签 |
| 拖动主体 | 调整桌面位置 |
| 拖动右下角书页折角 | 小卡片等比例缩放，范围 80%–200% |
| 便签右上角 / Esc | 收起并保留当前选择 |
| 右键 / F5 | 刷新、置顶、隐藏到托盘或退出 |

- 位置、大小、外形和置顶设置自动保存；每次启动默认显示 Codex。
- 每 5 分钟刷新一次，可随时手动刷新。
- 更新失败时保留上次成功值并显示状态；未知额度不会伪装成 0。
- 悬停查看更新时间和明细，右键额度行可打开详情。
- Codex 显示优先选择的周额度剩余百分比；Qoder 显示可用 Credits 合计；WorkBuddy 显示剩余积分。

## 快速开始

需要 **Windows 64 位、Python 3.11 或更新的兼容版本**。项目已在 Windows / Python 3.14 上验证。请先安装 Python，再下载仓库 ZIP 解压，或使用 Git：

```powershell
git clone https://github.com/Seraph310/quota-station.git
cd quota-station
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -DesktopShortcut
```

安装脚本只在项目的 `.venv` 中安装 Python 依赖；`-DesktopShortcut` 创建桌面快捷方式。它不安装各平台客户端、不更改全局配置，也不自动启动应用。

**先体验界面，无需登录任何账号：**

```powershell
.\.venv\Scripts\python.exe demo.py --expanded
```

演示模式使用临时目录和虚构数值，不读取真实登录与余额缓存，不联网查询。界面会明确显示“演示数据”。

**连接自己的账号：**

准备好下表中的客户端登录后，双击桌面的「额度小站」，或运行：

```powershell
.\.venv\Scripts\pythonw.exe app.py
```

也可双击仓库里的 `额度小站.vbs`。移动项目文件夹后，重新运行 `setup_desktop.ps1` 生成指向新位置的桌面快捷方式。

## 额度来源与连接条件

| 平台 | 来源与条件 |
| --- | --- |
| Codex | 已安装并通过 ChatGPT 账号登录的 Codex CLI，使用 `account/rateLimits/read`；不创建模型任务。仅有桌面 App 不一定包含可调用的 CLI。 |
| 新版 Qoder App | 优先复用当前 Windows 用户的独立 App 登录，已适配 0.4.3。只读解密本机登录，在内存中向客户端使用的 `GET /sash/api/v2/me/usage` 查询；无需启动旧 IDE，也无需 Node.js。登录过期时打开新版 Qoder 更新登录。 |
| 旧 Qoder 环境 | 无新版 App 配置时，支持官方 SDK 的 `getUsageInfo()`，再回退到正在运行且已登录的国际版 Qoder IDE 本地 `credit/usage`。此路径需要 Node.js。 |
| WorkBuddy | 同一 Windows 用户已有 WorkBuddy 登录。优先读取已有加密缓存；必要时只读访问 WorkBuddy 服务进程内存获取登录令牌，再向其计费接口查询。新用户无需安装旧积分球。 |

Qoder 合计包括套餐、附加包、分配给当前用户的组织额度和可用专用包；过期、暂停和不可用包不计入。专用包的使用范围仍以 Qoder 为准。官方界面按包展示，本项目的合计是这些可用分项的汇总。新版 App 账号存在时，查询失败不会静默切到另一个 IDE/CLI 账号。

可选安装旧 Qoder SDK 依赖（需 Node.js 20+ 和 npm）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -WithQoderSdk
```

如 Codex CLI 未在 PATH 中，可仅为本次 PowerShell 会话指定其**原生可执行文件**：

```powershell
$env:QUOTA_CODEX_EXECUTABLE = 'C:\path\to\codex.exe'
.\.venv\Scripts\pythonw.exe app.py
```

## 本地数据与兼容性

- 项目不设账号中转服务器，查询发往各平台自身的服务。登录凭证不写入明文日志。
- Qoder 登录文件只读，不修改或刷新原凭证。WorkBuddy 如需新增缓存，使用 Windows 数据保护 API（DPAPI）加密，保存在项目 `.cache` 中；不修改原缓存或进程，不请求调试提权。
- `state/` 只存本地设置和余额快照；`.cache/`、虚拟环境、真实验证结果和本机截图均排除在 Git 之外。请勿把这些目录一起公开打包。
- 本项目是个人实践作品。客户端兼容接口可能随版本变化；企业专属用量页、非标准服务域名和其他平台系统尚未全面适配。它不承诺跨电脑即装即用，数值以各平台自身页面为准。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe tools\render_demo.py
```

自动化测试使用合成响应、模拟网络和离屏界面，不访问真实账号。`tools/render_demo.py` 生成可公开的演示图。开发用的 `verify_live.py`、`verify_qoder_app.py` 和 `render_check.py` 会读取当前用户的真实状态，输出已通过 `.gitignore` 排除，不用于公开展示。

| 文件 / 目录 | 用途 |
| --- | --- |
| `app.py` / `demo.py` | 实际界面 / 隔离的离线演示 |
| `providers/` | 三个平台的额度适配器 |
| `install.ps1` / `setup_desktop.ps1` | 安装依赖 / 创建快捷方式 |
| `tests/` | 额度解析、账号边界和界面交互测试 |
| `docs/` / `output/pdf/` | 图文案例、演示图和可提交的 PDF |

相关资料：[Codex App Server](https://learn.chatgpt.com/docs/app-server) · [Qoder SDK 额度查询](https://docs.qoder.com/cli/sdk/cost-usage) · [新版 Qoder](https://docs.qoder.com/qoder/overview)
