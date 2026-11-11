#!/usr/bin/env python3
"""Windows Claude cleanup: audit first, verified backups, reversible quarantine."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass

# An audit must not create __pycache__ beside the bundled helpers.
sys.dont_write_bytecode = True
import claude_cleanup as common

DESKTOP_CACHE = ("Cache", "Code Cache", "GPUCache", "DawnCache", "logs", "Crashpad")
DESKTOP_SESSION = (
    "Cookies", "Cookies-journal", "Network/Cookies", "Network/Cookies-journal",
    "Local Storage", "Session Storage", "IndexedDB", "WebStorage", "Service Worker",
)
CONFIG_OVERRIDES = ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR")


def exists(path: pathlib.Path) -> bool:
    # Unlike Path.exists(), do not silently ignore dangling links or access errors.
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def check_path(path: pathlib.Path) -> pathlib.Path:
    """Reject link/junction ancestors before resolving or traversing a path."""
    if not path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"路径必须是无 .. 的绝对路径：{path}")
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RuntimeError(f"拒绝符号链接、junction 或其他 reparse point：{part}")
    return path.resolve()


@dataclass(frozen=True)
class Layout:
    home: pathlib.Path
    roaming: pathlib.Path
    local: pathlib.Path

    @classmethod
    def from_environment(cls) -> Layout:
        home = pathlib.Path.home()
        roaming = pathlib.Path(os.environ.get("APPDATA", str(home / "AppData/Roaming")))
        local = pathlib.Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
        for root in (home, roaming, local):
            check_path(root)
        for root in (roaming, local):
            if root == home or not root.is_relative_to(home):
                raise RuntimeError(f"暂不支持用户目录外的 AppData：{root}")
        return cls(home, roaming, local)

    @property
    def claude(self) -> pathlib.Path:
        return self.home / ".claude"

    @property
    def identity(self) -> pathlib.Path:
        return self.home / ".claude.json"

    @property
    def settings(self) -> pathlib.Path:
        return self.claude / "settings.json"

    def desktop_roots(self) -> list[pathlib.Path]:
        roots = [self.roaming / "Claude"]
        packages = self.local / "Packages"
        check_path(packages)
        if exists(packages):
            for package in sorted(packages.glob("Claude_*")):
                # Only the exact Electron data subdirectory, never the package itself.
                roots.append(package / "LocalCache/Roaming/Claude")
        return roots

    def candidates(self) -> tuple[set[pathlib.Path], set[pathlib.Path]]:
        safe = {self.claude / name for name in common.CLI_CACHE}
        safe.add(self.local / "claude-cli-nodejs")
        sessions: set[pathlib.Path] = set()
        for root in self.desktop_roots():
            check_path(root)
            safe.update(root / name for name in DESKTOP_CACHE)
            sessions.update(root / name for name in DESKTOP_SESSION)
        return safe, sessions


def discover(layout: Layout) -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    safe, sessions = layout.candidates()
    return tuple(sorted((p for p in paths if exists(p)), key=str) for paths in (safe, sessions))


def snapshot(root: pathlib.Path, *, reject_git: bool = False) -> dict:
    """Hash regular files without following any reparse points; include empty dirs."""
    check_path(root)
    if not exists(root):
        return {}
    result = {}
    pending = [root]
    while pending:
        path = pending.pop()
        check_path(path)
        if reject_git and path.name.lower() == ".git":
            raise RuntimeError(f"清理目标包含 Git 仓库：{path}")
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):
            result[relative] = {"type": "directory"}
            pending.extend(path.iterdir())
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[relative] = {"type": "file", "bytes": info.st_size, "sha256": digest.hexdigest()}
        else:
            raise RuntimeError(f"不支持的文件类型：{path}")
    return result


def validate_target(target: pathlib.Path, layout: Layout, *, credentials: bool = False) -> None:
    resolved = check_path(target)
    safe, sessions = layout.candidates()
    allowed = safe | sessions
    if credentials:
        allowed.add(layout.claude / ".credentials.json")
    if target not in allowed or resolved != target:
        raise RuntimeError(f"目标不在 Windows 清理白名单：{target}")
    for protected in (layout.claude, *(layout.claude / name for name in common.PROTECTED)):
        # The config root contains allowed children; it may never itself be moved.
        if target == protected or protected.is_relative_to(target):
            raise RuntimeError(f"目标包含保护路径：{target}")
        if protected != layout.claude and target.is_relative_to(protected):
            raise RuntimeError(f"目标位于保护路径内：{target}")
    for ancestor in target.parents:
        if exists(ancestor / ".git"):
            raise RuntimeError(f"目标位于 Git 仓库中：{target}")
        if ancestor == layout.home:
            break
    snapshot(target, reject_git=True)


def process_table() -> list[dict]:
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
        "@(Get-CimInstance Win32_Process -ErrorAction Stop | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, encoding="utf-8-sig", check=True, timeout=30,
    )
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data or any(
        not isinstance(item, dict) or not isinstance(item.get("ProcessId"), int)
        or not isinstance(item.get("ParentProcessId"), int) or not isinstance(item.get("Name"), str)
        for item in data
    ):
        raise RuntimeError("无法可靠读取 Windows 进程列表，停止操作")
    return data


def is_claude_process(process: dict) -> bool:
    name = process["Name"].lower().removesuffix(".exe")
    if name in {"claude", "claude-code", "claude-desktop"} or name.startswith("claude helper"):
        return True
    command = (process.get("CommandLine") or "").replace("\\", "/").lower()
    return name in {"node", "bun"} and bool(
        re.search(r"(?:@anthropic-ai/claude-code/|/claude-code/cli\.js(?:[\s\"]|$))", command)
    )


def under_claude(table: list[dict]) -> bool:
    if os.environ.get("CLAUDECODE"):
        return True
    by_pid = {item["ProcessId"]: item for item in table}
    pid, seen = os.getppid(), set()
    while pid in by_pid and pid not in seen:
        seen.add(pid)
        process = by_pid[pid]
        if is_claude_process(process):
            return True
        pid = process["ParentProcessId"]
    return False


def require_stopped() -> None:
    if any(is_claude_process(p) for p in process_table()):
        raise RuntimeError("仍有或重新出现 Claude 进程，请正常退出后重新运行")


def create_backup(layout: Layout) -> pathlib.Path:
    sources = {"dot-claude": layout.claude, "claude.json": layout.identity}
    before = {name: snapshot(path) for name, path in sources.items()}
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    partial = layout.home / "ClaudeBackups" / f"claude-cleanup-windows-{stamp}.partial"
    check_path(partial)
    partial.mkdir(parents=True)  # First filesystem mutation in a cleanup run.
    try:
        for name, source in sources.items():
            if not before[name]:
                continue
            destination = partial / name
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
            else:
                shutil.copy2(source, destination)
            if snapshot(destination) != before[name] or snapshot(source) != before[name]:
                raise RuntimeError("备份内容校验失败")
        # Also catch a previously absent source appearing during the copy.
        if any(snapshot(path) != before[name] for name, path in sources.items()):
            raise RuntimeError("备份期间源数据改变")
        common.write_json(partial / "manifest.json", {"platform": "windows", "sources": before})
        final = partial.with_suffix("")
        partial.rename(final)
        return final
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as error:
        raise RuntimeError(f"备份未完成，未清理；保留未完成副本：{partial}；{error}") from error


def quarantine(target: pathlib.Path, layout: Layout, batch: pathlib.Path, index: int, *, credentials: bool) -> pathlib.Path:
    validate_target(target, layout, credentials=credentials)
    quarantine_root = check_path(layout.home / "ClaudeCleanupTrash")
    resolved_batch = check_path(batch)
    if resolved_batch.parent != quarantine_root:
        raise RuntimeError(f"隔离目录越界：{batch}")
    if not exists(target):
        raise RuntimeError(f"确认后的目标已消失：{target}")
    destination = batch / f"{index:03d}-{target.name}"
    check_path(destination)
    if exists(destination):
        raise FileExistsError(f"拒绝覆盖隔离文件：{destination}")
    batch.mkdir(parents=True, exist_ok=True)
    # Never fall back to a recursive copy/delete across volumes.
    target.rename(destination)
    return destination


def verify_preserved(layout: Layout, backup: pathlib.Path, changed: list[pathlib.Path]) -> None:
    before = common.read_json(backup / "manifest.json")["sources"]["dot-claude"]
    after = snapshot(layout.claude)
    prefixes = [p.relative_to(layout.claude).as_posix() for p in changed if p.is_relative_to(layout.claude)]

    def kept(entries):
        return {key: value for key, value in entries.items() if not any(
            key == prefix or key.startswith(prefix + "/") for prefix in prefixes
        )}

    # Enabling simple mode can create an otherwise absent config root.
    if not before and changed:
        after.pop(".", None)
    if kept(before) != kept(after):
        raise RuntimeError("未选择修改的 Claude Code 数据发生变化，请检查备份和隔离清单")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows Claude 只读审计与可恢复清理（Python 3.10+）")
    parser.add_argument("--audit", action="store_true", help="仅列出状态和完整路径，不写盘")
    args = parser.parse_args(argv)
    backup = None
    try:
        if sys.platform != "win32":
            raise RuntimeError("此入口仅支持原生 Windows；macOS 请使用 claude_cleanup.py，WSL 不在清理范围内")
        layout = Layout.from_environment()
        for path in (layout.claude, layout.identity, layout.settings):
            check_path(path)
        env = common.settings_env(common.read_json(layout.settings, {}))
        overrides = [key for key in CONFIG_OVERRIDES if os.environ.get(key) or env.get(key)]
        safe, sessions = discover(layout)
        table = process_table()
        processes = [p for p in table if is_claude_process(p)]
        print("Windows Claude Cleanup：最终 CONFIRM 前不写盘；移除项进入可恢复隔离目录。")
        print(f"配置：{layout.claude}（{'存在' if exists(layout.claude) else '不存在'}）")
        print(f"身份：{layout.identity}（{'存在' if exists(layout.identity) else '不存在'}）")
        for label, paths in (("缓存/日志", safe), ("可选 Desktop 登录态", sessions)):
            print(f"{label}：{len(paths)} 项")
            for path in paths:
                print(f"  - {path}")
        print(f"相关进程：{len(processes)} 个（不会自动结束进程）")
        for process in processes:
            print(f"  - PID {process['ProcessId']} {process['Name']}")
        print("遥测：逐值保留；精简模式：" + ("已设置" if "CLAUDE_CODE_SIMPLE" in env else "未设置"))
        if overrides:
            print("检测到自定义配置目录，仅审计默认路径，禁止清理：" + ", ".join(overrides))
        if args.audit:
            return 0
        if overrides:
            raise RuntimeError("暂不支持自定义配置/凭据目录；不要取消该变量后清理其他配置")
        if under_claude(table):
            raise RuntimeError("由 Claude 启动时只允许 --audit，请改用独立的 PowerShell 或 Codex 终端")
        if not sys.stdin.isatty():
            raise RuntimeError("需要真实交互终端，不能使用管道代答或跳过 CONFIRM")

        rotate = common.ask_yes("轮换本地 userID/machineID，并清除已知账号缓存字段？")
        credentials = common.ask_yes("移走 .claude\\.credentials.json（会退出使用该文件的 CLI 登录）？")
        desktop = common.ask_yes("重置 Desktop 的白名单登录态/浏览器存储（可能丢失未同步内容）？")
        simple = common.ask_choice("精简模式：0 保持；1 启用；2 移除。选择 [0]：", {0, 1, 2})
        if processes:
            if rotate or credentials or desktop or simple:
                input("请正常退出所有 Claude Code / Desktop，退出后按 Enter 复检：")
                require_stopped()
            else:
                print("Claude 正在运行，已跳过缓存/日志；没有写盘。")
                return 0
        safe, sessions = discover(layout)
        targets = safe + (sessions if desktop else [])
        credential_path = layout.claude / ".credentials.json"
        if credentials and exists(credential_path):
            targets.append(credential_path)
        targets = sorted(set(targets), key=str)
        identity_files = [layout.identity] if rotate else []
        if rotate:
            if not layout.identity.is_file():
                raise FileNotFoundError(".claude.json 不存在，无法轮换本地 ID")
            check_path(layout.claude / "backups")
            identity_files += sorted((layout.claude / "backups").glob(".claude.json.backup.*"))
            for path in identity_files:
                check_path(path)
                if not path.is_file() or not isinstance(common.read_json(path), dict):
                    raise ValueError(f"身份文件不是普通 JSON object：{path}")
        for target in targets:
            validate_target(target, layout, credentials=credentials)
        # Validate the full backup tree and output paths before offering confirmation.
        snapshot(layout.claude)
        snapshot(layout.identity)
        check_path(layout.home / "ClaudeBackups")
        check_path(layout.home / "ClaudeCleanupTrash")
        if not targets and not rotate and not simple:
            print("没有可执行的清理项，没有写盘。")
            return 0
        print("\n最终执行清单：先完整复制 .claude 和 .claude.json（存在者），逐文件 SHA-256 校验。")
        print(f"备份根目录：{layout.home / 'ClaudeBackups'}")
        print(f"隔离根目录：{layout.home / 'ClaudeCleanupTrash'}（普通目录，不是 Windows 回收站）")
        for target in targets:
            print(f"  移入隔离：{target}")
        for path in identity_files:
            print(f"  轮换身份：{path}")
        if simple:
            print(f"  精简模式：{('保持', '启用', '移除')[simple]}；{layout.settings}")
        print("保留会话、项目、skills、plugins、hooks、MCP 配置和扩展；遥测键逐值保持不变。")
        if input("确认以上范围后输入 CONFIRM 开始；其他输入取消：").strip() != "CONFIRM":
            print("已取消，没有写盘。")
            return 1
        require_stopped()
        before_telemetry = common.telemetry(common.read_json(layout.settings, {}))
        backup = create_backup(layout)
        print(f"已完成并校验备份：{backup}")
        batch = layout.home / "ClaudeCleanupTrash" / backup.name
        moves = [{"source": str(p), "destination": str(batch / f"{i:03d}-{p.name}"), "status": "planned"}
                 for i, p in enumerate(targets)]
        common.write_json(backup / "moves.json", moves)
        require_stopped()
        for i, target in enumerate(targets):
            require_stopped()
            quarantine(target, layout, batch, i, credentials=credentials)
            moves[i]["status"] = "moved"
            common.write_json(backup / "moves.json", moves)
        changed = list(targets)
        if rotate:
            require_stopped()
            actual_files = [layout.identity, *sorted((layout.claude / "backups").glob(".claude.json.backup.*"))]
            if actual_files != identity_files:
                raise RuntimeError("确认后的身份文件清单发生变化，请重新审计")
            for path in identity_files:
                check_path(path)
            common.rotate_identity(layout.home)
            changed.extend(identity_files)
        if simple:
            require_stopped()
            check_path(layout.settings)
            common.update_simple(layout.home, simple)
            changed.append(layout.settings)
        if common.telemetry(common.read_json(layout.settings, {})) != before_telemetry:
            raise RuntimeError("遥测设置发生变化，停止操作")
        verify_preserved(layout, backup, changed)
        print(f"完成：隔离 {len(targets)} 项；身份轮换：{rotate}；精简模式：{simple}；遥测状态未变。")
        print(f"备份：{backup}\n恢复清单：{backup / 'moves.json'}")
        if targets:
            print(f"隔离批次：{batch}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, EOFError, KeyboardInterrupt) as error:
        state = f"已停止，可能部分完成；备份：{backup}" if backup else "已停止，未执行清理"
        print(f"{state}：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
