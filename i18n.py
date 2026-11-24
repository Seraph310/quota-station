"""Presentation-only translations, including snapshots saved by older versions.

Provider identifiers, account names, amounts and cached data stay unchanged.
Chinese source messages are stable keys; English is the fallback for other OS
languages. Known formatted messages are matched as whole strings, never by
replacing words inside account names or arbitrary upstream text.
"""
import re
from string import Formatter

from PySide6.QtCore import QLocale

CHOICES = ('auto', 'zh-CN', 'en')
_language = 'zh-CN'

EN = {
    '额度小站': 'Quota Station',
    '语言': 'Language',
    '跟随系统': 'System default',
    '显示额度小站': 'Show Quota Station',
    '展开全部额度': 'Expand quotas',
    '显示来源…': 'Sources…',
    '显示来源': 'Sources',
    '选择显示来源': 'Choose sources',
    '选择显示的 Agent 额度来源': 'Choose which agent quotas to display',
    '立即刷新': 'Refresh now',
    '立即刷新全部额度': 'Refresh all quotas now',
    '恢复小卡片默认大小': 'Reset card size',
    '取消边缘吸附': 'Undock from edge',
    '总在最前': 'Always on top',
    '隐藏到托盘': 'Hide to tray',
    '退出': 'Quit',
    '收起额度详情': 'Collapse quota details',
    '收起（Esc）': 'Collapse (Esc)',
    '每 5 分钟自动更新': 'Refreshes every 5 minutes',
    '刷新': 'Refresh',
    '小卡片': 'Card',
    '悬浮球': 'Orb',
    '拖动书页折角缩放小卡片': 'Drag the folded corner to resize the card',
    '拖住小折角，沿对角线调整大小': 'Drag the folded corner diagonally to resize',
    '不限量': 'Unlimited',
    '尚未更新': 'Not updated yet',
    '刚刚更新': 'Updated just now',
    '正在连接': 'Connecting',
    '待连接': 'Not connected',
    '上次余额': 'Last balance',
    '剩余额度': 'Remaining quota',
    '剩余余额': 'Balance',
    '剩余积分': 'Points left',
    '可用额度': 'Available quota',
    '本周剩余': 'Weekly remaining',
    '总额度': 'Total',
    '只显示总额度': 'Total only',
    '总额度 + 5 小时': 'Total + 5 hours',
    '可用 Credits 合计': 'Available credits',
    '剩余 Credits': 'Credits left',
    '积分': 'Points',
    '元': 'CNY',
    '左侧上一页 · 右侧下一页': 'Left: previous · Right: next',
    '单击切换': 'Click to switch',
    ' · 双击展开\n拖动调整位置 · 右键菜单 · Enter 展开 · 左右键切换': ' · Double-click to expand\nDrag to move · Right-click for menu · Enter to expand · Arrow keys to switch',
    '\n右键查看详情': '\nRight-click for details',
    '更新失败': 'Refresh failed',
    '暂不可用': 'Unavailable',
    '更新中…': 'Refreshing…',
    '更新中': 'Refreshing',
    '部分来源待连接': 'Some sources need attention',
    '尚未选择来源': 'No sources selected',
    '来源：': 'Source: ',
    '成功更新：': 'Last updated: ',
    ' · 额度详情': ' · Quota details',
    '本机直连': 'Local clients',
    '额度小站 · 显示来源': 'Quota Station · Sources',
    '一键同步 Magpie': 'Sync Magpie',
    '自动检测本机 Magpie 并同步额度来源': 'Find local Magpie and sync quota sources',
    '同步详情': 'Sync details',
    '完成': 'Done',
    '暂未连接': 'Disconnected',
    '额度暂不可用': 'Quota unavailable',
    '暂无来源': 'No sources yet',
    '同步中…': 'Syncing…',
    '刷新中…': 'Refreshing…',
    '正在检测本机 Magpie 并同步额度…': 'Finding Magpie and syncing quotas…',
    '程序路径：': 'Executable: ',
    '尚未检测到': 'Not detected yet',
    '版本：': 'Version: ',
    '连接方式：': 'Connection: ',
    'Magpie 命令行': 'Magpie CLI',
    '上次同步：': 'Last sync: ',
    '额度小站 · 检查更新': 'Quota Station · Updates',
    '更新内容': 'Release notes',
    '关闭': 'Close',
    '取消': 'Cancel',
    '检查更新': 'Check for updates',
    '检查更新…': 'Check for updates…',
    '安装桌面版': 'Install desktop app',
    '一键升级': 'Update now',
    '再次检查': 'Check again',
    '上次升级未完成…': 'Previous update failed…',
    '正在检查更新…': 'Checking for updates…',
    '已是最新版本': 'You’re up to date',
    '正在下载': 'Downloading',
    '正在准备升级': 'Preparing update',
    '已取消更新': 'Update cancelled',
    '检查更新失败，请稍后重试': 'Could not check for updates. Please try again.',
    '下载或准备失败，当前版本未改变，请重试': 'Could not prepare the update. Your current version is unchanged. Please retry.',
    '设置未能保存，升级已停止': 'Could not save settings. Update stopped.',
    '无法启动升级，当前版本未改变': 'Could not start the update. Your current version is unchanged.',
    '正在升级，即将重新打开…': 'Updating; the app will reopen shortly…',
    '额度返回格式不正确': 'Invalid quota response',
    '未返回可确认的剩余额度': 'No confirmed remaining quota returned',
    '剩余百分比超出范围': 'Remaining percentage is out of range',
    '连接暂不可用，请打开对应客户端并登录后刷新': 'Connection unavailable. Open the client, sign in and refresh.',
    '登录连接暂不可用，请打开对应客户端并登录后刷新': 'Sign-in unavailable. Open the client, sign in and refresh.',
    'Magpie 暂时无法连接': 'Could not connect to Magpie',
    'Magpie 连接设置尚未保存，请检查 state 目录权限': 'Could not save the Magpie connection. Check state folder permissions.',
    'Magpie 暂未提供可确认的额度': 'Magpie has not returned a confirmed quota',
    'Magpie 当前未返回此账号，请检查 Magpie 中的连接': 'Account missing from Magpie. Check its connection in Magpie.',
    '本地缓存未能保存，请检查 state 目录权限': 'Could not save the cache. Check state folder permissions.',
    '选择尚未保存，请检查 state 目录权限': 'Could not save your selection. Check state folder permissions.',
    '语言设置尚未保存，请检查 state 目录权限': 'Could not save the language. Check state folder permissions.',
    '额度小站侧边条，悬停查看，拖回屏幕恢复卡片': 'Quota Station edge bar. Hover to peek; drag inward to restore the card.',
    '额度小站 · 演示': 'Quota Station · Demo',
    '额度小站 · 显示来源（演示数据）': 'Quota Station · Sources (demo data)',
    '演示数据': 'Demo data',
    '演示模式 · 不连接账号': 'Demo · No accounts connected',
    '演示': 'Demo',
    '额度小站 · 演示模式': 'Quota Station · Demo',
    '虚构演示数据，不对应任何真实账号': 'Synthetic demo data; no real accounts',
    '本周': 'Weekly',
    '主额度窗口': 'Primary window',
    '次额度窗口': 'Secondary window',
    '可用额度重置次数': 'Quota resets available',
    '数据来源': 'Data source',
    '账号': 'Account',
    '套餐': 'Plan',
    '额度': 'Quota',
    '暂无数据': 'No data',
    '总积分': 'Total credits',
    '额外积分': 'Extra credits',
    '图片生成': 'Image generation',
    '余额': 'Balance',
    '赠送余额': 'Promotional balance',
    '充值余额': 'Topped-up balance',
    '套餐剩余': 'Plan remaining',
    '附加包剩余': 'Add-on remaining',
    '组织分配剩余': 'Organization allocation remaining',
    '专用资源包': 'Dedicated package',
    '个人专业版': 'Personal Pro',
    '套餐刷新': 'Plan resets',
    '套餐到期': 'Plan expires',
    'Qoder IDE 实时查询': 'Live Qoder IDE query',
    '新版 Qoder App 实时查询': 'Live Qoder App query',
    'Qoder 官方 SDK': 'Official Qoder SDK',
    '额度口径': 'Quota calculation',
    '各资源包本周期剩余积分之和': 'Sum of remaining points in all current-period packages',
    '资源包': 'Packages',
    '体验版': 'Trial',
    '版本信息格式不正确': 'Invalid version information',
    '当前系统暂不支持自动升级': 'Automatic updates are not supported on this platform',
    '未找到正式发布版本': 'No stable release found',
    '这个版本尚未提供当前系统的安装包': 'No package is available for this platform yet',
    '安装包信息或校验值不完整，暂不升级': 'Incomplete package information or checksum. Update stopped.',
    '下载跳转地址不属于 GitHub': 'The download redirected outside GitHub',
    '更新地址不正确': 'Invalid update URL',
    'GitHub 暂时限制了查询次数，请稍后再试': 'GitHub rate limit reached. Please try again later.',
    '无法连接 GitHub，请检查网络后重试': 'Could not connect to GitHub. Check your connection and retry.',
    '更新信息过大': 'Update metadata is too large',
    '无法解析 GitHub 更新信息': 'Could not read GitHub release information',
    '下载大小与发布信息不一致': 'Download size does not match the release',
    '安装包校验失败，当前版本未改变，请重试': 'Checksum failed. Your current version is unchanged. Please retry.',
    '请先把小站拖入 Applications，再检查更新': 'Move Quota Station to Applications before updating',
    '无法复制应用程序': 'Could not copy the application',
    '安装包解压大小异常': 'Unexpected unpacked size',
    '安装包目录不正确': 'Invalid package paths',
    '安装包缺少程序文件': 'The package is missing application files',
    '无法打开下载的安装包': 'Could not open the downloaded package',
    '安装包身份或版本不匹配': 'Package identity or version does not match',
    '应用签名校验失败': 'Application signature verification failed',
    '安装位置不正确': 'Invalid installation location',
    '当前安装目录不可写，请把程序移到你有写入权限的目录': 'The installation folder is not writable. Move the app to a folder you can write to.',
    '升级需要至少 1.5 GB 可用空间': 'Updates require at least 1.5 GB of free space',
    '更新任务路径校验失败': 'Invalid update task paths',
    '升级助手未能启动，当前版本未改变': 'The update helper could not start. Your current version is unchanged.',
    '升级助手启动超时，当前版本未改变': 'The update helper timed out. Your current version is unchanged.',
    '更新确认路径不正确': 'Invalid update confirmation path',
    '旧版本尚未退出，更新已停止': 'The old version is still running. Update stopped.',
    '备份目录已存在，更新已停止': 'The backup folder already exists. Update stopped.',
    '升级完成': 'Update complete',
    '新版本未能正常启动': 'The new version could not start',
    '新版本启动超时': 'The new version timed out during startup',
    '无法替换程序文件，请关闭占用它的窗口后重试。': 'Could not replace application files. Close anything using them and retry.',
    'Codex 返回的额度格式无效，请稍后重试。': 'Codex returned invalid quota data. Please retry.',
    'Codex 返回的多窗口额度格式无效。': 'Codex returned invalid quota windows.',
    'Codex 暂未提供可用的额度百分比，请确认已登录 ChatGPT 账户后重试。': 'Codex has not returned a quota percentage. Sign in with a ChatGPT account and retry.',
    '配置的 Codex 程序不存在，请检查 QUOTA_CODEX_EXECUTABLE。': 'Codex executable not found. Check QUOTA_CODEX_EXECUTABLE.',
    '没有找到 Codex 命令行程序，请先安装 Codex CLI 并登录。': 'Codex CLI not found. Install it and sign in first.',
    'Codex 额度服务未能启动，请检查 Codex CLI 安装。': 'Could not start the Codex quota service. Check your CLI installation.',
    'Codex 额度连接已关闭，请稍后重试。': 'The Codex quota connection closed. Please retry.',
    'Codex 额度查询超时，请检查网络后重试。': 'Codex quota query timed out. Check your connection and retry.',
    'Codex 额度服务意外退出，请检查登录状态和 CLI 版本。': 'The Codex quota service exited. Check your sign-in and CLI version.',
    'Codex 额度服务返回了无法识别的数据。': 'The Codex quota service returned unreadable data.',
    'Codex 额度服务返回了无效响应。': 'The Codex quota service returned an invalid response.',
    'Codex 额度查询失败，请在 Codex 中确认已登录并检查网络。': 'Codex quota query failed. Check your sign-in and network connection.',
    'Codex 额度服务返回了不完整的响应。': 'The Codex quota service returned an incomplete response.',
    'Codex 查询超时设置必须为正数。': 'The Codex query timeout must be positive.',
    'QUOTA_MAGPIE_EXECUTABLE 未指向有效的 Magpie 程序': 'QUOTA_MAGPIE_EXECUTABLE does not point to a valid Magpie executable',
    'Magpie 额度响应格式异常': 'Invalid Magpie quota response',
    'Magpie 返回了无法区分的同名账号，请在 Magpie 中设置不同名称': 'Magpie returned indistinguishable accounts. Give them different names in Magpie.',
    'Magpie 暂未读到此账号额度，请在 Magpie 中检查连接后刷新': 'Magpie could not read this quota. Check the account connection in Magpie and refresh.',
    'Magpie 本机查询地址发生跳转': 'The local Magpie endpoint redirected unexpectedly',
    'QUOTA_MAGPIE_PORT 必须是有效端口号': 'QUOTA_MAGPIE_PORT must be a valid port number',
    'Magpie 额度响应过大': 'Magpie quota response is too large',
    '未连接 Magpie，请打开 Magpie 后刷新': 'Magpie is not connected. Open Magpie and refresh.',
    'Magpie 暂时无法读取额度，请打开 Magpie 后刷新': 'Magpie could not read quotas. Open Magpie and refresh.',
    'Magpie 额度暂时不可用，请打开 Magpie 后刷新': 'Magpie quotas are unavailable. Open Magpie and refresh.',
    '未找到本机 Magpie，请先打开 Magpie，再点击一键同步': 'Magpie was not found. Open Magpie, then click Sync Magpie.',
    'Magpie 同步暂未完成，请确认已打开 Magpie 后重试': 'Magpie sync did not finish. Make sure Magpie is open and retry.',
    'Qoder CLI 尚未登录；请打开已登录的 Qoder IDE 后刷新。': 'Qoder CLI is not signed in. Open a signed-in Qoder IDE and refresh.',
    'Qoder 暂未返回账户额度，请稍后刷新。': 'Qoder has not returned account quotas. Please refresh later.',
    'Qoder SDK 暂时无法读取额度。': 'Qoder SDK could not read quotas.',
    '请打开并登录 Qoder IDE，然后刷新额度。': 'Open Qoder IDE, sign in and refresh.',
    '无法访问 Qoder IDE 本地服务，请以同一 Windows 用户运行小组件。': 'Cannot access Qoder IDE. Run Quota Station as the same Windows user.',
    'Qoder IDE 额度查询超时，请稍后刷新。': 'Qoder IDE quota query timed out. Please refresh later.',
    'Qoder 额度响应格式异常，请稍后刷新。': 'Invalid Qoder quota response. Please refresh later.',
    '未找到 Node.js，暂时无法读取 Qoder 额度。': 'Node.js is required for the legacy Qoder connection.',
    'Qoder 读取组件缺失，请重新安装小组件。': 'The Qoder reader is missing. Reinstall Quota Station.',
    'Qoder 额度查询超时，请稍后刷新。': 'Qoder quota query timed out. Please refresh later.',
    '无法启动 Qoder 额度读取组件。': 'Could not start the Qoder reader.',
    'Qoder 额度读取组件暂时不可用。': 'The Qoder reader is unavailable.',
    'Qoder 未返回完整的剩余额度，暂不显示余额。': 'Qoder returned incomplete quota data. Balance is unavailable.',
    'Qoder 返回了不同的计量单位，暂不合并余额。': 'Qoder returned different units. Balances cannot be combined.',
    'Qoder 未返回完整的专用资源包额度。': 'Qoder returned incomplete dedicated-package quotas.',
    'Qoder 未返回账户余额；已用额度或会话消耗不能代替剩余额度。': 'Qoder did not return a remaining balance. Used quota and session usage are not remaining quota.',
    '请打开新版 Qoder 并确认已登录，然后刷新额度。': 'Open Qoder App, make sure you are signed in, then refresh.',
    '新版 Qoder 额度响应格式异常，请稍后刷新。': 'Qoder App returned an invalid quota response. Please refresh later.',
    '新版 Qoder 额度服务暂时不可用，请稍后刷新。': 'Qoder App quota service is unavailable. Please refresh later.',
    '新版 Qoder 额度查询失败，请检查网络后刷新。': 'Qoder App quota query failed. Check your network and refresh.',
    '新版 Qoder 返回了不同的计量单位，暂不合并余额。': 'Qoder App returned different units. Balances cannot be combined.',
    '当前 Qoder 企业账号需在客户端查看用量，未提供可换算的 Credits 余额。': 'View this Qoder enterprise account in its client; no convertible Credits balance was returned.',
    'Qoder 登录状态刚刚更新，请再刷新一次额度。': 'Qoder sign-in just changed. Refresh quotas once more.',
    'WorkBuddy 登录读取需要 Windows 环境': 'Reading WorkBuddy sign-in requires Windows',
    'WorkBuddy 查询地址发生跳转，请稍后重试': 'The WorkBuddy endpoint redirected unexpectedly. Please retry.',
    'WorkBuddy 登录已失效，请打开 WorkBuddy 并确认已登录': 'WorkBuddy sign-in expired. Open WorkBuddy and sign in again.',
    '暂时无法连接 WorkBuddy，请检查网络后重试': 'Could not connect to WorkBuddy. Check your network and retry.',
    'WorkBuddy 返回数据异常，暂不能确认剩余积分': 'WorkBuddy returned invalid data. Remaining points are unavailable.',
    'WorkBuddy 返回格式异常，暂不能确认剩余积分': 'Invalid WorkBuddy response. Remaining points are unavailable.',
    'WorkBuddy 未能返回有效额度，请打开客户端确认登录状态': 'WorkBuddy did not return a valid quota. Check your sign-in in the client.',
    'WorkBuddy 未返回可确认的资源包，暂不能确认剩余积分': 'WorkBuddy did not return confirmed packages. Remaining points are unavailable.',
    'WorkBuddy 资源包额度字段异常，暂不能确认剩余积分': 'Invalid WorkBuddy package quota. Remaining points are unavailable.',
    '未找到 WorkBuddy 登录状态，请先打开 WorkBuddy 并登录': 'WorkBuddy sign-in not found. Open WorkBuddy and sign in.',
    'WorkBuddy 额度暂时无法读取，请稍后重试': 'Could not read WorkBuddy quotas. Please retry later.',
    'WorkBuddy 本机额度目前仅支持 Windows': 'Local WorkBuddy quotas are currently available on Windows.',
    'WorkBuddy 尚未显示当前账号的积分': 'Waiting for WorkBuddy to show credits for the current account.',
    'WorkBuddy 账号已切换，正在重新读取': 'WorkBuddy switched accounts. Checking the new balance.',
    '等待 WorkBuddy 客户端显示当前账号': 'Waiting for the WorkBuddy client to show the current account.',
    'WorkBuddy 客户端积分余额': 'Credit balance shown in the WorkBuddy client',
    'Antigravity 官方客户端': 'Official Antigravity app',
    'Antigravity 已关闭，等待客户端更新额度': 'Antigravity is closed. Waiting for the app to update quotas.',
    '请先在 Antigravity 官方客户端登录': 'Sign in to the official Antigravity app first.',
    'Antigravity 账号已切换，等待新账号额度': 'Antigravity switched accounts. Waiting for the new quotas.',
    'Antigravity 本机查询地址发生跳转': 'The local Antigravity endpoint redirected unexpectedly.',
    'Antigravity 额度响应过大': 'The Antigravity quota response is too large.',
    'Antigravity 额度响应格式异常': 'Invalid Antigravity quota response.',
    'Antigravity 暂未返回可确认的额度': 'Antigravity has not returned confirmed quotas yet.',
    'Antigravity 本机额度暂时无法读取，请稍后刷新': 'Antigravity quotas could not be read. Refresh later.',
    '上次读数': 'Last reading',
    '部分来源显示上次读数': 'Some sources show their last reading',
}

# These also render canonical Chinese snapshots/errors cached by pre-i18n apps.
TEMPLATES = {
    '{group} · {window}剩余': '{group} · {window} remaining',
    '{group} · {window}': '{group} · {window}',
    '{count} 分钟前': '{count} min ago',
    '{count} 小时前': '{count} hr ago',
    '{time} 重置': 'Resets {time}',
    '{name} {unit} {value}，{hint}，双击展开': '{name} {unit} {value}; {hint}; double-click to expand',
    '显示 {name}': 'Show {name}',
    '已选 {count} 项': '{count} selected',
    '本机网关 · 127.0.0.1:{port}': 'Local gateway · 127.0.0.1:{port}',
    '当前版本  v{version}': 'Current version  v{version}',
    '新版本  v{version}': 'New version  v{version}',
    '可安装桌面版  v{version}': 'Desktop app available  v{version}',
    '发现新版本 v{version}…': 'Update available: v{version}…',
    '已同步 {count} 个来源 · {unavailable} 个暂不可用': 'Synced {count} sources · {unavailable} unavailable',
    '已同步 {count} 个来源': 'Synced {count} sources',
    '{name}，{status} {value}，悬停查看，拖回屏幕恢复卡片': '{name}, {status} {value}. Hover to peek; drag inward to restore the card.',
    'GitHub 暂时无法连接（{code}），请稍后重试': 'Could not connect to GitHub ({code}). Please retry.',
    '升级未完成，已保留原版本。{reason}': 'Update failed; the previous version was kept. {reason}',
    '{message}  {percent}%': '{message}  {percent}%',
    '{days}天窗口': '{days}-day window',
    '{hours}小时窗口': '{hours}-hour window',
    '{minutes}分钟窗口': '{minutes}-minute window',
    '{hours} 小时': '{hours} hours',
    '{count} 次': '{count} times',
    '{count} 个': '{count}',
    '{amount} 积分': '{amount} Points',
    '剩余 {value} · {time} 重置': '{value} remaining · Resets {time}',
    '剩余 {value}': '{value} remaining',
    '{window}剩余': '{window} remaining',
    '{value}（暂不可用，不计入合计）': '{value} (unavailable; excluded from total)',
    'WorkBuddy 查询暂时失败（HTTP {code}）': 'WorkBuddy query failed (HTTP {code})',
}


def _compile(template):
    parts = []
    for literal, field, _, _ in Formatter().parse(template):
        parts.append(re.escape(literal))
        if field:
            parts.append(f'(?P<{field}>.+?)')
    return re.compile(''.join(parts), re.DOTALL)


PATTERNS = [(_compile(source), target) for source, target in sorted(
    TEMPLATES.items(), key=lambda entry: sum(len(literal) for literal, _, _, _ in Formatter().parse(entry[0])), reverse=True)]


def system_language():
    languages = QLocale.system().uiLanguages()
    return 'zh-CN' if languages and languages[0].lower().startswith('zh') else 'en'


def set_language(choice):
    global _language
    choice = choice if choice in CHOICES else 'auto'
    _language = system_language() if choice == 'auto' else choice
    return choice


def language():
    return _language


def _english(text, depth=0):
    if text in EN:
        return EN[text]
    if text in TEMPLATES:
        return TEMPLATES[text]
    if depth < 4:
        for pattern, target in PATTERNS:
            match = pattern.fullmatch(text)
            if match:
                return target.format(**{key: _english(value, depth + 1)
                                        for key, value in match.groupdict().items()})
    return text


def tr(text, **values):
    text = str(text)
    result = _english(text) if _language == 'en' else text
    return result.format(**values) if values else result


def pair(label, value):
    return f'{label}: {value}' if _language == 'en' else f'{label}：{value}'
