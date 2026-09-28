# Qoder 可选旧版兼容读取

`providers.qoder_provider.fetch()` 优先使用独立 Qoder App 登录，实现在上一级 `qoder_app.py`，不需要本目录的 Node 依赖。只有未检测到新版 App 配置时，才尝试以下路线。

1. `qoder_bridge.mjs` 先使用官方 Agent SDK 的 `getUsageInfo()`。
   输入异步迭代器不产生任何消息，不会启动 Agent turn。SDK 仅复用已有
   `qodercli` 登录；IDE 登录不能假定为 CLI 登录。
2. SDK 无可用余额时，`qoder_ide_bridge.mjs` 读取正在运行的国际版 Qoder IDE
   的本地连接元数据，通过 Windows 命名管道发送一次 `credit/usage`。
   这是 IDE 自己的额度面板采用的只读调用，属于兼容性接口，后续 IDE 更新
   可能需要适配。不会启动 IDE、初始化项目、发起模型请求或读取认证令牌。

SDK 锁定为 `@qoder-ai/qoder-agent-sdk@1.0.50`。
本目录的 `package-lock.json` 保留 JS 依赖版本；重建依赖可运行 `npm ci`。
安装脚本可能取得平台所需运行时，锁文件不代表所有下载的运行时均已锁定。
即使 SDK 依赖未装，IDE 回退仍只需要系统 Node.js。

套餐、附加包及可用组织资源包的余额分项列示；只有服务返回合法数值和
Credits 单位时才纳入余额。未知值不按零处理。`expiresAt` 是套餐到期日，
显示在详情，不作为额度恢复时间（`reset_at`）。读取失败时由上层显示错误
或保留明确标记过期的旧快照。

兼容验证版本：Qoder IDE 1.32.1。不要把 `node_modules/` 或 `.npm-cache/` 提交仓库。

来源：
- https://docs.qoder.com/cli/sdk/cost-usage
- https://docs.qoder.com/cli/sdk/authentication
- https://docs.qoder.com/cli/sdk/overview
- 本机 Qoder IDE 1.32.1 `aicoding-agent/dist/extension.js` 中
  `getSubscriptionAndCreditsInfo()` 调用 `credit/usage` 的实现。
