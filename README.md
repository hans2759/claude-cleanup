# claude-cleanup

Claude 本机清理 skill：在 macOS 上安全审计、完整备份、清理或重置 Claude Code 与 Claude Desktop 的本机状态。

适用于清理可再生缓存和日志、轮换本地 ID、重置桌面端登录态、移除应用、启用最小提示词模式或修改台北时区。

## 安全设计

- 用随附脚本执行，不临时拼接 `rm`；脚本采用窄白名单，目标与保护路径重叠立即停止
- 第一个写操作是完整复制并校验 `~/.claude`，同时备份 `~/.claude.json`
- 所有移除只进入时间戳废纸篓目录，不永久删除、不清空废纸篓
- 写盘前显示展开后的完整清单，用户输入一次 `CONFIRM` 后才开始；失败即停止
- 遥测设置（`DISABLE_TELEMETRY` 等三键）逐值保留，原样不动

## 用法

先跑只读审计：

```
python3 scripts/claude_cleanup.py --audit
```

正式执行要在 Codex 或普通终端里运行：

```
python3 scripts/claude_cleanup.py
```

注意：正在运行的 Claude Code 不能改自己的 `~/.claude`，由它启动时只允许 `--audit` 只读审计。

自动安全清理的范围是可再生缓存和日志（如 `~/.claude/cache`、`telemetry`、`usage-data`、`~/Library/Logs/Claude`）。身份轮换、钥匙串、桌面端登录态、应用移除、精简模式和时区属于风险操作，由用户在运行时逐项选择。

绝不动：`~/.claude/projects`、`sessions`、`history.jsonl`、`skills`、`plugins`、`hooks`、`commands`、`agents`、`mcp-servers`、`CLAUDE.md`、`settings.json` 等保护路径，以及任何项目目录和 Git 仓库。

## 边界

本 skill 用于本机隐私与排障，不用于规避封禁、支付检查、设备或 IP 信誉、浏览器指纹或任何平台风控；清理不承诺防封。

配套：[Claude 环境检测](https://www.agenai.cc/claude-check) 查网络环境，本 skill 管本机状态，两者都不查账号封没封。
