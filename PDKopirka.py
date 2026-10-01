import os
import sys
import time
import io
import math
import hmac
import hashlib
import random
import re
import ssl
import zipfile
import tempfile
import subprocess
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pymupdf as fitz
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QFileDialog, QLabel, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QTextEdit, QProgressBar, QFrame,
    QScrollArea, QDialog, QLineEdit, QMessageBox, QGroupBox,
    QRadioButton, QButtonGroup, QSizePolicy, QHeaderView, QGridLayout,
    QListWidget, QListWidgetItem, QToolButton
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent, QPropertyAnimation, QEasingCurve, pyqtProperty, QFileInfo, QSize
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor, QLinearGradient, QPixmap, QFontMetrics
import json
import shutil

try:
    import certifi
    _HAS_CERTIFI = True
except ImportError:
    _HAS_CERTIFI = False


# ─────────────────────────────────────────────────────────────────────────────
# Дизайн-токены (Material 3 structure + Apple-подобная полировка)
# ─────────────────────────────────────────────────────────────────────────────

THEME = {
    # Палитра 1:1 как в web-версии kopirka-maket.ru/pdkopirka (iOS/MD3)
    "primary":       "#007AFF",
    "primary_hover": "#0A84FF",
    "primary_press": "#0062CC",
    "primary_soft":  "#D6E8FF",
    "primary_border": "#A9CEFB",
    "primary_text":  "#004C99",
    "accent":        "#06B6D4",
    "accent_soft":   "#E0F7FB",
    # Поверхности
    "bg":            "#F5F5F7",
    "surface":       "#FFFFFF",
    "surface_alt":   "#FAFAFC",
    "surface_sunken": "#F0F0F4",
    "surface_high":  "#E9E9EE",
    # Границы и разделители
    "border":        "#D9D9DE",
    "border_strong": "#A1A1A6",
    "divider":       "#ECECF1",
    # Текст
    "text":          "#1D1D1F",
    "text_muted":    "#86868B",
    "text_faint":    "#A1A1A6",
    "text_on_primary": "#FFFFFF",
    # Состояния
    "danger":        "#FF3B30",
    "danger_hover":  "#FF453A",
    "danger_soft":   "#FFEBEB",
    "danger_text":   "#B3261E",
    "success":       "#34C759",
    "success_hover": "#30B350",
    "success_soft":  "#F0FFF4",
    "success_text":  "#1F9A3A",
    "warning":       "#FF9500",
    "warning_hover": "#F08A00",
    "warning_soft":  "#FFF4E5",
    "warning_text":  "#B26A00",
    "neutral":       "#8E8E93",
    "neutral_hover": "#7C7C81",
    "disabled_bg":   "#E9E9EE",
    "disabled_fg":   "#A1A1A6",
    "seg_track":     "#E4E4EA",
    "seg_thumb":     "#FFFFFF",
    # «Ближайший формат» — отдельный (сиреневый) акцент
    "nearest_soft":  "#F1ECFE",
    "nearest_hover": "#E4DBFC",
    "nearest_text":  "#5B45B8",
    # Скругления
    "r_xs": "6px",
    "r_sm": "10px",
    "r_md": "14px",
    "r_lg": "20px",
    "r_xl": "26px",
    "r_pill": "999px",
    # Типографика
    "font": "'Segoe UI Variable Text', 'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif",
    "font_display": "'Segoe UI Variable Display', 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif",
    "mono": "'Cascadia Mono', 'Consolas', 'Menlo', monospace",
}


def _normalize_font(raw):
    raw = (raw or "").split(",")[0].strip().strip("'\"")
    if not raw:
        return "Arial"
    for marker in ("Variable Display", "Variable Text", "Variable Small"):
        if marker in raw:
            raw = "Segoe UI"
            break
    return raw


def force_light_palette(app):
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    t = THEME
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(t["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.Base,             QColor(t["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase,    QColor(t["surface_alt"]))
    pal.setColor(QPalette.ColorRole.Text,             QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.Button,           QColor(t["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText,       QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase,      QColor(t["surface"]))
    pal.setColor(QPalette.ColorRole.ToolTipText,      QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText,  QColor(t["text_muted"]))
    pal.setColor(QPalette.ColorRole.Highlight,        QColor(t["primary"]))
    pal.setColor(QPalette.ColorRole.HighlightedText,  QColor(t["text_on_primary"]))
    pal.setColor(QPalette.ColorRole.BrightText,       QColor(t["text"]))
    pal.setColor(QPalette.ColorRole.Link,             QColor(t["primary"]))
    pal.setColor(QPalette.ColorRole.LinkVisited,      QColor(t["primary_press"]))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.WindowText, QColor(t["disabled_fg"]))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text, QColor(t["disabled_fg"]))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, QColor(t["disabled_fg"]))
    app.setPalette(pal)


def _qss_button(variant="filled", accent=None, accent_hover=None, radius=None):
    """Кнопки как в web: сплошной цвет, скруглённые углы, мягкий transition-эффект."""
    t = THEME
    acc = accent or t["primary"]
    hov = accent_hover or t["primary_hover"]
    rad = radius or t["r_md"]
    if variant == "filled":
        return (
            f"QPushButton{{background-color:{acc};color:{t['text_on_primary']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{hov};}}"
            f"QPushButton:pressed{{background-color:{t['primary_press']};}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    if variant == "tonal":
        return (
            f"QPushButton{{background-color:{t['primary_soft']};color:{t['primary_text']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:#C7DEFB;}}"
            f"QPushButton:pressed{{background-color:#B4D3F8;}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    if variant == "outlined":
        return (
            f"QPushButton{{background-color:transparent;color:{acc};"
            f"border:1px solid {t['border']};border-radius:{rad};"
            f"padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['primary_soft']};border-color:{acc};}}"
            f"QPushButton:pressed{{background-color:#C7DEFB;}}"
            f"QPushButton:disabled{{color:{t['disabled_fg']};border-color:{t['divider']};}}"
        )
    if variant == "text":
        return (
            f"QPushButton{{background-color:transparent;color:{acc};border:none;"
            f"border-radius:{rad};padding:8px 16px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['surface_sunken']};}}"
            f"QPushButton:pressed{{background-color:{t['surface_high']};}}"
            f"QPushButton:disabled{{color:{t['disabled_fg']};}}"
        )
    if variant == "danger":
        return (
            f"QPushButton{{background-color:{t['danger']};color:{t['text_on_primary']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['danger_hover']};}}"
            f"QPushButton:pressed{{background-color:#E03028;}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    if variant == "success":
        return (
            f"QPushButton{{background-color:{t['success']};color:{t['text_on_primary']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['success_hover']};}}"
            f"QPushButton:pressed{{background-color:#2AA049;}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    if variant == "warning":
        return (
            f"QPushButton{{background-color:{t['warning']};color:{t['text_on_primary']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['warning_hover']};}}"
            f"QPushButton:pressed{{background-color:#E08600;}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    if variant == "neutral":
        return (
            f"QPushButton{{background-color:{t['neutral']};color:{t['text_on_primary']};"
            f"border:none;border-radius:{rad};padding:10px 22px;font-weight:600;font-size:13px;}}"
            f"QPushButton:hover{{background-color:{t['neutral_hover']};}}"
            f"QPushButton:pressed{{background-color:#6E6E73;}}"
            f"QPushButton:disabled{{background-color:{t['disabled_bg']};color:{t['disabled_fg']};}}"
        )
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Пути к ресурсам
# ─────────────────────────────────────────────────────────────────────────────

def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# ─────────────────────────────────────────────────────────────────────────────
# Автообновление
# ─────────────────────────────────────────────────────────────────────────────

def _load_env_file():
    """Читает .env рядом с exe (сборка) или в папке проекта (разработка)."""
    if getattr(sys, "frozen", False):
        bases = [Path(sys.executable).resolve().parent]
    else:
        bases = [Path(__file__).resolve().parent, Path.cwd()]
    for base in bases:
        env_path = base / ".env"
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass
        return


_load_env_file()

APP_VERSION = "2.3.8"
INNO_APP_ID = "{8F4C8D7A-2D52-4A1A-9E6B-7A8B9C0D1E2F}"
UPDATE_REPO = "fabilya/PDKopirka"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
UPDATE_LIST_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases?per_page=5"
# Манифест обновления: отдаётся raw-хостингом GitHub без лимитов API (в отличие от api.github.com)
UPDATE_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{UPDATE_REPO}/master/latest.json"
)
UPDATE_PAGE_URL = f"https://github.com/{UPDATE_REPO}/releases/latest"


def _make_ssl_context_certifi():
    if not _HAS_CERTIFI:
        return None
    try:
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _urlopen_safe(req, timeout=15):
    last_error = None
    ctx = _make_ssl_context_certifi()
    if ctx is not None:
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except ssl.SSLError as e:
            last_error = e
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLError):
                last_error = e
            else:
                raise
    try:
        ctx = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except ssl.SSLError as e:
        last_error = e
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            last_error = e
        else:
            raise
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except Exception as e:
        if last_error:
            raise last_error
        raise


def _parse_version(v):
    if not v:
        return (0, 0, 0)
    v = str(v).lstrip("v").strip()
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)


def _app_data_dir():
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = Path(appdata) / "PDKopirka"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_version_file():
    if not getattr(sys, "frozen", False):
        return None
    version_file = Path(sys.executable).resolve().parent / "version.txt"
    try:
        text = version_file.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def _read_registry_version():
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    subkey = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        f"\\{INNO_APP_ID}_is1"
    )
    for root, flags in (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0)),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
    ):
        try:
            with winreg.OpenKey(root, subkey, 0, flags) as key:
                val, _ = winreg.QueryValueEx(key, "DisplayVersion")
                if val:
                    return str(val).strip()
        except OSError:
            continue
    return None


def get_app_version():
    """
    Версия для отображения и проверки обновлений:
    1) запуск из исходников — APP_VERSION (незакоммиченная сборка)
    2) version.txt рядом с exe (после установки Inno Setup)
    3) APP_VERSION из собранного exe (при сборке PyInstaller)
    4) реестр Windows — только запасной вариант
    """
    if not getattr(sys, "frozen", False):
        return APP_VERSION
    ver = _read_version_file()
    if ver:
        return ver
    reg = _read_registry_version()
    if reg:
        return reg
    return APP_VERSION


def _update_settings_path():
    return _app_data_dir() / "update_settings.json"


def _load_update_settings():
    path = _update_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_update_settings(data):
    path = _update_settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _mark_update_attempt(latest_tag):
    settings = _load_update_settings()
    latest_norm = str(latest_tag).lstrip("v").strip()
    settings["last_attempt_version"] = latest_norm
    settings["last_attempt_at"] = datetime.now().isoformat()
    _save_update_settings(settings)


def _clear_update_settings_if_current():
    current = _parse_version(get_app_version())
    settings = _load_update_settings()
    changed = False
    attempt = settings.get("last_attempt_version")
    if attempt and current >= _parse_version(attempt):
        settings.pop("last_attempt_version", None)
        settings.pop("last_attempt_at", None)
        changed = True
    if changed:
        _save_update_settings(settings)


def _create_single_instance_mutex():
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "PDKopirka_Mutex")
    except Exception:
        pass


def flash_taskbar_icon(window, count=0):
    """
    Мигает иконкой программы в панели задач Windows.
    count=0 — мигать пока пользователь не переключится на окно.
    count=N — мигнуть N раз.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        FLASHW_STOP = 0
        FLASHW_CAPTION = 0x00000001
        FLASHW_TRAY = 0x00000002
        FLASHW_ALL = FLASHW_CAPTION | FLASHW_TRAY
        FLASHW_TIMER = 0x00000004
        FLASHW_TIMERNOFG = 0x0000000C  # мигать пока окно не получит фокус

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        hwnd = int(window.winId())
        flags = FLASHW_ALL | (FLASHW_TIMERNOFG if count == 0 else 0)
        info = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=flags,
            uCount=count if count > 0 else 0,
            dwTimeout=0,
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def stop_flash_taskbar(window):
    """Останавливает мигание иконки."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        FLASHW_STOP = 0

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        hwnd = int(window.winId())
        info = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=hwnd,
            dwFlags=FLASHW_STOP,
            uCount=0,
            dwTimeout=0,
        )
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def bring_window_to_front(window):
    """
    «Безопасный» подъём окна наверх — Windows не даёт переключать активное
    приложение насильно, но это работает в большинстве случаев.
    """
    try:
        window.setWindowState(
            (window.windowState() & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowActive
        )
        window.raise_()
        window.activateWindow()
    except Exception:
        pass


def _find_asset_in_release(data):
    """Ищет .exe установщик в данных одного релиза. Возвращает (latest_tag, download_url) или (None, None)."""
    tag = data.get("tag_name", "")
    if not tag:
        return None, None
    for asset in data.get("assets", []):
        name_lower = asset["name"].lower()
        if name_lower.endswith(".exe") and (
            "setup" in name_lower or "install" in name_lower
        ):
            return tag, asset["browser_download_url"]
    for asset in data.get("assets", []):
        if asset["name"].lower().endswith(".exe"):
            return tag, asset["browser_download_url"]
    return tag, None


def _fetch_json(url, timeout=5):
    """Выполняет GET-запрос к GitHub API и возвращает распарсенный JSON."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "PDKopirka-Updater/1.0")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with _urlopen_safe(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_manifest():
    """Читает latest.json с raw-хостинга GitHub (без лимитов API).

    Возвращает dict {version, url, notes} или None.
    """
    req = urllib.request.Request(UPDATE_MANIFEST_URL)
    req.add_header("User-Agent", "PDKopirka-Updater/1.0")
    req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
    req.add_header("Pragma", "no-cache")
    # Кэш raw отдаёт ~5 минут, поэтому пробуем и с cache-busting параметром
    try:
        with _urlopen_safe(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
        if isinstance(data, dict) and data.get("version"):
            return data
    except Exception:
        pass
    try:
        sep = "&" if "?" in UPDATE_MANIFEST_URL else "?"
        req2 = urllib.request.Request(f"{UPDATE_MANIFEST_URL}{sep}_={int(time.time())}")
        req2.add_header("User-Agent", "PDKopirka-Updater/1.0")
        with _urlopen_safe(req2, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8-sig", errors="replace"))
        if isinstance(data, dict) and data.get("version"):
            return data
    except Exception:
        pass
    return None


def check_for_update():
    """Ищет обновление. Сначала — latest.json (raw, без лимитов API),
    затем fallback на GitHub API (/releases/latest, затем список релизов)."""
    current = get_app_version()
    last_err = None

    # Попытка 0: манифест latest.json (raw.githubusercontent.com, без лимитов)
    try:
        m = _fetch_manifest()
        if m:
            tag = str(m.get("version", "")).strip()
            url = str(m.get("url", "")).strip()
            if tag and url and _parse_version(tag) > _parse_version(current):
                return True, tag, url, None
            if tag and _parse_version(tag) <= _parse_version(current):
                # Манифест доступен и новее нас нет — сразу выходим (без API)
                return False, None, None, None
    except Exception as e:
        last_err = f"manifest: {type(e).__name__}: {e}"

    # Попытка 1: /releases/latest
    try:
        data = _fetch_json(UPDATE_API_URL)
        tag, dl_url = _find_asset_in_release(data)
        if tag and dl_url and _parse_version(tag) > _parse_version(current):
            return True, tag, dl_url, None
    except Exception as e:
        last_err = f"latest endpoint: {type(e).__name__}: {e}"

    # Попытка 2: список последних релизов
    try:
        releases = _fetch_json(UPDATE_LIST_URL, timeout=10)
        if isinstance(releases, list):
            best_tag, best_url, best_err = None, None, None
            for rel in releases:
                tag, dl_url = _find_asset_in_release(rel)
                if tag and dl_url:
                    if _parse_version(tag) > _parse_version(current):
                        if best_tag is None or _parse_version(tag) > _parse_version(best_tag):
                            best_tag, best_url = tag, dl_url
                else:
                    if tag and not dl_url:
                        best_err = f"В релизе {tag} нет .exe файла"
            if best_tag and best_url:
                return True, best_tag, best_url, None
            if best_err and not best_tag:
                return False, None, None, best_err
            if not best_tag:
                return False, None, None, "Новых версий не найдено."
    except Exception as e:
        err = last_err or f"list endpoint: {type(e).__name__}: {e}"
        return False, None, None, err

    return False, None, None, last_err


def _download_once(url, target_path, progress_callback=None):
    """Одна попытка скачивания. Возвращает (True,) или (False, причина, retryable)."""
    try:
        for old in [target_path, target_path + ".part"]:
            if os.path.exists(old):
                try:
                    os.remove(old)
                except OSError:
                    pass
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "PDKopirka-Updater/1.0")
        req.add_header("Accept", "application/octet-stream")
        resp = _urlopen_safe(req, timeout=300)
        with resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024
            temp_path = target_path + ".part"
            with open(temp_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        try:
                            progress_callback(downloaded, total_size)
                        except Exception:
                            pass
        if total_size > 0 and downloaded != total_size:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return (False, f"Размер не совпадает: скачано {downloaded} из {total_size} байт", True)
        size_mb = os.path.getsize(temp_path) / 1048576
        if os.path.getsize(temp_path) < 1024 * 100:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return (False, f"Файл слишком мал: {size_mb:.1f} МБ", True)
        # Проверка MZ-сигнатуры (.exe)
        with open(temp_path, "rb") as f:
            magic = f.read(2)
        if magic != b"MZ":
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return (False, "Скачанный файл не является .exe (нет MZ-сигнатуры)", False)
        # Перемещаем готовый файл на место (с ретраем на случай блокировки антивирусом)
        for attempt in range(5):
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                os.rename(temp_path, target_path)
                return (True,)
            except OSError:
                time.sleep(0.4)
        return (False, "Не удалось сохранить установщик (файл занят)", True)
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}", True)


def download_update(url, target_path, progress_callback=None, version=None):
    """Скачивает установщик .exe с несколькими попытками.

    Пробует несколько URL (прямая ссылка на ассет, затем прямой asset-URL по
    версии/тегу), делает до 3 попыток на каждый. Возвращает (True,) или (False, причина).
    """
    candidates = []
    if url:
        candidates.append(url)
    ver = str(version or "").lstrip("v").strip()
    if ver:
        # Прямой asset-URL по тегу (на случай, если browser_download_url устарел)
        candidates.append(
            f"https://github.com/{UPDATE_REPO}/releases/download/"
            f"{ver}/PDKopirka_Setup_{ver}.exe"
        )
    seen = set()
    last_err = "Неизвестная ошибка"
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        for attempt in range(3):
            res = _download_once(cand, target_path, progress_callback)
            if res[0]:
                return (True,)
            last_err = res[1] if len(res) > 1 else "Неизвестная ошибка"
            retryable = res[2] if len(res) > 2 else True
            if not retryable:
                break
            time.sleep(1.5)
    return (False, last_err)


def apply_update_and_restart(installer_path, latest_version="new"):
    """
    Запускает установщик Inno Setup в тихом режиме.
    Установщик сам:
    - закроет программу (taskkill)
    - заменит все файлы
    - запустит обновлённую версию
    """
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return

    if not os.path.exists(installer_path):
        QMessageBox.critical(
            None, "Ошибка обновления",
            f"Установщик не найден:\n{installer_path}"
        )
        return

    try:
        # /VERYSILENT          - полностью без окон (в отличие от /SILENT)
        # /SUPPRESSMSGBOXES    - без предупреждений
        # /SP-                 - без заставки установщика
        # /NORESTART           - не перезагружать ПК
        # /CLOSEAPPLICATIONS   - закрыть запущенную программу
        # /RESTARTAPPLICATIONS - запустить после установки
        subprocess.Popen(
            [
                installer_path,
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/SP-",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ],
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        QMessageBox.critical(
            None, "Ошибка запуска установщика",
            f"Не удалось запустить установщик:\n{e}"
        )
        return

    # Закрываем программу — установщик сделает всё сам
    app = QApplication.instance()
    if app:
        app.quit()
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# Диалог обновления
# ─────────────────────────────────────────────────────────────────────────────

# Глобальная ссылка, чтобы Qt/Python не удаляли диалог обновления сборщиком мусора
_update_dialog_ref = None


class UpdateDialog(QDialog):
    def __init__(self, latest_version, download_url, parent=None):
        super().__init__(parent)
        self.latest_version = latest_version
        self.download_url = download_url
        self.setWindowTitle("Обновление")
        self.setFixedSize(400, 180)
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )
        self._build_ui()
        QTimer.singleShot(100, self._do_update)

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(25, 25, 25, 25)
        t = QLabel(f"🔄 Обновление до версии {self.latest_version}")
        t.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.DemiBold))
        t.setStyleSheet(f"color: {THEME['primary']}; background: transparent;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)
        self.status_lbl = QLabel("Подготовка...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet(f"color: {THEME['text_muted']}; background: transparent;")
        lay.addWidget(self.status_lbl)
        self.setStyleSheet(f"QDialog {{ background-color: {THEME['surface']}; color: {THEME['text']}; }}")

    def closeEvent(self, e):
        e.ignore()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            e.ignore()

    def _do_update(self):
        safe_ver = str(self.latest_version).replace(".", "_").strip()
        new_installer = os.path.join(
            tempfile.gettempdir(), f"PDKopirka_Setup_{safe_ver}.exe"
        )

        def on_progress(downloaded, total):
            if total > 0:
                pct = min(100, int(downloaded * 100 / total))
                self.progress.setValue(pct)
                self.status_lbl.setText(
                    f"Загрузка... {downloaded / 1048576:.1f} / "
                    f"{total / 1048576:.1f} МБ ({pct}%)"
                )
            else:
                self.status_lbl.setText(
                    f"Загрузка... {downloaded / 1048576:.1f} МБ"
                )
            QApplication.processEvents()

        self.status_lbl.setText("Скачивание обновления...")
        QApplication.processEvents()
        dl_result = download_update(self.download_url, new_installer, on_progress,
                                    version=self.latest_version)
        if not dl_result[0]:
            err_msg = dl_result[1] if len(dl_result) > 1 else "Неизвестная ошибка"
            self.accept()
            QMessageBox.critical(
                None, "Ошибка обновления",
                f"Не удалось скачать обновление: {err_msg}\n\n"
                "Проверьте подключение к интернету и повторите попытку.\n\n"
                "Вы также можете скачать установщик вручную:\n"
                "https://github.com/fabilya/PDKopirka/releases/latest"
            )
            return
        self.progress.setValue(100)
        self.status_lbl.setText("✅ Запуск установщика...")
        QApplication.processEvents()
        time.sleep(1)
        apply_update_and_restart(new_installer, self.latest_version)


# ─────────────────────────────────────────────────────────────────────────────
# Диалог «Что нового»
# ─────────────────────────────────────────────────────────────────────────────

_CHANGELOG_HISTORY = [
    {
        "version": "2.3.8",
        "date": "30.09.2026",
        "sections": [
            ("🎨 Новый дизайн", [
                "Полностью обновлён интерфейс — современный стиль с синим акцентом, скруглениями и мягкими тенями",
                "Вкладки переименованы: «Детализация», «Менеджер», «Клиент», «История», «Заливка»",
                "На каждой вкладке добавлено краткое описание назначения",
                "Переключатели «Цветность», «Брошюровка», «Фальцовка» выполнены как анимированные сегменты",
                "«Учитывать заливку цветом» и «Резка» — тумблеры с синей подсветкой",
                "Плавная анимация при переключении вкладок",
                "Окно компактное — ровно по ширине строки вкладок, прокрутки на главной нет",
            ]),
            ("📂 Выбор файлов", [
                "Кнопки «Папка» и «Файл» убраны — по клику на зону открывается встроенный проводник",
                "Проводник стартует в папке «Загрузки» и имеет быстрый доступ («Мой компьютер», диск C:)",
                "Редактируемая адресная строка — путь можно вписать вручную и нажать Enter",
                "Столбец «Дата изменения» с сортировкой от нового к старому по клику",
                "Папки и PDF получили отдельные иконки; Enter на папке — вход, на PDF — выбор",
            ]),
            ("🎨 Заливка и детализация", [
                "Единая метрика заливки — покрытие тонером/чернилами (все не-белые пиксели), для цветных и ч/б страниц",
                "Страницы с заливкой более 50% помечаются в детализации как «[заливка]»",
                "Проценты во вкладке «Заливка» и в «Детализации» теперь совпадают",
                "Анализ стал заметно быстрее: многопоточная обработка страниц (в ~3.5 раза)",
            ]),
            ("📐 Нестандартный формат", [
                "Сетка форматов: столбцы A4/A3/A2/A1/A0, строки ×1…×9; цвета по формату",
                "При наведении подсвечиваются ячейка и её строка/столбец — видно, что выбираешь",
                "Строки A0×2…A0×9 отмечены как «ближайший формат» с подсказкой масштаба",
                "При выборе A0×N — предупреждение: печать возможна только в уменьшенном виде",
                "Резка в рулонной печати выставляется автоматически (допуск 40 мм к рулонам 610/841)",
                "Подсказка «?» с примерами; схема-пример резки; заголовок «Обнаружен неизвестный формат»",
            ]),
            ("📄 Отчёт для клиента", [
                "Кнопка «Сгенерировать PDF» — фирменный отчёт A4 с логотипом в цветах логотипа (#EF7F1A)",
                "Кнопки «Копировать» и «Сгенерировать PDF» — в один ряд",
                "Убрана оранжевая плашка сверху — чистая белая шапка с логотипом",
                "Заголовок «Анализ файлов» вынесен в шапку и выделен оранжевым",
                "Дата выровнена по правому краю — больше не накладывается на заголовок",
                "Исправлены «?????» в дате и подвале (шрифт с поддержкой кириллицы)",
                "Внизу оставлена только серая линия-разделитель",
            ]),
            ("👔 Менеджер", [
                "Блоки показывают всю информацию без внутренней прокрутки",
                "Фальцовка: нестандартные/рулонные сворачиваются в строку «A0 → …»",
                "Цветность/фальцовка/брошюровка — без цветового выделения резки (логика сохранена)",
            ]),
            ("⚙️ Параметры", [
                "Количество экземпляров — поле с кнопками «−» и «+», значение не меняется случайно",
                "Кнопки «Нашли ошибку?» (иконка Telegram) и «Что нового» — в одну строку",
                "Версия указана ненавязчиво: в подписи внизу и в заголовке окна",
            ]),
            ("🔄 Обновления", [
                "Автообновление с любой прошлой версии на новую (по GitHub Releases)",
                "Проверка обновлений через latest.json (raw GitHub) — работает даже при исчерпанном лимите GitHub API",
                "Несколько попыток и резервные адреса загрузки — обновление надёжнее на любых компьютерах",
                "При ошибке загрузки обновления показывается конкретная причина",
                "Исправлена критичная ошибка: окно обновления могло исчезать и обновление не запускалось",
                "Диалог обновления не блокирует окно программы",
                "Исправлено отображение версии при запуске из исходников",
                "Попап «Что нового» — безрамочное окно со скруглёнными углами и тенью",
                "Исправлен русский текст в установщике (были «?????») и ошибка ярлыка «Удалить»",
            ]),
        ],
    },
]


def _changelog_entry_html(entry, is_current=False):
    marker = "🆕 " if is_current else ""
    date = entry.get("date", "")
    date_html = f' <span style="color:{THEME["text_faint"]};font-weight:normal;font-size:12px;">{date}</span>' if date else ""
    title = f"Версия {entry['version']}" if is_current else f"История — версия {entry['version']}"
    parts = [f'<h2 style="color:{THEME["primary"]}; margin-bottom:10px;">{marker}{title}{date_html}</h2>']
    for section_title, items in entry.get("sections", []):
        parts.append(
            f'<h3 style="color:{THEME["primary"]}; border-bottom:1px solid {THEME["border"]}; '
            f'padding-bottom:4px; margin-top:16px;">{section_title}</h3>'
        )
        parts.append("<ul>")
        parts.extend(f"    <li>{item}</li>" for item in items)
        parts.append("</ul>")
    return "\n".join(parts)


def _changelog_html(version):
    """Что нового для текущей версии + история предыдущих изменений."""
    entries = list(_CHANGELOG_HISTORY)
    current_ver = str(version).lstrip("v").strip()
    known = {str(e["version"]) for e in entries}
    if current_ver and current_ver not in known:
        entries.insert(0, {"version": current_ver, "date": "", "sections": [
            ("✨ Изменения", ["Список изменений для этой версии не заполнен."]),
        ]})
    parts = []
    for idx, entry in enumerate(entries):
        is_current = str(entry["version"]) == current_ver
        if idx > 0:
            parts.append(
                f'<hr style="border:none;border-top:1px solid {THEME["divider"]};margin:20px 0 4px 0;">'
            )
        parts.append(_changelog_entry_html(entry, is_current))
    return "\n".join(parts)


class WhatsNewDialog(QDialog):
    """Красивый попап «Что нового»: безрамочное окно со скруглёнными углами."""

    RADIUS = 18

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(620, 620)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        entry = self._current_entry()

        outer = QVBoxLayout(self); outer.setContentsMargins(14, 14, 14, 14); outer.setSpacing(0)
        card = QFrame(); card.setObjectName("WNCard")
        card.setStyleSheet(
            f"QFrame#WNCard{{background:{THEME['surface']};"
            f"border:1px solid {THEME['border_strong']};border-radius:{self.RADIUS}px;}}"
        )
        outer.addWidget(card)

        # Тень, отделяющая окно от фона
        try:
            from PyQt6.QtWidgets import QGraphicsDropShadowEffect
            eff = QGraphicsDropShadowEffect(card)
            eff.setBlurRadius(40)
            eff.setOffset(0, 10)
            eff.setColor(QColor(0, 0, 0, 90))
            card.setGraphicsEffect(eff)
        except Exception:
            pass

        root = QVBoxLayout(card); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Шапка с градиентом ──
        header = QFrame()
        header.setStyleSheet(
            f"QFrame{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 #0A84FF, stop:1 #00C2FF);border:none;"
            f"border-top-left-radius:{self.RADIUS}px;border-top-right-radius:{self.RADIUS}px;}}"
        )
        hl = QVBoxLayout(header); hl.setContentsMargins(26, 22, 26, 22); hl.setSpacing(4)
        htitle = QLabel(f"Версия {self.current_version}")
        htitle.setFont(QFont("Segoe UI Variable Display", 22, QFont.Weight.Bold))
        htitle.setStyleSheet("color:#FFFFFF;background:transparent;")
        hl.addWidget(htitle)
        if entry.get("date"):
            hdate = QLabel(entry["date"])
            hdate.setStyleSheet("color:rgba(255,255,255,0.9);background:transparent;font-size:12px;")
            hl.addWidget(hdate)
        root.addWidget(header)

        # ── Список карточек ──
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(18, 16, 18, 16); bl.setSpacing(12)
        for section_title, items in entry.get("sections", []):
            bl.addWidget(self._section_card(section_title, items))
        bl.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # ── Кнопка ──
        footer = QWidget(); fl = QVBoxLayout(footer); fl.setContentsMargins(18, 6, 18, 16)
        btn = QPushButton("Отлично")
        btn.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.DemiBold))
        btn.setMinimumHeight(44); btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_qss_button("filled"))
        btn.clicked.connect(self.accept)
        fl.addWidget(btn)
        root.addWidget(footer)

    def _current_entry(self):
        ver = str(self.current_version).lstrip("v").strip()
        for e in _CHANGELOG_HISTORY:
            if str(e["version"]) == ver:
                return e
        return {"version": ver, "date": "", "sections": [("Изменения", ["Список изменений пуст."])]}

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_drag_pos", None) is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _section_card(self, title, items):
        card = QFrame(); card.setObjectName("Card")
        card.setStyleSheet(
            f"QFrame#Card{{background:{THEME['surface']};border:1px solid {THEME['divider']};"
            f"border-radius:{THEME['r_lg']};}}"
        )
        cl = QVBoxLayout(card); cl.setContentsMargins(18, 14, 18, 14); cl.setSpacing(8)
        tl = QLabel(title)
        tl.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        tl.setStyleSheet(f"color:{THEME['text']};background:transparent;")
        cl.addWidget(tl)
        for item in items:
            row = QHBoxLayout(); row.setSpacing(9)
            dot = QLabel("•")
            dot.setStyleSheet(f"color:{THEME['primary']};background:transparent;font-size:16px;font-weight:700;")
            dot.setFixedWidth(12)
            dot.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            row.addWidget(dot)
            txt = QLabel(item)
            txt.setWordWrap(True)
            txt.setStyleSheet(f"color:{THEME['text_muted']};background:transparent;font-size:13px;")
            row.addWidget(txt, stretch=1)
            cl.addLayout(row)
        return card


class DonateDialog(QDialog):
    """Поддержка проекта: только QR-код для перевода через СБП."""

    QR_PATH = "assets/donate_qr.png"
    PHONE = "+7 901 360-06-42"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Поддержать проект")
        self.setFixedSize(460, 700)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(f"QDialog {{ background-color: {THEME['bg']}; color: {THEME['text']}; }}")
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #34C759, stop:1 #00C2FF);border:none;}"
        )
        hl = QVBoxLayout(header); hl.setContentsMargins(24, 20, 24, 20); hl.setSpacing(2)
        t = QLabel("❤️  Поддержать проект")
        t.setFont(QFont("Segoe UI Variable Display", 19, QFont.Weight.Bold))
        t.setStyleSheet("color:#FFFFFF;background:transparent;")
        hl.addWidget(t)
        s = QLabel("Ваш вклад идёт на развитие PDKopirka: новые функции и улучшения")
        s.setStyleSheet("color:rgba(255,255,255,0.9);background:transparent;font-size:12px;")
        s.setWordWrap(True)
        hl.addWidget(s)
        root.addWidget(header)

        body = QWidget(); lay = QVBoxLayout(body); lay.setContentsMargins(22, 18, 22, 20); lay.setSpacing(12)

        # Главный акцент: сканировать QR именно в приложении банка
        callout = QFrame()
        callout.setStyleSheet(
            f"QFrame{{background:{THEME['warning_soft']};border:none;"
            f"border-radius:{THEME['r_md']};}}"
        )
        cl = QHBoxLayout(callout); cl.setContentsMargins(14, 12, 14, 12); cl.setSpacing(10)
        icon = QLabel("📱")
        icon.setStyleSheet("background:transparent;font-size:24px;")
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        cl.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        ctext = QLabel(
            "<b>Важно: отсканируйте QR камерой в приложении банка</b><br>"
            "<span>Откройте приложение банка на телефоне → «Оплата по QR» и наведите камеру.</span>"
        )
        ctext.setTextFormat(Qt.TextFormat.RichText)
        ctext.setWordWrap(True)
        ctext.setStyleSheet(f"color:{THEME['warning_text']};background:transparent;font-size:12px;")
        cl.addWidget(ctext, stretch=1)
        lay.addWidget(callout)

        qr_frame = QFrame(); qr_frame.setObjectName("Card")
        qr_frame.setStyleSheet(
            f"QFrame#Card{{background:{THEME['surface']};border:1px solid {THEME['divider']};"
            f"border-radius:{THEME['r_lg']};}}"
        )
        qfl = QVBoxLayout(qr_frame); qfl.setContentsMargins(16, 16, 16, 16); qfl.setSpacing(8)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(resource_path(self.QR_PATH))
        if not pix.isNull():
            self.qr_label.setPixmap(pix.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.qr_label.setText("QR-код не найден")
            self.qr_label.setStyleSheet(f"color:{THEME['danger']};background:transparent;")
        qfl.addWidget(self.qr_label)
        qr_frame.setMaximumWidth(360)
        lay.addWidget(qr_frame, alignment=Qt.AlignmentFlag.AlignHCenter)

        phone_lbl = QLabel(f"Получатель: <b style='color:{THEME['primary']};'>{self.PHONE}</b>")
        phone_lbl.setTextFormat(Qt.TextFormat.RichText)
        phone_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        phone_lbl.setStyleSheet(f"color:{THEME['text_muted']};background:transparent;font-size:13px;")
        lay.addWidget(phone_lbl)
        lay.addStretch()
        root.addWidget(body, stretch=1)

        btn_close = QPushButton("Закрыть")
        btn_close.setMinimumHeight(46); btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.DemiBold))
        btn_close.setStyleSheet(_qss_button("filled"))
        btn_close.clicked.connect(self.accept)
        footer = QWidget(); fl = QVBoxLayout(footer); fl.setContentsMargins(22, 0, 22, 18)
        fl.addWidget(btn_close)
        root.addWidget(footer)


# ─────────────────────────────────────────────────────────────────────────────
# История расчётов
# ─────────────────────────────────────────────────────────────────────────────

class SortableTableItem(QTableWidgetItem):
    def __init__(self, display_text, sort_value):
        super().__init__(str(display_text))
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, SortableTableItem):
            try:
                return self._sort_value < other._sort_value
            except TypeError:
                return str(self._sort_value) < str(other._sort_value)
        return super().__lt__(other)


class HistoryManager:
    @staticmethod
    def get_dir():
        appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
        path = Path(appdata) / 'PDKopirka' / 'history'
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _sanitize_filename(name):
        return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name)[:80].strip() or "Без_названия"

    @staticmethod
    def save(calc_data, name):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = HistoryManager._sanitize_filename(name)
        filename = f"{ts}__{safe_name}.json"
        filepath = HistoryManager.get_dir() / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(calc_data, f, ensure_ascii=False, indent=2)
        return filepath

    @staticmethod
    def list_all():
        items = []
        for path in HistoryManager.get_dir().glob('*.json'):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                items.append({
                    'path': str(path),
                    'name': data.get('name', path.stem),
                    'saved_at': data.get('saved_at', ''),
                    'data': data,
                })
            except Exception:
                continue
        items.sort(key=lambda x: x['saved_at'], reverse=True)
        return items

    @staticmethod
    def load(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def delete(filepath):
        try:
            os.remove(filepath)
            return True
        except OSError:
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Константы форматов
# ─────────────────────────────────────────────────────────────────────────────

Image.MAX_IMAGE_PIXELS = None
FORMAT_TOLERANCE_MM = 10

ISO_A = {
    "A4": (210, 297), "A3": (297, 420), "A2": (420, 594),
    "A1": (594, 841), "A0": (841, 1189),
}
# Расширенные форматы из справочника (размеры как в панели «Форматы»)
ISO_A_NONSTANDARD = {
    "A4x3": (297, 630), "A4x4": (297, 840), "A4x5": (297, 1050),
    "A4x6": (297, 1260), "A4x7": (297, 1470), "A4x8": (297, 1680), "A4x9": (297, 1890),
    "A3x3": (420, 891), "A3x4": (420, 1188), "A3x5": (420, 1485),
    "A3x6": (420, 1782), "A3x7": (420, 2079), "A3x8": (420, 2376), "A3x9": (420, 2673),
    "A2x3": (594, 1260), "A2x4": (594, 1680), "A2x5": (594, 2100),
    "A2x6": (594, 2520), "A2x7": (594, 2940), "A2x8": (594, 3360), "A2x9": (594, 3780),
    "A1x3": (841, 1782), "A1x4": (841, 2376), "A1x5": (841, 2970),
    "A1x6": (841, 3564), "A1x7": (841, 4158), "A1x8": (841, 4752), "A1x9": (841, 5346),
}

UNPRINTABLE_FORMATS = frozenset({
    "A0x2", "A0x3", "A0x4", "A0x5", "A0x6", "A0x7", "A0x8", "A0x9",
})
# Номинальные размеры A0×N (нельзя печатать) и ближайшие печатаемые (справочник)
A0_OVERSIZE_MM = {
    "A0x2": (1189, 1682), "A0x3": (1189, 2523), "A0x4": (1189, 3364),
    "A0x5": (1189, 4205), "A0x6": (1189, 5046), "A0x7": (1189, 5887),
    "A0x8": (1189, 6728), "A0x9": (1189, 7569),
}
A0_PRINTABLE_MM = {
    "A0x2": (910, 1287), "A0x3": (910, 1930), "A0x4": (910, 2575),
    "A0x5": (910, 3218), "A0x6": (910, 3862), "A0x7": (910, 4505),
    "A0x8": (910, 5150), "A0x9": (910, 5793),
}
PRINTABLE_A0_SIZE_NAMES = {wh: f"{wh[0]}×{wh[1]}" for wh in A0_PRINTABLE_MM.values()}
CONVERSION_RULES = {
    "A4x3": ("A1", 2), "A4x4": ("A1", 2),
    "A3x3": ("A0", 2), "A3x4": ("A0", 2),
}
PAPER_DENSITY_G_PER_MM2 = 5.0 / (210 * 297)
ROLL_WEIGHT_G_PER_MM = 80.0 / 1000.0
BINDING_WEIGHT_G = {"A4": 60.0, "A3": 90.0}
FMT_ORDER = ["A4", "A3", "A2", "A1", "A0"]
KIND_ORDER = ["ч/б", "цвет"]
FILL_MIN_RATIO = 0.50
PAGE_ANALYSIS_DPI = 200

CUTTING_FORMATS = {
    "A4x3", "A4x5", "A4x6", "A4x7", "A4x8", "A4x9",
    "A3x3", "A3x4", "A3x5", "A3x6", "A3x7", "A3x8", "A3x9",
}

# Ширина рулонов, мм
ROLL_WIDTHS_MM = (610, 841)
# Допуск: сторона в пределах ROLL_CUT_TOLERANCE_MM от ширины рулона — резка не нужна
ROLL_CUT_TOLERANCE_MM = 40


def page_needs_cutting(w, h, tol=ROLL_CUT_TOLERANCE_MM):
    """Нужна ли резка для страницы w×h при печати на рулонах 610/841.

    Резка НЕ нужна, если хотя бы одна сторона близко подходит к ширине рулона,
    т.е. лежит в диапазоне [roll - tol; roll] для 610 или 841 мм.
    Иначе остаётся белый участок, который нужно срезать.
    """
    sides = (float(w), float(h))
    for roll in ROLL_WIDTHS_MM:
        lo = roll - tol
        for s in sides:
            if lo <= s <= roll:
                return False
    return True

def _norm_format_key(s):
    return str(s).upper().replace("А", "A").replace("Х", "X").replace(" ", "")


def resolve_format_name(raw):
    """Имя формата из справочника по вводу пользователя."""
    key = _norm_format_key(raw)
    for name in list(ISO_A.keys()) + list(ISO_A_NONSTANDARD.keys()):
        if _norm_format_key(name) == key:
            return name
    for size_name in PRINTABLE_A0_SIZE_NAMES.values():
        if _norm_format_key(size_name) == key:
            return size_name
    return key


def format_dimensions_mm(name):
    """Размер формата в мм или None."""
    if name in ISO_A:
        return ISO_A[name]
    if name in ISO_A_NONSTANDARD:
        return ISO_A_NONSTANDARD[name]
    for wh, label in PRINTABLE_A0_SIZE_NAMES.items():
        if label == name:
            return wh
    return None


def page_size_mm(page):
    """
    Размер листа в мм (меньшая × большая сторона).

    В PDF из AutoCAD/CAD MediaBox часто огромный (например 2000×2000 мм),
    а реальный формат листа — в CropBox / page.rect (видимая область).
    """
    r = page.rect
    w = round(r.width * 25.4 / 72, 1)
    h = round(r.height * 25.4 / 72, 1)
    return tuple(sorted((w, h)))


# ─────────────────────────────────────────────────────────────────────────────
# Лицензия
# ─────────────────────────────────────────────────────────────────────────────

# Секретный Gist: https://gist.github.com/fabilya/6a921f617ea86c154dbad582a9c91dec
LICENSE_CHECK_URL = (
    "https://gist.githubusercontent.com/fabilya/"
    "6a921f617ea86c154dbad582a9c91dec/raw/gistfile1.txt"
)


def _get_key():
    _a = [72, 52, 102, 88, 49, 119, 77, 57]
    _b = [112, 84, 50, 115, 75, 53, 118, 66]
    return "".join(chr(c) for c in _a + _b)


def _verify_token(token):
    try:
        parts = token.strip().split("|")
        if len(parts) != 3:
            return False, "INVALID_FORMAT"
        date_str, status, received_sig = parts
        payload = f"{date_str}|{status}"
        expected_sig = hmac.new(
            _get_key().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, received_sig):
            return False, "INVALID_SIGNATURE"
        token_date = datetime.strptime(date_str, "%Y-%m-%d")
        if (datetime.now() - token_date).days > 30:
            return False, "TOKEN_EXPIRED"
        return True, status
    except Exception:
        return False, "PARSE_ERROR"


def _extract_token_from_gist(text):
    """Берёт первую подходящую строку токена из содержимого Gist."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("|") == 2:
            return line
    return text.strip()


def check_remote_license():
    if not LICENSE_CHECK_URL:
        return True, ""
    try:
        cb = f"{int(time.time())}_{random.randint(0, 999999)}"
        sep = "&" if "?" in LICENSE_CHECK_URL else "?"
        url = f"{LICENSE_CHECK_URL}{sep}_={cb}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "PDKopirka/1.0")
        req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
        req.add_header("Pragma", "no-cache")
        with _urlopen_safe(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8-sig", errors="replace")
        token = _extract_token_from_gist(raw)
        if not token:
            return False, (
                "Ошибка проверки лицензии.\n\n"
                "В Gist пустой файл или нет строки токена.\n\n"
                "Обратитесь к администратору."
            )
        valid, status = _verify_token(token)
        if not valid:
            return False, (
                f"Ошибка проверки лицензии.\n\nКод: {status}\n\n"
                "Обновите токен в Gist (generate_token.py) "
                "и проверьте подключение к интернету."
            )
        if status == "ACTIVE":
            return True, ""
        if status == "BLOCKED":
            return False, (
                "Доступ к программе заблокирован администратором.\n\n"
                "Обратитесь к администратору."
            )
        return False, (
            f"Неизвестный статус лицензии: {status}\n\n"
            "В Gist должен быть токен ACTIVE или BLOCKED."
        )
    except urllib.error.URLError:
        # Если gist недоступен — не блокируем (fail-open)
        return True, ""
    except Exception as e:
        return False, f"Ошибка проверки лицензии:\n{e}"


# ─────────────────────────────────────────────────────────────────────────────
# Виджеты
# ─────────────────────────────────────────────────────────────────────────────

class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class CopiesInput(QWidget):
    """Числовое поле с видимыми кнопками − / +, в стиле дизайна.

    API совпадает с QSpinBox для используемых методов (value, setValue,
    valueChanged, setMinimum/Maximum, blockSignals, setKeyboardTracking).
    """

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.spin = NoScrollSpinBox()
        self.spin.setMinimum(1); self.spin.setMaximum(100); self.spin.setValue(1)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setKeyboardTracking(True)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setFixedHeight(40)
        self.spin.setStyleSheet(
            f"QSpinBox{{background-color:{THEME['surface_sunken']};color:{THEME['text']};"
            f"border:1px solid transparent;border-radius:{THEME['r_md']};"
            f"padding:0 8px;font-size:15px;font-weight:700;min-width:44px;}}"
            f"QSpinBox:focus{{border:1px solid {THEME['primary']};background-color:{THEME['surface']};}}"
        )

        self.btn_minus = QPushButton("−")
        self.btn_plus = QPushButton("+")
        for b in (self.btn_minus, self.btn_plus):
            b.setFixedSize(40, 40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            # Кнопки не берут клавиатурный фокус: иначе при достижении границы
            # (кнопка блокируется) фокус «уезжает» в поле и значение можно
            # случайно изменить стрелками или колесом.
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFont(QFont("Segoe UI Variable Display", 15, QFont.Weight.Bold))
            b.setStyleSheet(
                f"QPushButton{{background-color:{THEME['primary_soft']};color:{THEME['primary_text']};"
                f"border:none;border-radius:{THEME['r_md']};padding:0;}}"
                f"QPushButton:hover{{background-color:#C7DEFB;}}"
                f"QPushButton:pressed{{background-color:#B4D3F8;}}"
                f"QPushButton:disabled{{background-color:{THEME['disabled_bg']};color:{THEME['disabled_fg']};}}"
            )
        self.btn_minus.clicked.connect(lambda: self._step(-1))
        self.btn_plus.clicked.connect(lambda: self._step(1))

        row.addWidget(self.btn_minus)
        row.addWidget(self.spin, stretch=0)
        row.addWidget(self.btn_plus)
        row.addStretch()

        self.spin.valueChanged.connect(self._sync)
        self.spin.valueChanged.connect(self.valueChanged.emit)
        self._sync(self.spin.value())

    def _step(self, delta):
        self.spin.setValue(self.spin.value() + delta)

    def _sync(self, _v=None):
        self.btn_minus.setEnabled(self.spin.value() > self.spin.minimum())
        self.btn_plus.setEnabled(self.spin.value() < self.spin.maximum())

    # ── проксирование API QSpinBox ──
    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self.spin.setValue(v)
        self._sync()

    def setMinimum(self, v):
        self.spin.setMinimum(v); self._sync()

    def setMaximum(self, v):
        self.spin.setMaximum(v); self._sync()

    def minimum(self):
        return self.spin.minimum()

    def maximum(self):
        return self.spin.maximum()

    def blockSignals(self, b):
        return self.spin.blockSignals(b)

    def setKeyboardTracking(self, v):
        self.spin.setKeyboardTracking(v)

    def setButtonSymbols(self, v):
        pass

    def setFixedWidth(self, w):
        super().setFixedWidth(w)

    def wheelEvent(self, event):
        event.ignore()


# ─────────────────────────────────────────────────────────────────────────────
def compact_page_list(pages):
    if not pages:
        return ""
    pages = sorted(pages)
    ranges, start, end = [], pages[0], pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = p
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ",".join(ranges)


# ─────────────────────────────────────────────────────────────────────────────
# Выдвижная панель подсказки форматов
# ─────────────────────────────────────────────────────────────────────────────

def _format_base_colors(base):
    """Мягкие (неяркие) цвета по базовому формату: A4 — голубой, A3 — зелёный,
    A2 — жёлтый, A1 — оранжевый, A0 — красный."""
    palette = {
        "A4": ("#E1F0FE", "#CBE4FC"),   # голубой
        "A3": ("#E2F6E8", "#CDEFD8"),   # зелёный
        "A2": ("#FBF3DA", "#F6E9BF"),   # жёлтый
        "A1": ("#FDEBD6", "#F9DCBC"),   # оранжевый
        "A0": ("#FCE3E3", "#F8D2D2"),   # красный
    }
    return palette.get(base, ("#F0F0F4", "#E4E4EA"))


def _format_hint_style(name):
    if name in UNPRINTABLE_FORMATS:
        return THEME["text_faint"], "Не печатаем"
    if name in PRINTABLE_A0_SIZE_NAMES.values():
        return THEME["success"], "Ближайший формат"
    if name in CUTTING_FORMATS:
        return THEME["primary"], "С учетом резки"
    return THEME["success"], "Без резки"


def _format_chip_palette(name):
    """(фон, фон_при_наведении, цвет_текста) — тональные чипы M3.

    Резка/без резки цветом не выделяются (менеджеру это не нужно — решение
    всё равно принимается в логике). Особые цвета только у «не печатаем»
    и «ближайший формат».
    """
    if name in UNPRINTABLE_FORMATS:
        return THEME["surface_sunken"], THEME["disabled_bg"], THEME["text_faint"]
    if name in PRINTABLE_A0_SIZE_NAMES.values():
        return THEME["nearest_soft"], THEME["nearest_hover"], THEME["nearest_text"]
    return THEME["surface"], THEME["primary_soft"], THEME["text"]


def _format_legend_html():
    return (
        f'<span style="color:{THEME["text_muted"]};font-size:13px;">●</span> Печатаем &nbsp;&nbsp; '
        f'<span style="color:{THEME["nearest_text"]};font-size:13px;">●</span> Ближайший формат &nbsp;&nbsp; '
        f'<span style="color:{THEME["text_faint"]};font-size:13px;">●</span> Не печатаем'
    )


# Сетка справочника: столбцы — базовые форматы, строки — множители (×1…×9).
_FORMAT_COLS = ["A4", "A3", "A2", "A1", "A0"]
_FORMAT_MULTS = [1] + list(range(2, 10))
_FORMAT_ROWS = ["A4", "A3", "A2", "A1"]
_A0_OVERSIZE_ORDER = [f"A0x{i}" for i in range(2, 10)]


class HelpIconButton(QToolButton):
    """Круглая иконка «?»; по нажатию показывает/скрывает облачко с подсказкой."""

    def __init__(self, html, parent=None):
        super().__init__(parent)
        self._html = html
        self._popup = None
        self.setText("?")
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QToolButton{{background:{THEME['primary']};color:#FFFFFF;border:none;"
            f"border-radius:13px;font-weight:800;font-size:14px;}}"
            f"QToolButton:hover{{background:{THEME['primary_hover']};}}"
        )
        self.clicked.connect(self.toggle_popup)

    def toggle_popup(self):
        if self._popup is not None and self._popup.isVisible():
            self._close_popup()
            return
        self._show_popup()

    def _show_popup(self):
        self._popup = QFrame(self.window())
        self._popup.setObjectName("HelpBubble")
        self._popup.setStyleSheet(
            f"QFrame#HelpBubble{{background:{THEME['surface']};"
            f"border:1px solid {THEME['warning']};border-radius:{THEME['r_md']};}}"
            f"QFrame#HelpBubble QLabel{{color:{THEME['text']};font-size:12px;background:transparent;}}"
        )
        lay = QVBoxLayout(self._popup)
        lay.setContentsMargins(14, 12, 14, 12)
        body = QLabel(self._html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setStyleSheet(f"color:{THEME['text']};background:transparent;font-size:12px;")
        lay.addWidget(body)
        self._popup.adjustSize()
        w = min(440, self._popup.sizeHint().width())
        self._popup.setFixedWidth(w)
        self._popup.adjustSize()

        # Позиционируем облачко рядом с иконкой «?»
        btn_tl = self.mapTo(self.window(), self.rect().topRight())
        x = btn_tl.x() + 8
        y = btn_tl.y() + self.height() + 6
        # Не вылезать за пределы окна
        win = self.window().rect()
        if x + self._popup.width() > win.width() - 10:
            x = win.width() - self._popup.width() - 10
        if y + self._popup.height() > win.height() - 10:
            y = btn_tl.y() - self._popup.height() - 6
        self._popup.move(max(10, x), max(10, y))
        self._popup.show()
        self._popup.raise_()

    def _close_popup(self):
        if self._popup is not None:
            self._popup.hide()
            self._popup.deleteLater()
            self._popup = None


class FormatGridCell(QPushButton):
    """Ячейка сетки форматов: сообщает о наведении для подсветки строки/столбца."""

    hovered = pyqtSignal(int, int)
    left = pyqtSignal()

    def __init__(self, row, col, base, text, on_click, parent=None):
        super().__init__(text, parent)
        self._row = row
        self._col = col
        self._base = base
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFlat(True)
        self.setToolTip("")

    def enterEvent(self, event):
        self.hovered.emit(self._row, self._col)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.left.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class A0NearestFormatRow(QFrame):
    """Строка A0×N: «ближайший формат» отдельным (сиреневым) цветом."""

    def __init__(self, key, on_format_click, parent=None):
        super().__init__(parent)
        self._fmt_name = PRINTABLE_A0_SIZE_NAMES[A0_PRINTABLE_MM[key]]
        self._on_format_click = on_format_click
        ow, oh = A0_OVERSIZE_MM[key]
        pw, ph = A0_PRINTABLE_MM[key]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"A0NearestFormatRow {{ background: {THEME['nearest_soft']}; "
            f"border: none; border-radius: {THEME['r_sm']}; }}"
            f"A0NearestFormatRow:hover {{ background: {THEME['nearest_hover']}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(0)
        title = QLabel(f"{key} → {pw}×{ph}")
        title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {THEME['nearest_text']}; background: transparent; border: none;")
        line = QLabel(f"{ow}×{oh}")
        line.setFont(QFont("Segoe UI", 7))
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line.setStyleSheet(f"color: {THEME['nearest_text']}; background: transparent; border: none;")
        lay.addWidget(title)
        lay.addWidget(line)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_format_click:
            self._on_format_click(self._fmt_name)
            event.accept()
            return
        super().mousePressEvent(event)


class FormatHintPanel(QFrame):
    """Справочник форматов: столбцы — A4/A3/A2/A1/A0, строки — множители ×1…×9.

    При наведении на ячейку подсвечиваются её строка и столбец — менеджер
    видит, что именно выбирает.
    """

    def __init__(self, parent=None, on_format_click=None):
        super().__init__(parent)
        self._on_format_click = on_format_click
        self.setStyleSheet(
            f"FormatHintPanel {{ background-color: {THEME['surface']}; "
            f"border: 1px solid {THEME['divider']}; border-radius: {THEME['r_xl']}; color: {THEME['text']}; }}"
        )
        self._cells = {}          # (row,col) -> FormatGridCell
        self._cell_keys = {}      # (row,col) -> name (для палитры)
        self._row_headers = {}    # row -> QLabel
        self._col_headers = {}    # col -> QLabel
        self.setMinimumWidth(680)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        cl = QVBoxLayout(self)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        head = QHBoxLayout(); head.setSpacing(6)
        title = QLabel("📐 Ближайший формат")
        title.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {THEME['text']}; background: transparent; border: none;")
        head.addWidget(title); head.addStretch()
        cl.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)

        # Заголовки столбцов — базовые форматы (яркие)
        for col, base in enumerate(_FORMAT_COLS, start=1):
            cap = QLabel(base)
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
            cap.setMinimumHeight(32)
            cap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._col_headers[col] = cap
            grid.addWidget(cap, 0, col)

        # Строки — множители
        for row, mult in enumerate(_FORMAT_MULTS, start=1):
            row_lbl = QLabel("×1" if mult == 1 else f"×{mult}")
            row_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_lbl.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
            row_lbl.setMinimumHeight(44)
            row_lbl.setFixedWidth(46)
            self._row_headers[row] = row_lbl
            grid.addWidget(row_lbl, row, 0)

            for col, base in enumerate(_FORMAT_COLS, start=1):
                cell = self._make_cell(row, col, base, mult)
                if cell is None:
                    cell = self._make_placeholder(row, col)
                grid.addWidget(cell, row, col)
            grid.setRowStretch(row, 1)

        cl.addLayout(grid, stretch=1)
        self._apply_headers_base()

    def _make_placeholder(self, row, col):
        """Серая плашка на месте отсутствующего формата (например, ×2 у A4)."""
        lbl = QLabel("—")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMinimumHeight(44)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        lbl.setStyleSheet(
            f"color:{THEME['text_faint']};background:{THEME['surface_sunken']};"
            f"border:none;border-radius:{THEME['r_sm']};"
        )
        return lbl

    def _cell_name(self, base, mult):
        """Имя формата для ячейки (без A0-ближайших) или None."""
        if mult == 1:
            return base if base in ISO_A else None
        key = f"{base}x{mult}"
        if base == "A0":
            return key if key in A0_OVERSIZE_MM else None
        return key if key in ISO_A_NONSTANDARD else None

    def _make_cell(self, row, col, base, mult):
        name = self._cell_name(base, mult)
        if name is None:
            return None

        if base == "A0" and mult > 1:
            # A0×N — на кнопке номинальный размер; уменьшение покажем в диалоге.
            ow, oh = A0_OVERSIZE_MM[name]
            cell = FormatGridCell(
                row, col, base, f"{ow}×{oh}",
                lambda n=name: self._click_a0(n),
            )
        else:
            w, h = format_dimensions_mm(name)
            cell = FormatGridCell(
                row, col, base, f"{w}×{h}",
                lambda n=name: self._click_format(n),
            )

        cell.hovered.connect(self._on_hover)
        cell.left.connect(self._on_unhover)
        self._cells[(row, col)] = cell
        self._cell_keys[(row, col)] = name
        cell.setStyleSheet(self._cell_style(name, "base"))
        return cell

    def _click_format(self, name):
        if self._on_format_click:
            self._on_format_click(name)

    def _click_a0(self, key):
        if self._on_format_click:
            self._on_format_click(PRINTABLE_A0_SIZE_NAMES[A0_PRINTABLE_MM[key]])

    # ── подсветка строки и столбца при наведении ──
    def _cell_style(self, name, state):
        # Цвет по базовому формату (A4 голубой … A0 красный), без рамок.
        base = name[0:2]
        bg, bg_h = _format_base_colors(base)
        if state == "active":
            return (f"QPushButton{{background:{THEME['primary']};color:{THEME['text_on_primary']};"
                    f"border:none;border-radius:{THEME['r_sm']};font-weight:700;}}")
        return (f"QPushButton{{background:{bg};color:{THEME['text']};"
                f"border:none;border-radius:{THEME['r_sm']};font-weight:600;}}"
                f"QPushButton:hover{{background:{bg_h};}}")

    def _header_style(self, base, active):
        if active:
            return (f"color:{THEME['text_on_primary']};background:{THEME['primary']};"
                    f"border:none;border-radius:{THEME['r_sm']};font-weight:700;")
        if base is None:
            return (f"color:{THEME['text']};background:{THEME['surface_sunken']};"
                    f"border:none;border-radius:{THEME['r_sm']};font-weight:700;")
        bg, _ = _format_base_colors(base)
        return (f"color:{THEME['text']};background:{bg};"
                f"border:none;border-radius:{THEME['r_sm']};font-weight:700;")

    def _apply_headers_base(self):
        for col, lbl in self._col_headers.items():
            lbl.setStyleSheet(self._header_style(_FORMAT_COLS[col - 1], False))
        for lbl in self._row_headers.values():
            lbl.setStyleSheet(self._header_style(None, False))

    def _on_hover(self, row, col):
        """Прямой угол: активная ячейка + её строка слева + столбец сверху."""
        for (r, c), cell in self._cells.items():
            state = "active" if (r, c) == (row, col) else "base"
            cell.setStyleSheet(self._cell_style(self._cell_keys[(r, c)], state))
        for r, lbl in self._row_headers.items():
            lbl.setStyleSheet(self._header_style(None, r == row))
        for c, lbl in self._col_headers.items():
            lbl.setStyleSheet(self._header_style(_FORMAT_COLS[c - 1], c == col))

    def _on_unhover(self):
        for (r, c), cell in self._cells.items():
            cell.setStyleSheet(self._cell_style(self._cell_keys[(r, c)], "base"))
        self._apply_headers_base()

    def _btn_style(self, name, enabled=True):
        if not enabled:
            return (
                f"QPushButton {{ color: {THEME['text_faint']}; background: {THEME['surface_sunken']}; "
                f"border: none; border-radius: {THEME['r_sm']}; padding: 4px 6px; "
                f"text-align: center; font-weight: 600; }}"
            )
        bg, bg_h, fg = _format_chip_palette(name)
        return (
            f"QPushButton {{ color: {fg}; background: {bg}; "
            f"border: none; border-radius: {THEME['r_sm']}; padding: 4px 6px; "
            f"text-align: center; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {bg_h}; }}"
            f"QPushButton:pressed {{ background: {bg_h}; }}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Диалог подтверждения уменьшения A0×N
# ─────────────────────────────────────────────────────────────────────────────

class A0ScaleConfirmDialog(QDialog):
    """Красивое подтверждение печати A0×N с уменьшением под рулон 910 мм."""

    def __init__(self, key, ow, oh, pw, ph, scale, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Формат нельзя напечатать в масштабе 1:1")
        self.setFixedWidth(540)
        self.setStyleSheet(f"QDialog{{background:{THEME['bg']};color:{THEME['text']};}}")

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Шапка с акцентом (синяя, как кнопки программы)
        header = QFrame()
        header.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #007AFF, stop:1 #00C2FF);border:none;}"
        )
        hl = QVBoxLayout(header); hl.setContentsMargins(24, 20, 24, 20); hl.setSpacing(6)
        t = QLabel(f"⚠️  {key} — уменьшение масштаба")
        t.setFont(QFont("Segoe UI Variable Display", 16, QFont.Weight.Bold))
        t.setStyleSheet("color:#FFFFFF;background:transparent;")
        t.setWordWrap(True)
        hl.addWidget(t)
        s = QLabel("Формат больше рулона, печать возможна только в уменьшенном виде")
        s.setFont(QFont("Segoe UI Variable Display", 16, QFont.Weight.Bold))
        s.setStyleSheet("color:#FFFFFF;background:transparent;")
        s.setWordWrap(True)
        hl.addWidget(s)
        root.addWidget(header)

        body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(24, 20, 24, 20); bl.setSpacing(14)

        # Наглядно: исходный → печатаемый
        card = QFrame(); card.setObjectName("Card")
        card.setStyleSheet(
            f"QFrame#Card{{background:{THEME['surface']};border:1px solid {THEME['divider']};"
            f"border-radius:{THEME['r_lg']};}}"
        )
        cl = QVBoxLayout(card); cl.setContentsMargins(20, 16, 20, 16); cl.setSpacing(10)

        def row(title, value, color, bold=False):
            r = QHBoxLayout()
            lbl = QLabel(title)
            lbl.setStyleSheet(f"color:{THEME['text_muted']};background:transparent;font-size:13px;font-weight:600;")
            val = QLabel(value)
            val.setFont(QFont("Segoe UI Variable Display", 14, QFont.Weight.Bold))
            val.setStyleSheet(f"color:{color};background:transparent;")
            r.addWidget(lbl); r.addStretch(); r.addWidget(val)
            cl.addLayout(r)

        row("Исходный размер", f"{ow}×{oh} мм", THEME["text"])
        arrow = QLabel("⬇")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet(f"color:{THEME['text_muted']};background:transparent;font-size:16px;")
        cl.addWidget(arrow)
        row("В масштабе " + f"{scale:.1f}%", f"{pw}×{ph} мм", THEME["primary"])
        bl.addWidget(card)

        warn = QLabel("❗ Обязательно предупредите клиента о том, что формат будет уменьшен.")
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"color:{THEME['primary_text']};background:{THEME['primary_soft']};"
            f"border:none;border-radius:{THEME['r_md']};padding:12px;font-size:12px;font-weight:600;"
        )
        bl.addWidget(warn)

        btns = QHBoxLayout(); btns.setSpacing(10)
        btn_no = QPushButton("Отмена"); btn_no.setMinimumHeight(46)
        btn_no.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_no.setStyleSheet(_qss_button("neutral")); btn_no.clicked.connect(self.reject)
        btns.addWidget(btn_no)
        btn_yes = QPushButton("Да, продолжить"); btn_yes.setMinimumHeight(46)
        btn_yes.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_yes.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.DemiBold))
        btn_yes.setStyleSheet(_qss_button("filled")); btn_yes.clicked.connect(self.accept)
        btns.addWidget(btn_yes, stretch=1)
        bl.addLayout(btns)

        root.addWidget(body)


# ─────────────────────────────────────────────────────────────────────────────
# Диалог нестандартного формата
# ─────────────────────────────────────────────────────────────────────────────

class UnknownFormatDialog(QDialog):
    def __init__(self, w, h, color, pages, pdf_path, parent=None):
        super().__init__(parent)
        self.w, self.h, self.color = w, h, color
        self.pages, self.pdf_path = pages, pdf_path
        self.result_action = self.result_value = self._temp_file = None
        self._overlay = None
        self._parent_window = parent
        if parent is not None:
            self._overlay = ModalOverlay(parent)
            self._overlay.show()
            self._overlay.raise_()
        self._build_ui()
        # После показа диалога — привлекаем внимание пользователя
        QTimer.singleShot(0, self._attract_attention)

    def _attract_attention(self):
        """Подсвечивает программу в панели задач и поднимает окно наверх."""
        target = self._parent_window or self
        # Поднимаем главное окно (с ним поднимется и диалог)
        bring_window_to_front(target)
        # Мигаем иконкой в трее, пока пользователь не переключится
        flash_taskbar_icon(target, count=0)
        # Поднимаем сам диалог поверх главного окна
        bring_window_to_front(self)

    def _build_ui(self):
        cs = "цвет" if self.color else "ч/б"
        rng = compact_page_list(self.pages)
        self.setWindowTitle("Нестандартный формат")
        self.setFixedWidth(1270)
        self.setModal(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Левая колонка — без прокрутки: высота окна подстраивается под содержимое.
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFixedWidth(545)
        left_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")

        mw = QWidget()
        root = QVBoxLayout(mw)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        # Информация о файле
        ib = QGroupBox("⚠️  Обнаружен неизвестный формат")
        ib.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
        ib.setStyleSheet(
            f"QGroupBox{{color:{THEME['danger_text']};background-color:{THEME['surface']};"
            f"border:1px solid {THEME['danger']};border-radius:{THEME['r_lg']};"
            f"margin-top:14px;padding:16px 14px 12px 14px;}}"
            f"QGroupBox::title{{color:{THEME['danger_text']};subcontrol-origin:margin;"
            f"subcontrol-position:top left;left:14px;padding:0 6px;}}"
        )
        il = QVBoxLayout(ib)
        for t in [
            f"Файл: <b>{os.path.basename(self.pdf_path)}</b>",
            f"Размер: <b>{self.w} × {self.h} мм</b>",
            f"Цветность: <b>{cs}</b>",
            f"Страниц: <b>{len(self.pages)}</b>  ({rng})",
        ]:
            lb = QLabel(t)
            lb.setFont(QFont("Segoe UI", 9))
            lb.setWordWrap(True)
            lb.setStyleSheet(f"color:{THEME['text']};background:transparent;")
            il.addWidget(lb)
        bo = QPushButton("👁️ Открыть страницы")
        bo.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        bo.setFixedHeight(38)
        bo.setCursor(Qt.CursorShape.PointingHandCursor)
        bo.setStyleSheet(
            f"QPushButton{{background:{THEME['primary']};color:#FFFFFF;border:none;"
            f"border-radius:{THEME['r_md']};padding:6px 12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{THEME['primary_hover']};}}"
        )
        bo.clicked.connect(self._open_pages)
        il.addWidget(bo)
        root.addWidget(ib)

        # Подсказка о выборе формата — на оранжевом фоне
        hint = QLabel(
            "💡 <b>Выберите формат справа</b> (нажмите на подходящий формат)"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.Bold))
        hint.setStyleSheet(
            f"color:#7A3D00;background:rgba(255,149,0,110);border:none;"
            f"border-radius:{THEME['r_md']};padding:12px;"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Вариант — рулонная печать
        rb = QGroupBox("Рулонная печать")
        rb.setStyleSheet(
            f"QGroupBox{{color:{THEME['text']};background-color:{THEME['surface']};}}"
            f"QGroupBox::title{{color:{THEME['text']};}}"
        )
        rl = QVBoxLayout(rb)
        rl.setContentsMargins(10, 6, 10, 10)
        rl.setSpacing(6)

        # Поле длины оставлено скрытым, чтобы не менять логику рулонной печати.
        self.edit_roll = QLineEdit()
        self.edit_roll.setVisible(False)

        roll_row = QHBoxLayout(); roll_row.setSpacing(6)
        ba = QPushButton(
            f"По бо́льшей стороне ({max(self.w, self.h):.0f} мм × {len(self.pages)} стр.)"
        )
        ba.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        ba.setFixedHeight(40)
        ba.setStyleSheet(
            f"QPushButton{{background:{THEME['primary']};color:#FFFFFF;border:none;"
            f"border-radius:{THEME['r_md']};padding:6px 10px;font-weight:600;}}"
            f"QPushButton:hover{{background:{THEME['primary_hover']};}}"
        )
        ba.setCursor(Qt.CursorShape.PointingHandCursor)
        ba.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ba.setMinimumWidth(0)
        ba.clicked.connect(self._apply_auto)
        roll_row.addWidget(ba, stretch=1)
        self.chk_cutting = SwitchCheckBox("Резка")
        # Автоматически: резка нужна, если ни одна сторона не близка к рулону 610/841.
        self.chk_cutting.setChecked(page_needs_cutting(self.w, self.h))
        self.chk_cutting.setStyleSheet(f"color:{THEME['text']};background:transparent;")
        roll_row.addWidget(self.chk_cutting)
        # Иконка-подсказка «?» рядом с резкой
        help_btn = HelpIconButton(self._cutting_help_html())
        roll_row.addWidget(help_btn)
        roll_row.addStretch()
        rl.addLayout(roll_row)

        # Схема-пример под кнопкой «По большей стороне»
        ex = QLabel()
        ex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ex_pix = QPixmap(resource_path("assets/cut_example.png"))
        if not ex_pix.isNull():
            ex.setPixmap(ex_pix.scaled(430, 250, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        ex.setStyleSheet(
            f"background:{THEME['surface']};border:1px solid {THEME['border']};"
            f"border-radius:{THEME['r_md']};padding:6px;"
        )
        rl.addWidget(ex)
        root.addWidget(rb)

        # Пропустить
        bs = QPushButton("Пропустить")
        bs.setFixedHeight(40)
        bs.setCursor(Qt.CursorShape.PointingHandCursor)
        bs.setStyleSheet(_qss_button("neutral"))
        bs.setToolTip("Не учитывать эти страницы")
        bs.clicked.connect(self._skip)
        root.addWidget(bs)

        left_scroll.setWidget(mw)
        outer.addWidget(left_scroll, stretch=0)
        self.hint_panel = FormatHintPanel(
            self, on_format_click=self._apply_format_by_name
        )
        outer.addWidget(self.hint_panel, stretch=1)

    def _cutting_help_html(self):
        return (
            "💡 <b>Когда нужна резка</b><br><br>"
            "Если ни одна из сторон не подходит близко для печати на рулонах "
            "610 / 841 мм — остаётся белый участок, который нужно срезать."
            "<br><br>"
            "<b>Пример №1:</b> Чертёж 420×1680 мм — при печати на рулоне 610 мм "
            "останется незапечатываемая область <b>190 мм</b>."
            "<br><br>"
            "<b>Пример №2:</b> Чертёж 750×3251 мм — при печати на рулоне 841 мм "
            "останется незапечатываемая область <b>91 мм</b>."
            "<br><br>"
            "Для таких форматов обязательно включайте <b>«Резка»</b>."
            "<br><br>"
            "<b>Рекомендуется сначала пользоваться таблицей форматов</b> — там резка "
            "уже учтена, если формат её требует."
        )

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parent()
        if parent:
            pg = parent.frameGeometry()
            # Без прокрутки: высота окна = высоте содержимого левой колонки.
            sc = self.findChild(QScrollArea)
            need_h = 720
            if sc is not None and sc.widget() is not None:
                need_h = max(need_h, sc.widget().sizeHint().height())
            self.setFixedHeight(min(need_h, 1040))
            x = pg.x() + max(0, (pg.width() - self.width()) // 2)
            y = pg.y() + max(0, (pg.height() - self.height()) // 2)
            self.move(x, y)

    def closeEvent(self, event):
        if self.result_action is None:
            self.result_action = "skip"
            self.result_value = None
        self._destroy_overlay()
        super().closeEvent(event)

    def done(self, result):
        # Срабатывает при accept() / reject() — убираем overlay и останавливаем мигание
        self._destroy_overlay()
        if self._parent_window is not None:
            stop_flash_taskbar(self._parent_window)
        super().done(result)

    def focusInEvent(self, event):
        # Когда пользователь переключился на диалог — останавливаем мигание
        if self._parent_window is not None:
            stop_flash_taskbar(self._parent_window)
        super().focusInEvent(event)

    def _destroy_overlay(self):
        if self._overlay is not None:
            try:
                parent = self._overlay.parent()
                if parent is not None:
                    parent.removeEventFilter(self._overlay)
                self._overlay.hide()
                self._overlay.deleteLater()
            except Exception:
                pass
            self._overlay = None

    def _open_pages(self):
        try:
            src = fitz.open(self.pdf_path)
            dst = fitz.open()
            # insert_pdf сохраняет поворот (/Rotate) и границы листа как в оригинале;
            # show_pdf_page часто «обрезает» чертежи из AutoCAD.
            for pn in sorted(self.pages):
                dst.insert_pdf(src, from_page=pn - 1, to_page=pn - 1)
            base = os.path.splitext(os.path.basename(self.pdf_path))[0]
            rng = compact_page_list(self.pages).replace(", ","_")
            tmp_dir = tempfile.gettempdir()
            tmp_path = os.path.join(tmp_dir, f"{base}__стр_{rng}.pdf")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except OSError:
                    tmp_path = os.path.join(tmp_dir, f"{base}__стр_{rng}_{datetime.now().strftime('%H%M%S')}.pdf")
            dst.save(tmp_path); dst.close(); src.close()
            self._temp_file = tmp_path
            if sys.platform == "win32": os.startfile(tmp_path)
            elif sys.platform == "darwin": subprocess.Popen(["open", tmp_path])
            else: subprocess.Popen(["xdg-open", tmp_path])
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть:\n{e}")

    def _open_cut_example(self):
        """Открывает схему примера резки в отдельном окне."""
        path = resource_path("assets/cut_example.png")
        if not os.path.exists(path):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Пример: где нужна резка")
        dlg.setStyleSheet(f"QDialog{{background:{THEME['bg']};}}")
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(10)
        pic = QLabel()
        pix = QPixmap(path)
        pic.setPixmap(pix.scaled(1000, 700, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pic)
        btn = QPushButton("Закрыть"); btn.setMinimumHeight(42)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_qss_button("filled")); btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    def _apply_format_by_name(self, name):
        # Если кликнули по ячейке A0xN — находим исходный A0xN-формат
        a0_key = None
        for key, printable_wh in A0_PRINTABLE_MM.items():
            if PRINTABLE_A0_SIZE_NAMES[printable_wh] == name:
                a0_key = key
                break
        if a0_key:
            ow, oh = A0_OVERSIZE_MM[a0_key]
            pw, ph = A0_PRINTABLE_MM[a0_key]
            scale = min(pw / ow, ph / oh) * 100
            dlg = A0ScaleConfirmDialog(a0_key, ow, oh, pw, ph, scale, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self.result_action = "a0_oversize"
            self.result_value = a0_key
            self.accept()
            return
        self._apply_format(preset=name)

    def _apply_format(self, preset=None):
        raw = (preset or "").strip()
        if not raw:
            QMessageBox.warning(self, "Ошибка", "Выберите формат в справочнике.")
            return
        matched = resolve_format_name(raw)
        if matched in UNPRINTABLE_FORMATS:
            QMessageBox.warning(
                self, "Нельзя печатать",
                f"Формат «{matched}» нельзя распечатать — выберите другой.",
            )
            return
        in_catalog = (
                matched in ISO_A
                or matched in ISO_A_NONSTANDARD
                or matched in PRINTABLE_A0_SIZE_NAMES.values()
        )
        if not in_catalog:
            if QMessageBox.question(
                    self, "Неизвестный формат",
                    f'Формат «{raw}» не найден в справочнике.\nВсё равно использовать?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.No:
                return
        self.result_action = "format"
        self.result_value = matched
        self.accept()

    def _apply_roll(self):
        t = self.edit_roll.text().strip().replace(",", ".")
        try:
            v = float(t)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Введите числовое значение в мм.")
            return
        if v <= 0:
            QMessageBox.warning(self, "Ошибка", "Значение должно быть > 0.")
            return
        self.result_action = "roll_mm"
        self.result_value = (v, self.chk_cutting.isChecked())
        self.accept()

    def _apply_auto(self):
        self.result_action = "roll_auto"
        self.result_value = (max(self.w, self.h), self.chk_cutting.isChecked())
        self.accept()

    def _skip(self):
        self.result_action="skip"; self.result_value=None; self.accept()


class SwitchCheckBox(QCheckBox):
    """Современный toggle-switch: скруглённый трек + белый «бегунок»."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)
        # Ширина по содержимому (трек + текст), но не меньше, чтобы тумблер не сжимался.
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # Свитч не должен держать клавиатурный фокус: иначе при disable()
        # Qt переводит фокус на следующий виджет (например, на поле экземпляров).
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self):
        hint = super().sizeHint()
        return hint.__class__(max(hint.width(), 60), max(hint.height(), 30))

    def sizeHint(self):
        hint = super().sizeHint()
        return hint.__class__(hint.width() + 8, max(hint.height(), 30))

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPainterPath
        from PyQt6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = 46, 26
        y = (self.height() - h) // 2
        track = QRectF(0, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(track, h / 2, h / 2)

        if not self.isEnabled():
            track_color = QColor(THEME["disabled_bg"])
        elif self.isChecked():
            grad = QLinearGradient(0, y, w, y + h)
            grad.setColorAt(0.0, QColor("#0A84FF"))
            grad.setColorAt(1.0, QColor("#00C2FF"))
            p.fillPath(path, grad)
            track_color = None
        else:
            track_color = QColor(THEME["seg_track"])
        if track_color is not None:
            p.fillPath(path, track_color)

        knob_d = h - 6
        knob_x = (w - knob_d - 3) if self.isChecked() else 3
        knob = QRectF(knob_x, y + 3, knob_d, knob_d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(knob)

        text_x = w + 10
        p.setPen(QColor(THEME["disabled_fg"] if not self.isEnabled() else THEME["text"]))
        p.setFont(self.font())
        p.drawText(
            QRectF(text_x, 0, self.width() - text_x, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        p.end()

    def hitButton(self, pos):
        return pos.x() < 56 and 0 <= pos.y() <= self.height()


class SegmentedControl(QWidget):
    """iOS-сегмент-контрол: трек + анимированный белый «бегунок», как .segmented."""

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self._options = list(options)
        self._index = 0
        self._thumb = 0.0
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Только мышь: при отключении сегмента фокус не должен «уезжать» на другие поля.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._anim = QPropertyAnimation(self, b"thumb", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setMinimumWidth(max(90, 70 * len(self._options)))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._on_change = None

    def getThumb(self):
        return self._thumb

    def setThumb(self, value):
        self._thumb = float(value)
        self.update()

    thumb = pyqtProperty(float, fget=getThumb, fset=setThumb)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, idx, animate=True):
        if not (0 <= idx < len(self._options)) or idx == self._index:
            if idx == self._index:
                return
            return
        self._index = idx
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._thumb)
            self._anim.setEndValue(float(idx))
            self._anim.start()
        else:
            self.setThumb(float(idx))
        if self._on_change:
            self._on_change(idx)

    def mousePressEvent(self, event):
        n = len(self._options)
        if n <= 0:
            return
        seg_w = self.width() / n
        self.setCurrentIndex(int(event.position().x() // seg_w))

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPainterPath
        from PyQt6.QtCore import QRectF
        n = len(self._options)
        if n == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(0, 0, w, h)
        path = QPainterPath(); path.addRoundedRect(track, h / 2, h / 2)
        p.fillPath(path, QColor(THEME["seg_track"]))

        seg_w = w / n
        thumb = QRectF(self._thumb * seg_w + 2, 2, seg_w - 4, h - 4)
        tpath = QPainterPath(); tpath.addRoundedRect(thumb, (h - 4) / 2, (h - 4) / 2)
        # Активный сегмент — сплошной primary в любом состоянии (как у «Брошюровки»).
        p.fillPath(tpath, QColor(THEME["primary"]))

        for i, text in enumerate(self._options):
            rect = QRectF(i * seg_w, 0, seg_w, h)
            active = (abs(self._thumb - i) < 0.5)
            if active:
                p.setPen(QColor(THEME["text_on_primary"]))
            else:
                p.setPen(QColor(THEME["text_muted"]))
            f = self.font(); f.setBold(active); p.setFont(f)
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
        p.end()


class ModalOverlay(QWidget):
    """Полупрозрачный затемняющий слой поверх главного окна."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 120);")
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):
        # Подстраиваем overlay под размер родителя при ресайзе
        if event.type() == QEvent.Type.Resize and obj is self.parent():
            self.setGeometry(self.parent().rect())
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        # Поглощаем клики, чтобы они не попадали на главное окно
        event.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Поток анализа
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisThread(QThread):
    progress        = pyqtSignal(int)
    status          = pyqtSignal(str)
    need_user_input = pyqtSignal(float, float, bool, list, str)
    finished        = pyqtSignal(dict, int, list, list)
    error           = pyqtSignal(str)
    stopped         = pyqtSignal()

    def __init__(self, pdfs, force_bw=False, count_fill=False):
        super().__init__()
        self.pdfs = pdfs; self.force_bw = force_bw; self.count_fill = count_fill
        self._user_action = self._user_value = None
        self._stop_requested = False
        import threading; self._wait_event = threading.Event(); self._pause_event = threading.Event()

    def request_stop(self):
        self._stop_requested = True; self._user_action = "skip"; self._user_value = None
        self._pause_event.clear(); self._wait_event.set()

    def request_pause(self):
        self._pause_event.set()

    def request_resume(self):
        self._pause_event.clear()

    def is_paused(self):
        return self._pause_event.is_set()

    def _pause_point(self):
        """Блокирует поток, пока включена пауза (или пока не запрошен стоп)."""
        while self._pause_event.is_set() and not self._stop_requested:
            time.sleep(0.05)

    def set_user_response(self, action, value):
        self._user_action = action; self._user_value = value; self._wait_event.set()

    def _wait_for_user(self):
        self._wait_event.clear(); self._wait_event.wait()

    def analyze_page(self, page, tol=12, white_thr=252, color_tol=15,
                     color_white_thr=248, min_colored_pixels=30,
                     min_colored_ratio=0.00005, pastel_ratio_threshold=0.02):
        """Один рендер страницы вместо трёх.

        Возвращает (цветная_страница, цветная_заливка%, покрытие%):
        цветность — как detect_page_color (учитывает пастельные фоны),
        покрытие% — доля всех не-белых пикселей (единая метрика заливки).
        """
        try:
            scale = PAGE_ANALYSIS_DPI / 72
            pix = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False
            )
            # Читаем пиксели напрямую (без PNG-энкода и PIL) — примерно в 2 раза быстрее.
            a = np.frombuffer(pix.samples, dtype=np.uint8)
            if pix.n == 3:
                a = a.reshape(pix.height, pix.width, 3)
            elif pix.n == 4:
                a = a.reshape(pix.height, pix.width, 4)[..., :3]
            else:
                a = a.reshape(pix.height, pix.width, pix.n)[..., :3]
            if a.ndim != 3:
                return (False, 0.0, 0.0)
            r = a[..., 0].astype(np.int16)
            g = a[..., 1].astype(np.int16)
            b = a[..., 2].astype(np.int16)
            mx = np.maximum(np.maximum(r, g), b)
            mn = np.minimum(np.minimum(r, g), b)
            diff = mx - mn
            total = a.shape[0] * a.shape[1]
            if total <= 0:
                return (False, 0.0, 0.0)

            not_white = mx < white_thr
            colored = not_white & (diff >= tol)
            color_pct = round(100.0 * int(colored.sum()) / total, 2)
            ink_pct = round(100.0 * int(not_white.sum()) / total, 2)

            is_color = False
            ink_dark = mx < color_white_thr
            ic = int(ink_dark.sum())
            if ic > 0:
                cc = int((ink_dark & (diff > color_tol)).sum())
                if cc >= min_colored_pixels or (cc / ic) >= min_colored_ratio:
                    is_color = True
            if not is_color:
                pastel = (mx > 180) & (mx < 254) & (diff >= 5)
                if int(pastel.sum()) / total >= pastel_ratio_threshold:
                    is_color = True

            return (is_color, color_pct, ink_pct)
        except Exception:
            return (False, 0.0, 0.0)

    def match_format_with_tolerance(self, w, h, table, tol=FORMAT_TOLERANCE_MM):
        for name,(fw,fh) in table.items():
            if ((abs(w-fw)<=tol and abs(h-fh)<=tol) or (abs(h-fw)<=tol and abs(w-fh)<=tol)):
                return name
        return None

    def _analyze_single_page(self, pdf_path, pno):
        """Анализ одной страницы в отдельном потоке (открывает свой документ)."""
        doc = None
        try:
            doc = fitz.open(pdf_path)
            p = doc[pno]
            w, h = page_size_mm(p)
            if self.count_fill and not self.force_bw:
                col, color_pct, ink_pct = self.analyze_page(p)
                fill = (color_pct, ink_pct)
            else:
                col = False if self.force_bw else self.analyze_page(p)[0]
                fill = None
            return pno, w, h, col, fill, None
        except Exception as e:
            return pno, 0.0, 0.0, False, None, str(e)
        finally:
            if doc is not None:
                doc.close()

    def run(self):
        try:
            grand=defaultdict(float); total_source=0; file_page_counts=[]; file_details=[]; total_files=len(self.pdfs)
            from concurrent.futures import ThreadPoolExecutor
            # Число потоков: по числу ядер, разумный диапазон
            max_workers = max(2, min(8, (os.cpu_count() or 4)))
            # Нестандартные groups собираем со всех файлов и спрашиваем в самом конце
            pending_unknown = []  # (pdf_path, w, h, col, pages)
            for file_idx, pdf_path in enumerate(self.pdfs):
                if self._stop_requested: break
                self._pause_point()
                if self._stop_requested: break
                try:
                    doc=fitz.open(pdf_path)
                    total=len(doc)
                    doc.close()
                    total_source+=total; file_page_counts.append(total)
                    name=os.path.basename(pdf_path); self.status.emit(f"Анализ: {name} ({total} стр.)")
                    ff=defaultdict(int); fp=defaultdict(list); frb=frc=0.0; frb_p,frc_p=[],[]
                    cg=defaultdict(list); file_roll_groups=[]; file_fill_pages=[]; file_fill_pcts={}

                    done=0
                    # Параллельно анализируем страницы (рендер PDF отпускает GIL)
                    with ThreadPoolExecutor(max_workers=max_workers) as ex:
                        futures = [ex.submit(self._analyze_single_page, pdf_path, i)
                                   for i in range(total)]
                        for fut in futures:
                            if self._stop_requested: break
                            self._pause_point()
                            if self._stop_requested: break
                            pno, w, h, col, fill, err = fut.result()
                            if err:
                                continue
                            pn = pno + 1
                            if fill is not None:
                                file_fill_pcts[pn] = fill
                                if fill[1] > FILL_MIN_RATIO * 100:
                                    file_fill_pages.append(pn)
                            fA=self.match_format_with_tolerance(w,h,ISO_A)
                            fN=self.match_format_with_tolerance(w,h,ISO_A_NONSTANDARD)
                            if fA:
                                key=f"{fA} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            elif fN:
                                key=f"{fN} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            else: cg[(w,h,col)].append(pn)
                            done+=1
                            prog=int(100*(file_idx+(done)/total)/total_files); self.progress.emit(prog)
                    if self._stop_requested:
                        file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups,"fill_pages":sorted(file_fill_pages),"fill_pcts":file_fill_pcts}); break
                    # Запоминаем нестандартные группы для обработки после всех файлов
                    for (w,h,col),pages in cg.items():
                        pending_unknown.append((name, pdf_path, w, h, col, pages))
                    file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups,"fill_pages":sorted(file_fill_pages),"fill_pcts":file_fill_pcts})
                except Exception as e: self.error.emit(f"Ошибка при обработке {pdf_path}: {e}"); continue

            # ── После анализа всех файлов: по очереди спрашиваем про нестандартные форматы ──
            for (name, pdf_path, w, h, col, pages) in pending_unknown:
                if self._stop_requested: break
                self._pause_point()
                if self._stop_requested: break
                self.need_user_input.emit(w,h,col,pages,pdf_path); self._wait_for_user()
                # Ответ применяем к нужному файлу (последний добавленный с этим именем)
                fd_idx = None
                for k in range(len(file_details)-1, -1, -1):
                    if file_details[k].get("name") == name:
                        fd_idx = k; break
                if fd_idx is None:
                    continue
                fd = file_details[fd_idx]
                action=self._user_action; value=self._user_value; kind="цвет" if col else "ч/б"
                ff = fd["formats"]; fp = fd["pages"]
                if action=="skip":
                    pass
                elif action=="format":
                    key=f"{value} {kind}"; grand[key]+=len(pages); ff[key]=ff.get(key,0)+len(pages); fp.setdefault(key,[]).extend(pages)
                elif action == "a0_oversize":
                    a0_key = value
                    pw, ph = A0_PRINTABLE_MM[a0_key]
                    ow, oh = A0_OVERSIZE_MM[a0_key]
                    key = f"{a0_key} {kind}"
                    grand[key] += len(pages)
                    ff[key] = ff.get(key,0)+len(pages)
                    fp.setdefault(key,[]).extend(pages)
                    mm = max(pw, ph) * len(pages)
                    if col:
                        grand["Рулон цвет мм"] += mm; fd["roll_color"] = fd.get("roll_color",0)+mm
                        fd["roll_color_pages"] = sorted(set(fd.get("roll_color_pages",[]))|set(pages))
                    else:
                        grand["Рулон ч/б мм"] += mm; fd["roll_bw"] = fd.get("roll_bw",0)+mm
                        fd["roll_bw_pages"] = sorted(set(fd.get("roll_bw_pages",[]))|set(pages))
                    fd.setdefault("roll_groups",[]).append({
                        "w": ow, "h": oh, "color": col, "count": len(pages),
                        "per_page_mm": max(pw, ph), "total_mm": mm, "pages": sorted(pages),
                        "cutting": False, "a0_key": a0_key,
                        "printable_w": pw, "printable_h": ph,
                    })
                elif action in ("roll_mm", "roll_auto"):
                    if isinstance(value, tuple):
                        ppm, need_cut = float(value[0]), bool(value[1])
                    else:
                        ppm, need_cut = float(value), False
                    mm = ppm * len(pages)
                    if col:
                        grand["Рулон цвет мм"] += mm; fd["roll_color"] = fd.get("roll_color",0)+mm
                        fd["roll_color_pages"] = sorted(set(fd.get("roll_color_pages",[]))|set(pages))
                    else:
                        grand["Рулон ч/б мм"] += mm; fd["roll_bw"] = fd.get("roll_bw",0)+mm
                        fd["roll_bw_pages"] = sorted(set(fd.get("roll_bw_pages",[]))|set(pages))
                    fd.setdefault("roll_groups",[]).append({
                        "w": w, "h": h, "color": col, "count": len(pages),
                        "per_page_mm": ppm, "total_mm": mm, "pages": sorted(pages),
                        "cutting": need_cut,
                    })
                    sk = f"{w:.0f}×{h:.0f}"
                    grand[f"_roll_fold_{sk}_{kind}"] = grand.get(f"_roll_fold_{sk}_{kind}", 0) + len(pages)

            if self._stop_requested:
                self.finished.emit(dict(grand),total_source,file_page_counts,file_details); self.stopped.emit()
            else:
                self.progress.emit(100); self.finished.emit(dict(grand),total_source,file_page_counts,file_details)
        except Exception as e: self.error.emit(f"Критическая ошибка: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────
class DropArea(QFrame):
    """Область для перетаскивания и клика (открывает выбор папки/файлов)."""

    files_dropped = pyqtSignal(list)
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._default_style = (
            f"DropArea {{ background-color: {THEME['surface_alt']}; "
            f"border: 2px dashed {THEME['primary_border']}; border-radius: {THEME['r_xl']}; }}"
        )
        self._hover_style = (
            f"DropArea {{ background-color: {THEME['primary_soft']}; "
            f"border: 2px dashed {THEME['primary']}; border-radius: {THEME['r_xl']}; }}"
        )
        self._selected_style = (
            f"DropArea {{ background-color: {THEME['success_soft']}; "
            f"border: 2px dashed {THEME['success']}; border-radius: {THEME['r_xl']}; }}"
        )
        self.setStyleSheet(self._default_style)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        # Вертикальное центрирование через stretch: без AlignCenter, иначе метки
        # сжимаются по sizeHint и длинный путь не помещается (обрезается в пустоту).
        layout.addStretch()

        self.icon_label = QLabel("📥")
        self.icon_label.setFont(QFont("Segoe UI Emoji", 30))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background:transparent;border:none;")
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("Переместите сюда папку или файл")
        self.title_label.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            f"color:{THEME['primary']};background:transparent;border:none;"
        )
        self.title_label.setWordWrap(True)
        # Клик по тексту должен открывать проводник, а не выделять текст.
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Длинный путь не должен влиять на минимальную ширину окна.
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(0)
        layout.addWidget(self.title_label)

        self.sub_label = QLabel("нажмите, чтобы выбрать папку или файлы")
        self.sub_label.setFont(QFont("Segoe UI", 9))
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setStyleSheet(
            f"color:{THEME['text_muted']};background:transparent;border:none;"
        )
        self.sub_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.sub_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.sub_label.setMinimumWidth(0)
        layout.addWidget(self.sub_label)
        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def set_selected_path(self, path, info_suffix=""):
        self.setStyleSheet(self._selected_style)
        self.icon_label.setText("")
        self.icon_label.setVisible(False)
        self.sub_label.setVisible(False)
        display = path if not info_suffix else f"{path}  {info_suffix}"
        self._full_text = display
        self.title_label.setFont(QFont("Segoe UI", 9))
        self.title_label.setWordWrap(False)
        self.title_label.setStyleSheet(
            f"color:{THEME['success']};background:transparent;border:none;"
        )
        # Длинный путь не должен растягивать окно: обрезаем, полный — в подсказке.
        self.title_label.setToolTip(display)
        self._update_elide()

    def _update_elide(self):
        text = getattr(self, "_full_text", "")
        if not text:
            return
        width = max(40, self.title_label.width())
        metrics = QFontMetrics(self.title_label.font())
        self.title_label.setText(
            metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elide()

    def reset(self):
        self.setStyleSheet(self._default_style)
        self._full_text = ""
        self.icon_label.setText("📥")
        self.icon_label.setVisible(True)
        self.sub_label.setVisible(True)
        self.title_label.setText("Переместите сюда папку или файл")
        self.title_label.setToolTip("")
        self.title_label.setFont(QFont("Segoe UI Variable Display", 11, QFont.Weight.DemiBold))
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            f"color:{THEME['primary']};background:transparent;border:none;"
        )

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isdir(path) or path.lower().endswith(".pdf"):
                event.acceptProposedAction()
                self.setStyleSheet(self._hover_style)
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # Если иконка скрыта — значит путь выбран
        if not self.icon_label.isVisible():
            self.setStyleSheet(self._selected_style)
        else:
            self.setStyleSheet(self._default_style)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isdir(p) or p.lower().endswith(".pdf"):
                paths.append(p)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.files_dropped.emit(paths)


class PathPickerDialog(QDialog):
    """Проводник в стиле программы: быстрый доступ слева, адресная строка,
    выбор папки или одного/нескольких PDF.

    Открывается в папке «Загрузки». В адресную строку можно вручную вписать
    путь к папке или файлу и нажать Enter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор папки или PDF файлов")
        self.resize(860, 600)
        self._cwd = self._default_dir()
        self._history = []
        self._selected_files = []
        self.setStyleSheet(f"QDialog {{ background-color: {THEME['bg']}; color: {THEME['text']}; }}")

        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(10)

        # Навигация
        nav = QHBoxLayout(); nav.setSpacing(8)
        self.btn_back = QPushButton("←  Назад")
        self.btn_back.setToolTip("Перейти в папку выше")
        self.btn_back.setStyleSheet(_qss_button("tonal")); self.btn_back.clicked.connect(self._go_up)
        nav.addWidget(self.btn_back)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Введите путь к папке или файлу и нажмите Enter")
        self.path_edit.setStyleSheet(
            f"QLineEdit{{background-color:{THEME['surface']};border:1px solid {THEME['border']};"
            f"border-radius:{THEME['r_md']};padding:9px 12px;color:{THEME['text']};}}"
            f"QLineEdit:focus{{border:1px solid {THEME['primary']};}}"
        )
        self.path_edit.returnPressed.connect(self._navigate_from_edit)
        nav.addWidget(self.path_edit, stretch=1)
        root.addLayout(nav)

        # Тело: быстрый доступ + список
        body = QHBoxLayout(); body.setSpacing(10)

        side = QVBoxLayout(); side.setSpacing(6)
        self.quick = QListWidget()
        self.quick.setFixedWidth(180)
        self.quick.setStyleSheet(
            f"QListWidget{{background-color:{THEME['surface']};color:{THEME['text']};"
            f"border:1px solid {THEME['divider']};border-radius:{THEME['r_md']};outline:none;padding:4px;}}"
            f"QListWidget::item{{padding:8px 8px;border-radius:{THEME['r_sm']};}}"
            f"QListWidget::item:selected{{background-color:{THEME['primary_soft']};color:{THEME['primary_text']};}}"
        )
        self._populate_quick()
        self.quick.itemClicked.connect(self._on_quick_click)
        side.addWidget(self.quick, stretch=1)
        body.addLayout(side)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Имя", "Дата изменения"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        self.table.installEventFilter(self)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSortIndicatorShown(True)
        hdr.setSectionsClickable(True)
        hdr.sortIndicatorChanged.connect(self._on_sort_changed)
        self.table.setStyleSheet(
            f"QTableWidget{{background-color:{THEME['surface']};color:{THEME['text']};"
            f"border:1px solid {THEME['divider']};border-radius:{THEME['r_md']};outline:none;}}"
            f"QTableWidget::item{{padding:6px 8px;border-bottom:1px solid {THEME['divider']};}}"
            f"QTableWidget::item:selected{{background-color:{THEME['primary_soft']};color:{THEME['primary_text']};}}"
        )
        self._sort_col = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._rows = []
        self._icon_cache = {}
        body.addWidget(self.table, stretch=1)
        root.addLayout(body, stretch=1)

        self.hint = QLabel("Двойной клик по папке — войти. Выберите папку или один/несколько PDF (Ctrl/Shift) и нажмите «Выбрать».")
        self.hint.setStyleSheet(f"color:{THEME['text_muted']};font-size:12px;background:transparent;")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # Кнопки
        btns = QHBoxLayout(); btns.setSpacing(10); btns.addStretch()
        btn_cancel = QPushButton("Отмена"); btn_cancel.setStyleSheet(_qss_button("neutral"))
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_cancel)
        btn_pick_folder = QPushButton("📂  Выбрать папку"); btn_pick_folder.setStyleSheet(_qss_button("tonal"))
        btn_pick_folder.clicked.connect(self._pick_folder)
        btns.addWidget(btn_pick_folder)
        btn_ok = QPushButton("✅  Выбрать"); btn_ok.setStyleSheet(_qss_button("filled"))
        btn_ok.clicked.connect(self._pick_selected)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

        self._refresh()

    def _default_dir(self):
        """Стартовая папка — «Загрузки», с откатом на домашнюю."""
        candidates = [
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(os.path.expanduser("~"), "Загрузки"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c
        return os.path.expanduser("~")

    def _populate_quick(self):
        home = os.path.expanduser("~")
        places = [
            ("💻  Мой компьютер", None),
            ("⬇  Загрузки", self._default_dir()),
            ("🖥  Рабочий стол", os.path.join(home, "Desktop")),
            ("📄  Документы", os.path.join(home, "Documents")),
            ("🖼  Изображения", os.path.join(home, "Pictures")),
        ]
        for label, path in places:
            if path is None or os.path.isdir(path):
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.quick.addItem(item)

    def _list_drives(self):
        """Список доступных дисков Windows."""
        drives = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
        return drives

    def _on_quick_click(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path is None:
            # «Мой компьютер» — показываем список дисков
            self._rows = []
            self._cwd = "Мой компьютер"
            self.path_edit.setText(self._cwd)
            for drive in self._list_drives():
                try:
                    mtime = os.path.getmtime(drive)
                except Exception:
                    mtime = 0
                self._rows.append({"kind": "dir", "path": drive, "name": drive, "mtime": mtime})
            self._refresh_highlight = None
            self._populate_table()
            return
        if os.path.isdir(path):
            self._navigate_to(path)

    def _navigate_from_edit(self):
        raw = self.path_edit.text().strip().strip('"')
        if not raw:
            return
        if os.path.isdir(raw):
            self._navigate_to(os.path.abspath(raw))
        elif os.path.isfile(raw):
            # Если ввели путь к файлу — открываем его папку и выделяем файл
            self._navigate_to(os.path.dirname(os.path.abspath(raw)))
            self._refresh(highlight=os.path.abspath(raw))
        else:
            self.hint.setText("❌ Путь не найден: " + raw)

    def _file_icon(self, kind):
        """Иконки: жёлтая папка и красный PDF-документ (рисуются кодом)."""
        key = kind
        if key in self._icon_cache:
            return self._icon_cache[key]
        from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QPen
        px = QPixmap(20, 20); px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "dir":
            body = QPainterPath()
            body.addRoundedRect(1, 5, 18, 12, 2.5, 2.5)
            tab = QPainterPath()
            tab.addRoundedRect(1, 3, 9, 6, 2, 2)
            p.fillPath(tab, QColor("#F6C452"))
            p.fillPath(body, QColor("#FBCB4A"))
            p.setPen(QPen(QColor("#E0A800"), 1))
            p.drawPath(body)
        elif kind == "up":
            body = QPainterPath()
            body.addRoundedRect(1, 6, 18, 11, 2.5, 2.5)
            p.fillPath(body, QColor("#D7D9E3"))
            p.setPen(QPen(QColor("#9AA0B4"), 1.4))
            p.drawLine(6, 5, 10, 1)
            p.drawLine(10, 1, 14, 5)
        else:
            doc = QPainterPath()
            doc.addRoundedRect(2, 1, 16, 18, 2.5, 2.5)
            p.fillPath(doc, QColor("#E5484D"))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            f = QFont("Segoe UI", 6, QFont.Weight.Bold)
            p.setFont(f)
            p.drawText(px.rect(), int(Qt.AlignmentFlag.AlignCenter), "PDF")
        p.end()
        self._icon_cache[key] = QIcon(px)
        return self._icon_cache[key]

    def _on_sort_changed(self, col, order):
        self._sort_col = col
        self._sort_order = order
        self._populate_table()

    def _refresh(self, highlight=None):
        self.path_edit.setText(self._cwd)
        self._rows = []
        parent_dir = QFileInfo(self._cwd).dir()
        if parent_dir.exists() and parent_dir.absolutePath() != self._cwd:
            self._rows.append({"kind": "up", "path": parent_dir.absolutePath(),
                               "name": "..", "mtime": 0})
        try:
            entries = os.listdir(self._cwd)
        except Exception:
            entries = []
        for name in entries:
            full = os.path.join(self._cwd, name)
            try:
                mtime = os.path.getmtime(full)
            except Exception:
                mtime = 0
            if os.path.isdir(full):
                self._rows.append({"kind": "dir", "path": full, "name": name, "mtime": mtime})
            elif name.lower().endswith(".pdf"):
                self._rows.append({"kind": "pdf", "path": full, "name": name, "mtime": mtime})
        self._refresh_highlight = highlight
        self._populate_table()

    def _populate_table(self):
        from datetime import datetime
        self.table.setSortingEnabled(False)
        # Папки всегда выше файлов, внутри — сортировка по выбранному столбцу
        col = self._sort_col
        desc = self._sort_order == Qt.SortOrder.DescendingOrder
        def key(r):
            if col == 1:
                return (r["kind"] != "up", 0 if r["kind"] == "dir" else 1, r["mtime"])
            return (r["kind"] != "up", 0 if r["kind"] == "dir" else 1, r["name"].lower())
        rows = sorted(self._rows, key=key, reverse=desc)
        # «..» и папки держим сверху независимо от направления
        ups = [r for r in rows if r["kind"] == "up"]
        dirs = [r for r in rows if r["kind"] == "dir"]
        pdfs = [r for r in rows if r["kind"] == "pdf"]
        rows = ups + dirs + pdfs

        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        highlight = getattr(self, "_refresh_highlight", None)
        for i, r in enumerate(rows):
            name_item = QTableWidgetItem(r["name"])
            name_item.setIcon(self._file_icon(r["kind"]))
            name_item.setData(Qt.ItemDataRole.UserRole, (r["kind"], r["path"]))
            if r["kind"] == "up":
                f = name_item.font(); f.setBold(True); name_item.setFont(f)
            self.table.setItem(i, 0, name_item)
            if r["kind"] == "pdf":
                dt = datetime.fromtimestamp(r["mtime"]).strftime("%d.%m.%Y %H:%M") if r["mtime"] else "—"
            else:
                dt = "—"
            date_item = QTableWidgetItem(dt)
            date_item.setForeground(QColor(THEME["text_muted"]))
            self.table.setItem(i, 1, date_item)
            if highlight and os.path.abspath(r["path"]) == highlight:
                self.table.selectRow(i)
        if highlight:
            self.hint.setText("Файл найден и выделен — нажмите «Выбрать».")
        elif not rows:
            self.hint.setText("Папка пуста или нет доступных PDF. Поднимитесь выше.")

    def _go_up(self):
        """«Назад» — подняться ровно на один уровень выше."""
        if self._cwd == "Мой компьютер":
            return
        parent = QFileInfo(self._cwd).dir()
        if parent.absolutePath() and parent.absolutePath() != self._cwd:
            self._cwd = parent.absolutePath(); self._refresh()

    def _navigate_to(self, path):
        self._cwd = path
        self._refresh()

    def eventFilter(self, obj, event):
        """Enter/Return на выделенной строке: папка — войти, PDF — выбрать."""
        if obj is getattr(self, "table", None):
            if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter,
            ):
                self._open_current_row()
                return True
        return super().eventFilter(obj, event)

    def _open_current_row(self):
        row = self.table.currentRow()
        if row < 0:
            sel = self.table.selectionModel().selectedRows()
            row = sel[0].row() if sel else -1
        if row < 0:
            return
        cell = self.table.item(row, 0)
        if cell is None:
            return
        kind, path = cell.data(Qt.ItemDataRole.UserRole)
        if kind in ("dir", "up"):
            self._navigate_to(path)
        elif kind == "pdf":
            self._selected_files = [path]
            self.accept()

    def _on_activated(self, index):
        """Запасной путь для сигнала activated."""
        self._open_current_row()

    def _on_double_click(self, item):
        row = item.row()
        cell = self.table.item(row, 0)
        if cell is None:
            return
        kind, path = cell.data(Qt.ItemDataRole.UserRole)
        if kind in ("dir", "up"):
            self._navigate_to(path)

    def _selected_pdf_paths(self):
        files = []
        for idx in self.table.selectionModel().selectedRows():
            cell = self.table.item(idx.row(), 0)
            if cell is None:
                continue
            kind, path = cell.data(Qt.ItemDataRole.UserRole)
            if kind == "pdf":
                files.append(path)
        return files

    def _selected_dir_path(self):
        """Путь выделенной папки (или «..»), иначе None."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        cell = self.table.item(rows[0].row(), 0)
        if cell is None:
            return None
        kind, path = cell.data(Qt.ItemDataRole.UserRole)
        if kind in ("dir", "up"):
            return path
        return None

    def _pick_folder(self):
        # Если выделена папка (или «..») — выбираем именно её,
        # иначе считаем выбранной текущую открытую папку.
        selected_dir = self._selected_dir_path()
        self._selected_files = [selected_dir or self._cwd]
        self.accept()

    def _pick_selected(self):
        files = self._selected_pdf_paths()
        if files:
            self._selected_files = files
            self.accept()
            return
        # Если выделена папка (или «..») — выбираем её,
        # иначе берём текущую открытую папку.
        selected_dir = self._selected_dir_path()
        self._selected_files = [selected_dir or self._cwd]
        self.accept()

    def selected_paths(self):
        return list(self._selected_files)


class PrintingCalculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Калькулятор расчёта проектной документации · v{get_app_version()}")
        self.setGeometry(100,100,1160,660)
        self.setMinimumHeight(420)
        self.setAcceptDrops(True)
        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.primary_color=THEME["primary"]; self.danger_color=THEME["danger"]; self.bg_color=THEME["bg"]
        self.card_color=THEME["surface"]; self.text_color=THEME["text"]; self.theme=THEME
        self.apply_style()
        self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
        self.selected_path=""; self.copies=1; self.force_bw=False; self.count_fill=True
        self._dropped_pdfs = None
        self.need_folding_a4=self.need_folding_a3=False
        self.need_binding_a4=self.need_binding_a3=False
        self.thread=self.current_dialog=None; self._history_items=[]
        self.init_ui()
        # Минимальная ширина — по строке вкладок, чтобы вкладки не обрезались
        self._apply_tab_min_width()
        # Компактный стартовый размер: ширина ровно до края вкладки «Заливка»
        QTimer.singleShot(0, self._reset_window_size)
        QTimer.singleShot(100, self.refresh_history)

    def _apply_selected_path(self, path):
        if not path or not os.path.exists(path):
            self.label_status.setText("❌ Путь не существует")
            return
        self.selected_path = path
        self._dropped_pdfs = None
        self.drop_area.set_selected_path(path)

    def save_details_txt(self):
        text=self.text_details.toPlainText().strip()
        if not text: QMessageBox.information(self,"Сохранение","Нет данных для сохранения.\nСначала выполните анализ."); return
        default_name=f"detalizaciya_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        file_path,_=QFileDialog.getSaveFileName(self,"Сохранить детализацию в TXT",default_name,"Текстовые файлы (*.txt);;Все файлы (*)")
        if not file_path: return
        if not file_path.lower().endswith(".txt"): file_path+=".txt"
        try:
            with open(file_path,"w",encoding="utf-8") as f: f.write(text)
            self.label_status.setText(f"✅ Детализация сохранена: {file_path}")
        except Exception as e: QMessageBox.critical(self,"Ошибка сохранения",f"Не удалось сохранить файл:\n{e}")

    def apply_style(self):
        t = THEME
        font = t["font"]
        # Современный визуальный язык 2026: aurora-градиенты, bento-карточки,
        # крупные радиусы, мягкие тени, отсутствие жёстких рамок.
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color:{t['bg']}; color:{t['text']}; font-family:{font}; font-size:13px; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background-color:{t['bg']}; border:none; }}

            /* ── Навигация: pill-вкладки с заметным активным состоянием ── */
            QTabWidget {{ background: transparent; }}
            QTabWidget::pane {{ border:none; background-color:{t['bg']}; margin-top:10px; }}
            QTabBar {{ background: transparent; qproperty-drawBase:0; }}
            QTabBar::tab {{
                background-color:{t['surface_sunken']}; color:{t['text_muted']};
                padding:10px 18px; margin:0 6px 0 0; min-height:22px;
                border:none; border-radius:{t['r_sm']};
                font-weight:600; font-size:13px;
            }}
            QTabBar::tab:hover {{ color:{t['text']}; background-color:{t['surface_high']}; }}
            QTabBar::tab:selected {{
                color:{t['text_on_primary']}; background-color:{t['primary']};
            }}

            /* ── Карточки ── */
            QFrame#Card {{
                background-color:{t['surface']}; border:1px solid {t['divider']};
                border-radius:{t['r_lg']};
            }}
            QGroupBox {{
                background-color:{t['surface']}; border:1px solid {t['divider']};
                border-radius:{t['r_lg']}; margin-top:16px; padding:18px 16px 14px 16px;
                font-weight:600; font-size:13px; color:{t['text']};
            }}
            QGroupBox::title {{
                subcontrol-origin:margin; subcontrol-position:top left;
                left:18px; padding:0 6px; color:{t['text']};
            }}

            /* ── Кнопки: скруглённые углы ── */
            QPushButton {{
                background-color:{t['primary']}; color:{t['text_on_primary']};
                border:none; border-radius:{t['r_md']}; padding:10px 22px;
                font-weight:600; font-size:13px; min-height:20px;
            }}
            QPushButton:hover {{ background-color:{t['primary_hover']}; }}
            QPushButton:pressed {{ background-color:{t['primary_press']}; }}
            QPushButton:disabled {{ background-color:{t['disabled_bg']}; color:{t['disabled_fg']}; }}
            QPushButton:focus {{ outline:none; }}

            QLabel {{ color:{t['text']}; background:transparent; }}

            /* ── Поля ввода ── */
            QLineEdit {{
                background-color:{t['surface_sunken']}; border:1px solid transparent;
                border-radius:{t['r_md']}; padding:10px 14px; color:{t['text']};
                selection-background-color:{t['primary_soft']}; selection-color:{t['primary_text']};
            }}
            QLineEdit:focus {{ border:1px solid {t['primary']}; background-color:{t['surface']}; }}
            QLineEdit:disabled {{ background-color:{t['disabled_bg']}; color:{t['disabled_fg']}; }}

            QTextEdit {{
                background-color:{t['surface_alt']}; border:1px solid {t['divider']};
                border-radius:{t['r_md']}; color:{t['text']}; padding:12px;
                selection-background-color:{t['primary_soft']}; selection-color:{t['primary_text']};
            }}
            QTextEdit:focus {{ border:1px solid {t['primary']}; }}

            QSpinBox {{
                background-color:{t['surface_sunken']}; color:{t['text']};
                border:1px solid transparent; border-radius:{t['r_md']};
                padding:6px 26px 6px 14px; min-height:32px;
            }}
            QSpinBox:focus {{ border:1px solid {t['primary']}; background-color:{t['surface']}; }}
            QSpinBox::up-button {{
                subcontrol-origin:border; subcontrol-position:top right;
                width:22px; border:none; background-color:{t['surface_sunken']};
            }}
            QSpinBox::down-button {{
                subcontrol-origin:border; subcontrol-position:bottom right;
                width:22px; border:none; background-color:{t['surface_sunken']};
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color:{t['surface_high']}; }}

            /* ── Чекбокс-свитч ── */
            QCheckBox {{ color:{t['text']}; background:transparent; spacing:10px; font-size:13px; }}
            QCheckBox::indicator {{
                width:46px; height:26px; border:none;
                border-radius:13px; background:{t['disabled_bg']};
            }}
            QCheckBox::indicator:hover {{ background:{t['surface_high']}; }}
            QCheckBox::indicator:checked {{ background-color:{t['success']}; }}
            QCheckBox::indicator:checked:hover {{ background-color:{t['success_hover']}; }}
            QCheckBox::indicator:disabled {{ background:{t['disabled_bg']}; }}
            QCheckBox:disabled {{ color:{t['disabled_fg']}; }}

            /* ── Радио: segmented control ── */
            QRadioButton {{
                background-color:{t['seg_track']}; color:{t['text_muted']};
                padding:9px 20px; font-weight:600; font-size:13px; spacing:0;
                border-radius:{t['r_pill']}; margin-right:4px;
            }}
            QRadioButton:hover {{ color:{t['text']}; }}
            QRadioButton::indicator {{ width:0; height:0; }}
            QRadioButton:checked {{
                background-color:{t['surface']}; color:{t['primary_text']};
                border:1px solid {t['primary_border']};
            }}
            QRadioButton:disabled {{ color:{t['disabled_fg']}; background:{t['disabled_bg']}; }}

            /* ── Таблицы / деревья ── */
            QTableWidget, QTreeWidget {{
                background-color:{t['surface']}; alternate-background-color:{t['surface_alt']};
                color:{t['text']}; gridline-color:transparent;
                border:1px solid {t['divider']}; border-radius:{t['r_lg']};
                selection-background-color:{t['primary_soft']}; selection-color:{t['primary_text']};
                outline:none;
            }}
            QTableWidget::item, QTreeWidget::item {{ padding:9px 8px; border-bottom:1px solid {t['divider']}; }}
            QTableWidget::item:hover, QTreeWidget::item:hover {{ background-color:{t['surface_sunken']}; }}
            QTableWidget::item:selected, QTreeWidget::item:selected {{
                background-color:{t['primary_soft']}; color:{t['primary_text']};
            }}
            QHeaderView {{ background:transparent; }}
            QHeaderView::section {{
                background-color:{t['surface']}; padding:11px 10px;
                border:none; border-bottom:1px solid {t['border']};
                font-weight:600; font-size:11px; color:{t['text_muted']};
            }}
            QTableCornerButton::section {{ background-color:{t['surface']}; border:none; }}

            /* ── Прогресс: тонкая полоса как .progress ── */
            QProgressBar {{
                border:none; border-radius:{t['r_pill']}; text-align:center;
                height:8px; color:transparent; background-color:{t['surface_high']};
            }}
            QProgressBar::chunk {{ background-color:{t['primary']}; border-radius:{t['r_pill']}; }}

            /* ── Скроллбары: синий ползунок в общем стиле ── */
            QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
            QScrollBar::handle:vertical {{
                background:{t['primary']}; border-radius:5px; min-height:32px;
            }}
            QScrollBar::handle:vertical:hover {{ background:{t['primary_hover']}; }}
            QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
            QScrollBar::handle:horizontal {{
                background:{t['primary']}; border-radius:5px; min-width:32px;
            }}
            QScrollBar::handle:horizontal:hover {{ background:{t['primary_hover']}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

            QToolTip {{
                background-color:{t['text']}; color:{t['surface']};
                border:none; border-radius:{t['r_sm']}; padding:7px 10px;
            }}
            QMessageBox {{ background-color:{t['surface']}; color:{t['text']}; }}
            QDialog {{ background-color:{t['bg']}; color:{t['text']}; }}
        """)

    def init_ui(self):
        c=QWidget(); self.setCentralWidget(c); ml=QVBoxLayout(c); ml.setContentsMargins(18,14,18,14); ml.setSpacing(8)

        self.tabs=QTabWidget()
        self.tabs.addTab(self.create_input_tab(),"📁  Параметры")
        self.tabs.addTab(self.create_details_tab(),"📊  Детализация")
        self.tabs.addTab(self.create_manager_tab(),"👔  Менеджер")
        self.tabs.addTab(self.create_report_tab(),"📄  Клиент")
        self.tabs.addTab(self.create_history_tab(),"📚  История")
        self.tabs.addTab(self.create_fill_tab(),"🎨  Заливка")
        self.tabs.currentChanged.connect(self._animate_tab_switch)
        ml.addWidget(self.tabs)

    def _animate_tab_switch(self, index):
        """Плавное появление содержимого вкладки (fade, как .tab-pane fade в web)."""
        widget = self.tabs.widget(index)
        if widget is None:
            return
        try:
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
            self._fade_widget = widget
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: widget.setGraphicsEffect(None))
            anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            self._fade_anim = anim
        except Exception:
            pass
        # Вкладка «Менеджер»: пересчёт высот блоков и подгонка окна
        if index == self._manager_tab_index():
            QTimer.singleShot(0, self._refit_manager_blocks)
            QTimer.singleShot(60, self._refit_manager_blocks)
            QTimer.singleShot(120, self._fit_window_for_manager)
        else:
            QTimer.singleShot(0, self._reset_window_size)

    def _min_window_width(self):
        """Ширина окна = естественная ширина строки вкладок (+небольшой отступ)."""
        bar = self.tabs.tabBar()
        return max(720, bar.sizeHint().width() + 36)

    def _apply_tab_min_width(self):
        """Не даём окну сжиматься уже, чем нужно строке вкладок (иначе вкладки
        обрезаются и появляются стрелки прокрутки). См. apply_style/init_ui."""
        w = self._min_window_width()
        if self.minimumWidth() < w:
            self.setMinimumWidth(w)

    def _reset_window_size(self):
        """Компактный размер окна для обычных вкладок: ширина — по вкладкам,
        высота — чтобы содержимое текущей вкладки помещалось без прокрутки."""
        self._apply_tab_min_width()
        w = max(self.minimumWidth(), self._min_window_width())
        # Высоту подгоняем под содержимое вкладки «Параметры»
        h = 620
        try:
            sc = self.tabs.widget(0).findChild(QScrollArea)
            if sc is not None and sc.widget() is not None:
                sc.widget().adjustSize()
                h = sc.widget().sizeHint().height() + 96  # шапка вкладок + отступы
        except Exception:
            pass
        screen = QApplication.primaryScreen().availableGeometry()
        h = max(560, min(h, screen.height() - 40))
        self.resize(w, h)

    def _fit_window_for_manager(self):
        """Подгоняет высоту окна под содержимое вкладки «Менеджер» (без прокрутки)."""
        self._refit_manager_blocks()
        sc = getattr(self, "_manager_scroll", None)
        content_h = 0
        if sc is not None and sc.widget() is not None:
            sc.widget().adjustSize()
            content_h = sc.widget().sizeHint().height()
        chrome = self.height() - (sc.height() if sc is not None else self.height())
        need_h = content_h + chrome + 20
        w = self._min_window_width()
        screen = QApplication.primaryScreen().availableGeometry()
        need_h = min(need_h, screen.height() - 40)
        # Ширина — как у остальных вкладок (край «Заливка»), но не уже 900
        w = max(900, w)
        self.resize(w, max(560, need_h))

    def _manager_tab_index(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).strip().endswith("Менеджер"):
                return i
        return 2

    def _bold_label(self, text, size=11):
        lb=QLabel(text); lb.setFont(QFont("Segoe UI Variable Display",size,QFont.Weight.DemiBold)); lb.setStyleSheet(f"color:{self.text_color};background:transparent;"); return lb

    def _section_title(self, text):
        lb=QLabel(text)
        lb.setFont(QFont("Segoe UI Variable Display", 13, QFont.Weight.Bold))
        lb.setStyleSheet(f"color:{self.theme['text']};background:transparent;letter-spacing:-0.2px;")
        return lb

    def _field_label(self, text):
        lb=QLabel(text)
        lb.setFont(QFont("Segoe UI Variable Text", 11, QFont.Weight.DemiBold))
        lb.setStyleSheet(f"color:{self.theme['text_muted']};background:transparent;")
        lb.setWordWrap(True)
        lb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lb.setMinimumWidth(0)
        return lb

    def _card_title(self, text):
        lb=QLabel(text)
        lb.setFont(QFont("Segoe UI Variable Display", 12, QFont.Weight.Bold))
        lb.setStyleSheet(f"color:{self.theme['text']};background:transparent;padding-bottom:2px;")
        return lb

    def show_whats_new(self):
        WhatsNewDialog(get_app_version(), parent=self).exec()

    def open_donate(self):
        DonateDialog(self).exec()

    def open_telegram(self):
        import webbrowser
        webbrowser.open("https://t.me/fabilya")

    def create_input_tab(self):
        w=QWidget()
        # Вертикальная прокрутка: при уменьшении высоты окна содержимое не сжимается
        # и не накладывается друг на друга.
        outer=QScrollArea(); outer.setWidgetResizable(True); outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner=QWidget(); lay=QVBoxLayout(inner); lay.setSpacing(12); lay.setContentsMargins(16,14,16,14)
        cols=QHBoxLayout(); cols.setSpacing(12)

        # ── Левая колонка (компактная) ──
        left=QVBoxLayout(); left.setSpacing(12)

        dz_card=QFrame(); dz_card.setObjectName("Card"); dz_card.setMinimumHeight(150); dcl=QVBoxLayout(dz_card); dcl.setContentsMargins(14,14,14,14); dcl.setSpacing(8)
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._handle_dropped_paths)
        self.drop_area.clicked.connect(self.browse_input)
        dcl.addWidget(self.drop_area)
        left.addWidget(dz_card)

        # Сохраняем label_path как ссылку на title — чтобы не ломать остальной код
        self.label_path = self.drop_area.title_label

        cf=QFrame(); cf.setObjectName("Card"); cf.setMinimumHeight(130)
        cl=QVBoxLayout(cf); cl.setContentsMargins(16,14,16,14); cl.setSpacing(10)
        cl.addWidget(self._section_title("🎨 Цветность"))
        # Скрытые радио хранят состояние (логика ниже не меняется), видимый UI — сегменты.
        self.rb_color_auto=QRadioButton("По файлу"); self.rb_color_bw=QRadioButton("Ч/б"); self.rb_color_auto.setChecked(True)
        self.color_mode_group=QButtonGroup(self); self.color_mode_group.addButton(self.rb_color_auto); self.color_mode_group.addButton(self.rb_color_bw)
        self.rb_color_auto.hide(); self.rb_color_bw.hide()
        self.color_segmented = SegmentedControl(["По файлу", "Ч/б"])
        self.color_segmented._on_change = lambda i: (
            self.rb_color_auto.setChecked(i == 0) if i == 0 else self.rb_color_bw.setChecked(True)
        )
        cl.addWidget(self.color_segmented)
        self.cb_count_fill = SwitchCheckBox("Учитывать заливку цветом")
        self.cb_count_fill.setChecked(False)
        self.cb_count_fill.setStyleSheet(f"color:{self.text_color};background:transparent;font-size:13px;")
        cl.addWidget(self.cb_count_fill)
        self.rb_color_auto.toggled.connect(self._update_fill_checkbox)
        self.rb_color_bw.toggled.connect(self._update_fill_checkbox)
        self._update_fill_checkbox()
        left.addWidget(cf)

        pf=QFrame(); pf.setObjectName("Card"); pf.setMinimumHeight(230)
        pl=QVBoxLayout(pf); pl.setContentsMargins(16,14,16,14); pl.setSpacing(10)
        pl.addWidget(self._section_title("⚙️ Параметры"))
        r2=QHBoxLayout(); r2.setSpacing(10)
        lbl_copies=QLabel("Количество экземпляров:"); lbl_copies.setStyleSheet(f"color:{self.theme['text_muted']};background:transparent;font-size:13px;font-weight:600;"); r2.addWidget(lbl_copies)
        self.spinbox_copies=CopiesInput(); self.spinbox_copies.setValue(1)
        self.spinbox_copies.valueChanged.connect(self.on_params_changed); r2.addWidget(self.spinbox_copies); r2.addStretch(); pl.addLayout(r2)

        pl.addWidget(self._field_label("📌 Брошюровка на пластиковую пружину:"))
        self.rb_binding_none=QRadioButton("Не нужна"); self.rb_binding_a4=QRadioButton("A4"); self.rb_binding_a3=QRadioButton("A3"); self.rb_binding_none.setChecked(True)
        self.binding_group=QButtonGroup(self)
        for rb in (self.rb_binding_none,self.rb_binding_a4,self.rb_binding_a3): self.binding_group.addButton(rb); rb.hide()
        self.binding_segmented = SegmentedControl(["Не нужна", "A4", "A3"])
        self.binding_segmented._on_change = self._set_binding_index
        pl.addWidget(self.binding_segmented)

        pl.addWidget(self._field_label("📋 Фальцовка:"))
        self.rb_folding_none=QRadioButton("Не нужна"); self.rb_folding_a4=QRadioButton("Под A4"); self.rb_folding_a3=QRadioButton("Под A3"); self.rb_folding_none.setChecked(True)
        self.folding_group=QButtonGroup(self)
        for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): self.folding_group.addButton(rb); rb.hide()
        self.folding_segmented = SegmentedControl(["Не нужна", "Под A4", "Под A3"])
        self.folding_segmented._on_change = self._set_folding_index
        pl.addWidget(self.folding_segmented)

        self.binding_group.buttonClicked.connect(self.on_binding_changed); self.folding_group.buttonClicked.connect(self.on_params_changed)
        left.addWidget(pf)
        left.addStretch()
        cols.addLayout(left, stretch=3)

        # ── Правая колонка: статус + анализ + ссылки ──
        right=QVBoxLayout(); right.setSpacing(12)

        sc_card=QFrame(); sc_card.setObjectName("Card")
        scl=QVBoxLayout(sc_card); scl.setContentsMargins(16,14,16,14); scl.setSpacing(10)
        scl.addWidget(self._section_title("⚡ Статус анализа"))
        self.label_status=QLabel("Готово"); self.label_status.setStyleSheet(f"color:{self.text_color};background:transparent;font-size:15px;font-weight:600;")
        self.label_status.setWordWrap(True)
        self.label_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label_status.setMinimumWidth(0)
        scl.addWidget(self.label_status)
        scl_note=QLabel("Расчёт выполняется локально на вашем компьютере — файлы никуда не отправляются.")
        scl_note.setStyleSheet(f"color:{self.theme['text_muted']};font-size:11px;background:transparent;")
        scl_note.setWordWrap(True)
        scl_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        scl_note.setMinimumWidth(0)
        scl.addWidget(scl_note)
        self.progress_bar=QProgressBar(); self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            f"QProgressBar{{border:none;border-radius:5px;text-align:center;height:10px;"
            f"color:transparent;background-color:{THEME['surface_high']};}}"
            f"QProgressBar::chunk{{border-radius:5px;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #0A84FF, stop:1 #00C2FF);}}"
        )
        scl.addWidget(self.progress_bar)
        arow=QHBoxLayout(); arow.setSpacing(10)
        self.btn_analyze=QPushButton("▶️  Начать анализ"); self.btn_analyze.setFont(QFont("Segoe UI Variable Display",13,QFont.Weight.Bold)); self.btn_analyze.setMinimumHeight(48)
        self.btn_analyze.setStyleSheet(_qss_button("filled"))
        self.btn_analyze.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_analyze.clicked.connect(self.on_primary_action); arow.addWidget(self.btn_analyze, stretch=1)
        self.btn_stop=QPushButton("⏹  Стоп"); self.btn_stop.setFont(QFont("Segoe UI Variable Display",12,QFont.Weight.DemiBold)); self.btn_stop.setMinimumHeight(48)
        self.btn_stop.setStyleSheet(_qss_button("danger")); self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.clicked.connect(self.stop_analysis); self.btn_stop.setEnabled(False); arow.addWidget(self.btn_stop, stretch=0)
        scl.addLayout(arow)
        right.addWidget(sc_card)

        lc_card=QFrame(); lc_card.setObjectName("Card")
        lcl=QVBoxLayout(lc_card); lcl.setContentsMargins(16,14,16,14); lcl.setSpacing(10)
        btn_donate=QPushButton("❤️  DONATE")
        btn_donate.setFont(QFont("Segoe UI Variable Display",12,QFont.Weight.Bold)); btn_donate.setMinimumHeight(44)
        btn_donate.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_donate.setStyleSheet(_qss_button("success"))
        btn_donate.clicked.connect(self.open_donate)
        lcl.addWidget(btn_donate)

        # «Нашли ошибку?» и «Что нового» — в одну строку, белые как outlined
        row_btns=QHBoxLayout(); row_btns.setSpacing(8)
        _btn_small = (
            f"QPushButton{{background-color:transparent;color:{THEME['primary']};"
            f"border:1px solid {THEME['border_strong']};border-radius:{THEME['r_md']};"
            f"padding:8px 6px;font-weight:600;font-size:12px;}}"
            f"QPushButton:hover{{background-color:{THEME['primary_soft']};border-color:{THEME['primary']};}}"
            f"QPushButton:pressed{{background-color:{THEME['primary_soft']};}}"
        )
        btn_bug=QPushButton("Нашли ошибку?")
        tg_icon = QIcon(resource_path("assets/telegram.png"))
        if not tg_icon.isNull():
            btn_bug.setIcon(tg_icon)
            btn_bug.setIconSize(QSize(15, 15))
        btn_bug.setFont(QFont("Segoe UI Variable Text",9,QFont.Weight.DemiBold))
        btn_bug.setMinimumHeight(40)
        btn_bug.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_bug.setStyleSheet(_btn_small)
        btn_bug.setMinimumWidth(1)
        btn_bug.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_bug.setToolTip("Открыть чат в Telegram")
        btn_bug.clicked.connect(self.open_telegram)
        row_btns.addWidget(btn_bug, stretch=1)

        btn_whats_new=QPushButton("🎉  Что нового"); btn_whats_new.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_whats_new.setFont(QFont("Segoe UI Variable Text",9,QFont.Weight.DemiBold))
        btn_whats_new.setMinimumHeight(40)
        btn_whats_new.setStyleSheet(_btn_small)
        btn_whats_new.setMinimumWidth(1)
        btn_whats_new.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_whats_new.setToolTip(f"Что нового в версии {get_app_version()}")
        btn_whats_new.clicked.connect(self.show_whats_new)
        row_btns.addWidget(btn_whats_new, stretch=1)
        lcl.addLayout(row_btns)

        # Ненавязчивая версия внизу карточки
        ver_lbl=QLabel(f"PDKopirka · v{get_app_version()}")
        ver_lbl.setStyleSheet(f"color:{self.theme['text_faint']};background:transparent;font-size:10px;")
        ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lcl.addWidget(ver_lbl)
        right.addWidget(lc_card)
        right.addStretch()
        cols.addLayout(right, stretch=5)

        lay.addLayout(cols)
        outer.setWidget(inner)
        root=QVBoxLayout(w); root.setContentsMargins(0,0,0,0); root.addWidget(outer)
        return w

    def _set_binding_index(self, i):
        btn = (self.rb_binding_none, self.rb_binding_a4, self.rb_binding_a3)[i]
        if not btn.isEnabled():
            # откатываем визуальный сегмент назад
            cur = 2
            if self.rb_binding_none.isChecked(): cur = 0
            elif self.rb_binding_a4.isChecked(): cur = 1
            self.binding_segmented.setCurrentIndex(cur)
            return
        btn.setChecked(True)
        self.on_binding_changed()

    def _set_folding_index(self, i):
        btn = (self.rb_folding_none, self.rb_folding_a4, self.rb_folding_a3)[i]
        if not btn.isEnabled():
            cur = 2
            if self.rb_folding_none.isChecked(): cur = 0
            elif self.rb_folding_a4.isChecked(): cur = 1
            self.folding_segmented.setCurrentIndex(cur)
            return
        btn.setChecked(True)
        self.on_params_changed()

    def on_binding_changed(self):
        if self.rb_binding_a4.isChecked():
            self.rb_folding_a4.setChecked(True)
            self.folding_segmented.setCurrentIndex(1)
            for rb in (self.rb_folding_none,self.rb_folding_a3,self.rb_folding_a4): rb.setEnabled(False)
            self.folding_segmented.setEnabled(False)
        elif self.rb_binding_a3.isChecked():
            self.rb_folding_a3.setChecked(True)
            self.folding_segmented.setCurrentIndex(2)
            for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): rb.setEnabled(False)
            self.folding_segmented.setEnabled(False)
        else:
            for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): rb.setEnabled(True)
            self.folding_segmented.setEnabled(True)
        self.on_params_changed()

    def _tab_desc(self, text):
        lb=QLabel(text)
        lb.setStyleSheet(f"color:{self.theme['text_muted']};font-size:12px;background:transparent;")
        lb.setWordWrap(True)
        return lb

    def create_details_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,16,20,16); lay.setSpacing(10)
        head=QVBoxLayout(); head.setSpacing(4)
        head.addWidget(self._section_title("📊 Детализация"))
        head.addWidget(self._tab_desc(
            "Полная подробная информация по каждому файлу: 1 экземпляр, с номерами страниц "
            "и пометками конвертаций и заливки."
        ))
        lay.addLayout(head)
        self.text_details=QTextEdit(); self.text_details.setReadOnly(True); self.text_details.setFont(QFont("Cascadia Mono",9))
        self.text_details.setStyleSheet(f"QTextEdit{{background-color:{self.theme['surface']};color:{self.text_color};border:1px solid {self.theme['divider']};border-radius:{self.theme['r_lg']};padding:14px;}}"); lay.addWidget(self.text_details)
        btn_save=QPushButton("💾  Сохранить в TXT (для производства)"); btn_save.setMinimumHeight(46); btn_save.setStyleSheet(_qss_button("filled")); btn_save.setCursor(Qt.CursorShape.PointingHandCursor); btn_save.clicked.connect(self.save_details_txt); lay.addWidget(btn_save); return w

    def create_manager_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,16,20,16); lay.setSpacing(10)
        ear=QVBoxLayout(); ear.setSpacing(4)
        ear.addWidget(self._section_title("👔 Менеджер"))
        ear.addWidget(self._tab_desc(
            "Точные значения для ввода в CRM KOPIRKA."
        ))
        lay.addLayout(ear)

        # Единая прокрутка всей вкладки: блоки показывают всю информацию целиком,
        # без внутренних скроллов, которые скрывают часть данных.
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        content=QWidget(); cl=QVBoxLayout(content); cl.setContentsMargins(0,0,6,0); cl.setSpacing(14)

        sl=QHBoxLayout(); sl.setSpacing(16); sl.setContentsMargins(0,0,0,0)

        def make_block(title,attr,weight=1):
            frame=QFrame(); frame.setObjectName("Card")
            # Высота всегда по содержимому; не сжимается — текст не обрезается.
            frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            fl_=QVBoxLayout(frame); fl_.setContentsMargins(18,16,18,16); fl_.setSpacing(8)
            title_lbl = self._card_title(title)
            fl_.addWidget(title_lbl)
            te=QTextEdit(); te.setReadOnly(True)
            # Внутренний скролл выключен: блок всегда показывает весь текст.
            te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            te.setStyleSheet(
                f"QTextEdit{{background-color:{self.theme['surface_alt']};color:{self.text_color};"
                f"border:1px solid {self.theme['divider']};border-radius:{self.theme['r_md']};"
                f"padding:12px;font-family:{self.theme['mono']};font-size:12px;}}"
            )
            fl_.addWidget(te, stretch=0); setattr(self,attr,te)
            setattr(self, attr + "_frame", frame)
            setattr(self, attr + "_weight", weight)

            def refit(*_a, _te=te, _frame=frame):
                _te.document().setTextWidth(max(40, _te.viewport().width()))
                doc_h = _te.document().size().height()
                m = _te.contentsMargins()
                extra = m.top() + m.bottom() + 2 * _te.frameWidth() + 4
                h = int(doc_h) + extra
                _te.setFixedHeight(max(48, h))
                _frame.setMinimumHeight(
                    max(48, h) + title_lbl.sizeHint().height() + 34
                )
            te._refit = refit
            te.document().documentLayout().documentSizeChanged.connect(refit)
            refit()
            return frame, weight

        left=QVBoxLayout(); left.setSpacing(14)
        for title, attr, wt in [
            ("🖨️ Печать (с конвертацией, с учётом экземпляров)", "text_printing", 5),
            ("🌀 Рулонная печать", "text_roll", 3),
            ("📋 Фальцовка", "text_folding", 4),
        ]:
            frame, weight = make_block(title, attr, wt); left.addWidget(frame, stretch=0)
        left.addStretch(1)
        self._manager_left_layout = left
        sl.addLayout(left, stretch=6)

        right=QVBoxLayout(); right.setSpacing(14)
        r1,_ = make_block("✂️ Резка","text_cutting"); right.addWidget(r1, stretch=0)
        r2,_ = make_block("📌 Брошюровка","text_binding"); right.addWidget(r2, stretch=0)
        right.addStretch(1)
        self._manager_right_layout = right
        sl.addLayout(right, stretch=6)
        cl.addLayout(sl)

        scroll.setWidget(content)
        lay.addWidget(scroll, stretch=1)
        # При изменении размеров вкладки пересчитываем высоты блоков
        self._manager_scroll = scroll

        # «Итоговый вес» — компактная карточка-футер на всю ширину.
        tf=QFrame(); tf.setObjectName("Card")
        tf.setStyleSheet(
            f"QFrame#Card{{background:{self.theme['surface']};border:1px solid {self.theme['divider']};"
            f"border-radius:{self.theme['r_lg']};}}"
        )
        tf.setFixedHeight(76)
        tl=QHBoxLayout(tf); tl.setContentsMargins(20,12,20,12); tl.setSpacing(12)
        wt=QLabel("⚖️ Итоговый вес"); wt.setStyleSheet(f"color:{self.theme['text_muted']};background:transparent;font-size:13px;font-weight:600;")
        tl.addWidget(wt); tl.addStretch()
        self.label_total=QLabel("—"); self.label_total.setFont(QFont("Segoe UI Variable Display",24,QFont.Weight.Bold))
        self.label_total.setStyleSheet(f"color:{self.primary_color};background:transparent;"); tl.addWidget(self.label_total)
        self._weight_frame = tf
        lay.addWidget(tf, stretch=0)
        return w

    def _set_block_visible(self, attr, visible):
        """Скрывает/показывает раздел вкладки «Менеджер»."""
        frame = getattr(self, attr + "_frame", None)
        if frame is not None:
            frame.setVisible(visible)

    def create_report_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,16,20,16); lay.setSpacing(10)
        head=QVBoxLayout(); head.setSpacing(4)
        head.addWidget(self._section_title("📄 Клиент"))
        head.addWidget(self._tab_desc(
            "Информация для клиента без сложных формул пересчёта форматов. "
            "Отчёт уже сформирован с учётом количества экземпляров."
        ))
        lay.addLayout(head)
        self.text_report=QTextEdit(); self.text_report.setReadOnly(True); self.text_report.setFont(QFont("Cascadia Mono",9))
        self.text_report.setStyleSheet(f"QTextEdit{{background-color:{self.theme['surface']};color:{self.text_color};border:1px solid {self.theme['divider']};border-radius:{self.theme['r_lg']};padding:14px;}}"); lay.addWidget(self.text_report)
        rep_btns=QHBoxLayout(); rep_btns.setSpacing(10)
        self.btn_copy_report=QPushButton("📋  Копировать"); self.btn_copy_report.setMinimumHeight(46); self.btn_copy_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_report.clicked.connect(self.copy_report)
        self._copy_btn_style=_qss_button("filled")
        self.btn_copy_report.setStyleSheet(self._copy_btn_style)
        rep_btns.addWidget(self.btn_copy_report, stretch=1)
        self.btn_pdf_report=QPushButton("📄  Сгенерировать PDF"); self.btn_pdf_report.setMinimumHeight(46)
        self.btn_pdf_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pdf_report.setStyleSheet(_qss_button("success"))
        self.btn_pdf_report.clicked.connect(self.generate_client_pdf)
        rep_btns.addWidget(self.btn_pdf_report, stretch=1)
        lay.addLayout(rep_btns); return w

    def create_history_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,16,20,16); lay.setSpacing(10)
        header=QHBoxLayout(); header.addWidget(self._section_title("📚 История")); header.addStretch()
        btn_refresh=QPushButton("🔄  Обновить"); btn_refresh.setStyleSheet(_qss_button("tonal")); btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor); btn_refresh.clicked.connect(self.refresh_history); header.addWidget(btn_refresh); lay.addLayout(header)
        hint=QLabel("💡 Расчёты сохраняются автоматически. Двойной клик по строке — загрузить расчёт. Клик по заголовку столбца — сортировка.")
        hint.setStyleSheet(f"color:{self.theme['text_muted']};font-size:12px;padding:2px;background:transparent;"); hint.setWordWrap(True); lay.addWidget(hint)
        self.history_table=QTableWidget(); self.history_table.setColumnCount(4); self.history_table.setHorizontalHeaderLabels(["Дата и время","Название","Файлов","Страниц"])
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.history_table.cellDoubleClicked.connect(self.load_history_item)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False); self.history_table.setSortingEnabled(True); lay.addWidget(self.history_table)
        btns=QHBoxLayout(); btns.setSpacing(10)
        btn_load=QPushButton("📂  Загрузить выбранный"); btn_load.setMinimumHeight(44); btn_load.setStyleSheet(_qss_button("filled")); btn_load.setCursor(Qt.CursorShape.PointingHandCursor); btn_load.clicked.connect(self.load_selected_history)
        btn_load.setMinimumWidth(1); btn_load.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btns.addWidget(btn_load, stretch=1)
        btn_delete=QPushButton("🗑  Удалить выбранный"); btn_delete.setMinimumHeight(44)
        btn_delete.setStyleSheet(_qss_button("danger")); btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.setMinimumWidth(1); btn_delete.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_delete.clicked.connect(self.delete_selected_history); btns.addWidget(btn_delete, stretch=1)
        btn_folder=QPushButton("📁  Открыть папку истории"); btn_folder.setMinimumHeight(44)
        btn_folder.setStyleSheet(_qss_button("neutral")); btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setMinimumWidth(1); btn_folder.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn_folder.clicked.connect(self.open_history_folder); btns.addWidget(btn_folder, stretch=1); lay.addLayout(btns); return w

    def _fill_pct_color(self, pct):
        if pct<25: return QColor(THEME["success"])
        if pct<50: return QColor("#84CC16")
        if pct<75: return QColor(THEME["warning"])
        return QColor(THEME["danger"])

    def create_fill_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(12)
        header=QHBoxLayout(); header.addWidget(self._section_title("🎨 Заливка")); header.addStretch()
        btn_expand=QPushButton("▶  Развернуть все"); btn_expand.setFixedHeight(38); btn_expand.setStyleSheet(_qss_button("outlined")); btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_expand.clicked.connect(lambda: self.fill_tree.expandAll())
        header.addWidget(btn_expand)
        btn_collapse=QPushButton("◀  Свернуть все"); btn_collapse.setFixedHeight(38); btn_collapse.setStyleSheet(_qss_button("outlined")); btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_collapse.clicked.connect(lambda: self.fill_tree.collapseAll())
        header.addWidget(btn_collapse)
        lay.addLayout(header)
        hint=QLabel("💡 Заливка — доля не-белых пикселей на странице. Страницы с заливкой более 50% помечаются в детализации как «[заливка]». Данные собираются при включённой галочке «Учитывать заливку цветом».")
        hint.setStyleSheet(f"color:{self.theme['text_muted']};font-size:12px;padding:2px;background:transparent;"); hint.setWordWrap(True); lay.addWidget(hint)
        self.fill_tree=QTreeWidget()
        self.fill_tree.setColumnCount(4)
        self.fill_tree.setHeaderLabels(["Файл / Страница","Формат","Цветность","Заливка %"])
        self.fill_tree.setAlternatingRowColors(True)
        self.fill_tree.setRootIsDecorated(True)
        self.fill_tree.setAnimated(True)
        self.fill_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        lay.addWidget(self.fill_tree)
        return w

    def display_fill_pcts(self):
        self.fill_tree.clear()
        for fd in self.file_details:
            fname=fd.get("name","")
            fill_pcts=fd.get("fill_pcts",{})
            if not fill_pcts:
                continue
            total=fd.get("total",0)
            pages_map=fd.get("pages",{})
            page_info={}
            for key,pages in pages_map.items():
                fmt,kind=self._pfk(key)
                for pn in pages:
                    page_info[pn]=(fmt,kind)
            root=QTreeWidgetItem([fname])
            root_font=root.font(0); root_font.setBold(True); root.setFont(0,root_font)
            total_pct=0
            for pn in range(1,total+1):
                val=fill_pcts.get(pn,(0.0,0.0))
                color_pct,ink_pct=val if isinstance(val,tuple) else (float(val),float(val))
                fmt,kind=page_info.get(pn,("?","ч/б"))
                pct=ink_pct
                total_pct+=pct
                child=QTreeWidgetItem([f"Стр. {pn}",fmt,kind,f"{pct}%"])
                if kind=="цвет":
                    child.setForeground(2,QColor(THEME["danger"]))
                child.setForeground(3,self._fill_pct_color(pct))
                root.addChild(child)
            avg=total_pct/total if total>0 else 0.0
            root.setText(1,f"{total} стр.")
            root.setText(3,f"сред. {avg:.1f}%")
            root.setForeground(3,self._fill_pct_color(avg))
            root.setExpanded(True)
            self.fill_tree.addTopLevelItem(root)
        if self.fill_tree.topLevelItemCount()>0:
            header=self.fill_tree.header()
            header.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
            for col in [1,2,3]:
                header.setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)

    def browse_input(self):
        """Открывает проводник, где можно выбрать папку или один/несколько PDF."""
        dlg = PathPickerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._handle_dropped_paths(dlg.selected_paths())

    def _update_fill_checkbox(self):
        auto = self.rb_color_auto.isChecked()
        self.cb_count_fill.setEnabled(auto)
        if not auto:
            self.cb_count_fill.setChecked(False)

    def on_params_changed(self):
        self.copies=self.spinbox_copies.value(); self.need_folding_a4=self.rb_folding_a4.isChecked(); self.need_folding_a3=self.rb_folding_a3.isChecked()
        self.need_binding_a4=self.rb_binding_a4.isChecked(); self.need_binding_a3=self.rb_binding_a3.isChecked(); self.calculate_and_display()

    def on_primary_action(self):
        """Одна кнопка: Начать анализ → Пауза → Продолжить."""
        running = self.thread is not None and self.thread.isRunning()
        if not running:
            self.start_analysis()
            return
        if self.thread.is_paused():
            self.thread.request_resume()
            self.btn_analyze.setText("⏸  Пауза")
            self.btn_analyze.setStyleSheet(_qss_button("warning"))
            self.label_status.setText("⏳ Анализ продолжен...")
        else:
            self.thread.request_pause()
            self.btn_analyze.setText("▶️  Продолжить")
            self.btn_analyze.setStyleSheet(_qss_button("success"))
            self.label_status.setText("⏸ Пауза")

    def start_analysis(self):
        # Приоритет — перетянутые файлы (если есть)
        if self._dropped_pdfs:
            pdfs = list(self._dropped_pdfs)
        else:
            if not self.selected_path:
                self.label_status.setText("❌ Выберите папку или файл")
                return
            if not os.path.exists(self.selected_path):
                self.label_status.setText("❌ Путь не существует")
                return
            if self.selected_path.lower().endswith(".pdf"):
                pdfs = [self.selected_path]
            else:
                pdfs = [
                    os.path.join(r, f)
                    for r, _, fs in os.walk(self.selected_path)
                    for f in fs
                    if f.lower().endswith(".pdf")
                ]
        if not pdfs:
            self.label_status.setText("❌ PDF файлы не найдены")
            return
        self.force_bw=self.rb_color_bw.isChecked()
        count_fill = self.cb_count_fill.isChecked() and not self.force_bw
        self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
        self.label_status.setText("⏳ Идет анализ..."); self.progress_bar.setValue(0)
        self.btn_analyze.setEnabled(True); self.btn_analyze.setText("⏸  Пауза")
        self.btn_analyze.setStyleSheet(_qss_button("warning"))
        self.btn_stop.setEnabled(True)
        self.thread=AnalysisThread(pdfs, force_bw=self.force_bw, count_fill=count_fill)
        self.thread.progress.connect(self.update_progress); self.thread.status.connect(self.update_status)
        self.thread.need_user_input.connect(self.show_unknown_format_dialog); self.thread.finished.connect(self.analysis_finished)
        self.thread.error.connect(self.analysis_error); self.thread.stopped.connect(self.analysis_stopped); self.thread.start()

    def stop_analysis(self):
        if not self.thread or not self.thread.isRunning(): return
        self.label_status.setText("⏹ Отменяю расчёт..."); self.btn_stop.setEnabled(False)
        self.btn_analyze.setEnabled(False)
        if self.current_dialog:
            try: self.current_dialog.result_action="skip"; self.current_dialog.result_value=None; self.current_dialog.reject()
            except: pass
            self.current_dialog=None
        self.thread.request_stop()

    def _reset_primary_button(self):
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("▶️  Начать анализ")
        self.btn_analyze.setStyleSheet(_qss_button("filled"))

    def show_unknown_format_dialog(self, w, h, color, pages, pdf_path):
        if self.thread and self.thread._stop_requested: self.thread.set_user_response("skip",None); return
        dlg=UnknownFormatDialog(w,h,color,pages,pdf_path,parent=self); self.current_dialog=dlg; dlg.exec(); self.current_dialog=None
        self.thread.set_user_response(dlg.result_action, dlg.result_value)

    def update_progress(self, v): self.progress_bar.setValue(v)
    def update_status(self, s): self.label_status.setText(f"⏳ {s}")

    def analysis_finished(self, grand, total_source, fpc, fd):
        stopped = bool(self.thread and self.thread._stop_requested)
        if stopped:
            # Стоп = полная отмена расчёта: результаты не применяем и не сохраняем.
            self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
            self.text_details.clear(); self.fill_tree.clear(); self.text_report.clear()
            for a in ("text_printing","text_roll","text_cutting","text_folding","text_binding"):
                getattr(self, a).clear()
            self.label_total.setText("—")
            self._reset_primary_button(); self.btn_stop.setEnabled(False)
            self.progress_bar.setValue(0)
            return
        self.grand=grand; self.total_source=total_source; self.file_page_counts=fpc; self.file_details=fd
        self.label_status.setText("✅ Анализ завершен"); self.progress_bar.setValue(100)
        self._reset_primary_button(); self.btn_stop.setEnabled(False)
        self.display_details(); self.display_fill_pcts(); self.calculate_and_display()
        if self.grand: self._auto_save_to_history()

    def _auto_save_to_history(self):
        if not self.grand: return
        try:
            if self.selected_path:
                base=os.path.basename(self.selected_path.rstrip("\\/"))
                if base.lower().endswith(".pdf"): base=os.path.splitext(base)[0]
                name=base or "Расчёт"
            else: name="Расчёт"
            calc_data={'version':1,'app_version':get_app_version(),'saved_at':datetime.now().isoformat(),'name':name,
                'source':{'path':self.selected_path,'files_count':len(self.file_page_counts),'total_pages':self.total_source},
                'params':{'copies':self.copies,'force_bw':self.force_bw,'count_fill':self.cb_count_fill.isChecked(),
                    'folding':('A4' if self.need_folding_a4 else ('A3' if self.need_folding_a3 else None)),
                    'binding':('A4' if self.need_binding_a4 else ('A3' if self.need_binding_a3 else None))},
                'grand':self.grand,'file_page_counts':self.file_page_counts,'file_details':self.file_details,'report_text':self.text_report.toPlainText()}
            HistoryManager.save(calc_data,name); self.refresh_history()
        except Exception as e: print(f"Ошибка автосохранения: {e}")

    def analysis_stopped(self):
        self.label_status.setText("⏹ Расчёт отменён")
        self._reset_primary_button(); self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(0)

    def analysis_error(self, error):
        self.label_status.setText(f"❌ {error}")
        self._reset_primary_button(); self.btn_stop.setEnabled(False)

    def refresh_history(self):
        try: items=HistoryManager.list_all()
        except: items=[]
        self._history_items=items; self.history_table.setSortingEnabled(False); self.history_table.setRowCount(len(items))
        for row,item in enumerate(items):
            data=item['data']
            try: dt=datetime.fromisoformat(data.get('saved_at','')); date_str=dt.strftime("%d.%m.%Y %H:%M:%S"); sort_key=dt.strftime("%Y%m%d%H%M%S")
            except: date_str="—"; sort_key="0"
            src=data.get('source',{}); files_count=src.get('files_count',0); total_pages=src.get('total_pages',0)
            di=SortableTableItem(date_str,sort_key); di.setData(Qt.ItemDataRole.UserRole,row); di.setForeground(QColor(self.text_color)); self.history_table.setItem(row,0,di)
            ni=QTableWidgetItem(data.get('name','')); ni.setData(Qt.ItemDataRole.UserRole,row); ni.setForeground(QColor(self.text_color)); self.history_table.setItem(row,1,ni)
            fi=SortableTableItem(str(files_count),files_count); fi.setData(Qt.ItemDataRole.UserRole,row); fi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); fi.setForeground(QColor(self.text_color)); self.history_table.setItem(row,2,fi)
            pi=SortableTableItem(str(total_pages),total_pages); pi.setData(Qt.ItemDataRole.UserRole,row); pi.setTextAlignment(Qt.AlignmentFlag.AlignCenter); pi.setForeground(QColor(self.text_color)); self.history_table.setItem(row,3,pi)
        header=self.history_table.horizontalHeader()
        header.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents); header.setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents); header.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setSortingEnabled(True); self.history_table.sortItems(0,Qt.SortOrder.DescendingOrder)

    def _load_history_data(self, data):
        try:
            self.grand=data.get('grand',{}); self.total_source=data.get('source',{}).get('total_pages',0)
            self.file_page_counts=data.get('file_page_counts',[]); self.file_details=data.get('file_details',[])
            self.selected_path = data.get('source', {}).get('path', '')
            if self.selected_path:
                self.drop_area.set_selected_path(self.selected_path)
            else:
                self.drop_area.reset()
            params=data.get('params',{}); self.copies=params.get('copies',1); self.force_bw=params.get('force_bw',False)
            self.spinbox_copies.blockSignals(True); self.spinbox_copies.setValue(self.copies); self.spinbox_copies.blockSignals(False)
            folding=params.get('folding')
            if folding=='A4': self.rb_folding_a4.setChecked(True); self.need_folding_a4,self.need_folding_a3=True,False
            elif folding=='A3': self.rb_folding_a3.setChecked(True); self.need_folding_a4,self.need_folding_a3=False,True
            else: self.rb_folding_none.setChecked(True); self.need_folding_a4=self.need_folding_a3=False
            binding=params.get('binding')
            if binding=='A4': self.rb_binding_a4.setChecked(True); self.need_binding_a4,self.need_binding_a3=True,False
            elif binding=='A3': self.rb_binding_a3.setChecked(True); self.need_binding_a4,self.need_binding_a3=False,True
            else: self.rb_binding_none.setChecked(True); self.need_binding_a4=self.need_binding_a3=False
            if self.force_bw: self.rb_color_bw.setChecked(True)
            else: self.rb_color_auto.setChecked(True)
            # Синхронизируем анимированные сегменты с загруженным расчётом
            try:
                self.color_segmented.setCurrentIndex(1 if self.force_bw else 0, animate=False)
                self.binding_segmented.setCurrentIndex(
                    1 if binding=='A4' else (2 if binding=='A3' else 0), animate=False)
                self.folding_segmented.setCurrentIndex(
                    1 if folding=='A4' else (2 if folding=='A3' else 0), animate=False)
                self.spinbox_copies.setValue(self.copies)
            except Exception:
                pass
            self.cb_count_fill.setChecked(params.get('count_fill', False))
            self._update_fill_checkbox()
            self.display_details(); self.display_fill_pcts(); self.calculate_and_display(); self.tabs.setCurrentIndex(1)
            self.label_status.setText(f"📂 Загружен расчёт: {data.get('name','')}")
        except Exception as e: QMessageBox.critical(self,"Ошибка загрузки",f"Не удалось загрузить расчёт:\n{e}")

    def _get_item_index_at_row(self, row):
        item=self.history_table.item(row,0)
        if item is None: return -1
        idx=item.data(Qt.ItemDataRole.UserRole)
        if isinstance(idx,int) and 0<=idx<len(self._history_items): return idx
        return -1

    def load_selected_history(self):
        row=self.history_table.currentRow()
        if row<0: QMessageBox.information(self,"История","Выберите расчёт в таблице."); return
        idx=self._get_item_index_at_row(row)
        if idx<0: return
        self._load_history_data(self._history_items[idx]['data'])

    def load_history_item(self, row, col):
        idx=self._get_item_index_at_row(row)
        if idx<0: return
        self._load_history_data(self._history_items[idx]['data'])

    def delete_selected_history(self):
        row=self.history_table.currentRow()
        if row<0: QMessageBox.information(self,"История","Выберите расчёт в таблице."); return
        idx=self._get_item_index_at_row(row)
        if idx<0: return
        item=self._history_items[idx]; name=item['data'].get('name','без названия')
        ans=QMessageBox.question(self,"Подтверждение удаления",f"Удалить расчёт «{name}»?\n\nЭто действие необратимо.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
        if ans!=QMessageBox.StandardButton.Yes: return
        if HistoryManager.delete(item['path']): self.refresh_history(); self.label_status.setText(f"🗑 Удалён расчёт: {name}")
        else: QMessageBox.warning(self,"Ошибка","Не удалось удалить файл.")

    def open_history_folder(self):
        path=str(HistoryManager.get_dir())
        try:
            if sys.platform=="win32": os.startfile(path)
            elif sys.platform=="darwin": subprocess.Popen(["open",path])
            else: subprocess.Popen(["xdg-open",path])
        except Exception as e: QMessageBox.warning(self,"Ошибка",f"Не удалось открыть папку:\n{e}\n\nПуть: {path}")

    def _pfk(self, key):
        if key.endswith(" ч/б"): return key[:-4],"ч/б"
        if key.endswith(" цвет"): return key[:-5],"цвет"
        return None,None

    def _gfs(self, fmt):
        return format_dimensions_mm(fmt)

    def _detail_format_lines(self, f, kn, ss, pages, fill_p):
        """Строки детализации: с заливкой и без — отдельными позициями."""
        if not pages:
            return []
        split = self.cb_count_fill.isChecked() and not self.force_bw and fill_p
        if not split:
            rng = compact_page_list(pages)
            line = f"    {f} {kn}{ss} — {len(pages)} стр."
            if rng:
                line += f" ({rng})"
            return [line]
        with_fill = [p for p in pages if p in fill_p]
        without = [p for p in pages if p not in fill_p]
        out = []
        if with_fill:
            rng = compact_page_list(with_fill)
            out.append(
                f"    {f} {kn}{ss} — {len(with_fill)} стр. [заливка] ({rng})"
            )
        if without:
            rng = compact_page_list(without)
            out.append(f"    {f} {kn}{ss} — {len(without)} стр. ({rng})")
        return out

    def _autosize(self, te, minh=80, maxh=2000):
        """Подгоняет высоту поля под весь текст (без внутреннего скролла)."""
        d=te.document(); d.setTextWidth(te.viewport().width())
        te.setFixedHeight(max(minh, min(int(d.size().height() + 10), maxh)))

    def _build_print_summary(self):
        """
        Возвращает:
          st  — {(fmt, kind, has_fill): count}  — для печати по экземплярам
          di  — {(fmt, kind, has_fill): [(src_fmt, src_qty, added)]} — конвертации
          erb — длина рулона ч/б (мм) из нестандартных форматов
          erc — длина рулона цвет (мм) из нестандартных форматов
        has_fill — True если страница с заливкой, False — без, None — не различаем
        """
        c = self.copies
        st = defaultdict(int)
        di = defaultdict(list)
        split_fill = self.cb_count_fill.isChecked() and not self.force_bw

        # Считаем заливочные страницы по форматам из file_details
        fill_counts = defaultdict(int)  # {(fmt, kind): count}
        if split_fill:
            for fd in self.file_details:
                fill_pages = set(fd.get("fill_pages", []))
                if not fill_pages:
                    continue
                pages_map = fd.get("pages", {})
                for key, pages in pages_map.items():
                    fmt, kind = self._pfk(key)
                    if not fmt:
                        continue
                    cnt = sum(1 for p in pages if p in fill_pages)
                    if cnt > 0:
                        fill_counts[(fmt, kind)] += cnt

        # Стандартные форматы
        for fmt in ISO_A:
            for kind in KIND_ORDER:
                total_cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if total_cnt <= 0:
                    continue
                fill_cnt = fill_counts.get((fmt, kind), 0) if split_fill else 0
                normal_cnt = total_cnt - fill_cnt
                if split_fill and fill_cnt > 0:
                    st[(fmt, kind, True)] += fill_cnt * c
                if normal_cnt > 0:
                    st[(fmt, kind, False)] += normal_cnt * c

        # Конвертации (A4x3, A4x4 → A1; A3x3, A3x4 → A0)
        for src, (tgt, div) in CONVERSION_RULES.items():
            for kind in KIND_ORDER:
                total_cnt = int(self.grand.get(f"{src} {kind}", 0))
                if total_cnt <= 0:
                    continue
                fill_cnt = fill_counts.get((src, kind), 0) if split_fill else 0
                normal_cnt = total_cnt - fill_cnt

                if split_fill and fill_cnt > 0:
                    sq = fill_cnt * c
                    add = math.ceil(sq / div)
                    st[(tgt, kind, True)] += add
                    di[(tgt, kind, True)].append((src, sq, add))
                if normal_cnt > 0:
                    sq = normal_cnt * c
                    add = math.ceil(sq / div)
                    st[(tgt, kind, False)] += add
                    di[(tgt, kind, False)].append((src, sq, add))

        # Рулон из нестандартных
        erb = erc = 0.0
        ps = set(CONVERSION_RULES)
        for fmt, (fw, fh) in ISO_A_NONSTANDARD.items():
            if fmt in ps:
                continue
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    mm = max(fw, fh) * cnt * c
                    if kind == "цвет":
                        erc += mm
                    else:
                        erb += mm
        return st, di, erb, erc

    def _roll_totals_mm(self):
        """Рулон: ручной ввод + длина листов A4x3, A2x3 и др. (пог. м по длинной стороне)."""
        _, _, erb, erc = self._build_print_summary()
        rbt = self.grand.get("Рулон ч/б мм", 0) * self.copies + erb
        rct = self.grand.get("Рулон цвет мм", 0) * self.copies + erc
        return rbt, rct

    def _collect_roll_fold_groups(self):
        groups=[]
        for k,v in self.grand.items():
            if not k.startswith("_roll_fold_"): continue
            rest=k[len("_roll_fold_"):]
            if rest.endswith("_ч/б"): groups.append((rest[:-4],"ч/б",int(v)))
            elif rest.endswith("_цвет"): groups.append((rest[:-5],"цвет",int(v)))
        return [g for g in groups if g[2]>0]

    def _calc_folding(self, target):
        sl,nl,tf=[],[],0
        if target=="A4": sf,ex=["A3","A2","A1","A0"],{"A4"}
        elif target=="A3": sf,ex=["A2","A1","A0"],{"A4","A3"}
        else: return sl,nl,tf
        for fmt in sf:
            qty=(int(self.grand.get(f"{fmt} цвет",0))+int(self.grand.get(f"{fmt} ч/б",0)))*self.copies
            if qty>0: sl.append(f"{fmt} → {target} — {qty} шт."); tf+=qty
        for fmt in ISO_A_NONSTANDARD:
            qty=(int(self.grand.get(f"{fmt} цвет",0))+int(self.grand.get(f"{fmt} ч/б",0)))*self.copies
            if qty>0: nl.append(f"{fmt} → {target} — {qty} шт."); tf+=qty
        ct=defaultdict(int)
        for k in self.grand:
            if k.startswith("Рулон") or k.startswith("_roll_fold_"): continue
            fmt,kind=self._pfk(k)
            if not fmt or fmt in ex or fmt in ISO_A or fmt in ISO_A_NONSTANDARD: continue
            ct[fmt]+=int(self.grand.get(k,0))
        for fmt in sorted(ct):
            qty=ct[fmt]*self.copies
            if qty>0: nl.append(f"{fmt} → {target} — {qty} шт."); tf+=qty
        for ss,kind,count in self._collect_roll_fold_groups():
            qty=count*self.copies
            if qty>0: nl.append(f"{ss} мм {kind} → {target} — {qty} шт."); tf+=qty
        return sl,nl,tf

    def _calc_cutting(self):
        lines, total = [], 0
        for fmt in ISO_A_NONSTANDARD:
            if fmt not in CUTTING_FORMATS:
                continue
            qty = (
                int(self.grand.get(f"{fmt} цвет", 0))
                + int(self.grand.get(f"{fmt} ч/б", 0))
            ) * self.copies
            if qty > 0:
                fw, fh = ISO_A_NONSTANDARD[fmt]
                lines.append(f"{fmt} ({fw}×{fh} мм) — {qty} шт.")
                total += qty
        roll_cut = defaultdict(int)
        for fd in self.file_details:
            for rg in fd.get("roll_groups", []):
                if not rg.get("cutting"):
                    continue
                kind = "цвет" if rg.get("color") else "ч/б"
                key = f"{rg['w']:.0f}×{rg['h']:.0f} мм {kind}"
                roll_cut[key] += int(rg.get("count", 0))
        for key in sorted(roll_cut):
            qty = roll_cut[key] * self.copies
            if qty > 0:
                lines.append(f"{key} — {qty} шт.")
                total += qty
        return lines, total

    def _count_fill_pages(self):
        return sum(len(fd.get("fill_pages", [])) for fd in self.file_details)

    def _calc_binding(self):
        bl,tb=[],0
        if not self.file_page_counts: return bl,tb
        thrs=[30,70,110,170,220,280,400,470]; bins=defaultdict(int)
        for pc in self.file_page_counts:
            for t in thrs:
                if pc<=t: bins[t]+=1; break
            else: bins[thrs[-1]]+=1
        for t in thrs:
            if bins[t]>0: q=bins[t]*self.copies; bl.append(f"До {t} стр. — {q} шт."); tb+=q
        return bl,tb

    def _fw(self, g): return f"{g/1000:.2f} кг"

    def _calc_weight(self, st, rbm, rcm, bt, tb):
        total = 0.0
        for fmt in FMT_ORDER:
            sz = ISO_A.get(fmt)
            if not sz:
                continue
            wps = sz[0] * sz[1] * PAPER_DENSITY_G_PER_MM2
            qty = sum(
                st.get((fmt, k, hf), 0)
                for k in KIND_ORDER
                for hf in (True, False)
            )
            if qty > 0:
                total += wps * qty
        rm = rbm + rcm
        if rm > 0:
            total += rm * ROLL_WEIGHT_G_PER_MM
        if bt and tb > 0:
            u = BINDING_WEIGHT_G.get(bt, 0)
            if u > 0:
                total += u * tb
        return total

    def display_details(self):
        if not self.file_details: self.text_details.setText("Нет данных. Сначала проведите анализ."); return
        lines=[]
        for fd in self.file_details:
            lines.append(f"📄 {fd['name']}  ({fd['total']} стр.)")
            fmts=fd.get("formats",{}); pm=fd.get("pages",{})
            fill_p = set(fd.get("fill_pages", []))
            def sk(item):
                f,k=self._pfk(item[0])
                if f in FMT_ORDER: return (0,FMT_ORDER.index(f),k or "")
                if f in ISO_A_NONSTANDARD: return (1,list(ISO_A_NONSTANDARD).index(f),k or "")
                return (2,f or "",k or "")

            for k, _cnt in sorted(fmts.items(), key=sk):
                f, kn = self._pfk(k)
                if not f:
                    continue
                # A0xN не выводим здесь — они показываются ниже как roll_groups
                if f in UNPRINTABLE_FORMATS:
                    continue
                pages = pm.get(k, [])
                sz = self._gfs(f)
                ss = f" ({sz[0]}×{sz[1]} мм)" if sz else ""
                lines.extend(self._detail_format_lines(f, kn, ss, pages, fill_p))
            for rg in fd.get("roll_groups", []):
                kind_str = "цвет" if rg["color"] else "ч/б"
                rng = compact_page_list(rg["pages"])
                if rg.get("a0_key"):
                    pw = rg["printable_w"]
                    ph = rg["printable_h"]
                    line = (
                        f"    {rg['a0_key']} {kind_str} "
                        f"({rg['w']:.0f}×{rg['h']:.0f} мм) → "
                        f"{pw}×{ph} — {rg['count']} стр."
                    )
                else:
                    line = (
                        f"    Рулон {kind_str} "
                        f"({rg['w']:.0f}×{rg['h']:.0f} мм) — {rg['count']} стр."
                    )
                if rg.get("cutting"):
                    line += " [резка]"
                if rng:
                    line += f" ({rng})"
                lines.append(line)
            if not fd.get("roll_groups"):
                for label,pk,mk in [("Рулон ч/б","roll_bw_pages","roll_bw"),("Рулон цвет","roll_color_pages","roll_color")]:
                    rp=fd.get(pk,[]); rm=fd.get(mk,0)
                    if rp or rm>0:
                        rng=compact_page_list(rp); line=f"    {label} — {rm:.0f} мм"
                        if rng: line+=f" ({rng})"
                        lines.append(line)
            lines.append("")
        self.text_details.setText("\n".join(lines).rstrip())

    def calculate_and_display(self):
        if not self.grand:
            return
        self.display_details()
        st, di, erb, erc = self._build_print_summary()
        pl, tpp = [], 0
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                # Сначала позиция с заливкой (если есть)
                for has_fill in (True, False):
                    t = st.get((fmt, kind, has_fill), 0)
                    if t <= 0:
                        continue
                    suffix = " [заливка]" if has_fill else ""
                    line = f"{fmt} {kind} ({fw}×{fh} мм) — {t} стр.{suffix}"
                    conv = di.get((fmt, kind, has_fill))
                    if conv:
                        parts = [f"из {s}: {sq}→{a}" for s, sq, a in conv]
                        line += "  [" + ", ".join(parts) + "]"
                    pl.append(line)
                    tpp += t
        self.text_printing.setText("\n".join(pl) if pl else "Нет данных для печати")
        self._set_block_visible("text_printing", bool(pl))
        rbt = self.grand.get("Рулон ч/б мм", 0) * self.copies + erb
        rct = self.grand.get("Рулон цвет мм", 0) * self.copies + erc
        rl = []
        if rbt>0: rl.append(f"Ч/б — {rbt:.0f} мм ({rbt/1000:.2f} м)")
        if rct>0: rl.append(f"Цвет — {rct:.0f} мм ({rct/1000:.2f} м)")
        self.text_roll.setText("\n".join(rl) if rl else "Рулонная печать не требуется")
        self._set_block_visible("text_roll", bool(rl))
        cut_lines,cut_total=self._calc_cutting()
        if cut_lines:
            cp=["Форматы, требующие резки:",""]; cp.extend(cut_lines); cp.append(""); cp.append(f"Итого листов на резку: {cut_total}")
            self.text_cutting.setText("\n".join(cp))
        else: self.text_cutting.setText("Резка не требуется")
        self._set_block_visible("text_cutting", bool(cut_lines))
        ftp,tf,ft=[],0,None; slr,nlr=[],[]
        if self.need_folding_a4: ft="A4"
        elif self.need_folding_a3: ft="A3"
        if ft:
            slr,nlr,tf=self._calc_folding(ft)
            # Для менеджера: нестандартные/рулонные сворачиваем в строку «A0»
            # (в отчёте для клиента остаётся отдельный блок — он не меняется).
            nonstd_total = 0
            for l in nlr:
                try:
                    nonstd_total += int(l.rsplit("—", 1)[-1].strip().split()[0])
                except Exception:
                    pass
            mgr_lines = []
            base_a0 = 0
            for l in slr:
                if l.startswith("A0 →"):
                    try:
                        base_a0 = int(l.rsplit("—", 1)[-1].strip().split()[0])
                    except Exception:
                        base_a0 = 0
                else:
                    mgr_lines.append(l)
            a0_qty = base_a0 + nonstd_total
            if a0_qty > 0:
                mgr_lines.append(f"A0 → {ft} — {a0_qty} шт.")
            ftp.append(f"Фальцовка под {ft}"); ftp.append("")
            if mgr_lines:
                ftp.append("Стандартные форматы:")
                ftp.extend(mgr_lines)
        self.text_folding.setText("\n".join(ftp) if ftp else "Фальцовка не требуется")
        self._set_block_visible("text_folding", bool(ftp))

        blines,tb,bt=[],0,None
        if self.need_binding_a4: bt="A4"; blines,tb=self._calc_binding()
        elif self.need_binding_a3: bt="A3"; blines,tb=self._calc_binding()
        if bt:
            bp=[f"Брошюровка на пружину {bt}",""]; bp.extend(blines if blines else ["Нет данных"]); self.text_binding.setText("\n".join(bp))
        else: self.text_binding.setText("Брошюровка не требуется")
        self._set_block_visible("text_binding", bool(bt))
        tw=self._calc_weight(st,rbt,rct,bt,tb)
        self.label_total.setText(self._fw(tw) if tw > 0 else "0.00 кг")
        # Пересчитываем высоту блоков после раскладки (чтобы весь текст был виден)
        self._refit_manager_blocks()
        QTimer.singleShot(0, self._refit_manager_blocks)
        QTimer.singleShot(80, self._refit_manager_blocks)
        self._build_report(ft,slr,nlr,tf,bt,blines,tb,tw)

    def _refit_manager_blocks(self):
        """Подгоняет высоту каждого блока менеджера под весь его текст."""
        for attr in ("text_printing", "text_roll", "text_cutting",
                     "text_folding", "text_binding"):
            te = getattr(self, attr, None)
            refit = getattr(te, "_refit", None)
            if refit is not None:
                refit()

    def _build_report(self, ft, fs, fn, tf, bt, bl, tb, tw):
        c=self.copies; tpr=0
        sb=[]
        for fmt in FMT_ORDER:
            fw,fh=ISO_A[fmt]
            for kind in KIND_ORDER:
                cnt=int(self.grand.get(f"{fmt} {kind}",0))
                if cnt>0: q=cnt*c; sb.append(f"{fmt} {kind} ({fw}×{fh} мм) — {q} стр."); tpr+=q
        nb = []
        # Обычные расширенные форматы
        for fmt, (fw, fh) in ISO_A_NONSTANDARD.items():
            if fmt in UNPRINTABLE_FORMATS:
                continue
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    q = cnt * c
                    tpr += q
                    nb.append(f"{fmt} {kind} ({fw}×{fh} мм) — {q} стр.")

        # A0xN — добавляем в тот же блок с указанием печатаемого размера и масштаба
        a0_agg = defaultdict(int)  # {(a0_key, kind, ow, oh, pw, ph): qty}
        for fd in self.file_details:
            for rg in fd.get("roll_groups", []):
                if not rg.get("a0_key"):
                    continue
                count = rg.get("count", 0)
                if count <= 0:
                    continue
                kind_str = "цвет" if rg.get("color") else "ч/б"
                key = (
                    rg["a0_key"], kind_str,
                    int(rg["w"]), int(rg["h"]),
                    rg["printable_w"], rg["printable_h"],
                )
                a0_agg[key] += count * c
        for (a0_key, kind_str, ow, oh, pw, ph), qty in sorted(a0_agg.items()):
            scale = min(pw / ow, ph / oh) * 100
            nb.append(
                f"{a0_key} {kind_str} ({ow}×{oh} мм) → {pw}×{ph} "
                f"(масштаб {scale:.1f}%) — {qty} шт."
            )
            tpr += qty
        cb = []
        for k in self.grand:
            if k.startswith("Рулон") or k.startswith("_roll_fold_"):
                continue
            fmt, kind = self._pfk(k)
            if not fmt or not kind:
                continue
            if fmt in ISO_A or fmt in ISO_A_NONSTANDARD:
                continue
            # A0xN — не выводим в "Произвольных", они идут в "Печать на рулоне"
            if fmt in UNPRINTABLE_FORMATS:
                continue
            cnt = int(self.grand.get(k, 0))
            if cnt > 0:
                q = cnt * c
                cb.append(f"{fmt} {kind} — {q} стр.")
                tpr += q
        rb_lines = []
        for fd in self.file_details:
            for rg in fd.get("roll_groups", []):
                # A0xN уже учтены выше в nb
                if rg.get("a0_key"):
                    continue
                count = rg.get("count", 0)
                if count <= 0:
                    continue
                q = count * c
                tpr += q
                kind_str = "цвет" if rg.get("color") else "ч/б"
                w = rg.get("w", 0)
                h = rg.get("h", 0)
                rb_lines.append(f"{w:.0f}×{h:.0f} мм {kind_str} — {q} шт.")

        if rb_lines:
            agg = defaultdict(int)
            for line in rb_lines:
                m = re.match(r'(.+?) — (\d+) шт\.$', line)
                if m:
                    agg[m.group(1)] += int(m.group(2))
            rb_lines = [f"{k} — {v} шт." for k, v in agg.items()]
        cms="Ч/б (принудительно)" if self.force_bw else "По файлу"
        lines=["="*60,"АНАЛИЗ ПРОЕКТНОЙ ДОКУМЕНТАЦИИ","="*60,f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Всего страниц в источнике: {self.total_source}",f"Количество экземпляров: {c}",f"Режим цветности: {cms}","",
            "ПЕЧАТЬ (с учетом кол-ва экземпляров):"]
        if sb: lines.append("• Стандартные форматы:"); lines.extend(f"  {l}" for l in sb)
        if nb:
            if sb: lines.append("")
            lines.append("• Расширенные форматы:"); lines.extend(f"  {l}" for l in nb)
        if cb:
            if sb or nb: lines.append("")
            lines.append("• Произвольные форматы:"); lines.extend(f"  {l}" for l in cb)
        if rb_lines:
            if sb or nb or cb:
                lines.append("")
            lines.append("• Нестандартные/рулонные форматы:")
            lines.extend(f"  {l}" for l in rb_lines)
        if not (sb or nb or cb or rb_lines):
            lines.append("Нет данных")
        lines.append(f"Итого страниц: {tpr}")
        lines.append("")
        if ft:
            lines.append(f"ФАЛЬЦОВКА ПОД {ft}:")
            if fs: lines.append("• Стандартные форматы:"); lines.extend(f"  {l}" for l in fs)
            if fn:
                if fs: lines.append("")
                lines.append("• Нестандартные/рулонные форматы:"); lines.extend(f"  {l}" for l in fn)
            if not (fs or fn): lines.append("Не требуется")
            lines.append(f"Итого листов: {tf}"); lines.append("")
        if bt:
            lines.append(f"БРОШЮРОВКА НА ПРУЖИНУ {bt}:")
            if bl: lines.append("• По количеству страниц:"); lines.extend(f"  {l}" for l in bl)
            else: lines.append("Не требуется")
            lines.append(f"Итого брошюр: {tb}"); lines.append("")
        lines.append("─"*60); lines.append(f"ВЕС: {self._fw(tw)}"); lines.append("="*60)
        self.text_report.setText("\n".join(lines))
        # Структурированные данные для генерации PDF (сохраняем для кнопки PDF)
        self._report_data = {
            "date": datetime.now().strftime('%d.%m.%Y %H:%M'),
            "total_source": self.total_source,
            "copies": c,
            "color_mode": cms,
            "print_std": sb,
            "print_ext": nb,
            "print_custom": cb,
            "print_roll": rb_lines,
            "total_pages": tpr,
            "folding_type": ft,
            "folding_std": fs,
            "folding_nonstd": fn,
            "folding_total": tf,
            "binding_type": bt,
            "binding_lines": bl,
            "binding_total": tb,
            "weight": tw,
        }

    def generate_client_pdf(self):
        """Красиво оформленный PDF-отчёт для клиента."""
        data = getattr(self, "_report_data", None)
        if not data:
            QMessageBox.warning(self, "Нет данных", "Сначала выполните анализ.")
            return
        default_name = f"Отчет_{datetime.now().strftime('%d.%m.%Y_%H%M')}.pdf"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить PDF-отчёт", default_name, "PDF (*.pdf)"
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
        try:
            self._render_report_pdf(data, out_path)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать PDF:\n{e}")
            return
        try:
            if sys.platform == "win32": os.startfile(out_path)
            elif sys.platform == "darwin": subprocess.Popen(["open", out_path])
            else: subprocess.Popen(["xdg-open", out_path])
        except Exception:
            pass
        QMessageBox.information(self, "Готово", f"PDF-отчёт сохранён:\n{out_path}")

    def _render_report_pdf(self, data, out_path):
        """Рисует красивый PDF-отчёт (A4) в фирменных цветах логотипа (#EF7F1A)."""
        import fitz as _fitz

        # Фирменная палитра (из логотипа): оранжевый + графитовый
        ORANGE = (0.937, 0.498, 0.102)        # #EF7F1A
        ORANGE_DARK = (0.792, 0.388, 0.043)   # #CA6310
        ORANGE_SOFT = (0.996, 0.937, 0.898)   # мягкий фон #FEEF E5
        ORANGE_BAND = (0.984, 0.898, 0.835)   # плашка #FB E5 D5
        GRAPH = (0.169, 0.165, 0.161)         # #2B2A29
        GREY = (0.55, 0.55, 0.56)
        WHITE = (1.0, 1.0, 1.0)

        reg = _fitz.Font(fontfile=r"C:\Windows\Fonts\segoeui.ttf")
        bold = _fitz.Font(fontfile=r"C:\Windows\Fonts\segoeuib.ttf")

        doc = _fitz.open()
        pw, ph = _fitz.paper_size("a4")
        margin = 42
        content_w = pw - 2 * margin

        page = doc.new_page(width=pw, height=ph)
        y = 0

        def new_page_if_needed(need):
            nonlocal page, y
            if y + need > ph - margin:
                page = doc.new_page(width=pw, height=ph)
                y = margin + 10

        # ── Шапка без цветной плашки: логотип слева, заголовок оранжевым ──
        y = margin
        logo = resource_path("assets/logo.png")
        logo_w, logo_h = 150, 44
        if os.path.exists(logo):
            try:
                page.insert_image(
                    _fitz.Rect(margin, y, margin + logo_w, y + logo_h),
                    filename=logo, keep_proportion=True,
                )
            except Exception:
                pass
        # Заголовок справа от логотипа — оранжевым (не белым)
        tw = _fitz.TextWriter(page.rect)
        tw.append((margin + logo_w + 22, y + 20), "Анализ файлов",
                  font=bold, fontsize=18)
        tw.write_text(page, color=ORANGE)
        # Дата — справа, выровнена по правому краю, серым
        date_text = f"Дата: {data['date']}"
        dw = reg.text_length(date_text, fontsize=10)
        twd = _fitz.TextWriter(page.rect)
        twd.append((pw - margin - dw, y + 20), date_text, font=reg, fontsize=10)
        twd.write_text(page, color=GREY)
        y += logo_h + 10
        # Тонкая оранжевая линия-разделитель под шапкой
        page.draw_line(_fitz.Point(margin, y), _fitz.Point(pw - margin, y),
                       color=ORANGE, width=1.6)
        y += 20

        def section(title):
            nonlocal y
            new_page_if_needed(40)
            band = _fitz.Rect(margin, y, margin + content_w, y + 26)
            page.draw_rect(band, color=None, fill=ORANGE_BAND, radius=0.12)
            # оранжевая засечка слева
            page.draw_rect(_fitz.Rect(margin, y, margin + 4, y + 26),
                           color=None, fill=ORANGE, radius=0.4)
            tws = _fitz.TextWriter(page.rect)
            tws.append((margin + 16, y + 18), title, font=bold, fontsize=11.5)
            tws.write_text(page, color=ORANGE_DARK)
            y += 36

        def line(text, indent=10, size=10, color=GRAPH, is_bold=False, gap=15):
            nonlocal y
            new_page_if_needed(gap + 2)
            twl = _fitz.TextWriter(page.rect)
            twl.append((margin + indent, y), text,
                       font=(bold if is_bold else reg), fontsize=size)
            twl.write_text(page, color=color)
            y += gap

        # ── Сводка ──
        section("Общие сведения")
        line(f"Всего страниц в источнике: {data['total_source']}")
        line(f"Количество экземпляров: {data['copies']}")
        line(f"Режим цветности: {data['color_mode']}")
        y += 6

        # ── Печать ──
        section("Печать (с учётом количества экземпляров)")
        groups = [
            ("Стандартные форматы", data["print_std"]),
            ("Расширенные форматы", data["print_ext"]),
            ("Произвольные форматы", data["print_custom"]),
            ("Нестандартные / рулонные форматы", data["print_roll"]),
        ]
        any_print = any(items for _, items in groups)
        if any_print:
            for title, items in groups:
                if not items:
                    continue
                line(title + ":", indent=10, is_bold=True, color=ORANGE_DARK)
                for it in items:
                    line("•  " + it, indent=22)
            # Итог в рамке
            new_page_if_needed(30)
            tot_rect = _fitz.Rect(margin, y - 2, margin + content_w, y + 22)
            page.draw_rect(tot_rect, color=None, fill=ORANGE_SOFT, radius=0.12)
            twp = _fitz.TextWriter(page.rect)
            twp.append((margin + 12, y + 14), f"Итого страниц: {data['total_pages']}",
                       font=bold, fontsize=11)
            twp.write_text(page, color=ORANGE_DARK)
            y += 32
        else:
            line("Нет данных")
        y += 6

        # ── Фальцовка ──
        if data["folding_type"]:
            section(f"Фальцовка под {data['folding_type']}")
            if data["folding_std"]:
                line("Стандартные форматы:", is_bold=True, color=ORANGE_DARK)
                for it in data["folding_std"]:
                    line("•  " + it, indent=22)
            if data["folding_nonstd"]:
                line("Нестандартные / рулонные форматы:", is_bold=True, color=ORANGE_DARK)
                for it in data["folding_nonstd"]:
                    line("•  " + it, indent=22)
            if not (data["folding_std"] or data["folding_nonstd"]):
                line("Не требуется")
            line(f"Итого листов: {data['folding_total']}", is_bold=True, gap=20, color=ORANGE_DARK)
            y += 6

        # ── Брошюровка ──
        if data["binding_type"]:
            section(f"Брошюровка на пружину {data['binding_type']}")
            if data["binding_lines"]:
                for it in data["binding_lines"]:
                    line("•  " + it, indent=22)
            else:
                line("Не требуется")
            line(f"Итого брошюр: {data['binding_total']}", is_bold=True, gap=20, color=ORANGE_DARK)
            y += 6

        # ── Итоговый вес: оранжевая карточка ──
        new_page_if_needed(64)
        card = _fitz.Rect(margin, y, margin + content_w, y + 52)
        page.draw_rect(card, color=None, fill=ORANGE, radius=0.1)
        twt = _fitz.TextWriter(page.rect)
        twt.append((margin + 18, y + 32), "Итоговый вес: ", font=bold, fontsize=13)
        twt.write_text(page, color=(1.0, 1.0, 1.0, 0.85) if False else WHITE)
        twt2 = _fitz.TextWriter(page.rect)
        twt2.append((margin + 150, y + 33), self._fw(data["weight"]), font=bold, fontsize=16)
        twt2.write_text(page, color=WHITE)

        # ── Подвал: только серая линия ──
        foot_y = ph - 30
        page.draw_line(_fitz.Point(margin, foot_y - 6),
                       _fitz.Point(pw - margin, foot_y - 6),
                       color=(0.85, 0.85, 0.86), width=0.8)

        doc.save(out_path, deflate=True)
        doc.close()

    def copy_report(self):
        txt=self.text_report.toPlainText()
        try:
            import pyperclip; pyperclip.copy(txt)
        except Exception:
            try:
                p=subprocess.Popen(['clip'],stdin=subprocess.PIPE,shell=True)
                p.communicate(txt.encode('utf-8'))
            except Exception:
                pass
        self.btn_copy_report.setText("✅ Скопировано")
        self.btn_copy_report.setStyleSheet(_qss_button("filled", accent=THEME["success"]))
        QTimer.singleShot(
            1500,
            lambda: (
                self.btn_copy_report.setText("📋 Копировать в буфер обмена"),
                self.btn_copy_report.setStyleSheet(self._copy_btn_style),
            ),
        )
    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        # Принимаем, если хотя бы один путь — это PDF или папка
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isdir(path) or path.lower().endswith(".pdf"):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isdir(p) or p.lower().endswith(".pdf"):
                paths.append(p)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._handle_dropped_paths(paths)

    def _handle_dropped_paths(self, paths):
        """Обработка перетянутых файлов/папок."""
        if len(paths) == 1:
            self.selected_path = paths[0]
            self._dropped_pdfs = None
            self.drop_area.set_selected_path(paths[0])
            self.label_status.setText("📥 Готово — нажмите «Начать анализ»")
            return
        # Несколько объектов
        pdfs = []
        for p in paths:
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    for f in fs:
                        if f.lower().endswith(".pdf"):
                            pdfs.append(os.path.join(r, f))
            elif p.lower().endswith(".pdf"):
                pdfs.append(p)
        if not pdfs:
            self.label_status.setText("❌ PDF файлы не найдены в перетянутых объектах")
            return
        self._dropped_pdfs = pdfs
        common_dir = (
            os.path.commonpath([os.path.dirname(p) for p in pdfs])
            if len(pdfs) > 1 else os.path.dirname(pdfs[0])
        )
        self.selected_path = common_dir
        self.drop_area.set_selected_path(
            common_dir, info_suffix=f"({len(pdfs)} PDF)"
        )
        self.label_status.setText(f"📥 Перетянуто {len(pdfs)} PDF — нажмите «Начать анализ»")

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning(): self.thread.request_stop(); self.thread.wait(2000)
        super().closeEvent(event)


class _UpdateChecker(QThread):
    """Фоновая проверка обновлений: не блокирует интерфейс."""

    found = pyqtSignal(bool, str, str)

    def run(self):
        try:
            has_update, latest_ver, dl_url, _err = check_for_update()
        except Exception:
            has_update, latest_ver, dl_url = False, None, None
        self.found.emit(bool(has_update), latest_ver or "", dl_url or "")


_update_checker_keepalive = []


def _check_update_background():
    checker = _UpdateChecker()
    checker.found.connect(lambda h, v, u: _on_update_found(h, v, u))
    checker.found.connect(lambda *_: checker.deleteLater())
    _update_checker_keepalive.append(checker)
    checker.start()


def _on_update_found(has_update, latest_ver, dl_url):
    global _update_dialog_ref
    if has_update and latest_ver:
        _mark_update_attempt(latest_ver)
        # Держим ссылку, иначе диалог удаляется сборщиком мусора и обновление не скачивается
        _update_dialog_ref = UpdateDialog(latest_ver, dl_url)
        _update_dialog_ref.show()
        _update_dialog_ref.raise_()
        _update_dialog_ref.activateWindow()


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

class _LicenseChecker(QThread):
    """Фоновая проверка лицензии: не задерживает запуск программы."""

    result_ready = pyqtSignal(bool, str)

    def __init__(self, window, app):
        super().__init__(window)
        self._window = window
        self._app = app
        self.result_ready.connect(self._on_result)

    def run(self):
        try:
            ok, msg = check_remote_license()
        except Exception as e:
            ok, msg = True, str(e)   # fail-open при сбое
        self.result_ready.emit(ok, msg)

    def _on_result(self, ok, msg):
        if not ok:
            try:
                self._window.close()
            except Exception:
                pass
            QMessageBox.critical(None, "Доступ запрещён", msg)
            self._app.exit(1)
            return
        if getattr(sys, "frozen", False):
            _clear_update_settings_if_current()
            QTimer.singleShot(800, lambda: _check_update_background())


def main():
    app = QApplication(sys.argv)
    force_light_palette(app)

    icon_path = resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    _create_single_instance_mutex()

    # Главное окно показываем сразу — запуск быстрый, без ожидания сети
    window = PrintingCalculator()
    window.show()

    # Проверка лицензии — в фоне, не задерживает запуск
    _LicenseChecker(window, app).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()