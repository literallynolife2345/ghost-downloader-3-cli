"""
Feature-pack service for Ghost Downloader 3.

Manages feature pack lifecycle (load, start, stop) and URL parsing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.config.paths import executableDir
from app.services.pack_loader import loadPacks

if TYPE_CHECKING:
    from app.models.pack import FeaturePack, TaskParser, FileType, PackPage
    from app.models.task import Task, TaskOptions


class FeatureService:
    """Discovers, loads, and manages feature packs.

    The core responsibility is matching URLs to the right pack parser and
    producing ``Task`` objects.
    """

    def __init__(self):
        self._packs: list[FeaturePack] = []
        self._parsers: list[TaskParser] = []
        self._pack_by_pack_id: dict[str, FeaturePack] = {}

    # ── Properties ────────────────────────────────────────────────

    @property
    def packs(self) -> list[FeaturePack]:
        return list(self._packs)

    @property
    def parsers(self) -> list[TaskParser]:
        return list(self._parsers)

    # ── Lifecycle ─────────────────────────────────────────────────

    def load(self) -> None:
        """Load all feature packs from the ``features/`` directory."""
        features_dir = executableDir / "features"
        for pack in loadPacks(features_dir):
            self._register(pack)

    def start(self) -> None:
        """Call ``start()`` on every loaded pack."""
        for pack in self._packs:
            try:
                pack.start()
            except Exception as e:
                from loguru import logger
                logger.opt(exception=e).warning("pack {}.start() failed", pack.packId)

    def stop(self) -> None:
        """Call ``stop()`` on every loaded pack."""
        for pack in self._packs:
            try:
                pack.stop()
            except Exception as e:
                from loguru import logger
                logger.opt(exception=e).warning("pack {}.stop() failed", pack.packId)

    # ── Registration ──────────────────────────────────────────────

    def _register(self, pack: FeaturePack) -> None:
        self._packs.append(pack)
        self._pack_by_pack_id[pack.packId] = pack
        for parser in pack.parsers():
            if hasattr(parser, 'priority'):
                self._parsers.append(parser)
        self._parsers.sort(key=lambda p: getattr(p, 'priority', 100))

    # ── Task parsing ───────────────────────────────────────────────

    async def parse(self, options: TaskOptions) -> Task:
        """Find the first parser that matches *options* and produce a ``Task``."""
        # Apply identity presets based on URL host
        if not options.clientProfile:
            from app.client import matchIdentityPreset
            host = urlparse(options.url).hostname or ""
            preset = matchIdentityPreset(host)
            if preset is not None:
                kwargs = {}
                if preset.get("clientProfile"):
                    kwargs["clientProfile"] = preset["clientProfile"]
                if preset.get("userAgent"):
                    kwargs["userAgent"] = preset["userAgent"]
                if kwargs:
                    options = replace(options, **kwargs)

        for parser in self._parsers:
            if parser.match(options):
                task = await parser.parse(options)
                if not task.category:
                    from app.services.category_service import categoryService
                    task.category = categoryService.categoryOf(task)
                return task
        raise ValueError(f"No parser matched: {options.url}")

    def match_passive(self, url: str) -> bool:
        """Check if any parser *passively* matches *url* (for clipboard etc.)."""
        from app.models.task import TaskOptions
        options = TaskOptions(url=url)
        return any(parser.matchPassive(options) for parser in self._parsers)

    # ── Runtimes & file types ───────────────────────────────────────

    def runtimes(self):
        from app.models.pack import BinaryRuntime
        result: list[BinaryRuntime] = []
        for pack in self._packs:
            result.extend(pack.runtimes())
        return result

    def file_types(self) -> list[FileType]:
        types: list[FileType] = []
        for pack in self._packs:
            types.extend(pack.fileTypes())
        return types


# Module-level singleton
featureService = FeatureService()
