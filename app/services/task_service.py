"""
Asyncio-based task lifecycle service for Ghost Downloader 3.

Manages task lifecycle (store, queue, concurrency control, event dispatch)
with callback-based signalling in place of Qt signals and timers.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from loguru import logger

from app.config.cfg import cfg
from app.config.paths import APP_DATA_DIR

if TYPE_CHECKING:
    from app.models.task import Task


# ---------------------------------------------------------------------------
# Event bus — lightweight signal replacement
# ---------------------------------------------------------------------------

class TaskEventBus:
    """Stand-in for Qt signals.  Subscribe with ``on()``, fire with ``emit()``."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event: str, handler: Callable):
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable | None = None):
        if handler is None:
            self._handlers.pop(event, None)
        else:
            handlers = self._handlers.get(event, [])
            self._handlers[event] = [h for h in handlers if h is not handler]

    def emit(self, event: str, *args, **kwargs):
        for handler in self._handlers.get(event, []):
            try:
                handler(*args, **kwargs)
            except Exception as e:
                logger.opt(exception=e).error("event handler failed for {}", event)


# ---------------------------------------------------------------------------
# Task store (unchanged from original, minus Qt paths)
# ---------------------------------------------------------------------------

class TaskStore:
    """Persists tasks to a JSONL file."""

    def __init__(self, data_dir: str = APP_DATA_DIR):
        self._tasks: dict[str, Task] = {}
        self._loaded = False
        self._path = Path(data_dir) / "tasks.jsonl"

    # ── Dict interface ────────────────────────────────────────────

    def add(self, task: Task) -> None:
        self._tasks[task.taskId] = task

    def remove(self, task_id: str) -> Task | None:
        return self._tasks.pop(task_id, None)

    def task_by_id(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    @property
    def tasks(self) -> dict[str, Task]:
        return self._tasks

    @property
    def task_list(self) -> list[Task]:
        return list(self._tasks.values())

    # ── Persistence ───────────────────────────────────────────────

    def flush(self) -> None:
        if not self._loaded:
            return
        lines: list[str] = []
        for task in self._tasks.values():
            try:
                lines.append(json.dumps(task.toDict(), ensure_ascii=False) + "\n")
            except Exception as e:
                logger.opt(exception=e).error("failed to serialize task {}", task.taskId)

        temp_file = self._path.with_name(self._path.name + ".tmp")
        try:
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_file, "w", encoding="utf-8") as f:
                f.writelines(lines)
            temp_file.replace(self._path)
        except Exception as e:
            logger.opt(exception=e).error("failed to write tasks.jsonl")

    def load_saved(self) -> list[Task]:
        from app.models.task import Task

        tasks: list[Task] = []
        if not self._path.exists():
            self._loaded = True
            return tasks

        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    task = Task.fromDict(json.loads(line))
                    self._tasks[task.taskId] = task
                    tasks.append(task)
                except Exception as e:
                    logger.opt(exception=e).error("failed to parse task record")

        self._loaded = True
        return tasks


# ---------------------------------------------------------------------------
# Task queue (pure Python, unchanged logic)
# ---------------------------------------------------------------------------

class TaskQueue:
    """Manages waiting and running task IDs."""

    def __init__(self):
        self._waiting: list[str] = []
        self._running: dict[str, str] = {}

    def wait(self, task_id: str) -> None:
        if task_id not in self._waiting:
            self._waiting.append(task_id)

    def cancel(self, task_id: str) -> None:
        if task_id in self._waiting:
            self._waiting.remove(task_id)
        self._running.pop(task_id, None)

    def run(self, task_id: str, work_id: str) -> None:
        self._running[task_id] = work_id

    def done(self, task_id: str) -> None:
        self._running.pop(task_id, None)

    def work_id_of(self, task_id: str) -> str | None:
        return self._running.get(task_id)

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running

    def is_waiting(self, task_id: str) -> bool:
        return task_id in self._waiting

    def running_count(self) -> int:
        return len(self._running)

    def running_ids(self) -> list[str]:
        return list(self._running)

    def next_waiting(self) -> str | None:
        return self._waiting.pop(0) if self._waiting else None


# ---------------------------------------------------------------------------
# Task service
# ---------------------------------------------------------------------------

class TaskService:
    """Central task lifecycle manager.

    Events (subscribe via ``events.on(...)``):

    - ``"task_added"``      (task)
    - ``"task_removed"``    (task_id)
    - ``"task_started"``    (task)
    - ``"task_paused"``     (task)
    - ``"task_completed"``  (task)
    - ``"task_failed"``     (task)
    - ``"all_completed"``   ()
    - ``"file_disappeared"`` (task)
    """

    def __init__(self):
        self.events = TaskEventBus()
        self._store = TaskStore()
        self._queue = TaskQueue()
        self._flush_handle: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Convenience aliases for the event bus ─────────────────────

    def on_task_added(self, handler): return self.events.on("task_added", handler)
    def on_task_removed(self, handler): return self.events.on("task_removed", handler)
    def on_task_started(self, handler): return self.events.on("task_started", handler)
    def on_task_paused(self, handler): return self.events.on("task_paused", handler)
    def on_task_completed(self, handler): return self.events.on("task_completed", handler)
    def on_task_failed(self, handler): return self.events.on("task_failed", handler)
    def on_all_completed(self, handler): return self.events.on("all_completed", handler)

    # ── Properties ────────────────────────────────────────────────

    @property
    def tasks(self) -> list[Task]:
        return self._store.task_list

    def task_by_id(self, task_id: str) -> Task | None:
        return self._store.task_by_id(task_id)

    def running_count(self) -> int:
        return self._queue.running_count()

    # ── Task lifecycle ────────────────────────────────────────────

    def add(self, task: Task) -> None:
        if task.taskId in self._store.tasks:
            return
        if cfg.isCategoryEnabled.value:
            from app.services.category_service import categoryService
            if task.category is None:
                task.category = categoryService.categoryOf(task)
            if task.category and task.outputFolder == Path(cfg.downloadFolder.value):
                folder = categoryService.folderOf(task.category)
                if folder:
                    task.outputFolder = Path(folder)
        task.deduplicateFilename()
        self._store.add(task)
        self._schedule_flush()
        self.events.emit("task_added", task)
        if task.fileSize > 0:
            from shutil import disk_usage
            try:
                free = disk_usage(task.outputFolder).free
                if free < task.fileSize:
                    self.events.emit("disk_space_insufficient", free, task.fileSize)
                    return
            except OSError:
                pass
        self._schedule(task)

    def start(self, task: Task) -> None:
        if self._queue.is_running(task.taskId) or self._queue.is_waiting(task.taskId):
            return
        self._schedule(task)

    def pause(self, task: Task) -> None:
        from app.models.task import TaskStatus
        self._cancel_run(task)
        task.setStatus(TaskStatus.PAUSED)
        self._schedule_flush()
        self.events.emit("task_paused", task)

    def delete(self, task: Task, should_delete_files: bool = False) -> None:
        self._cancel_run(task, finished=task.deleteFiles if should_delete_files else None)
        self._store.remove(task.taskId)
        self._schedule_flush()
        self.events.emit("task_removed", task.taskId)
        self._pump()

    def redownload(self, task: Task) -> None:
        def after_stopped():
            task.deleteFiles()
            task.reset()
            self._schedule_flush()
            self._schedule(task)
        self._cancel_run(task, finished=after_stopped)

    def edit(self, task: Task, options: dict, new_task: Task | None = None) -> None:
        needs_delete = new_task is not None and not task.canReuseProgress(new_task)
        def after_stopped():
            if needs_delete:
                task.deleteFiles()
            if new_task is not None:
                task.replaceWith(new_task)
            task.setOptions(options)
            self._schedule_flush()
            self._schedule(task)
        self._cancel_run(task, finished=after_stopped)

    def start_all(self) -> None:
        from app.models.task import TaskStatus
        for task in self._store.tasks.values():
            if task.status in {TaskStatus.PAUSED, TaskStatus.WAITING, TaskStatus.FAILED}:
                self._schedule(task)

    def pause_all(self) -> None:
        for task in list(self._store.tasks.values()):
            if self._queue.is_running(task.taskId) or self._queue.is_waiting(task.taskId):
                self.pause(task)

    def resume_saved(self) -> None:
        from app.models.task import TaskStatus
        for task in self._store.load_saved():
            self.events.emit("task_added", task)
            if task.status == TaskStatus.COMPLETED and task.hasOutputFile and Path(task.outputPath).exists():
                pass  # auto-reload completed tasks not supported
            elif task.status in {TaskStatus.WAITING, TaskStatus.RUNNING}:
                task.setStatus(TaskStatus.WAITING)
                self._schedule(task)

    def stop(self) -> None:
        """Pause all running/waiting tasks."""
        from app.models.task import TaskStatus
        for task in self._store.tasks.values():
            if task.status in {TaskStatus.RUNNING, TaskStatus.WAITING}:
                task.setStatus(TaskStatus.PAUSED)

    def flush(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        self._store.flush()

    # ── Internal scheduling ───────────────────────────────────────

    def _schedule(self, task: Task) -> None:
        self._queue.wait(task.taskId)
        self._pump()

    def _dispatch(self, task: Task) -> None:
        from app.models.task import TaskStatus
        from app.services.coroutine_runner import coroutineRunner

        task.setStatus(TaskStatus.RUNNING)
        work_id = coroutineRunner.submit(
            task.run(),
            done=lambda _: self._on_run_done(task),
            failed=lambda error: self._on_run_failed(task, error),
        )
        self._queue.run(task.taskId, work_id)
        self.events.emit("task_started", task)

    def _cancel_run(self, task: Task, finished: Callable = None) -> None:
        from app.services.coroutine_runner import coroutineRunner

        work_id = self._queue.work_id_of(task.taskId)
        self._queue.cancel(task.taskId)
        if work_id is not None:
            coroutineRunner.cancel(work_id, finished=finished)
        elif finished is not None:
            finished()

    def _pump(self) -> None:
        while self._queue.running_count() < cfg.maxTaskNum.value:
            task_id = self._queue.next_waiting()
            if task_id is None:
                break
            task = self._store.task_by_id(task_id)
            if task is not None:
                self._dispatch(task)

    def _rebalance(self) -> None:
        from app.models.task import TaskStatus
        for task_id in self._queue.running_ids()[cfg.maxTaskNum.value:]:
            task = self._store.task_by_id(task_id)
            if task is not None and task.canPause:
                self._cancel_run(task)
                task.setStatus(TaskStatus.WAITING)
                self._queue.wait(task_id)
        self._pump()

    def _on_run_done(self, task: Task) -> None:
        self._queue.done(task.taskId)
        self._schedule_flush()
        self.events.emit("task_completed", task)
        self._pump()
        if self._queue.running_count() == 0:
            self.events.emit("all_completed")

    def _on_run_failed(self, task: Task, error: str) -> None:
        self._queue.done(task.taskId)
        self._schedule_flush()
        self.events.emit("task_failed", task)
        self._pump()
        if self._queue.running_count() == 0:
            self.events.emit("all_completed")

    def _schedule_flush(self) -> None:
        """Debounced flush: persist after 200 ms of inactivity."""
        if self._flush_handle is not None:
            self._flush_handle.cancel()
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        self._flush_handle = loop.call_later(0.2, self._store.flush)


# Module-level singleton
taskService = TaskService()
