"""
Qt (PySide6) & qfluentwidgets compatibility module.

Provides the subset of Qt types needed by feature packs at import time,
so the engine can run without PySide6 and qfluentwidgets installed.
"""

from __future__ import annotations

import asyncio
import sys
import typing
from types import ModuleType, SimpleNamespace

if typing.TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# QtCore compatibility types
# ---------------------------------------------------------------------------

class _QObject:
    """QObject-compatible base with callback-based signal plumbing."""

    def __init__(self, parent=None):
        self._signals: dict[str, list[Callable]] = {}
        self._destroy_handlers: list[Callable] = []

    def connect(self, signal_name: str, slot: Callable):
        self._signals.setdefault(signal_name, []).append(slot)

    def disconnect(self, signal_name: str, slot: Callable | None = None):
        if slot is None:
            self._signals.pop(signal_name, None)
        else:
            handlers = self._signals.get(signal_name, [])
            self._signals[signal_name] = [h for h in handlers if h is not slot]

    def emit(self, signal_name: str, *args, **kwargs):
        for handler in self._signals.get(signal_name, []):
            handler(*args, **kwargs)

    @property
    def destroyed(self):
        return _SignalProxy(self, "destroyed")

    def __repr__(self):
        return f"<QObject at 0x{id(self):x}>"


class _Signal:
    """Describes a Qt signal type."""

    def __init__(self, *types):
        self._types = types

    def __call__(self, *args, **kwargs):
        pass


class _SignalProxy:
    """Lazy-connect wrapper so that ``obj.destroyed.connect(fn)`` works."""

    def __init__(self, obj: _QObject, name: str):
        self._obj = obj
        self._name = name

    def connect(self, slot: Callable):
        self._obj.connect(self._name, slot)

    def disconnect(self, slot: Callable | None = None):
        self._obj.disconnect(self._name, slot)

    def emit(self, *args, **kwargs):
        self._obj.emit(self._name, *args, **kwargs)


class _QTimer:
    """QTimer-compatible timer using asyncio."""

    def __init__(self, parent=None, interval: int = 0):
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._timeout: Callable | None = None
        self._single_shot = False

    def setInterval(self, ms: int):
        self._interval = ms

    def setSingleShot(self, single: bool):
        self._single_shot = single

    def setTimeout(self, callback: Callable):
        self._timeout = callback

    @property
    def timeout(self):
        return _SignalProxy(self, "timeout")

    def start(self):
        if self._task is not None:
            return
        async def _run():
            while True:
                await asyncio.sleep(self._interval / 1000.0)
                if self._timeout:
                    self._timeout()
                if self._single_shot:
                    break
        self._task = asyncio.create_task(_run())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def isActive(self) -> bool:
        return self._task is not None and not self._task.done()

    def singleShot(self, ms: int, callback: Callable):
        async def _once():
            await asyncio.sleep(ms / 1000.0)
            callback()
        asyncio.create_task(_once())


class _QCoreApplication:
    @staticmethod
    def translate(context: str, source_text: str, disambiguation: str = "", n: int = -1) -> str:
        return source_text


class _QLocale:
    class Language:
        Chinese = "Chinese"
        English = "English"
        Cantonese = "Cantonese"

    class Country:
        China = "China"
        Taiwan = "Taiwan"
        HongKong = "HongKong"
        UnitedStates = "UnitedStates"
        Japan = "Japan"
        Russia = "Russia"
        Brazil = "Brazil"

    def __init__(self, *args):
        pass

    def name(self) -> str:
        return "en_US"


class _QT_TRANSLATE_NOOP:
    """i18n marker that returns the source text unchanged."""
    _instances: dict[tuple[str, str, str], str] = {}

    def __call__(self, context: str, text: str, disambiguation: str = "") -> str:
        key = (context, text, disambiguation)
        self._instances[key] = text
        return text


# Pre-create the singleton marker function
QT_TRANSLATE_NOOP = _QT_TRANSLATE_NOOP()


class _QRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self): return self._x
    def y(self): return self._y
    def width(self): return self._w
    def height(self): return self._h


class _QUrl:
    """QUrl-compatible URL wrapper."""
    def __init__(self, url: str = ""):
        self._url = url

    def __str__(self):
        return self._url

    def __repr__(self):
        return f"QUrl({self._url!r})"

    def toString(self) -> str:
        return self._url

    @staticmethod
    def fromLocalFile(path: str):
        from urllib.parse import urljoin
        return _QUrl(urljoin("file://", path))

    def isValid(self) -> bool:
        return bool(self._url)

    def scheme(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self._url).scheme

    def host(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self._url).hostname or ""


class _QStandardPaths:
    class StandardLocation:
        DownloadLocation = 0
        AppDataLocation = 1
        GenericDataLocation = 2

    @staticmethod
    def writableLocation(location: int) -> str:
        import os
        return os.path.join(os.path.expanduser("~"), "Downloads")


class _Qt:
    """Qt enums and flags."""
    AlignLeft = 1
    AlignRight = 2
    AlignHCenter = 4
    AlignTop = 8
    AlignBottom = 16
    AlignVCenter = 32
    AlignCenter = AlignHCenter | AlignVCenter


def _build_QtCore_module() -> ModuleType:
    mod = ModuleType("PySide6.QtCore")
    mod.QObject = _QObject
    mod.Signal = _Signal
    mod.QTimer = _QTimer
    mod.QCoreApplication = _QCoreApplication
    mod.QLocale = _QLocale
    mod.QT_TRANSLATE_NOOP = QT_TRANSLATE_NOOP
    mod.QRect = _QRect
    mod.QUrl = _QUrl
    mod.QStandardPaths = _QStandardPaths
    mod.Qt = _Qt
    # For `from PySide6.QtCore import Qt`
    # Already accessible as mod.Qt
    return mod


# ---------------------------------------------------------------------------
# QtGui compatibility types
# ---------------------------------------------------------------------------

class _QColor:
    def __init__(self, *args):
        pass


class _QPainter:
    pass


class _QPaintEvent:
    pass


class _QDesktopServices:
    @staticmethod
    def openUrl(url):
        import webbrowser
        webbrowser.open(str(url))


class _QPixmap:
    def __init__(self, *args):
        pass


class _QStandardItem:
    def __init__(self, *args):
        pass


class _QStandardItemModel:
    def __init__(self, *args, **kwargs):
        pass


def _build_QtGui_module() -> ModuleType:
    mod = ModuleType("PySide6.QtGui")
    mod.QColor = _QColor
    mod.QPainter = _QPainter
    mod.QPaintEvent = _QPaintEvent
    mod.QDesktopServices = _QDesktopServices
    mod.QPixmap = _QPixmap
    mod.QStandardItem = _QStandardItem
    mod.QStandardItemModel = _QStandardItemModel
    return mod


# ---------------------------------------------------------------------------
# QtWidgets compatibility types
# ---------------------------------------------------------------------------

class _QWidget:
    def __init__(self, parent=None):
        self._parent = parent

    def setParent(self, parent):
        self._parent = parent


class _QHBoxLayout:
    def __init__(self, parent=None):
        pass

    def addWidget(self, widget, *args, **kwargs):
        pass

    def setContentsMargins(self, *args):
        pass


class _QVBoxLayout:
    def __init__(self, parent=None):
        pass

    def addWidget(self, widget, *args, **kwargs):
        pass

    def setContentsMargins(self, *args):
        pass


class _QFileDialog:
    @staticmethod
    def getOpenFileName(*args, **kwargs):
        return "", ""


class _QAbstractItemView:
    pass


class _QHeaderView:
    pass


class _QFileIconProvider:
    pass


def _build_QtWidgets_module() -> ModuleType:
    mod = ModuleType("PySide6.QtWidgets")
    mod.QWidget = _QWidget
    mod.QHBoxLayout = _QHBoxLayout
    mod.QVBoxLayout = _QVBoxLayout
    mod.QFileDialog = _QFileDialog
    mod.QAbstractItemView = _QAbstractItemView
    mod.QHeaderView = _QHeaderView
    mod.QFileIconProvider = _QFileIconProvider
    return mod


# ---------------------------------------------------------------------------
# qfluentwidgets compatibility types
# ---------------------------------------------------------------------------

class _ConfigItem:
    """ConfigItem compatible with qfluentwidgets-based pack configs."""
    def __init__(self, group: str, name: str, default, validator=None, serializer=None, restart=False):
        self.group = group
        self.name = name
        self._default = default
        self._value = default
        self.validator = validator
        self.serializer = serializer
        self.restart = restart
        self.key = f"{group}.{name}"

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v

    def deserializeFrom(self, v):
        self._value = v

    def serialize(self):
        if self.serializer:
            return self.serializer.serialize(self._value)
        return str(self._value)


class _OptionsConfigItem(_ConfigItem):
    pass


class _RangeConfigItem(_ConfigItem):
    pass


class _BoolValidator:
    def validate(self, value) -> bool:
        return isinstance(value, bool)

    def correct(self, value) -> bool:
        return bool(value) if isinstance(value, bool) else False


class _OptionsValidator:
    def __init__(self, options):
        self._options = options

    def validate(self, value) -> bool:
        return value in self._options if hasattr(self._options, '__iter__') else isinstance(value, self._options)

    def correct(self, value):
        return value if self.validate(value) else (list(self._options)[0] if hasattr(self._options, '__iter__') else None)


class _RangeValidator:
    def __init__(self, lo: int, hi: int):
        self._lo, self._hi = lo, hi

    def validate(self, value) -> bool:
        return isinstance(value, int) and self._lo <= value <= self._hi

    def correct(self, value) -> int:
        return max(self._lo, min(self._hi, int(value)))


class _FolderValidator:
    def validate(self, value) -> bool:
        return isinstance(value, str) and bool(value)

    def correct(self, value) -> str:
        return value if isinstance(value, str) else ""


class _ConfigValidator:
    def validate(self, value) -> bool:
        return True

    def correct(self, value):
        return value


class _ConfigSerializer:
    def serialize(self, value):
        return str(value)

    def deserialize(self, value: str):
        return value


class _EnumSerializer(_ConfigSerializer):
    def __init__(self, enum_class=None):
        self._enum = enum_class

    def serialize(self, value) -> str:
        return value.value if hasattr(value, 'value') else str(value)

    def deserialize(self, value: str):
        if self._enum:
            try:
                return self._enum(value)
            except (ValueError, TypeError):
                pass
        return value


class _FolderListValidator(_ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, list)

    def correct(self, value) -> list:
        return list(value) if isinstance(value, list) else []


class _QConfig:
    """QConfig-compatible config container."""
    def __init__(self):
        self._items: dict[str, _ConfigItem] = {}

    def _register_item(self, item: _ConfigItem):
        self._items[item.key] = item

    def load(self, file_path: str = ""):
        """Load config from JSON file."""
        import json, os
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        for k, v in data.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    key = f"{k}.{sub_k}"
                    if key in self._items:
                        self._items[key].deserializeFrom(sub_v)
            else:
                if k in self._items:
                    self._items[k].deserializeFrom(v)

    @property
    def file(self) -> str:
        return getattr(self, "_file_path", "")

    @file.setter
    def file(self, path: str):
        self._file_path = path


class _FluentIcon:
    """Type for FluentIcon enum-like attribute access."""
    def __init__(self, name: str = ""):
        self._name = name
    def __repr__(self):
        return f"FluentIcon.{self._name}" if self._name else "FluentIcon"
    def __getattr__(self, name):
        # Allow `FluentIcon.BOOK_SHELF` etc. to return sub-instances
        return _FluentIcon(name)


# ---------------------------------------------------------------------------
# UI widget types — import compatibility for feature pack configs
# ---------------------------------------------------------------------------

class _WidgetBase:
    """Minimal widget base accepting a parent argument."""
    def __init__(self, parent=None):
        self._parent = parent

    def setParent(self, parent):
        self._parent = parent


class _BodyLabel(_WidgetBase):
    pass


class _CaptionLabel(_WidgetBase):
    pass


class _ComboBox(_WidgetBase):
    pass


class _ComboBoxSettingCard(_WidgetBase):
    pass


class _HyperlinkButton(_WidgetBase):
    pass


class _IconWidget(_WidgetBase):
    def __init__(self, icon=None, parent=None):
        super().__init__(parent)
        self._icon = icon


class _IndeterminateProgressRing(_WidgetBase):
    pass


class _LineEdit(_WidgetBase):
    pass


class _MessageBoxBase(_WidgetBase):
    """Dialog base type (no-op on CLI)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.yesButton = _WidgetBase()
        self.cancelButton = _WidgetBase()
        self.widget = _WidgetBase()

    def exec_(self):
        return 0  # Rejected / Cancel


class _PasswordLineEdit(_WidgetBase):
    pass


class _PixmapLabel(_WidgetBase):
    pass


class _PlainTextEdit(_WidgetBase):
    pass


class _PrimaryPushButton(_WidgetBase):
    pass


class _PushButton(_WidgetBase):
    pass


class _SettingCard(_WidgetBase):
    pass


class _SettingCardGroup(_WidgetBase):
    def __init__(self, title="", name="", parent=None):
        super().__init__(parent)
        self._title = title


class _SimpleCardWidget(_WidgetBase):
    pass


class _SubtitleLabel(_WidgetBase):
    pass


class _TitleLabel(_WidgetBase):
    pass


class _ToolButton(_WidgetBase):
    pass


class _ToolTipFilter:
    """No-op tooltip filter for import compatibility."""
    def __init__(self, *args, **kwargs):
        pass


class _TransparentToolButton(_WidgetBase):
    pass


def _build_qfluentwidgets_module() -> ModuleType:
    mod = ModuleType("qfluentwidgets")
    # Config system
    mod.QConfig = _QConfig
    mod.ConfigItem = _ConfigItem
    mod.OptionsConfigItem = _OptionsConfigItem
    mod.RangeConfigItem = _RangeConfigItem
    # Validators
    mod.BoolValidator = _BoolValidator
    mod.OptionsValidator = _OptionsValidator
    mod.RangeValidator = _RangeValidator
    mod.FolderValidator = _FolderValidator
    mod.ConfigValidator = _ConfigValidator
    mod.FolderListValidator = _FolderListValidator
    # Serializers
    mod.ConfigSerializer = _ConfigSerializer
    mod.EnumSerializer = _EnumSerializer
    # Icons
    mod.FluentIcon = _FluentIcon(
    )
    # UI widget types (import compatibility)
    mod.BodyLabel = _BodyLabel
    mod.CaptionLabel = _CaptionLabel
    mod.ComboBox = _ComboBox
    mod.ComboBoxSettingCard = _ComboBoxSettingCard
    mod.HyperlinkButton = _HyperlinkButton
    mod.IconWidget = _IconWidget
    mod.IndeterminateProgressRing = _IndeterminateProgressRing
    mod.LineEdit = _LineEdit
    mod.MessageBoxBase = _MessageBoxBase
    mod.PasswordLineEdit = _PasswordLineEdit
    mod.PixmapLabel = _PixmapLabel
    mod.PlainTextEdit = _PlainTextEdit
    mod.PrimaryPushButton = _PrimaryPushButton
    mod.PushButton = _PushButton
    mod.SettingCard = _SettingCard
    mod.SettingCardGroup = _SettingCardGroup
    mod.SimpleCardWidget = _SimpleCardWidget
    mod.SubtitleLabel = _SubtitleLabel
    mod.TitleLabel = _TitleLabel
    mod.ToolButton = _ToolButton
    mod.ToolTipFilter = _ToolTipFilter
    mod.TransparentToolButton = _TransparentToolButton
    return mod


# ---------------------------------------------------------------------------
# shiboken6 compatibility
# ---------------------------------------------------------------------------

def _build_shiboken6_module() -> ModuleType:
    mod = ModuleType("shiboken6")

    def isValid(obj) -> bool:
        try:
            return hasattr(obj, "__dict__")
        except Exception:
            return False

    mod.isValid = isValid
    return mod


# ---------------------------------------------------------------------------
# Public installer
# ---------------------------------------------------------------------------

_COMPAT_PACKAGES: dict[str, Callable[[], ModuleType, ]] = {
    "PySide6.QtCore": _build_QtCore_module,
    "PySide6.QtGui": _build_QtGui_module,
    "PySide6.QtWidgets": _build_QtWidgets_module,
    "qfluentwidgets": _build_qfluentwidgets_module,
    "shiboken6": _build_shiboken6_module,
}


def install_stubs():
    """Register Qt-compatible modules so feature packs can import from
    ``PySide6.QtCore``, ``PySide6.QtGui``, ``PySide6.QtWidgets``,
    ``qfluentwidgets``, and ``shiboken6`` without the real libraries."""
    for name, builder in _COMPAT_PACKAGES.items():
        if name not in sys.modules:
            sys.modules[name] = builder()
