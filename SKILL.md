---
name: claude-cleanup
license: MIT
description: 审计、备份和清理 macOS 或原生 Windows 上 Claude Code / Claude Desktop 的本机缓存、日志与登录状态。用于本机隐私清理、重置及排障；不处理项目清理、云端聊天删除、WSL/Linux 或规避平台风控。
---

# Claude 本机清理

使用本 skill 随附的脚本。脚本负责白名单、备份、交互确认和失败即停止，不自行拼接递归删除命令。

## 选择入口

以本 `SKILL.md` 所在目录为 skill 根目录，把下面的脚本路径解析为绝对路径；不要误用用户当前项目中的同名脚本。需要 Python 3.10+，Windows 的 PowerShell 入口会查找可用解释器。

| 平台 | 只读审计 | 执行及恢复细节 |
| --- | --- | --- |
| macOS | `python3 scripts/claude_cleanup.py --audit` | [macOS 范围](references/macos.md) |
| 原生 Windows | `& .\scripts\claude_cleanup_windows.ps1 -Audit` | [Windows 范围](references/windows.md) |

只读取当前平台的参考文件。Windows 也可使用 `py -3 -B -X utf8 scripts/claude_cleanup_windows.py --audit`。WSL/Linux 尚未支持，不把 Windows 入口用于 WSL 的主目录。

## 工作流程

1. 先审计并说明发现的目标、运行中的 Claude 进程和平台限制。只要求审计、阅读代码或修改脚本，不授权实际清理。
2. 用户已明确要求清理时，直接准备交互执行；无需另加一轮聊天确认。若当前执行者是 Claude Code，或脚本检测到 Claude 祖先进程，只做审计，交由用户在独立终端执行。
3. 在用户可操作的真实终端中运行相应入口，去掉审计参数。缓存/日志自动进入候选清单；身份、凭据、Desktop 登录态和精简模式仍由用户逐项选择。macOS 另有应用移除和时区选项。
4. 由用户检查完整路径清单并输入最终 `CONFIRM`。不要代填、管道代答、增加免确认参数或修改脚本绕过检查。已有聊天授权不替代脚本中的具体选项。
5. 报告实际完成的操作、跳过项、备份及恢复位置、遥测保留结果。取消、无可清理项、进程占用和部分失败要分别说明；不能统称成功。

只选缓存/日志但 Claude 正在运行时，脚本跳过清理。风险操作要求用户正常退出并复检，不能自动结束进程。Windows 在确认后和各项修改前也复检进程；进程查询失败不等于没有进程。

## 数据边界

- 保留 Claude Code 的 `projects`、`sessions`、`history.jsonl`、`file-history`、`debug`、`skills`、`plugins`、`hooks`、`commands`、`scripts`、`agents`、`mcp-servers`、`plans`、`tasks`、`todos`、`session-env`、`CLAUDE.md` 和设置文件。任何项目、Git 仓库或 Codex 数据都不属于清理目标。
- `settings.json` 仅在选择精简模式时结构化修改 `env.CLAUDE_CODE_SIMPLE`，保留其他字段及秘密；不把配置或凭据全文输出到对话。
- `backups` 不移动或删除；选择 ID 轮换时，允许同步修改已知 `.claude.json.backup.*` 文件的 ID 与账号缓存字段，先保留外部原始备份。
- 遥测三键 `DISABLE_TELEMETRY`、`DISABLE_ERROR_REPORTING`、`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` 的值和缺省状态保持不变，不主动开关。
- Windows 保留 Desktop MCP 配置和扩展，只移动白名单子项；macOS 的整目录 Desktop 重置会连同其中的 MCP 配置和扩展一起移入废纸篓，必须提前说明这一差异。
- 首个写操作用于完整备份现存 Claude Code 状态。Windows 使用 SHA-256 校验，并拒绝链接、junction、其他 reparse point 和含 Git 仓库的清理目标；遇到这些布局不要自行解引用或扩大白名单。

Windows 用 `%USERPROFILE%\ClaudeCleanupTrash` 普通隔离目录；macOS 用 `~/.Trash` 下的批次目录。不要把 Windows 隔离目录称作系统回收站。备份、隔离及废纸篓可能含凭据与会话，均不上传、不自动清空。

本 skill 仅处理本机状态，不承诺退出所有认证方式、撤销远程令牌、释放等量磁盘空间或改变平台关联判断；不用于规避封禁、支付检查、设备/IP 信誉或其他平台风控。
