# claude-cleanup

Claude 本机清理 skill，支持 **macOS 与原生 Windows**：审计、备份、清理 Claude Code / Claude Desktop 的缓存、日志及可选登录状态。需要 **Python 3.10+**，无第三方 Python 依赖。

## 快速开始

在本仓库目录执行。先只读审计，再根据清单选择是否运行交互清理。

### Windows

支持 Windows 10/11、PowerShell 5.1/7。入口自动查找 `py` 或 `python`，无需管理员权限。

```powershell
# 只读审计
& .\scripts\claude_cleanup_windows.ps1 -Audit

# 交互清理：选择可选操作，检查完整路径，最后输入 CONFIRM
& .\scripts\claude_cleanup_windows.ps1
```

如果执行策略阻止 `.ps1`，可直接运行 Python 入口，无需修改系统策略：

```powershell
py -3 -B -X utf8 .\scripts\claude_cleanup_windows.py --audit
py -3 -B -X utf8 .\scripts\claude_cleanup_windows.py
```

### macOS

```bash
python3 scripts/claude_cleanup.py --audit
python3 scripts/claude_cleanup.py
```

实际清理需要用户可交互的终端。正在运行的 Claude Code 只能启动只读审计，不能修改自己的配置；改用独立终端或 Codex 的终端执行。脚本不提供跳过确认参数，不自动结束 Claude 进程。

## 平台范围

| 功能 | Windows | macOS |
| --- | --- | --- |
| Code 缓存、用量缓存和日志 | 支持 | 支持 |
| Desktop 缓存和日志 | 标准目录及已知 MSIX 目录中的白名单子项 | 脚本中的 Library 白名单 |
| 本地 ID 轮换 | 可选，备份后同步已知内部备份 | 同左 |
| CLI 登录凭据 | 可选移走 `.claude\.credentials.json` | 可选删除指定钥匙串条目 |
| Desktop 登录态重置 | 只移动白名单存储，保留 MCP 配置和扩展 | 整体移动已知数据目录，包含其中的 MCP 配置和扩展 |
| 精简模式 | 可选设置/移除 `CLAUDE_CODE_SIMPLE` | 同左 |
| 应用移除、台北时区 | 不处理 | 可选 |
| 文件移除去向 | `ClaudeCleanupTrash` 可恢复隔离目录 | `~/.Trash` 批次目录 |

Windows 以 `%USERPROFILE%\.claude`、`%APPDATA%\Claude` 为主要数据目录，并识别现存 `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`。不处理整个 AppData、应用安装目录、注册表、Windows 凭据管理器或 WSL。自定义配置/凭据目录只允许默认路径审计，禁止清理；AppData 位于用户目录外时停止。

完整白名单、限制和恢复步骤见 [Windows 说明](references/windows.md) 与 [macOS 说明](references/macos.md)。供 agent 使用的入口说明见 [SKILL.md](SKILL.md)。

## 安全与恢复

- 清理前先完整备份现存 `.claude` 和 `.claude.json`，保存到用户目录的 `ClaudeBackups`。Windows 逐文件 SHA-256 校验；macOS 保留原有数量/大小校验。
- Windows 拒绝符号链接、junction、其他 reparse point，以及位于或包含 Git 仓库的清理目标。进程查询失败或检测到 Claude 重新启动时停止，不把查询失败当作“进程已退出”。
- 所有**文件移除**都可恢复，不永久删除。Windows 隔离目录是 `%USERPROFILE%\ClaudeCleanupTrash`，不是系统回收站；备份内的 `moves.json` 记录源路径、隔离路径和完成状态。钥匙串删除、时区修改不属于文件移除。
- Code 会话、项目、历史、skills、plugins、hooks、commands、agents、MCP 等保护数据不移走。仅在明确选择时修改精简模式键或已知身份文件；其他设置和遥测三键逐值保留。
- 失败立即停止，可能保留 `.partial` 备份或已移动项。恢复前退出 Claude，逐项核对路径；原路径已有新数据时不要覆盖。备份和隔离可能含凭据、会话，不上传、不自动清空。
- 完整备份与保留隔离文件可能增加磁盘占用，不能当作立即释放空间的工具。

## 验证

```powershell
python -B -X utf8 -m unittest discover -s tests -v
```

测试在临时目录构造数据，不清理真实用户配置。覆盖备份、取消、保护数据、遥测保留、Windows 登录态与 MSIX 路径、同大小内容损坏、进程检查、部分失败，以及 Windows junction 越界防护。macOS 交互与系统命令使用模拟验证，仍需在 macOS 上做原生验证。

## 边界

用于本机隐私与排障，不删除云端聊天、不保证撤销所有登录方式或远程令牌，不用于规避封禁、支付检查、设备/IP 信誉或其他平台风控。

配套：[Claude 环境检测](https://www.agenai.cc/claude-check) 查网络环境，本 skill 管本机状态，两者都不查账号封没封。

## License

本项目采用 [MIT License](LICENSE)。
