# Quota sources and connection details

[Project home](../README.md) · [中文指南](GUIDE.zh-CN.md#额度来源与连接条件)

Quota Station reads remaining quotas. It does not send model prompts, combine incompatible units, or treat unknown values as zero. A failed refresh keeps the last successful reading with an error state.

## Codex

Install Codex CLI and sign in with a ChatGPT account. Quota Station calls the CLI’s `account/rateLimits/read` endpoint; it does not create a model task. Installing only the Codex desktop app may not provide a callable CLI.

The card prefers the weekly remaining percentage when available. Other windows and reset times remain in the details. If the native CLI executable is not on PATH, set `QUOTA_CODEX_EXECUTABLE` to its full path before launching the app.

## Qoder · Windows

The current adapter prefers the standalone Qoder App login, verified with App 0.4.3. It reads the local sign-in file without changing or refreshing its credentials and queries the client’s `GET /sash/api/v2/me/usage` endpoint. This path does not require Node.js or the old IDE. If the App account exists but its query fails, Quota Station does not silently switch to another account in an IDE or CLI.

If no App configuration exists, the legacy path uses the official SDK’s `getUsageInfo()`, then the local `credit/usage` service of a running, signed-in international Qoder IDE. That path needs Node.js 20+ and the optional dependencies installed by:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -WithQoderSdk
```

The available total includes the usable plan, add-ons, organization allocation assigned to the user, and dedicated packages. Expired, suspended, and unavailable packages are excluded. Dedicated-package restrictions still apply in Qoder. Enterprise-only usage pages and nonstandard service domains are not fully supported.

## WorkBuddy · Windows

Keep WorkBuddy desktop running and signed in. While this source is selected, Windows notifies Quota Station when the active account file changes. Switching accounts clears the previous balance and starts a fresh lookup. The card shows **—** until the new balance arrives. The regular balance refresh runs every five minutes. Deselecting WorkBuddy stops the file watch.

Quota Station uses Windows accessibility to open the account menu, refresh **Credits Balance**, and close a menu it opened. An already open account menu stays open. If WorkBuddy is closed or its menu is unavailable, the card can show the last confirmed balance for the same account with its original timestamp.

## Magpie · Windows and macOS

Connect and manage accounts in Magpie first. **Sync Magpie** looks for the running app, PATH entries and common installation directories, plus Windows installation records where available. It reads `magpie status --json` to discover the local gateway port and queries `/v1/magpie/quotas`. If the gateway is unavailable, it tries the detected CLI’s `quota --json` command.

For a custom installation, set `QUOTA_MAGPIE_EXECUTABLE` or `QUOTA_MAGPIE_PORT`. The source window’s **Sync details** shows the detected path, version, connection and last-sync time.

Syncing imports quotas and source metadata. It does not change Magpie routes, account enablement, automatic resets, notifications or Credits spending settings. Existing choices are preserved and newly discovered accounts start unchecked.

Accounts from local clients and Magpie are independent sources even if their provider names match. The app does not add their balances together. When a window has both an amount and percentage, it prefers the available amount. Currencies retain their original units; negative monetary balances are displayed as returned. Descriptive `Unknown` values are not interpreted as 100% remaining.

The interface language can be changed independently of account data. Custom account names and unfamiliar upstream plan or package labels are displayed as supplied.

## Compatibility and privacy

Upstream client interfaces can change. All native adapters use local sign-in state; credentials are sent only to the corresponding provider for the quota query. Magpie reads use its local gateway or CLI. This project has no account relay or analytics server. GitHub is contacted for release checks and downloads.

Settings and caches contain account display names and quota snapshots. They are excluded from Git and release packages. Only synthetic responses are used for public screenshots, automated tests and CI. Never attach `state/`, `.cache/`, tokens or raw authenticated responses to an issue.
