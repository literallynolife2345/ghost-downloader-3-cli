"""
JSON-backed configuration system for Ghost Downloader 3.
"""

from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from enum import Enum
from re import compile as _compile
from urllib.request import getproxies


# Default headers used by the download engine
BASE_HEADERS = {
    "accept-encoding": "deflate, br, gzip",
    "accept-language": "zh-CN,zh;q=0.9",
    "cookie": "down_ip=1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}


# ---------------------------------------------------------------------------
# Lightweight config item
# ---------------------------------------------------------------------------

class ConfigItem:
    """A named config value with a default, validator, and optional serializer.

    The ``value`` property auto-corrects on set via the validator.
    """

    def __init__(
        self,
        group: str,
        name: str,
        default,
        validator=None,
        serializer=None,
        restart: bool = False,
    ):
        self.group = group
        self.name = name
        self.key = f"{group}.{name}"
        self._default = default
        self._value = default
        self.validator = validator
        self.serializer = serializer
        self.restart = restart

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if self.validator is not None and not self.validator.validate(v):
            v = self.validator.correct(v)
        self._value = v

    def deserializeFrom(self, v):
        """Deserialize a raw value from JSON config storage."""
        if self.serializer is not None:
            self._value = self.serializer.deserialize(v)
        else:
            self._value = v

    def serialize(self):
        if self.serializer is not None:
            return self.serializer.serialize(self._value)
        if isinstance(self._value, Enum):
            return self._value.value
        return self._value


class OptionsConfigItem(ConfigItem):
    """Config item restricted to a set of allowed values."""
    pass


class RangeConfigItem(ConfigItem):
    """Config item restricted to an integer range."""
    pass


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

class BoolValidator:
    def validate(self, value) -> bool:
        return isinstance(value, bool)

    def correct(self, value) -> bool:
        return bool(value) if isinstance(value, (bool, int)) else False


class RangeValidator:
    def __init__(self, lo: int, hi: int):
        self._lo, self._hi = lo, hi

    def validate(self, value) -> bool:
        return isinstance(value, int) and self._lo <= value <= self._hi

    def correct(self, value) -> int:
        return max(self._lo, min(self._hi, int(value)))


class OptionsValidator:
    def __init__(self, options):
        self._options = options

    def validate(self, value) -> bool:
        return value in self._options

    def correct(self, value):
        return value if self.validate(value) else list(self._options)[0] if self._options else value


class FolderValidator:
    def validate(self, value) -> bool:
        return isinstance(value, str) and bool(value)

    def correct(self, value) -> str:
        return str(value) if value else os.path.expanduser("~/Downloads")


class StringListValidator:
    def validate(self, value) -> bool:
        return isinstance(value, list) and all(isinstance(i, str) for i in value)

    def correct(self, value) -> list:
        return [i for i in value if isinstance(i, str)] if isinstance(value, list) else []


class ConfigValidator:
    def validate(self, value) -> bool:
        return True

    def correct(self, value):
        return value


class ConfigSerializer:
    def serialize(self, value):
        return str(value)

    def deserialize(self, value: str):
        return value


class EnumSerializer(ConfigSerializer):
    def __init__(self, enum_class=None):
        self._enum = enum_class

    def serialize(self, value) -> str:
        return value.value if hasattr(value, "value") else str(value)

    def deserialize(self, value: str):
        if self._enum:
            try:
                return self._enum(value)
            except (ValueError, TypeError):
                pass
        return value


class JsonConfigSerializer(ConfigSerializer):
    def __init__(self, expected: type, fallback):
        self._expected = expected
        self._fallback = fallback

    def serialize(self, value) -> str:
        return json.dumps(value, ensure_ascii=False)

    def deserialize(self, value: str):
        try:
            result = json.loads(value)
            return result if isinstance(result, self._expected) else self._fallback() if callable(self._fallback) else self._fallback
        except (ValueError, TypeError):
            return self._fallback() if callable(self._fallback) else self._fallback


# ---------------------------------------------------------------------------
# Proxy validator
# ---------------------------------------------------------------------------

_PROXY_PATTERN = _compile(
    r"^"
    r"(?P<protocol>http|https|socks4|socks5|socks5h)://"
    r"(?:(?P<user>\w+):(?P<password>[\w!@#$%^&*()]+)@)?"
    r"(?:"
    r"(?P<ip>(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?))|"
    r"(?P<domain>(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6})"
    r")"
    r":(?P<port>\d{1,5})"
    r"$"
)


class ProxyValidator(ConfigValidator):
    def validate(self, value: str) -> bool:
        return bool(_PROXY_PATTERN.match(value)) or value in {"Auto", "Off"}

    def correct(self, value) -> str:
        return value if self.validate(value) else "Auto"


class ClientProfileValidator(ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, str) and bool(value)

    def correct(self, value) -> str:
        return value if isinstance(value, str) and value else "auto"


class HeadersValidator(ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())

    def correct(self, value) -> dict:
        return value if self.validate(value) else dict(BASE_HEADERS)


class CategoryListValidator(ConfigValidator):
    def validate(self, value) -> bool:
        if not isinstance(value, list):
            return False
        return all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in value)

    def correct(self, value) -> list:
        return value if self.validate(value) else []


class IdentityPresetListValidator(ConfigValidator):
    REQUIRED_KEYS = {"name", "clientProfile", "userAgent", "hosts"}

    def validate(self, value) -> bool:
        return isinstance(value, list) and all(
            isinstance(item, dict) and self.REQUIRED_KEYS <= item.keys()
            for item in value
        )

    def correct(self, value) -> list:
        if not isinstance(value, list):
            return []
        return [item for item in value if self._is_valid(item)]

    @staticmethod
    def _is_valid(item) -> bool:
        return (
            isinstance(item, dict)
            and IdentityPresetListValidator.REQUIRED_KEYS <= item.keys()
            and isinstance(item["name"], str)
            and isinstance(item["clientProfile"], str)
            and isinstance(item["userAgent"], str)
            and isinstance(item["hosts"], list)
            and all(isinstance(h, str) for h in item["hosts"])
        )


# ---------------------------------------------------------------------------
# Config singleton
# ---------------------------------------------------------------------------

class Config:
    """Application configuration, backed by a JSON file.

    Usage::

        from app.config.cfg import cfg
        print(cfg.downloadFolder.value)
    """

    def __init__(self, config_dir: str = ""):
        self._config_dir = Path(config_dir) if config_dir else Path.home() / ".config" / "ghost-downloader-3"

        # ── Download settings ──────────────────────────────────────
        self.downloadFolder = ConfigItem(
            "GeneralDownload", "DownloadFolder",
            str(Path.home() / "Downloads"),
            FolderValidator(),
        )
        self.memoryDownloadFolders = ConfigItem(
            "GeneralDownload", "HistoryDownloadFolder", [], StringListValidator()
        )
        self.maxTaskNum = RangeConfigItem("GeneralDownload", "MaxTaskNum", 3, RangeValidator(1, 10))
        self.isSpeedLimitEnabled = ConfigItem("GeneralDownload", "isSpeedLimitEnabled", False, BoolValidator())
        self.speedLimitation = RangeConfigItem(
            "GeneralDownload", "SpeedLimitation", 4194304, RangeValidator(1024, 104857600)
        )
        self.shouldVerifySsl = ConfigItem("GeneralDownload", "shouldVerifySsl", False, BoolValidator())
        self.proxyServer = ConfigItem("GeneralDownload", "ProxyServer", "Auto", ProxyValidator())
        self.preBlockNum = RangeConfigItem("GeneralDownload", "PreBlockNum", 8, RangeValidator(1, 256))
        self.autoSpeedUp = ConfigItem("GeneralDownload", "AutoSpeedUp", True, BoolValidator())
        self.shouldPreserveLastModified = ConfigItem("GeneralDownload", "PreserveLastModified", False, BoolValidator())
        self.shouldDeleteFilesOnRemove = ConfigItem("GeneralDownload", "DeleteFilesOnRemove", False, BoolValidator())
        self.maxReassignSize = RangeConfigItem(
            "GeneralDownload", "MaxReassignSize", 512, RangeValidator(64, 102400)
        )

        # ── Category ───────────────────────────────────────────────
        self.isCategoryEnabled = ConfigItem("Category", "EnableCategory", False, BoolValidator())
        self.categoryRules = ConfigItem(
            "Category", "CategoryRules", [],
            CategoryListValidator(), JsonConfigSerializer(list, list),
        )

        # ── Browser extension ──────────────────────────────────────
        self.isBrowserExtensionEnabled = ConfigItem("Browser", "EnableBrowserExtension", True, BoolValidator())
        self.browserExtensionPairToken = ConfigItem("Browser", "BrowserExtensionPairToken", "")
        self.browserExtensionPort = RangeConfigItem("Browser", "Port", 14370, RangeValidator(1024, 65535))

        # ── Aria2 RPC ──────────────────────────────────────────────
        self.isAria2RpcEnabled = ConfigItem("Aria2Rpc", "Enabled", False, BoolValidator())
        self.aria2RpcPort = RangeConfigItem("Aria2Rpc", "Port", 16800, RangeValidator(1024, 65535))
        self.aria2RpcToken = ConfigItem("Aria2Rpc", "Token", "")
        self.aria2RpcEmulateFingerprint = ConfigItem("Aria2Rpc", "EmulateFingerprint", False, BoolValidator())

        # ── Network ────────────────────────────────────────────────
        self.clientProfile = ConfigItem("Network", "ClientProfile", "auto", ClientProfileValidator())
        self.defaultRequestHeaders = ConfigItem(
            "Network", "DefaultHeaders", dict(BASE_HEADERS),
            HeadersValidator(), JsonConfigSerializer(dict, lambda: dict(BASE_HEADERS)),
        )
        self.identityPresets = ConfigItem(
            "Network", "IdentityPresets",
            [{"name": "Baidu NetDisk", "clientProfile": "raw",
              "userAgent": "pan.baidu.com", "hosts": ["*.pcs.baidu.com"],
              "isEnabled": True}],
            IdentityPresetListValidator(), JsonConfigSerializer(list, list),
        )

        # ── Software ───────────────────────────────────────────────
        self.shouldCheckUpdateAtStartup = ConfigItem("Software", "CheckUpdateAtStartUp", True, BoolValidator())
        self.isClipboardListenerEnabled = ConfigItem("Software", "ClipboardListener", False, BoolValidator())

    # ── Persistence ──────────────────────────────────────────────

    def _config_path(self) -> Path:
        return self._config_dir / "config.json"

    def load(self, config_path: str = "") -> None:
        """Load config from a JSON file.  If *config_path* is empty, uses the
        default location ``~/.config/ghost-downloader-3/config.json``."""
        path = Path(config_path) if config_path else self._config_path()
        if not path.exists():
            self._config_dir.mkdir(parents=True, exist_ok=True)
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        # Map each ConfigItem attribute to its key
        for attr_name in dir(self):
            item = getattr(self, attr_name, None)
            if not isinstance(item, ConfigItem):
                continue
            group, name = item.group, item.name
            if group in data and name in data[group]:
                item.deserializeFrom(data[group][name])

    def save(self) -> None:
        path = self._config_path()
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, dict] = {}
        for attr_name in dir(self):
            item = getattr(self, attr_name, None)
            if not isinstance(item, ConfigItem):
                continue
            data.setdefault(item.group, {})[item.name] = item.serialize()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# Module-level singleton
cfg = Config()


def proxy() -> str | None:
    """Resolve the proxy setting.

    Returns ``None`` for "Off", a URL string for a configured proxy, or the
    system proxy for "Auto".
    """
    if cfg.proxyServer.value == "Off":
        return None
    if cfg.proxyServer.value == "Auto":
        system = getproxies()
        return next((v for v in system.values() if v), None) if system else None
    server = str(cfg.proxyServer.value).strip()
    return server or None
