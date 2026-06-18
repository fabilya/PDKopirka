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
    QTableWidget, QTableWidgetItem, QTextEdit, QProgressBar, QFrame,
    QScrollArea, QDialog, QLineEdit, QMessageBox, QGroupBox,
    QRadioButton, QButtonGroup, QSizePolicy, QHeaderView, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor
import json
import shutil

try:
    import certifi
    _HAS_CERTIFI = True
except ImportError:
    _HAS_CERTIFI = False


# ─────────────────────────────────────────────────────────────────────────────
# Принудительная светлая палитра
# ─────────────────────────────────────────────────────────────────────────────

def force_light_palette(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor("#f5f6f7"))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor("#333333"))
    pal.setColor(QPalette.ColorRole.Base,             QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.AlternateBase,    QColor("#f8f9fa"))
    pal.setColor(QPalette.ColorRole.Text,             QColor("#333333"))
    pal.setColor(QPalette.ColorRole.Button,           QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ButtonText,       QColor("#333333"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,      QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipText,      QColor("#333333"))
    pal.setColor(QPalette.ColorRole.PlaceholderText,  QColor("#999999"))
    pal.setColor(QPalette.ColorRole.Highlight,        QColor("#0066cc"))
    pal.setColor(QPalette.ColorRole.HighlightedText,  QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.BrightText,       QColor("#333333"))
    pal.setColor(QPalette.ColorRole.Link,             QColor("#0066cc"))
    pal.setColor(QPalette.ColorRole.LinkVisited,      QColor("#0052a3"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.WindowText, QColor("#aaaaaa"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text, QColor("#aaaaaa"))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, QColor("#aaaaaa"))
    app.setPalette(pal)


# ─────────────────────────────────────────────────────────────────────────────
# Пути к ресурсам
# ─────────────────────────────────────────────────────────────────────────────

def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.abspath(".")
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

APP_VERSION = "2.2.1"
INNO_APP_ID = "{8F4C8D7A-2D52-4A1A-9E6B-7A8B9C0D1E2F}"
UPDATE_REPO = "fabilya/PDKopirka"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
GITHUB_TOKEN = os.environ.get("PDKOPIRKA_GITHUB_TOKEN", "").strip()


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
    1) version.txt рядом с exe (после установки Inno Setup)
    2) APP_VERSION из собранного exe (при сборке PyInstaller)
    3) реестр Windows — только запасной вариант
    """
    ver = _read_version_file()
    if ver:
        return ver
    if getattr(sys, "frozen", False):
        return APP_VERSION
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


def check_for_update():
    """Ищет установщик (.exe) в последнем релизе."""
    try:
        req = urllib.request.Request(UPDATE_API_URL)
        req.add_header("User-Agent", "PDKopirka-Updater/1.0")
        req.add_header("Accept", "application/vnd.github.v3+json")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"token {GITHUB_TOKEN}")
        with _urlopen_safe(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = data.get("tag_name", "")
        if not latest_tag:
            return False, None, None, "GitHub вернул пустой tag_name."
        current = get_app_version()
        if _parse_version(latest_tag) <= _parse_version(current):
            return False, None, None, None
        assets = data.get("assets", [])
        download_url = None
        # Сначала ищем установщик (с "setup" или "install" в имени)
        for asset in assets:
            name_lower = asset["name"].lower()
            if name_lower.endswith(".exe") and (
                "setup" in name_lower or "install" in name_lower
            ):
                if GITHUB_TOKEN:
                    download_url = asset["url"]
                else:
                    download_url = asset["browser_download_url"]
                break
        # Запасной вариант — любой .exe
        if not download_url:
            for asset in assets:
                if asset["name"].lower().endswith(".exe"):
                    if GITHUB_TOKEN:
                        download_url = asset["url"]
                    else:
                        download_url = asset["browser_download_url"]
                    break
        if not download_url:
            return False, None, None, f"В релизе {latest_tag} не найден .exe файл."
        return True, latest_tag, download_url, None
    except urllib.error.HTTPError as e:
        return False, None, None, f"HTTP ошибка: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return False, None, None, f"Нет доступа к GitHub: {e.reason}"
    except Exception as e:
        return False, None, None, f"{type(e).__name__}: {e}"


def download_update(url, target_path, progress_callback=None):
    """Скачивает установщик .exe"""
    try:
        for old in [target_path, target_path + ".part"]:
            if os.path.exists(old):
                try:
                    os.remove(old)
                except OSError:
                    pass
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "PDKopirka-Updater/1.0")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"token {GITHUB_TOKEN}")
            req.add_header("Accept", "application/octet-stream")
        with _urlopen_safe(req, timeout=300) as resp:
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
            return False
        if os.path.getsize(temp_path) < 1024 * 100:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False
        # Проверка MZ-сигнатуры (.exe)
        with open(temp_path, "rb") as f:
            magic = f.read(2)
        if magic != b"MZ":
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False
        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(temp_path, target_path)
        return True
    except Exception:
        return False


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
        t.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        t.setStyleSheet("color: #0066cc; background: transparent;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar { border: 1px solid #ddd; border-radius: 4px; "
            "background-color: white; color: #333; } "
            "QProgressBar::chunk { background-color: #0066cc; }"
        )
        lay.addWidget(self.progress)
        self.status_lbl = QLabel("Подготовка...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #555; background: transparent;")
        lay.addWidget(self.status_lbl)

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
        ok = download_update(self.download_url, new_installer, on_progress)
        if not ok:
            self.status_lbl.setText("❌ Ошибка загрузки.")
            self.progress.setValue(0)
            QApplication.processEvents()
            time.sleep(3)
            os._exit(1)
            return
        self.progress.setValue(100)
        self.status_lbl.setText("✅ Запуск установщика...")
        QApplication.processEvents()
        time.sleep(1)
        apply_update_and_restart(new_installer, self.latest_version)


# ─────────────────────────────────────────────────────────────────────────────
# Диалог «Что нового»
# ─────────────────────────────────────────────────────────────────────────────

def _changelog_html(version):
    return f"""
<h2 style="color:#0066cc; margin-bottom:10px;">Версия {version}</h2>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    📂 Выбор файлов и папок
</h3>
<ul>
    <li>Добавлена зона перетаскивания (Drag & Drop) — можно перетащить папку или PDF файл прямо в окно программы</li>
    <li>Кнопки «Папка» и «Файл» вынесены в отдельный блок справа от зоны DnD</li>
    <li>Визуальная подсветка зоны при наведении файла (синяя пунктирная рамка)</li>
    <li>После выбора зона становится зелёной и показывает путь</li>
    <li>Путь отображается в одну строку, при необходимости можно выделить и скопировать мышкой</li>
</ul>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    📐 Определение форматов
</h3>
<ul>
    <li>Погрешность определения формата увеличена с 5 до 10 мм — корректнее распознаются чертежи с нестандартными размерами</li>
</ul>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    🎯 Обработка форматов A0×N
</h3>
<ul>
    <li>Клик по ячейке A0×N в справочнике корректно обрабатывается как печать на рулоне 910 мм</li>
    <li>В детализации: <code>A0x2 ч/б (1189×1682 мм) → 910×1287 — 2 стр. (1-2)</code></li>
    <li>В блоке для менеджера (CRM): добавляется метраж в рулонную печать по большей стороне печатаемого формата</li>
    <li>В отчёте для клиента: A0×N отображаются в общем списке расширенных форматов с указанием печатаемого размера и масштаба</li>
    <li>Устранено дублирование A0×N в детализации (раньше выводились дважды — в общем блоке и в roll_groups)</li>
</ul>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    📄 Отчёт для клиента
</h3>
<ul>
    <li>Объединены блоки расширенных форматов и A0×N в одну группу</li>
    <li>«Итого страниц» перенесено в конец отчёта</li>
</ul>
"""


class WhatsNewDialog(QDialog):
    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.setWindowTitle("🎉 Что нового")
        self.setMinimumSize(550, 450)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(25, 25, 25, 25)
        title = QLabel(f"🎉 Версия {self.current_version}")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #0066cc; background: transparent;")
        lay.addWidget(title)
        self.te = QTextEdit()
        self.te.setReadOnly(True)
        self.te.setFont(QFont("Arial", 10))
        self.te.setStyleSheet(
            "QTextEdit { background: white; color: #333; border: 1px solid #ddd; "
            "border-radius: 6px; padding: 8px; }"
        )
        self.te.setHtml(_changelog_html(self.current_version))
        lay.addWidget(self.te)
        btn = QPushButton("👍 Закрыть")
        btn.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        btn.setMinimumHeight(40)
        btn.setStyleSheet(
            "QPushButton { background-color: #0066cc; color: white; "
            "border: none; border-radius: 6px; font-weight: bold; } "
            "QPushButton:hover { background-color: #0052a3; }"
        )
        btn.clicked.connect(self.accept)
        lay.addWidget(btn)
        self.setStyleSheet("QDialog { background-color: #f5f6f7; color: #333; }")


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

CUTTING_FORMATS = {
    "A4x3", "A4x5", "A4x6", "A4x7", "A4x8", "A4x9",
    "A3x3", "A3x4", "A3x5", "A3x6", "A3x7", "A3x8", "A3x9",
}

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
        with _urlopen_safe(req, timeout=15) as resp:
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
        return False, (
            "Не удалось проверить лицензию.\n\n"
            "Проверьте подключение к интернету."
        )
    except Exception as e:
        return False, f"Ошибка проверки лицензии:\n{e}"


# ─────────────────────────────────────────────────────────────────────────────
# Виджеты
# ─────────────────────────────────────────────────────────────────────────────

class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


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

def _format_hint_style(name):
    if name in UNPRINTABLE_FORMATS:
        return "#888888", "Не печатаем"
    if name in PRINTABLE_A0_SIZE_NAMES.values():
        return "#2e7d32", "Ближайший формат"
    if name in CUTTING_FORMATS:
        return "#1565c0", "С учетом резки"
    return "#2e7d32", "Без резки"


def _format_legend_html():
    return (
        '<span style="color:#2e7d32;font-size:12px;">●</span> Без резки &nbsp;&nbsp; '
        '<span style="color:#1565c0;font-size:12px;">●</span> С учетом резки &nbsp;&nbsp; '
        '<span style="color:#ff0000;font-size:12px;">●</span> Не печатаем &nbsp;&nbsp; '
        '<span style="color:#2e7d32;font-size:12px;">●</span> Ближайший формат'
    )


# Столбцы справочника (блоки 1–4)
_FORMAT_COL_A4 = ["A4"] + [f"A4x{i}" for i in range(3, 10)]
_FORMAT_COL_A3 = ["A3"] + [f"A3x{i}" for i in range(3, 10)]
_FORMAT_COL_A2 = ["A2"] + [f"A2x{i}" for i in range(3, 10)]
_FORMAT_COL_A1 = ["A1"] + [f"A1x{i}" for i in range(3, 10)]
_A0_OVERSIZE_ORDER = [f"A0x{i}" for i in range(2, 10)]


class A0NearestFormatRow(QFrame):
    """Строка A0×N: номинал (серый) → печатаемый размер (зелёный), клик — ближайший формат."""

    def __init__(self, key, on_format_click, parent=None):
        super().__init__(parent)
        self._fmt_name = PRINTABLE_A0_SIZE_NAMES[A0_PRINTABLE_MM[key]]
        self._on_format_click = on_format_click
        ow, oh = A0_OVERSIZE_MM[key]
        pw, ph = A0_PRINTABLE_MM[key]
        self.setStyleSheet(
            "A0NearestFormatRow { background: white; border: 1px solid #ccc; border-radius: 4px; }"
            "A0NearestFormatRow:hover { background: #e8f4ff; border-color: #2e7d32; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        title = QLabel(key)
        title.setFont(QFont("Arial", 8, QFont.Weight.Bold))
        title.setStyleSheet("color: #333; background: transparent; border: none;")
        line = QLabel(
            f'<span style="color:#c62828;">{ow}×{oh}</span>'
            f' → <span style="color:#2e7d32;">{pw}×{ph}</span>'
        )
        line.setTextFormat(Qt.TextFormat.RichText)
        line.setFont(QFont("Arial", 8))
        line.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(title)
        lay.addWidget(line)


class FormatHintPanel(QFrame):
    """Справочник форматов (5 блоков); клик вызывает on_format_click(name)."""

    # Высота одной строки в колонке (одинаковая для всех типов ячеек)
    _ROW_HEIGHT = 38
    # Количество строк в колонке (1 базовый + 7 расширенных)
    _ROWS_COUNT = 8

    def __init__(self, parent=None, on_format_click=None):
        super().__init__(parent)
        self._on_format_click = on_format_click
        self._panel_width = 540
        self.setStyleSheet(
            "FormatHintPanel { background-color: #f9f9f9; "
            "border: 2px solid #0066cc; border-radius: 8px; color: #333; }"
        )
        self.setFixedWidth(self._panel_width)
        cl = QVBoxLayout(self)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(6)

        title = QLabel("📐 Выберите ближайший формат")
        title.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #0066cc; background: transparent; border: none;")
        cl.addWidget(title)

        legend = QLabel(_format_legend_html())
        legend.setTextFormat(Qt.TextFormat.RichText)
        legend.setFont(QFont("Arial", 8))
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legend.setStyleSheet("color: #333; background: transparent; border: none;")
        legend.setWordWrap(True)
        cl.addWidget(legend)

        inner = QFrame()
        inner.setStyleSheet(
            "QFrame { background: white; border: 1px solid #ddd; "
            "border-radius: 4px; }"
        )
        root = QHBoxLayout(inner)
        root.setSpacing(4)
        root.setContentsMargins(4, 4, 4, 4)

        root.addWidget(self._make_column_block(_FORMAT_COL_A4), stretch=1)
        root.addWidget(self._make_column_block(_FORMAT_COL_A3), stretch=1)
        root.addWidget(self._make_column_block(_FORMAT_COL_A2), stretch=1)
        root.addWidget(self._make_column_block(_FORMAT_COL_A1), stretch=1)
        root.addWidget(self._make_a0_column(), stretch=1)

        cl.addWidget(inner, stretch=1)

    def _btn_style(self, color, enabled=True):
        if not enabled:
            return (
                f"QPushButton {{ color: {color}; background: #fafafa; "
                f"border: 1px solid #ddd; border-radius: 4px; "
                f"padding: 2px 4px; text-align: center; }}"
            )
        return (
            f"QPushButton {{ color: {color}; background: white; "
            f"border: 1px solid #ccc; border-radius: 4px; "
            f"padding: 2px 4px; text-align: center; }}"
            f"QPushButton:hover {{ background: #e8f4ff; border-color: {color}; }}"
        )

    def _make_format_button(self, name, label=None, color=None, tip=None,
                             enabled=True, fmt_name=None):
        fmt_name = fmt_name or name
        if color is None:
            color, tip = _format_hint_style(fmt_name)
        btn = QPushButton(label or name)
        btn.setFont(QFont("Arial", 7))
        btn.setToolTip(tip or "")
        btn.setFixedHeight(self._ROW_HEIGHT)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(self._btn_style(color, enabled))
        if enabled and self._on_format_click:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, n=fmt_name: self._on_format_click(n))
        else:
            btn.setEnabled(False)
        return btn

    def _make_filler(self):
        """Невидимая ячейка той же высоты, чтобы выровнять колонки."""
        filler = QWidget()
        filler.setFixedHeight(self._ROW_HEIGHT)
        filler.setStyleSheet("background: transparent; border: none;")
        return filler

    def _make_column_block(self, format_names):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #fafafa; border: 1px solid #ccc; "
            "border-radius: 6px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        for name in format_names:
            wh = format_dimensions_mm(name)
            if not wh:
                continue
            w, h = wh
            lay.addWidget(self._make_format_button(name, f"{name}\n{w}×{h}"))
        # Добавляем пустые ячейки, чтобы колонка имела ту же высоту,
        # что и самая длинная (A0)
        rows_added = len(format_names)
        for _ in range(self._ROWS_COUNT - rows_added):
            lay.addWidget(self._make_filler())
        return frame

    def _make_a0_column(self):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #fafafa; border: 1px solid #ccc; "
            "border-radius: 6px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        # A0 — стандартный
        w0, h0 = ISO_A["A0"]
        lay.addWidget(self._make_format_button("A0", f"A0\n{w0}×{h0}"))

        # A0x2..A0x8 — не печатаем, показываем ближайший
        for key in _A0_OVERSIZE_ORDER[:7]:  # без A0x9
            lay.addWidget(self._make_a0_row(key))

        return frame

    def _make_a0_row(self, key):
        """Строка A0×N: название (зелёное) + (красный номинал) (зелёный печатаемый)."""
        ow, oh = A0_OVERSIZE_MM[key]
        pw, ph = A0_PRINTABLE_MM[key]
        fmt_name = PRINTABLE_A0_SIZE_NAMES[A0_PRINTABLE_MM[key]]

        frame = QFrame()
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        frame.setFixedHeight(self._ROW_HEIGHT)
        frame.setStyleSheet(
            "QFrame { background: white; border: 1px solid #ccc; "
            "border-radius: 4px; }"
            "QFrame:hover { background: #e8f4ff; border-color: #2e7d32; }"
        )

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)

        title = QLabel(key)
        title.setFont(QFont("Arial", 7, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color: #2e7d32; background: transparent; border: none;"
        )

        sizes = QLabel(
            f'<span style="color:#c62828;font-weight:bold;">{ow}×{oh}</span>'
            f'<span style="color:#555;"> </span>'
            f'<span style="color:#2e7d32;font-weight:bold;">({pw}×{ph})</span>'
        )
        sizes.setTextFormat(Qt.TextFormat.RichText)
        sizes.setFont(QFont("Arial", 7, QFont.Weight.Bold))
        sizes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sizes.setStyleSheet("background: transparent; border: none;")

        lay.addWidget(title)
        lay.addWidget(sizes)

        def on_click(event):
            if (event.button() == Qt.MouseButton.LeftButton
                    and self._on_format_click):
                self._on_format_click(fmt_name)

        frame.mousePressEvent = on_click
        return frame


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
        self.setMinimumWidth(540)
        self.setModal(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        mw = QWidget()
        root = QVBoxLayout(mw)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        # Информация о файле
        ib = QGroupBox("Обнаружен неизвестный формат")
        ib.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        ib.setStyleSheet(
            "QGroupBox{color:#333;background-color:white;}"
            "QGroupBox::title{color:#333;}"
        )
        il = QVBoxLayout(ib)
        for t in [
            f"Файл: <b>{os.path.basename(self.pdf_path)}</b>",
            f"Размер: <b>{self.w} × {self.h} мм</b>",
            f"Цветность: <b>{cs}</b>",
            f"Страниц: <b>{len(self.pages)}</b>  ({rng})",
        ]:
            lb = QLabel(t)
            lb.setFont(QFont("Arial", 10))
            lb.setStyleSheet("color:#333;background:transparent;")
            il.addWidget(lb)
        bo = QPushButton("👁️ Открыть эти страницы для просмотра")
        bo.setFont(QFont("Arial", 10))
        bo.setStyleSheet(
            "QPushButton{background-color:#e67e22;color:white;padding:10px;}"
            "QPushButton:hover{background-color:#d35400;}"
        )
        bo.clicked.connect(self._open_pages)
        il.addWidget(bo)
        root.addWidget(ib)

        # Подсказка о выборе формата
        hint = QLabel(
            "💡 <b>Выберите формат справа</b> в справочнике "
            "(нажмите на нужную ячейку)"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setFont(QFont("Arial", 10))
        hint.setStyleSheet(
            "color:#0066cc;background:#eaf3ff;border:1px solid #b3d4f5;"
            "border-radius:4px;padding:10px;"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Вариант — рулонная печать
        rb = QGroupBox("Рулонная печать")
        rb.setStyleSheet(
            "QGroupBox{color:#333;background-color:white;}"
            "QGroupBox::title{color:#333;}"
        )
        rl = QVBoxLayout(rb)
        rl.setContentsMargins(10, 6, 10, 10)
        rl.setSpacing(6)

        rr = QHBoxLayout()
        lbl_len = QLabel("Длина на страницу (мм):")
        lbl_len.setStyleSheet("color:#333;background:transparent;")
        rr.addWidget(lbl_len)
        self.edit_roll = QLineEdit()
        self.edit_roll.setPlaceholderText("Например: 594")
        self.edit_roll.setFont(QFont("Arial", 10))
        self.edit_roll.setStyleSheet(
            "QLineEdit{color:#333;background:white;border:1px solid #ccc;"
            "padding:4px 6px;}"
        )
        rr.addWidget(self.edit_roll)
        br = QPushButton("Применить длину")
        br.setFixedWidth(160)
        br.clicked.connect(self._apply_roll)
        rr.addWidget(br)
        rl.addLayout(rr)

        roll_row = QHBoxLayout()
        ba = QPushButton(
            f"По бо́льшей стороне  ({max(self.w, self.h):.0f} мм × "
            f"{len(self.pages)} стр.)"
        )
        ba.setFont(QFont("Arial", 10))
        ba.clicked.connect(self._apply_auto)
        roll_row.addWidget(ba)
        self.chk_cutting = QCheckBox("Резка")
        self.chk_cutting.setChecked(True)
        self.chk_cutting.setStyleSheet("color:#333;background:transparent;")
        roll_row.addWidget(self.chk_cutting)
        roll_row.addStretch()
        rl.addLayout(roll_row)
        root.addWidget(rb)

        # Пропустить
        bs = QPushButton("Пропустить (не учитывать эти страницы)")
        bs.setStyleSheet(
            "QPushButton{background-color:#888;color:white;}"
            "QPushButton:hover{background-color:#666;}"
        )
        bs.clicked.connect(self._skip)
        root.addWidget(bs)

        outer.addWidget(mw, stretch=1)
        self.hint_panel = FormatHintPanel(
            self, on_format_click=self._apply_format_by_name
        )
        outer.addWidget(self.hint_panel, stretch=0)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parent()
        if parent:
            pg = parent.frameGeometry()
            self.adjustSize()
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

    def _apply_format_by_name(self, name):
        # Если кликнули по ячейке A0xN — находим исходный A0xN-формат
        a0_key = None
        for key, printable_wh in A0_PRINTABLE_MM.items():
            if PRINTABLE_A0_SIZE_NAMES[printable_wh] == name:
                a0_key = key
                break
        if a0_key:
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
        import threading; self._wait_event = threading.Event()

    def request_stop(self):
        self._stop_requested = True; self._user_action = "skip"; self._user_value = None; self._wait_event.set()

    def set_user_response(self, action, value):
        self._user_action = action; self._user_value = value; self._wait_event.set()

    def _wait_for_user(self):
        self._wait_event.clear(); self._wait_event.wait()

    def detect_page_color(self, page, tol=15, white_thr=248,
                          min_colored_pixels=30, min_colored_ratio=0.00005,
                          pastel_ratio_threshold=0.02):
        """Определяет цветная ли страница (учитывает пастельные фоны)."""
        try:
            scale = 200/72
            pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale), colorspace=fitz.csRGB, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            a = np.asarray(img, dtype=np.uint8)
            if a.ndim != 3: return False
            r=a[...,0].astype(np.int16); g=a[...,1].astype(np.int16); b=a[...,2].astype(np.int16)
            mx=np.maximum(np.maximum(r,g),b); mn=np.minimum(np.minimum(r,g),b)
            diff = mx - mn

            # Проверка 1: тёмные цветные пиксели (текст, графика)
            ink = mx < white_thr; ic=int(ink.sum())
            if ic > 0:
                colored_dark = ink & (diff > tol)
                cc = int(colored_dark.sum())
                if cc >= min_colored_pixels or (cc/ic) >= min_colored_ratio:
                    return True

            # Проверка 2: светлые цветные пиксели (пастельные фоны)
            not_pure_white = mx < 254
            pastel = not_pure_white & (diff >= 5)
            total_pixels = a.shape[0] * a.shape[1]
            pastel_count = int(pastel.sum())
            if total_pixels > 0:
                if (pastel_count / total_pixels) >= pastel_ratio_threshold:
                    return True

            return False
        except Exception: return False

    def detect_page_fill(self, page, min_fill_ratio=0.50, tol=12):
        """Цветная заливка более 50% площади страницы."""
        try:
            scale = 200 / 72
            pix = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False
            )
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            a = np.asarray(img, dtype=np.uint8)
            if a.ndim != 3:
                return False
            r = a[..., 0].astype(np.int16)
            g = a[..., 1].astype(np.int16)
            b = a[..., 2].astype(np.int16)
            mx = np.maximum(np.maximum(r, g), b)
            mn = np.minimum(np.minimum(r, g), b)
            diff = mx - mn
            not_white = mx < 252
            colored = not_white & (diff >= tol)
            total = a.shape[0] * a.shape[1]
            if total <= 0:
                return False
            return (int(colored.sum()) / total) >= min_fill_ratio
        except Exception:
            return False

    def match_format_with_tolerance(self, w, h, table, tol=FORMAT_TOLERANCE_MM):
        for name,(fw,fh) in table.items():
            if ((abs(w-fw)<=tol and abs(h-fh)<=tol) or (abs(h-fw)<=tol and abs(w-fh)<=tol)):
                return name
        return None

    def run(self):
        try:
            grand=defaultdict(float); total_source=0; file_page_counts=[]; file_details=[]; total_files=len(self.pdfs)
            for file_idx, pdf_path in enumerate(self.pdfs):
                if self._stop_requested: break
                try:
                    with fitz.open(pdf_path) as doc:
                        total=len(doc); total_source+=total; file_page_counts.append(total)
                        name=os.path.basename(pdf_path); self.status.emit(f"Анализ: {name} ({total} стр.)")
                        ff=defaultdict(int); fp=defaultdict(list); frb=frc=0.0; frb_p,frc_p=[],[]
                        cg=defaultdict(list); file_roll_groups=[]; file_fill_pages=[]
                        for i,p in enumerate(doc):
                            if self._stop_requested: break
                            pn=i+1
                            w, h = page_size_mm(p)
                            col = False if self.force_bw else self.detect_page_color(p)
                            has_fill = (
                                self.count_fill and not self.force_bw and col
                                and self.detect_page_fill(p)
                            )
                            if has_fill:
                                file_fill_pages.append(pn)
                            fA=self.match_format_with_tolerance(w,h,ISO_A)
                            fN=self.match_format_with_tolerance(w,h,ISO_A_NONSTANDARD)
                            if fA:
                                key=f"{fA} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            elif fN:
                                key=f"{fN} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            else: cg[(w,h,col)].append(pn)
                            prog=int(100*(file_idx+(i+1)/total)/total_files); self.progress.emit(prog); time.sleep(0.001)
                        if self._stop_requested:
                            file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups,"fill_pages":sorted(file_fill_pages)}); break
                        for (w,h,col),pages in cg.items():
                            if self._stop_requested: break
                            self.need_user_input.emit(w,h,col,pages,pdf_path); self._wait_for_user()
                            if self._stop_requested: break
                            action=self._user_action; value=self._user_value; kind="цвет" if col else "ч/б"
                            if action=="skip": pass
                            elif action=="format":
                                key=f"{value} {kind}"; grand[key]+=len(pages); ff[key]+=len(pages); fp[key].extend(pages)
                            elif action == "a0_oversize":
                                # Печатаем A0xN на рулоне 910 мм (по большей стороне печатаемого)
                                a0_key = value
                                pw, ph = A0_PRINTABLE_MM[a0_key]
                                ow, oh = A0_OVERSIZE_MM[a0_key]
                                key = f"{a0_key} {kind}"
                                grand[key] += len(pages)
                                ff[key] += len(pages)
                                fp[key].extend(pages)
                                # Добавляем в рулон по большей стороне печатаемого формата
                                mm = max(pw, ph) * len(pages)
                                if col:
                                    grand["Рулон цвет мм"] += mm
                                    frc += mm
                                    frc_p.extend(pages)
                                else:
                                    grand["Рулон ч/б мм"] += mm
                                    frb += mm
                                    frb_p.extend(pages)
                                # Сохраняем как отдельную A0-группу для CRM и клиента
                                file_roll_groups.append({
                                    "w": ow, "h": oh, "color": col,
                                    "count": len(pages),
                                    "per_page_mm": max(pw, ph),
                                    "total_mm": mm,
                                    "pages": sorted(pages),
                                    "cutting": False,
                                    "a0_key": a0_key,
                                    "printable_w": pw,
                                    "printable_h": ph,
                                })
                            elif action in ("roll_mm", "roll_auto"):
                                if isinstance(value, tuple):
                                    ppm, need_cut = float(value[0]), bool(value[1])
                                else:
                                    ppm, need_cut = float(value), False
                                mm = ppm * len(pages)
                                if col:
                                    grand["Рулон цвет мм"] += mm; frc += mm; frc_p.extend(pages)
                                else:
                                    grand["Рулон ч/б мм"] += mm; frb += mm; frb_p.extend(pages)
                                file_roll_groups.append({
                                    "w": w, "h": h, "color": col, "count": len(pages),
                                    "per_page_mm": ppm, "total_mm": mm, "pages": sorted(pages),
                                    "cutting": need_cut,
                                })
                                sk = f"{w:.0f}×{h:.0f}"
                                rfk = f"_roll_fold_{sk}_{kind}"
                                grand[rfk] = grand.get(rfk, 0) + len(pages)
                        file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups,"fill_pages":sorted(file_fill_pages)})
                except Exception as e: self.error.emit(f"Ошибка при обработке {pdf_path}: {e}"); continue
            if self._stop_requested:
                self.finished.emit(dict(grand),total_source,file_page_counts,file_details); self.stopped.emit()
            else:
                self.progress.emit(100); self.finished.emit(dict(grand),total_source,file_page_counts,file_details)
        except Exception as e: self.error.emit(f"Критическая ошибка: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────
class DropArea(QFrame):
    """Область только для перетаскивания файлов/папок."""

    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)

        self._default_style = (
            "DropArea { background-color: #fafbfc; border: 2px dashed #b3d4f5; "
            "border-radius: 8px; }"
        )
        self._hover_style = (
            "DropArea { background-color: #d6eaff; border: 2px dashed #0066cc; "
            "border-radius: 8px; }"
        )
        self._selected_style = (
            "DropArea { background-color: #ecf7ec; border: 2px dashed #2e7d32; "
            "border-radius: 8px; }"
        )
        self.setStyleSheet(self._default_style)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel("📥")
        self.icon_label.setFont(QFont("Arial", 22))
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background:transparent;border:none;")
        layout.addWidget(self.icon_label)

        self.title_label = QLabel("Переместите сюда папку или файл")
        self.title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(
            "color:#0066cc;background:transparent;border:none;"
        )
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

    def set_selected_path(self, path, info_suffix=""):
        self.setStyleSheet(self._selected_style)
        self.icon_label.setText("")
        self.icon_label.setVisible(False)
        display = path if not info_suffix else f"{path}  {info_suffix}"
        self.title_label.setText(display)
        self.title_label.setFont(QFont("Arial", 9))
        self.title_label.setWordWrap(False)
        self.title_label.setStyleSheet(
            "color:#2e7d32;background:transparent;border:none;"
        )
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

    def reset(self):
        self.setStyleSheet(self._default_style)
        self.icon_label.setText("📥")
        self.icon_label.setVisible(True)
        self.title_label.setText("Переместите сюда папку или файл")
        self.title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            "color:#0066cc;background:transparent;border:none;"
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


class PrintingCalculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Калькулятор расчёта проектной документации")
        self.setGeometry(100,100,1200,700)
        self.setAcceptDrops(True)
        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.primary_color="#0066cc"; self.danger_color="#d33"; self.bg_color="#f5f6f7"
        self.card_color="#ffffff"; self.text_color="#333333"
        self.apply_style()
        self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
        self.selected_path=""; self.copies=1; self.force_bw=False; self.count_fill=True
        self._dropped_pdfs = None
        self.need_folding_a4=self.need_folding_a3=False
        self.need_binding_a4=self.need_binding_a3=False
        self.thread=self.current_dialog=None; self._history_items=[]
        self.init_ui()
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
        self.setStyleSheet(f"""
            QMainWindow,QWidget{{background-color:{self.bg_color};color:{self.text_color};}}
            QTabWidget::pane{{border:1px solid #ddd;background-color:{self.bg_color};color:{self.text_color};}}
            QTabBar::tab{{background-color:#e8e8e8;padding:8px 20px;margin-right:2px;border:1px solid #ddd;color:{self.text_color};font-weight:bold;}}
            QTabBar::tab:selected{{background-color:{self.primary_color};color:white;}}
            QFrame{{background-color:{self.card_color};border-radius:4px;border:1px solid #e0e0e0;color:{self.text_color};}}
            QGroupBox{{background-color:{self.card_color};border:1px solid #d0d0d0;border-radius:6px;margin-top:8px;padding-top:4px;font-weight:bold;color:{self.text_color};}}
            QGroupBox::title{{subcontrol-origin:margin;subcontrol-position:top left;padding:0 6px;color:{self.text_color};}}
            QPushButton{{background-color:{self.primary_color};color:white;border:none;padding:8px 16px;border-radius:4px;font-weight:bold;font-size:11px;}}
            QPushButton:hover{{background-color:#0052a3;}}
            QPushButton:pressed{{background-color:#003d7a;}}
            QPushButton:disabled{{background-color:#bbb;color:#eee;}}
            QLabel{{color:{self.text_color};background:transparent;}}
            QLineEdit{{background-color:white;border:1px solid #ccc;border-radius:4px;padding:4px 6px;color:{self.text_color};}}
            QTextEdit{{background-color:{self.card_color};border:1px solid #e0e0e0;border-radius:4px;color:{self.text_color};selection-background-color:#cce4ff;selection-color:#000;}}
            QSpinBox{{
                background-color:white;color:{self.text_color};
                border:1px solid #888;border-radius:4px;padding:2px 24px 2px 6px;min-height:28px;
            }}
            QSpinBox::up-button{{
                subcontrol-origin:border;subcontrol-position:top right;
                width:22px;border-left:1px solid #888;background-color:#e0e0e0;
            }}
            QSpinBox::down-button{{
                subcontrol-origin:border;subcontrol-position:bottom right;
                width:22px;border-left:1px solid #888;background-color:#e0e0e0;
            }}
            QSpinBox::up-button:hover,QSpinBox::down-button:hover{{background-color:#c8c8c8;}}
            QCheckBox{{color:{self.text_color};background:transparent;spacing:8px;font-size:11px;}}
            QCheckBox::indicator{{width:18px;height:18px;border:2px solid #666;border-radius:3px;background:white;}}
            QCheckBox::indicator:hover{{border-color:{self.primary_color};}}
            QCheckBox::indicator:checked{{background-color:{self.primary_color};border-color:{self.primary_color};}}
            QCheckBox::indicator:disabled{{background-color:#eee;border-color:#ccc;}}
            QRadioButton{{background-color:transparent;color:{self.text_color};padding:4px 8px;font-weight:normal;spacing:8px;}}
            QRadioButton::indicator{{width:16px;height:16px;}}
            QRadioButton::indicator:unchecked{{background-color:white;border:2px solid #ccc;border-radius:9px;}}
            QRadioButton::indicator:checked{{background-color:{self.primary_color};border:2px solid {self.primary_color};border-radius:9px;}}
            QRadioButton:disabled{{color:#aaa;}}
            QRadioButton::indicator:disabled{{background-color:#eee;border:2px solid #ddd;}}
            QTableWidget{{background-color:white;color:{self.text_color};gridline-color:#ddd;selection-background-color:#cce4ff;selection-color:#000;}}
            QHeaderView::section{{background-color:#e8e8e8;padding:6px;border:1px solid #ddd;font-weight:bold;color:{self.text_color};}}
            QProgressBar{{border:1px solid #ddd;border-radius:4px;text-align:center;height:25px;color:{self.text_color};background-color:white;}}
            QProgressBar::chunk{{background-color:{self.primary_color};}}
            QScrollArea{{background-color:{self.bg_color};color:{self.text_color};border:none;}}
            QToolTip{{background-color:#ffffcc;color:#333;border:1px solid #999;padding:4px;}}
            QMessageBox{{background-color:{self.bg_color};color:{self.text_color};}}
        """)

    def init_ui(self):
        c=QWidget(); self.setCentralWidget(c); ml=QVBoxLayout(c); ml.setContentsMargins(10,10,10,10); ml.setSpacing(10)
        self.tabs=QTabWidget()
        self.tabs.addTab(self.create_input_tab(),"📁 Параметры")
        self.tabs.addTab(self.create_details_tab(),"📊 Детализация файлов")
        self.tabs.addTab(self.create_manager_tab(),"👔 Для менеджера (CRM)")
        self.tabs.addTab(self.create_report_tab(),"📄 Для клиента")
        self.tabs.addTab(self.create_history_tab(),"📚 История расчетов")
        ml.addWidget(self.tabs)

    def _bold_label(self, text, size=11):
        lb=QLabel(text); lb.setFont(QFont("Arial",size,QFont.Weight.Bold)); lb.setStyleSheet(f"color:{self.text_color};background:transparent;"); return lb

    def show_whats_new(self):
        WhatsNewDialog(get_app_version(), parent=self).exec()

    def create_input_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(15); lay.setContentsMargins(20,20,20,20)
        ff = QFrame()
        ff.setStyleSheet("QFrame { background: transparent; border: none; }")
        fl = QVBoxLayout(ff)
        fl.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.setSpacing(10)

        # Слева — область для DnD
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._handle_dropped_paths)
        row.addWidget(self.drop_area, stretch=1)

        # Справа — кнопки
        btns_frame = QFrame()
        btns_frame.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
        )
        btns_layout = QVBoxLayout(btns_frame)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(8)

        btn_folder = QPushButton("📂  Папка")
        btn_folder.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        btn_folder.setMinimumHeight(48)
        btn_folder.setMinimumWidth(180)
        btn_folder.clicked.connect(self.browse_path)
        btns_layout.addWidget(btn_folder)

        btn_file = QPushButton("📄  Файл")
        btn_file.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        btn_file.setMinimumHeight(48)
        btn_file.setMinimumWidth(180)
        btn_file.clicked.connect(self.browse_file)
        btns_layout.addWidget(btn_file)

        row.addWidget(btns_frame, stretch=0)
        fl.addLayout(row)

        # Сохраняем label_path как ссылку на title — чтобы не ломать остальной код
        self.label_path = self.drop_area.title_label
        lay.addWidget(ff)
        cf=QFrame(); cl=QVBoxLayout(cf); cl.addWidget(self._bold_label("🎨 Цветность:"))
        cr=QHBoxLayout(); self.rb_color_auto=QRadioButton("По файлу"); self.rb_color_bw=QRadioButton("Ч/б"); self.rb_color_auto.setChecked(True)
        self.color_mode_group=QButtonGroup(self); self.color_mode_group.addButton(self.rb_color_auto); self.color_mode_group.addButton(self.rb_color_bw)
        cr.addWidget(self.rb_color_auto); cr.addWidget(self.rb_color_bw); cr.addStretch(); cl.addLayout(cr)
        self.cb_count_fill = QCheckBox("Учитывать заливку цветом")
        self.cb_count_fill.setChecked(False)
        self.cb_count_fill.setStyleSheet("color:#333;background:transparent;")
        cl.addWidget(self.cb_count_fill)
        h=QLabel(
            "«По файлу» — анализ цвета каждой страницы.  «Ч/б» — всё считается чёрно-белым.  "
            "Заливка — если цвет занимает более 50% площади листа."
        )
        h.setStyleSheet("color:#666;font-size:10px;background:transparent;"); h.setWordWrap(True); cl.addWidget(h)
        self.rb_color_auto.toggled.connect(self._update_fill_checkbox)
        self.rb_color_bw.toggled.connect(self._update_fill_checkbox)
        self._update_fill_checkbox()
        lay.addWidget(cf)
        pf=QFrame(); pl=QVBoxLayout(pf); pl.addWidget(self._bold_label("⚙️ Параметры:"))
        r2=QHBoxLayout(); lbl_copies=QLabel("Количество экземпляров:"); lbl_copies.setStyleSheet(f"color:{self.text_color};background:transparent;"); r2.addWidget(lbl_copies)
        self.spinbox_copies=NoScrollSpinBox(); self.spinbox_copies.setMinimum(1); self.spinbox_copies.setMaximum(100); self.spinbox_copies.setValue(1); self.spinbox_copies.setFixedWidth(90)
        self.spinbox_copies.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        self.spinbox_copies.valueChanged.connect(self.on_params_changed); r2.addWidget(self.spinbox_copies); r2.addStretch(); pl.addLayout(r2)
        pl.addWidget(self._bold_label("📌 Брошюровка на пластиковую пружину:",10))
        br=QHBoxLayout(); self.rb_binding_none=QRadioButton("Не нужна"); self.rb_binding_a4=QRadioButton("A4"); self.rb_binding_a3=QRadioButton("A3"); self.rb_binding_none.setChecked(True)
        self.binding_group=QButtonGroup(self)
        for rb in (self.rb_binding_none,self.rb_binding_a4,self.rb_binding_a3): self.binding_group.addButton(rb); br.addWidget(rb)
        br.addStretch(); pl.addLayout(br)
        pl.addWidget(self._bold_label("📋 Фальцовка:",10))
        fr=QHBoxLayout(); self.rb_folding_none=QRadioButton("Не нужна"); self.rb_folding_a4=QRadioButton("Под A4"); self.rb_folding_a3=QRadioButton("Под A3"); self.rb_folding_none.setChecked(True)
        self.folding_group=QButtonGroup(self)
        for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): self.folding_group.addButton(rb); fr.addWidget(rb)
        fr.addStretch(); pl.addLayout(fr)
        self.binding_group.buttonClicked.connect(self.on_binding_changed); self.folding_group.buttonClicked.connect(self.on_params_changed); lay.addWidget(pf)
        pgf=QFrame(); pgl=QVBoxLayout(pgf); pgl.addWidget(self._bold_label("Статус анализа:",10))
        self.label_status=QLabel("Готово"); self.label_status.setStyleSheet(f"color:{self.text_color};background:transparent;"); pgl.addWidget(self.label_status)
        self.progress_bar=QProgressBar(); self.progress_bar.setValue(0); pgl.addWidget(self.progress_bar); lay.addWidget(pgf)
        brow=QHBoxLayout()
        self.btn_analyze=QPushButton("▶️ НАЧАТЬ АНАЛИЗ"); self.btn_analyze.setFont(QFont("Arial",12,QFont.Weight.Bold)); self.btn_analyze.setMinimumHeight(50); self.btn_analyze.clicked.connect(self.start_analysis); brow.addWidget(self.btn_analyze,stretch=3)
        self.btn_stop=QPushButton("⏹ СТОП"); self.btn_stop.setFont(QFont("Arial",12,QFont.Weight.Bold)); self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet(f"QPushButton{{background-color:{self.danger_color};color:white;border:none;padding:8px 16px;border-radius:4px;font-weight:bold;}}QPushButton:hover{{background-color:#a00;}}QPushButton:disabled{{background-color:#ddd;color:#999;}}")
        self.btn_stop.clicked.connect(self.stop_analysis); self.btn_stop.setEnabled(False); brow.addWidget(self.btn_stop,stretch=1); lay.addLayout(brow); lay.addStretch()
        links_layout=QHBoxLayout(); links_layout.setContentsMargins(0,5,0,0); links_layout.setSpacing(10)
        lbl_thx=QLabel('⭐ <a href="https://kopirkaru.bitrix24.ru/company/personal/user/423876/" style="color:#0066cc;text-decoration:none;">Оставить благодарность в Bitrix</a>')
        lbl_thx.setFont(QFont("Arial",9)); lbl_thx.setStyleSheet("background:transparent;border:none;color:#333;"); lbl_thx.setOpenExternalLinks(True); links_layout.addWidget(lbl_thx); links_layout.addStretch()
        btn_whats_new=QPushButton(f"🎉 Что нового (v{get_app_version()})"); btn_whats_new.setFont(QFont("Arial",9)); btn_whats_new.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_whats_new.setStyleSheet("QPushButton{background-color:transparent;color:#0066cc;border:1px solid #0066cc;border-radius:4px;padding:4px 10px;font-weight:normal;}QPushButton:hover{background-color:#0066cc;color:white;}")
        btn_whats_new.clicked.connect(self.show_whats_new); links_layout.addWidget(btn_whats_new); links_layout.addStretch()
        lbl_bug=QLabel('🐛 Сообщить об ошибке: ilya.fabiyanskiy@yandex.ru'); lbl_bug.setFont(QFont("Arial",9))
        lbl_bug.setStyleSheet("background:transparent;border:none;color:#666;"); lbl_bug.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); links_layout.addWidget(lbl_bug)
        lay.addLayout(links_layout); return w

    def on_binding_changed(self):
        if self.rb_binding_a4.isChecked():
            self.rb_folding_a4.setChecked(True)
            for rb in (self.rb_folding_none,self.rb_folding_a3,self.rb_folding_a4): rb.setEnabled(False)
        elif self.rb_binding_a3.isChecked():
            self.rb_folding_a3.setChecked(True)
            for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): rb.setEnabled(False)
        else:
            for rb in (self.rb_folding_none,self.rb_folding_a4,self.rb_folding_a3): rb.setEnabled(True)
        self.on_params_changed()

    def create_details_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        lay.addWidget(self._bold_label("📊 Детализация по файлам (1 экз., с номерами страниц):"))
        self.text_details=QTextEdit(); self.text_details.setReadOnly(True); self.text_details.setFont(QFont("Consolas",9))
        self.text_details.setStyleSheet(f"QTextEdit{{background-color:white;color:{self.text_color};border:1px solid #e0e0e0;border-radius:4px;}}"); lay.addWidget(self.text_details)
        btn_save=QPushButton("💾 Сохранить в TXT (Для производства)"); btn_save.setMinimumHeight(40); btn_save.clicked.connect(self.save_details_txt); lay.addWidget(btn_save); return w

    def create_manager_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(15)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); sc=QWidget(); sl=QVBoxLayout(sc); sl.setSpacing(15)
        def make_block(title,attr,minh=80):
            frame=QFrame(); fl_=QVBoxLayout(frame); fl_.setContentsMargins(10,10,10,10); fl_.addWidget(self._bold_label(title))
            te=QTextEdit(); te.setReadOnly(True); te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setSizePolicy(te.sizePolicy().horizontalPolicy(),QSizePolicy.Policy.Fixed); te.setMinimumHeight(minh)
            te.setStyleSheet(f"QTextEdit{{background-color:white;color:{self.text_color};border:1px solid #e0e0e0;border-radius:4px;}}"); fl_.addWidget(te); setattr(self,attr,te); return frame
        sl.addWidget(make_block("🖨️ Печать (с конвертацией, с учётом экземпляров):","text_printing",120))
        sl.addWidget(make_block("🌀 Рулонная печать:","text_roll",80))
        sl.addWidget(make_block("✂️ Резка:","text_cutting",80))
        sl.addWidget(make_block("📋 Фальцовка:","text_folding",120))
        sl.addWidget(make_block("📌 Брошюровка:","text_binding",80))
        tf=QFrame(); tl=QVBoxLayout(tf)
        self.label_total=QLabel("⚖️ Вес: —"); self.label_total.setFont(QFont("Arial",14,QFont.Weight.Bold))
        self.label_total.setStyleSheet(f"color:{self.primary_color};background:transparent;"); tl.addWidget(self.label_total); sl.addWidget(tf); sl.addStretch()
        scroll.setWidget(sc); lay.addWidget(scroll); return w

    def create_report_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        lay.addWidget(self._bold_label("📄 Полный отчет:"))
        self.text_report=QTextEdit(); self.text_report.setReadOnly(True); self.text_report.setFont(QFont("Courier",9))
        self.text_report.setStyleSheet(f"QTextEdit{{background-color:white;color:{self.text_color};border:1px solid #e0e0e0;border-radius:4px;}}"); lay.addWidget(self.text_report)
        self.btn_copy_report=QPushButton("📋 Копировать в буфер обмена")
        self.btn_copy_report.setMinimumHeight(40)
        self.btn_copy_report.clicked.connect(self.copy_report)
        self._copy_btn_style=(
            "QPushButton{background-color:#0066cc;color:white;border:none;"
            "padding:8px 16px;border-radius:4px;font-weight:bold;}"
            "QPushButton:hover{background-color:#0052a3;}"
        )
        self.btn_copy_report.setStyleSheet(self._copy_btn_style)
        lay.addWidget(self.btn_copy_report); return w

    def create_history_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(10)
        header=QHBoxLayout(); header.addWidget(self._bold_label("📚 История расчётов:")); header.addStretch()
        btn_refresh=QPushButton("🔄 Обновить"); btn_refresh.clicked.connect(self.refresh_history); header.addWidget(btn_refresh); lay.addLayout(header)
        hint=QLabel("💡 Расчёты сохраняются автоматически. Двойной клик по строке — загрузить расчёт. Клик по заголовку столбца — сортировка.")
        hint.setStyleSheet("color:#666;font-size:10px;padding:4px;background:transparent;"); hint.setWordWrap(True); lay.addWidget(hint)
        self.history_table=QTableWidget(); self.history_table.setColumnCount(4); self.history_table.setHorizontalHeaderLabels(["Дата и время","Название","Файлов","Страниц"])
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.history_table.cellDoubleClicked.connect(self.load_history_item)
        self.history_table.setAlternatingRowColors(True); self.history_table.setStyleSheet(f"QTableWidget{{alternate-background-color:#f8f9fa;color:{self.text_color};background-color:white;}}")
        self.history_table.verticalHeader().setVisible(False); self.history_table.setSortingEnabled(True); lay.addWidget(self.history_table)
        btns=QHBoxLayout()
        btn_load=QPushButton("📂 Загрузить выбранный"); btn_load.setMinimumHeight(40); btn_load.clicked.connect(self.load_selected_history); btns.addWidget(btn_load)
        btn_delete=QPushButton("🗑 Удалить выбранный"); btn_delete.setMinimumHeight(40)
        btn_delete.setStyleSheet("QPushButton{background-color:#d33;color:white;border:none;padding:8px 16px;border-radius:4px;font-weight:bold;}QPushButton:hover{background-color:#a00;}")
        btn_delete.clicked.connect(self.delete_selected_history); btns.addWidget(btn_delete); btns.addStretch()
        btn_folder=QPushButton("📁 Открыть папку истории"); btn_folder.setMinimumHeight(40)
        btn_folder.setStyleSheet("QPushButton{background-color:#888;color:white;border:none;padding:8px 16px;border-radius:4px;font-weight:bold;}QPushButton:hover{background-color:#666;}")
        btn_folder.clicked.connect(self.open_history_folder); btns.addWidget(btn_folder); lay.addLayout(btns); return w

    def browse_path(self):
        p = QFileDialog.getExistingDirectory(self, "Выберите папку с PDF файлами")
        if p:
            self.selected_path = p
            self._dropped_pdfs = None
            self.drop_area.set_selected_path(p)

    def browse_file(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Выберите PDF файл", "",
            "PDF (*.pdf);;Все файлы (*.*)",
        )
        if p:
            self.selected_path = p
            self._dropped_pdfs = None
            self.drop_area.set_selected_path(p)

    def _update_fill_checkbox(self):
        auto = self.rb_color_auto.isChecked()
        self.cb_count_fill.setEnabled(auto)
        if not auto:
            self.cb_count_fill.setChecked(False)

    def on_params_changed(self):
        self.copies=self.spinbox_copies.value(); self.need_folding_a4=self.rb_folding_a4.isChecked(); self.need_folding_a3=self.rb_folding_a3.isChecked()
        self.need_binding_a4=self.rb_binding_a4.isChecked(); self.need_binding_a3=self.rb_binding_a3.isChecked(); self.calculate_and_display()

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
        self.label_status.setText("⏳ Идет анализ..."); self.progress_bar.setValue(0); self.btn_analyze.setEnabled(False); self.btn_stop.setEnabled(True)
        self.thread=AnalysisThread(pdfs, force_bw=self.force_bw, count_fill=count_fill)
        self.thread.progress.connect(self.update_progress); self.thread.status.connect(self.update_status)
        self.thread.need_user_input.connect(self.show_unknown_format_dialog); self.thread.finished.connect(self.analysis_finished)
        self.thread.error.connect(self.analysis_error); self.thread.stopped.connect(self.analysis_stopped); self.thread.start()

    def stop_analysis(self):
        if not self.thread or not self.thread.isRunning(): return
        self.label_status.setText("⏹ Останавливаю анализ..."); self.btn_stop.setEnabled(False)
        if self.current_dialog:
            try: self.current_dialog.result_action="skip"; self.current_dialog.result_value=None; self.current_dialog.reject()
            except: pass
            self.current_dialog=None
        self.thread.request_stop()

    def show_unknown_format_dialog(self, w, h, color, pages, pdf_path):
        if self.thread and self.thread._stop_requested: self.thread.set_user_response("skip",None); return
        dlg=UnknownFormatDialog(w,h,color,pages,pdf_path,parent=self); self.current_dialog=dlg; dlg.exec(); self.current_dialog=None
        self.thread.set_user_response(dlg.result_action, dlg.result_value)

    def update_progress(self, v): self.progress_bar.setValue(v)
    def update_status(self, s): self.label_status.setText(f"⏳ {s}")

    def analysis_finished(self, grand, total_source, fpc, fd):
        self.grand=grand; self.total_source=total_source; self.file_page_counts=fpc; self.file_details=fd
        if not self.thread or not self.thread._stop_requested: self.label_status.setText("✅ Анализ завершен"); self.progress_bar.setValue(100)
        self.btn_analyze.setEnabled(True); self.btn_stop.setEnabled(False); self.display_details(); self.calculate_and_display()
        if self.grand and not (self.thread and self.thread._stop_requested): self._auto_save_to_history()

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
        self.label_status.setText("⏹ Анализ остановлен пользователем"); self.btn_analyze.setEnabled(True); self.btn_stop.setEnabled(False)

    def analysis_error(self, error):
        self.label_status.setText(f"❌ {error}"); self.btn_analyze.setEnabled(True); self.btn_stop.setEnabled(False)

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
            self.cb_count_fill.setChecked(params.get('count_fill', False))
            self._update_fill_checkbox()
            self.display_details(); self.calculate_and_display(); self.tabs.setCurrentIndex(1)
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
        d=te.document(); d.setTextWidth(te.viewport().width()); te.setFixedHeight(max(minh,min(int(d.size().height()+10),maxh)))

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
                    if not fmt or kind != "цвет":
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
        rbt = self.grand.get("Рулон ч/б мм", 0) * self.copies + erb
        rct = self.grand.get("Рулон цвет мм", 0) * self.copies + erc
        rl = []
        if rbt>0: rl.append(f"Ч/б — {rbt:.0f} мм ({rbt/1000:.2f} м)")
        if rct>0: rl.append(f"Цвет — {rct:.0f} мм ({rct/1000:.2f} м)")
        self.text_roll.setText("\n".join(rl) if rl else "Рулонная печать не требуется")
        cut_lines,cut_total=self._calc_cutting()
        if cut_lines:
            cp=["Форматы, требующие резки:",""]; cp.extend(cut_lines); cp.append(""); cp.append(f"Итого листов на резку: {cut_total}")
            self.text_cutting.setText("\n".join(cp))
        else: self.text_cutting.setText("Резка не требуется")
        ftp,tf,ft=[],0,None; slr,nlr=[],[]
        if self.need_folding_a4: ft="A4"
        elif self.need_folding_a3: ft="A3"
        if ft:
            slr,nlr,tf=self._calc_folding(ft); ftp.append(f"Фальцовка под {ft}"); ftp.append("")
            if slr: ftp.append("Стандартные форматы:"); ftp.extend(slr)
            if nlr:
                if slr: ftp.append("")
                ftp.append("Нестандартные/рулонные форматы:"); ftp.extend(nlr)
                nlt = sum(int(l.rsplit("—", 1)[-1].strip().split()[0]) for l in nlr)
                ftp.append(f"Итого нестандартных фальцовок: {nlt}")
        self.text_folding.setText("\n".join(ftp) if ftp else "Фальцовка не требуется")

        blines,tb,bt=[],0,None
        if self.need_binding_a4: bt="A4"; blines,tb=self._calc_binding()
        elif self.need_binding_a3: bt="A3"; blines,tb=self._calc_binding()
        if bt:
            bp=[f"Брошюровка на пружину {bt}",""]; bp.extend(blines if blines else ["Нет данных"]); self.text_binding.setText("\n".join(bp))
        else: self.text_binding.setText("Брошюровка не требуется")
        tw=self._calc_weight(st,rbt,rct,bt,tb)
        self.label_total.setText(f"⚖️ Вес: {self._fw(tw) if tw>0 else '0.00 кг'}")
        QTimer.singleShot(0, lambda: self._autosize(self.text_printing,120))
        QTimer.singleShot(0, lambda: self._autosize(self.text_roll,80))
        QTimer.singleShot(0, lambda: self._autosize(self.text_cutting,80))
        QTimer.singleShot(0, lambda: self._autosize(self.text_folding,120))
        QTimer.singleShot(0, lambda: self._autosize(self.text_binding,80))
        self._build_report(ft,slr,nlr,tf,bt,blines,tb,tw)

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
            "ПЕЧАТЬ (исходные форматы × экземпляры):"]
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
        self.btn_copy_report.setText("Скопировано")
        self.btn_copy_report.setStyleSheet(
            "QPushButton{background-color:#28a745;color:white;border:none;"
            "padding:8px 16px;border-radius:4px;font-weight:bold;}"
        )
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


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    force_light_palette(app)

    icon_path = resource_path("logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Проверка лицензии через Gist (ACTIVE / BLOCKED)
    ok, msg = check_remote_license()
    if not ok:
        QMessageBox.critical(None, "Доступ запрещён", msg)
        sys.exit(1)

    _create_single_instance_mutex()

    # Обновление без запроса (только в exe)
    if getattr(sys, "frozen", False):
        _clear_update_settings_if_current()
        has_update, latest_ver, dl_url, _upd_err = check_for_update()
        if has_update:
            _mark_update_attempt(latest_ver)
            UpdateDialog(latest_ver, dl_url).exec()

    # Главное окно
    window = PrintingCalculator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()