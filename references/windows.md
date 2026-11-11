# Windows 操作范围与恢复

支持 Windows 10/11 原生用户配置，PowerShell 5.1/7 和 Python 3.10+；不需要第三方 Python 包或管理员权限。

## 入口

在 skill 根目录执行，或将脚本路径替换为该 skill 中的绝对路径：

```powershell
# 只读审计
& .\scripts\claude_cleanup_windows.ps1 -Audit
# 交互清理
& .\scripts\claude_cleanup_windows.ps1
```

若本机执行策略不允许 `.ps1`，直接运行 Python 入口，不修改系统执行策略：

```powershell
py -3 -B -X utf8 .\scripts\claude_cleanup_windows.py --audit
py -3 -B -X utf8 .\scripts\claude_cleanup_windows.py
```

脚本拒绝由 Claude 进程启动的写操作。需要让用户在独立 PowerShell/Windows Terminal 中完成最终确认。

## 白名单

默认 Code 根目录是 `%USERPROFILE%\.claude`，外部身份文件是 `%USERPROFILE%\.claude.json`。

自动清理候选：

- Code 根目录内的 `cache`、`stats-cache.json`、`telemetry`、`usage-data`、`usage.jsonl`、`usage.with-fix.jsonl`。
- `%LOCALAPPDATA%\claude-cli-nodejs`。
- Desktop 数据根目录中的 `Cache`、`Code Cache`、`GPUCache`、`DawnCache`、`logs`、`Crashpad`。

Desktop 数据根目录限定为 `%APPDATA%\Claude`，以及现存 `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`。仅检查这些路径，不移动整个 `Packages`、MSIX 包、安装目录或整个 Desktop 数据目录。

可选操作默认均关闭：

| 操作 | 实际效果 |
| --- | --- |
| 本地 ID 轮换 | 修改 `.claude.json` 的 `userID`/`machineID`，清除脚本列出的账号缓存字段，并同步 `.claude\backups\.claude.json.backup.*`；外部备份保留旧值 |
| CLI 凭据移走 | 只隔离 `.claude\.credentials.json`；不操作 Windows 凭据管理器、环境变量/API key 或远程令牌 |
| Desktop 登录态重置 | 只隔离 `Cookies`、`Cookies-journal`、`Network\Cookies`、`Network\Cookies-journal`、`Local Storage`、`Session Storage`、`IndexedDB`、`WebStorage`、`Service Worker`；可能丢失未同步内容，且不保证清除每个版本的全部认证状态 |
| 精简模式 | 设置 `env.CLAUDE_CODE_SIMPLE="1"` 或仅移除该键；其他设置保持原值 |

Desktop 的 `claude_desktop_config.json`、扩展、其他未知文件都保留。Windows 版不卸载应用、不修改时区，不处理其他安装变体或 WSL 内的数据。

检测到 `CLAUDE_CONFIG_DIR` / `CLAUDE_SECURESTORAGE_CONFIG_DIR` 时，只能审计默认目录，禁止写操作；不要通过清空变量绕过。AppData 位于用户目录外、路径包含符号链接/junction/reparse point，或清理目标位于/包含 Git 仓库时停止；只报告具体受阻路径，不扩展清理范围。

Windows 凭据位置参见 [Claude Code 官方认证文档](https://code.claude.com/docs/en/authentication#credential-management)。Desktop 标准配置与日志路径参见 [MCP 官方本地服务器指南](https://modelcontextprotocol.io/docs/develop/connect-local-servers)。MSIX 路径兼容来自 [上游 Windows 问题报告](https://github.com/anthropics/claude-code/issues/25579)，属于已知布局支持，并非所有版本的保证。

## 备份、失败与恢复

首个写操作创建 `%USERPROFILE%\ClaudeBackups\claude-cleanup-windows-时间戳.partial`，复制现存 `.claude` 与 `.claude.json`，比较路径、类型、大小和逐文件 SHA-256，再改为正式批次名。没有 CLI 配置的 Desktop 用户仍可清理，`manifest.json` 记录缺失的源。备份失败只保留 `.partial`，不移动清理目标。

移除项进入 `%USERPROFILE%\ClaudeCleanupTrash\批次名`，这是普通隔离目录，不是 Windows 回收站。移动使用同卷重命名，不做跨卷复制后删除。完整 Code 备份加隔离可能增加空间占用，不能报告“释放了同等大小的空间”。

备份中的 `moves.json` 记录每项原路径、隔离路径及 `planned`/`moved` 状态。中途失败时已成功移动的项留在隔离目录，不自动回滚、不继续后续操作。报告备份位置和错误；如果日志更新本身失败，状态可能停留在 `planned`，应只读核实源和目标是否存在。

恢复时：

1. 正常退出 Claude；根据 `moves.json` 核对要恢复的原路径与隔离路径。
2. 原路径不存在时，将对应隔离项移回。原路径已重建时保留两份，先比较，不覆盖当前数据。
3. 若要撤销身份或精简模式修改，分别从 `claude.json`、`dot-claude\settings.json` 和 `dot-claude\backups` 恢复对应文件；先核对新旧内容，不把整个 `.claude` 覆盖回去。

退出码：`0` 完成审计、完成清理或无操作；`1` 最终确认取消；`2` 检查失败、执行失败或中断。必须结合输出判断是否执行过操作。
