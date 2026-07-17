"""
Feature-pack plugin system for Ghost Downloader 3.

Defines the base classes that every protocol pack (HTTP, BitTorrent, FTP, …)
subclasses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config.cfg import cfg, ConfigItem

if TYPE_CHECKING:
    from app.models.task import Task, TaskOptions
    from typing import Any


def _translate(text: str) -> str:
    """Stand-in for ``QCoreApplication.translate`` — returns the text as-is."""
    return text


@dataclass(frozen=True)
class FileType:
    extensions: tuple[str, ...]
    displayName: str
    mimeType: str
    icon: str


class TaskParser:
    priority: int = 100

    def match(self, options: TaskOptions) -> bool:
        raise NotImplementedError

    def matchPassive(self, options: TaskOptions) -> bool:
        return self.match(options)

    async def parse(self, options: TaskOptions) -> Task:
        raise NotImplementedError


class PackConfig:
    """Pack-level configuration.

    Subclasses declare ``ConfigItem`` class attributes which are automatically
    registered on the global ``cfg`` object via ``__init_subclass__``.
    """

    _items: dict[str, ConfigItem] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for attrName, attrValue in cls.__dict__.items():
            if isinstance(attrValue, ConfigItem):
                setattr(cfg.__class__, f"pack_{cls.__name__}_{attrName}", attrValue)
                PackConfig._items[attrValue.key] = attrValue

    @classmethod
    def load(cls) -> None:
        """Load pack config values from ``cfg.file``."""
        if not cls._items:
            return
        try:
            with open(cfg._config_path(), encoding="utf-8") as f:
                import json
                data = json.load(f)
        except Exception:
            return
        for k, v in data.items():
            if not isinstance(v, dict):
                if k in cls._items:
                    cls._items[k].deserializeFrom(v)
            else:
                for name, value in v.items():
                    if (key := k + "." + name) in cls._items:
                        cls._items[key].deserializeFrom(value)

    def settingGroups(self, parent: Any = None) -> list:
        return []

    def isFileAssociationEnabled(self) -> bool:
        return True

    def fileAssociationToggle(self):
        return None

    def tr(self, text: str) -> str:
        return _translate(text)


class BinaryRuntime:
    """Represents an external binary (e.g. ffmpeg, yt-dlp) needed by a pack."""

    name: str = ""
    canInstall: bool = False
    title: str = ""
    description: str = ""
    icon: str = ""
    isRecommended: bool = False

    @property
    def runtimeId(self) -> str:
        cls = type(self)
        return f"{cls.__module__}.{cls.__qualname__}"

    def path(self) -> str:
        raise NotImplementedError

    async def probeVersion(self) -> str:
        path = self.path()
        if not path:
            return ""
        process = await asyncio.create_subprocess_exec(
            path, "--version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return ""
        lines = stdout.decode("utf-8", errors="ignore").splitlines()
        return lines[0].strip() if lines else ""

    async def installTask(self) -> Task:
        raise NotImplementedError


class PackPage:
    """A page contributed by a pack (used in the original GUI)."""
    icon: ...
    title: str = ""


class FeaturePack:
    """Base class for every protocol pack.

    Subclasses override hooks to contribute parsers, runtimes, and file types.
    UI-related hooks (``taskCard``, ``optionCards``, …) default to no-ops.
    """

    packId: str = ""
    config: PackConfig | None = None
    proxySchemes: set[str] | None = None

    def parsers(self) -> list[TaskParser]:
        return []

    def taskCard(self, task: Task, parent=None):
        return None

    def draftCard(self, task: Task, parent=None):
        return None

    def optionCards(self, task: Task, parent=None):
        return []

    def editCards(self, task: Task, parent=None):
        return self.optionCards(task, parent)

    def runtimes(self) -> list[BinaryRuntime]:
        return []

    def fileTypes(self) -> list[FileType]:
        return []

    def pages(self) -> list[type[PackPage]]:
        return []

    def start(self):
        pass

    def stop(self):
        pass

    def tr(self, text: str) -> str:
        return _translate(text)
