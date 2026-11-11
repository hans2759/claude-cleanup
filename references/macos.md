# macOS 操作范围

使用 Python 3.10+，在 skill 根目录运行 `python3 scripts/claude_cleanup.py --audit`；交互执行时去掉 `--audit`。Windows 不可使用该入口。

## 自动清理候选

```text
~/.claude/cache
~/.claude/stats-cache.json
~/.claude/telemetry
~/.claude/usage-data
~/.claude/usage.jsonl
~/.claude/usage.with-fix.jsonl
~/Library/Caches/claude-cli-nodejs
~/Library/Caches/com.anthropic.claudefordesktop*
~/Library/Logs/Claude
~/Library/Logs/DiagnosticReports/Claude*
~/Library/Application Support/CrashReporter/Claude*
```

Claude 进程正在运行时，单纯缓存/日志清理会跳过；风险操作要求用户正常退出并复检。脚本不结束进程。

## 可选操作

- **本地身份轮换**：轮换 `~/.claude.json` 的 `userID`、`machineID`，清除已知账号缓存字段，同步 `~/.claude/backups/.claude.json.backup.*`；外部备份保持原值。
- **钥匙串**：删除 `Claude Code-credentials`，可能退出 CLI 登录。此项不是文件移入废纸篓，不能从文件备份还原钥匙串条目；需要重新登录。不承诺覆盖所有凭据来源。
- **Desktop**：`0` 保留；`1` 移走脚本白名单内的持久数据；`2` 再移走 `/Applications/Claude.app`。其中 `~/Library/Application Support/Claude` 等目录是整体移动，会包含 Desktop MCP 配置和扩展；提前告知用户并核对清单。
- **精简模式**：设置或移除 `settings.json` 中的 `env.CLAUDE_CODE_SIMPLE`。不删除 skills、plugins、hooks、MCP 等资产。
- **台北时区**：仅在当前不是 `Asia/Taipei` 时询问。通过 `sudo systemsetup` 修改并验证；密码仅由用户在终端的原生隐藏提示中输入，不发送给执行者、不读取或保存。

## 备份与恢复位置

首个写操作完整复制 `~/.claude` 并备份现存 `~/.claude.json`，存入 `~/ClaudeBackups/claude-cleanup-时间戳`；原脚本按普通文件数量和总大小校验，身份文件按大小校验，不宣称做 SHA-256 校验。`~/.claude` 缺失时不能执行清理。

文件移除进入 `~/.Trash/claude-cleanup-时间戳`，不永久删除或清空废纸篓。恢复前退出 Claude，核对备份或废纸篓批次；不要直接覆盖已经重新生成的当前文件。钥匙串和时区属于独立系统修改，不能靠复制 `.claude` 撤销。

如检测到自定义 Claude 配置目录、链接或其他非标准布局，先保持只读，不临时扩大脚本白名单。Windows 专属的 reparse point 检查、SHA-256 校验和 `moves.json` 不能视作 macOS 脚本已有的功能。
