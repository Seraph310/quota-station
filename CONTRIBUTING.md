# Contributing / 参与项目

English and Chinese issues and pull requests are welcome. Please read the [PolyForm Noncommercial license](LICENSE) first. Contributions to this repository are made under the same license; third-party material must keep its own license and attribution.

欢迎用中文或英文反馈问题、提交 PR。请先阅读[非商业许可证](LICENSE)。提交到仓库的贡献遵循相同许可；第三方材料保留原有许可与署名。

## Report a problem / 反馈问题

Include your OS and architecture, Quota Station version, affected source, steps to reproduce, and what you expected. Use demo data in screenshots where possible. Do not attach account tokens, login files, real account caches, or the `state/` and `.cache/` directories.

请提供操作系统与架构、小站版本、涉及的来源、复现步骤及预期结果。截图尽量使用演示数据；不要上传令牌、登录文件、真实账号缓存或 `state/`、`.cache/` 目录。

## Development / 开发

Use Python 3.11+ and an isolated virtual environment with `requirements.txt`. Run checks from the repository root:

```bash
python -m unittest discover -s tests -p "test_*.py"
python tools/render_public.py
```

Tests run offline using synthetic provider responses and Qt’s offscreen backend. The public renderer uses isolated temporary state. Scripts named `verify_live.py`, `verify_qoder_app.py`, `verify_magpie_sync.py`, and `render_check.py` can read real local account state; do not use their output as public assets.

测试使用合成响应与离屏 Qt 界面，不访问真实账号。公开演示图使用临时隔离状态。名称包含 live 的验证脚本及上述真实连接验证脚本可能读取本机账号，其输出不能作为公开素材。

## Languages / 语言

UI translations live in `i18n.py`. Add Chinese message keys and English values there, and call `tr()` at display boundaries. Keep provider IDs, account names, stored units and quota values unchanged. Formatted templates must keep matching placeholder names. `tests/test_i18n.py` verifies live switching, persistence, safe error messages and cached data.

界面翻译在 `i18n.py`。展示时调用 `tr()`，不要翻译来源 ID、账号名或改写缓存数据；模板中英文占位符需一致。新增功能同时更新两种语言和对应文档。

## Desktop builds / 桌面打包

Build on the target OS with `requirements-build.txt` and `python tools/build_release.py`. Windows x64, Apple silicon and Intel Mac packages are built in GitHub Actions. Each build runs offline tests, renders both UI languages from the frozen app, and performs a real replacement-and-restart update in an isolated directory.

For a release, update `version.py` and bilingual `docs/RELEASE.md`, run the build workflow with draft publication enabled, inspect all platform reports and checksums, then publish the draft. Published release packages must not be overwritten. Keep `LICENSE`, `NOTICE`, dependency notices and both download guides in packages.
