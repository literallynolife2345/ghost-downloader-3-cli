"""
gd3 — Ghost Downloader 3 CLI

Usage::

    gd3 download <url> [options]
    gd3 list-packs
    gd3 config [key] [value]
    gd3 --help
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _install_stubs():
    """Register Qt-compatible modules before engine imports."""
    from gd3._qt_stubs import install_stubs
    install_stubs()


_install_stubs()  # must run before app.* imports

from app.config.cfg import cfg, ConfigItem
from app.config.paths import APP_DATA_DIR
from app.models.task import Task, TaskOptions, TaskStatus
from app.services.coroutine_runner import coroutineRunner
from app.services.speed_meter import speedMeter
from app.services.task_service import taskService
from app.services.feature_service import featureService




# ── Progress display ──────────────────────────────────────────────────

class _ProgressDisplay:
    """Terminal progress display for active downloads."""

    def __init__(self):
        self._tasks: dict[str, tuple[str, float, int, str]] = {}  # taskId -> (name, progress, speed, status)

    def attach(self):
        taskService.on_task_added(self._on_added)
        taskService.on_task_started(self._on_updated)
        taskService.on_task_completed(self._on_done)
        taskService.on_task_failed(self._on_failed)

    def _on_added(self, task):
        self._tasks[task.taskId] = (task.name, 0.0, 0, "WAITING")

    def _on_updated(self, task):
        self._tasks[task.taskId] = (task.name, task.progress, task.speed, "RUNNING")

    def _on_done(self, task):
        self._tasks[task.taskId] = (task.name, 100.0, 0, "COMPLETED")
        self._print_line(task)

    def _on_failed(self, task):
        self._tasks[task.taskId] = (task.name, 0.0, 0, "FAILED")
        self._print_line(task)

    @staticmethod
    def _print_line(task):
        status = task.status.name if hasattr(task.status, 'name') else "?"
        pct = min(task.progress, 100.0) if task.progress else 0
        speed = _format_speed(task.speed) if hasattr(task, 'speed') and task.speed else ""
        print(f"  [{status:>8}] {task.name}  {pct:.1f}%  {speed}")


def _format_speed(bps: int) -> str:
    if bps < 1024:
        return f"{bps} B/s"
    elif bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps / 1024 / 1024:.1f} MB/s"


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ── Engine bootstrap ──────────────────────────────────────────────────

def _init_engine() -> None:
    """Load config and discover feature packs.

    Background services (coroutine runner, speed meter, pack start)
    are started later inside the event loop via ``_start_async_services()``.
    """
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="CRITICAL", format="<level>{level:>8}</level> {message}")

    # Ensure UTF-8 output on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cfg.load()
    featureService.load()


def _start_async_services():
    """Start background services that need a running event loop."""
    coroutineRunner.start()
    speedMeter.start()
    featureService.start()


def _stop_async_services():
    """Stop background services started by ``_start_async_services``."""
    speedMeter.stop()
    taskService.stop()
    coroutineRunner.stop()
    featureService.stop()


def _shutdown_engine() -> None:
    """Sync-only shutdown — saves config."""
    cfg.save()


def _run(coro):
    """Run an async command inside a temporary event loop."""
    async def _wrapper():
        _start_async_services()
        try:
            return await coro
        finally:
            _stop_async_services()
    return asyncio.run(_wrapper())


# ── Commands ──────────────────────────────────────────────────────────

async def _download_url(args: argparse.Namespace) -> int:
    """Parse a URL, create a download task, and run it (optionally waiting)."""
    url = args.url
    output_dir = Path(args.output or cfg.downloadFolder.value)
    output_dir.mkdir(parents=True, exist_ok=True)

    options = TaskOptions(
        url=url,
        outputFolder=str(output_dir),
        clientProfile=args.client_profile or cfg.clientProfile.value,
        headers=dict(cfg.defaultRequestHeaders.value),
    )

    print(f"Parsing: {url}")
    try:
        task = await featureService.parse(options)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if args.name:
        task.name = args.name

    task.outputFolder = output_dir
    print(f"  Name:     {task.name}")
    print(f"  Size:     {_format_size(task.fileSize) if task.fileSize > 0 else 'unknown'}")
    print(f"  Pack:     {task.packId}")
    print(f"  Output:   {output_dir / task.name}")
    print()

    if args.dry_run:
        print("[dry-run] would download")
        return 0

    taskService.add(task)

    if args.wait:
        # Wait synchronously
        done_event = asyncio.Event()
        taskService.on_task_completed(lambda t: done_event.set() if t.taskId == task.taskId else None)
        taskService.on_task_failed(lambda t: done_event.set() if t.taskId == task.taskId else None)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=args.timeout if args.timeout > 0 else None)
        except asyncio.TimeoutError:
            print(f"  Timed out after {args.timeout}s")
            return 2
        except KeyboardInterrupt:
            print("\n  Interrupted")
            taskService.pause(task)
            return 130

        # Print final status
        status = task.status
        if status == TaskStatus.COMPLETED:
            print(f"  [OK] Completed — {_format_size(task.fileSize)} at {task.outputPath}")
            return 0
        else:
            err = task.lastError
            msg = err.message if err else "unknown error"
            print(f"  [FAIL] Failed: {msg}")
            return 3

    return 0


async def _batch_download(args: argparse.Namespace) -> int:
    """Download multiple URLs from a file."""
    url_file = Path(args.file)
    if not url_file.exists():
        print(f"Error: file not found: {args.file}")
        return 1

    urls = url_file.read_text(encoding="utf-8").strip().splitlines()
    urls = [u.strip() for u in urls if u.strip() and not u.startswith("#")]
    print(f"Loaded {len(urls)} URLs from {args.file}")

    exit_code = 0
    for i, url in enumerate(urls):
        print(f"\n[{i + 1}/{len(urls)}] {url}")
        sub_args = argparse.Namespace(
            url=url,
            output=args.output,
            name=None,
            client_profile=args.client_profile or "auto",
            dry_run=args.dry_run,
            wait=True,
            timeout=0,
        )
        code = await _download_url(sub_args)
        if code != 0:
            exit_code = code
    return exit_code


def _list_packs(args: argparse.Namespace) -> None:
    """List all loaded feature packs and their parsers."""
    print(f"Feature packs ({len(featureService.packs)}):")
    for pack in featureService.packs:
        parsers = pack.parsers()
        print(f"  {pack.packId} ({len(parsers)} parsers)")
        for parser in parsers:
            prio = getattr(parser, "priority", 100)
            print(f"    L priority {prio}: {type(parser).__name__}")
    print()
    runtimes = featureService.runtimes()
    if runtimes:
        print("Runtimes:")
        for rt in runtimes:
            print(f"  {rt.runtimeId}: {rt.name or rt.__class__.__name__}")


def _show_config(args: argparse.Namespace) -> None:
    """Show or set configuration values."""
    items = {k: v for k, v in cfg.__dict__.items() if isinstance(v, ConfigItem)}

    if args.key:
        key = args.key
        if args.value is not None:
            # Set a value
            for name, item in items.items():
                if name == key or item.key == key or f"{item.group}.{item.name}" == key:
                    item.value = args.value
                    cfg.save()
                    print(f"  {key} = {item.value}")
                    return
            print(f"Error: unknown config key: {key}")
            print(f"Available keys: {', '.join(sorted(items.keys()))}")
            return

        # Show a single value
        for name, item in items.items():
            if name == key or item.key == key or f"{item.group}.{item.name}" == key:
                print(f"{item.key} = {item.value}")
                return
        print(f"Error: unknown config key: {key}")
        return

    # Show all
    print("Configuration:")
    for name, item in sorted(items.items(), key=lambda x: x[1].key if hasattr(x[1], 'key') else x[0]):
        print(f"  {item.key} = {item.value}")


def _info(args: argparse.Namespace) -> None:
    """Print engine version and status info."""
    from app.config.constants import VERSION

    print(f"Ghost Downloader 3 CLI (gd3)")
    print(f"  Engine version: {VERSION}")
    print(f"  Config dir:     {cfg._config_path()}")
    print(f"  Data dir:       {APP_DATA_DIR}")
    print(f"  Feature packs:  {len(featureService.packs)} loaded")

    runtimes = featureService.runtimes()
    if runtimes:
        print(f"  Runtimes:       {len(runtimes)} registered")
        for rt in runtimes:
            probe_ok = ""
            path = rt.path()
            if path:
                probe_ok = " [ok]" if rt.path() else " [missing]"
            print(f"    {rt.runtimeId}: {path or 'not found'}{probe_ok}")


# ── Main entry point ──────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """Parse arguments, initialise the engine, and dispatch."""
    # Load packs before argument parsing so --help lists available protocols
    _init_engine()

    parser = argparse.ArgumentParser(
        prog="gd3",
        description="Ghost Downloader 3 CLI — multi-protocol downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Protocols: HTTP(S), FTP, BitTorrent/Magnet, M3U8/HLS, eD2k,
           YouTube (yt-dlp), Bilibili, GitHub Releases, HuggingFace

Examples:
  gd3 download https://example.com/video.mp4
  gd3 download https://youtube.com/watch?v=... -o ./videos
  gd3 download 'magnet:?xt=urn:btih:...' --wait
  gd3 batch urls.txt
  gd3 config downloadFolder ~/Downloads
  gd3 list-packs
""",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # download
    dl = sub.add_parser("download", aliases=["dl"], help="Download a single URL")
    dl.add_argument("url", help="URL to download")
    dl.add_argument("-o", "--output", help="Output directory (default: config downloadFolder)")
    dl.add_argument("-n", "--name", help="Override filename")
    dl.add_argument("-p", "--client-profile", help="Browser fingerprint profile (auto, chrome, etc.)")
    dl.add_argument("--wait", action="store_true", help="Wait for download to finish")
    dl.add_argument("--timeout", type=int, default=0, help="Max wait time in seconds (0 = unlimited)")
    dl.add_argument("--dry-run", action="store_true", help="Parse but don't download")
    dl.set_defaults(func=lambda a: _run(_download_url(a)))

    # batch
    batch = sub.add_parser("batch", aliases=["b"], help="Download URLs from a file")
    batch.add_argument("file", help="File containing URLs (one per line)")
    batch.add_argument("-o", "--output", help="Output directory")
    batch.add_argument("-p", "--client-profile", help="Browser fingerprint profile")
    batch.add_argument("--dry-run", action="store_true", help="Parse but don't download")
    batch.set_defaults(func=lambda a: _run(_batch_download(a)))

    # list-packs
    sub.add_parser("list-packs", aliases=["lp"], help="List loaded feature packs").set_defaults(func=_list_packs)

    # info
    sub.add_parser("info", aliases=["i"], help="Engine version and status").set_defaults(func=_info)

    # config
    cfg_cmd = sub.add_parser("config", aliases=["c"], help="Show or set configuration")
    cfg_cmd.add_argument("key", nargs="?", help="Config key to show/set")
    cfg_cmd.add_argument("value", nargs="?", help="Value to set")
    cfg_cmd.set_defaults(func=_show_config)

    # Parse
    args = parser.parse_args(argv)

    try:
        exit_code = args.func(args)
        if isinstance(exit_code, int):
            return exit_code
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    finally:
        _shutdown_engine()


if __name__ == "__main__":
    sys.exit(main())
