# Quota Station · Desktop downloads

[简体中文](DOWNLOAD.md) · [Project home](../README.md)

Download from [GitHub Releases](https://github.com/Seraph310/quota-station/releases/latest). Python is not required.

## Install

**Windows 10/11 x64:** extract the whole ZIP. Open the `QuotaStation` folder and run `QuotaStation.exe`. Keep its `_internal` folder beside it. You can create a desktop shortcut to the executable.

**macOS:** choose arm64 for Apple silicon or x64 for Intel. Open the DMG and drag `Quota Station.app` into Applications before launching it or using in-app updates. Packages are built and tested on macOS 15.

Current Windows packages are unsigned. Mac apps use ad-hoc signatures and are not notarized. If macOS cannot verify the developer, follow [Apple’s instructions for opening this specific app](https://support.apple.com/en-us/102445) after confirming you downloaded it from this project. Do not disable system security protections.

## Choose accounts and language

Sign in to the corresponding clients on this computer first. Windows supports Codex CLI, Qoder, WorkBuddy, and Magpie. macOS supports Codex CLI and Magpie; native Qoder and WorkBuddy sign-in reading is not implemented there.

Double-click the card, open **Sources**, and check the accounts you want to display. **Sync Magpie** detects the local installation and imports its connected sources.

Right-click the card or tray icon → **Language / 语言** → **System default / 简体中文 / English**. Language changes apply immediately and are saved. First launch follows the OS UI language: Chinese for Chinese locales, English otherwise.

Click the card’s left or right half to turn pages. Drag the folded corner to resize. Drag past either side of the screen to dock into a slim quota bar; hover to peek, move away to tuck it back, or drag inward to restore the card.

## Update

Starting with v0.4.0, right-click → **Check for updates** → **Update now**. Quota Station downloads the matching GitHub package, verifies its SHA-256, preserves your settings, and restarts. A failed startup restores the previous version. The installation folder must be writable by your user.

Release checks run silently once per day. Updates are installed only when you choose them. Versions before v0.4.0 need a one-time manual upgrade. From source, the same window offers **Install desktop app**, copies your current settings, and updates this project’s desktop shortcut on Windows while preserving your source checkout.

For a manual update, quit from the tray menu before replacing the complete application folder or `.app` bundle.

## Local data

- Windows: `%LOCALAPPDATA%\QuotaStation`
- macOS: `~/Library/Application Support/QuotaStation`

Settings, selected sources and cached balances stay in those directories when the app is updated or moved. Releases do not contain the author’s accounts or sign-in credentials. On a new computer, sign in to your clients there; do not copy someone else’s login files.

## License

Quota Station uses the [PolyForm Noncommercial License 1.0.0](../LICENSE). Commercial uses outside its permitted purposes require separate authorization. `LICENSE.txt` and `NOTICE.txt` are included with downloads. Dependencies retain their own licenses, included under `_internal/licenses` on Windows or `Contents/Resources/licenses` inside the Mac app. Copies of the project license and notice are also included there and retained by the updater.
