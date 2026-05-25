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
    QRadioButton, QButtonGroup, QSizePolicy, QHeaderView
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

APP_VERSION = "1.0.3"
UPDATE_REPO = "fabilya/PDKopirka"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
GITHUB_TOKEN = "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"


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
        if _parse_version(latest_tag) <= _parse_version(APP_VERSION):
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
        # /SILENT              - без диалогов, но с прогресс-баром
        # /SUPPRESSMSGBOXES    - без предупреждений
        # /NORESTART           - не перезагружать ПК
        # /CLOSEAPPLICATIONS   - закрыть запущенную программу
        # /RESTARTAPPLICATIONS - запустить после установки
        subprocess.Popen(
            [
                installer_path,
                "/SILENT",
                "/SUPPRESSMSGBOXES",
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

CHANGELOG_HTML = """
<h2 style="color:#0066cc; margin-bottom:10px;">🚀 Версия 1.0.5</h2>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    🔄 Полностью переработанное обновление
</h3>
<ul>
    <li>📦 <b>Папочная сборка</b> — программа теперь устанавливается в папку</li>
    <li>✅ <b>Обновление работает на 100%</b> — заменяется только содержимое, EXE не блокируется</li>
    <li>⚡ <b>Мгновенный запуск</b> — больше нет распаковки при старте</li>
    <li>🛡️ <b>Меньше ложных срабатываний антивируса</b></li>
</ul>

<h3 style="color:#0066cc; border-bottom:1px solid #ddd; padding-bottom:4px; margin-top:16px;">
    🎨 Улучшено определение цветности
</h3>
<ul>
    <li>🎨 Теперь распознаются страницы со <b>светло-цветными фонами</b></li>
    <li>🌈 Лучше определяются пастельные оттенки и градиенты</li>
</ul>

<h2 style="color:#0066cc; margin-bottom:10px;">🚀 Версия 1.0.4</h2>
<ul>
    <li>🖥️ Принудительная светлая тема для Windows 11</li>
    <li>🎯 Стиль Fusion для стабильного отображения</li>
</ul>

<h2 style="color:#0066cc; margin-bottom:10px;">🚀 Версия 1.0.3</h2>
<ul>
    <li>💾 Кнопка «Сохранить в TXT» в детализации</li>
    <li>✂️ Компактные номера страниц</li>
</ul>

<h2 style="color:#0066cc; margin-bottom:10px;">🚀 Версия 1.0.2</h2>
<ul>
    <li>💾 <b>История расчётов</b></li>
    <li>📚 Вкладка «История»</li>
</ul>

<h2 style="color:#0066cc; margin-bottom:10px;">🚀 Версия 1.0.1</h2>
<ul>
    <li>📐 Справочник форматов</li>
    <li>✂️ Блок «Резка»</li>
    <li>🌀 Учёт рулонных страниц при фальцовке</li>
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
        self.te.setHtml(CHANGELOG_HTML)
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
FORMAT_TOLERANCE_MM = 5

ISO_A = {
    "A4": (210, 297), "A3": (297, 420), "A2": (420, 594),
    "A1": (594, 841), "A0": (841, 1189),
}
ISO_A_NONSTANDARD = {
    "A4x3": (297, 630), "A4x4": (297, 841), "A4x5": (297, 1051),
    "A4x6": (297, 1261), "A4x7": (297, 1471), "A4x8": (297, 1682),
    "A4x9": (297, 1892),
    "A3x3": (420, 891), "A3x4": (420, 1189), "A3x5": (420, 1486),
    "A3x6": (420, 1783), "A3x7": (420, 2080),
    "A2x3": (594, 1261), "A2x4": (594, 1682), "A2x5": (594, 2102),
    "A1x3": (841, 1783), "A1x4": (841, 2378),
}
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


# ─────────────────────────────────────────────────────────────────────────────
# Лицензия
# ─────────────────────────────────────────────────────────────────────────────

def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()

_VL = _h("admin")
_VP = _h("1qwer432")

LICENSE_CHECK_URL = (
    "https://gist.githubusercontent.com/fabilya/"
    "d460ac938145cd8d99f261c250f90255/raw/gistfile1.txt"
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


def check_remote_license():
    if not LICENSE_CHECK_URL:
        return True, ""
    try:
        cb = f"{int(time.time())}_{random.randint(0, 999999)}"
        sep = "&" if "?" in LICENSE_CHECK_URL else "?"
        url = f"{LICENSE_CHECK_URL}{sep}_={cb}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "PrintCalc/1.0")
        req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
        req.add_header("Pragma", "no-cache")
        with _urlopen_safe(req, timeout=15) as resp:
            token = resp.read().decode("utf-8").strip()
        valid, status = _verify_token(token)
        if not valid:
            return False, (
                f"Ошибка проверки лицензии.\n\nКод: {status}\n\n"
                "Обратитесь к администратору."
            )
        if status == "ACTIVE":
            return True, ""
        return False, (
            "Доступ к программе заблокирован администратором.\n\n"
            "Обратитесь к администратору."
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


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Авторизация")
        self.setFixedSize(400, 280)
        self.setModal(True)
        self.authenticated = False
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(15)
        lay.setContentsMargins(30, 30, 30, 30)
        t = QLabel("🔐 Вход в систему")
        t.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("color: #0066cc; background: transparent;")
        lay.addWidget(t)
        s = QLabel("Калькулятор расчёта проектной документации")
        s.setFont(QFont("Arial", 10))
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setStyleSheet("color: #666; background: transparent;")
        lay.addWidget(s)
        lay.addSpacing(10)
        ist = (
            "QLineEdit { background-color: white; border: 2px solid #ccc; "
            "border-radius: 6px; padding: 6px 12px; color: #333; } "
            "QLineEdit:focus { border: 2px solid #0066cc; }"
        )
        self.edit_login = QLineEdit()
        self.edit_login.setPlaceholderText("Логин")
        self.edit_login.setFont(QFont("Arial", 11))
        self.edit_login.setMinimumHeight(36)
        self.edit_login.setStyleSheet(ist)
        lay.addWidget(self.edit_login)
        self.edit_password = QLineEdit()
        self.edit_password.setPlaceholderText("Пароль")
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_password.setFont(QFont("Arial", 11))
        self.edit_password.setMinimumHeight(36)
        self.edit_password.setStyleSheet(ist)
        self.edit_password.returnPressed.connect(self._try_login)
        lay.addWidget(self.edit_password)
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet(
            "color: red; font-size: 11px; background: transparent;"
        )
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_error)
        b = QPushButton("Войти")
        b.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        b.setMinimumHeight(40)
        b.setStyleSheet(
            "QPushButton { background-color: #0066cc; color: white; "
            "border: none; border-radius: 6px; font-weight: bold; } "
            "QPushButton:hover { background-color: #0052a3; }"
        )
        b.clicked.connect(self._try_login)
        lay.addWidget(b)
        be = QPushButton("Выход")
        be.setFont(QFont("Arial", 10))
        be.setMinimumHeight(32)
        be.setStyleSheet(
            "QPushButton { background-color: #999; color: white; "
            "border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #777; }"
        )
        be.clicked.connect(self._exit_app)
        lay.addWidget(be)
        self.setStyleSheet("QDialog { background-color: #f5f6f7; color: #333; }")

    def _try_login(self):
        if _h(self.edit_login.text().strip().lower()) == _VL and \
           _h(self.edit_password.text().strip()) == _VP:
            self.authenticated = True
            self.accept()
        else:
            self.lbl_error.setText("❌ Неверный логин или пароль")
            self.edit_password.clear()
            self.edit_password.setFocus()

    def _exit_app(self):
        self.authenticated = False
        self.reject()

    def closeEvent(self, event):
        if not self.authenticated:
            self.reject()
        super().closeEvent(event)


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

class FormatHintPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._panel_width = 520
        self._btn_width = 28
        self.setStyleSheet(
            "FormatHintPanel { background-color: #f9f9f9; "
            "border: 2px solid #0066cc; border-radius: 8px; color: #333; }"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.btn_toggle = QPushButton("◀\n📐\nФ\nо\nр\nм\nа\nт\nы")
        self.btn_toggle.setFixedWidth(self._btn_width)
        self.btn_toggle.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self.btn_toggle.setStyleSheet(
            "QPushButton { background-color: #0066cc; color: white; border: none; "
            "border-radius: 4px; font-size: 11px; font-weight: bold; padding: 4px 2px; } "
            "QPushButton:hover { background-color: #0052a3; }"
        )
        self.btn_toggle.clicked.connect(self.toggle)
        root.addWidget(self.btn_toggle)
        self.content = QWidget()
        self.content.setFixedWidth(self._panel_width - self._btn_width)
        self.content.setVisible(False)
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(4)
        title = QLabel("📐 Справочник форматов")
        title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #0066cc; background: transparent; border: none;")
        cl.addWidget(title)
        legend = QLabel(
            '<span style="color:#2e7d32;">● Без резки</span> &nbsp;&nbsp; '
            '<span style="color:#1565c0;">● Нужна резка</span> &nbsp;&nbsp; '
            '<span style="color:#c62828;">● Нет возможности печати</span>'
        )
        legend.setFont(QFont("Arial", 8))
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        legend.setStyleSheet("background: transparent; border: none; padding: 2px; color: #333;")
        legend.setWordWrap(True)
        cl.addWidget(legend)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        fw = QWidget()
        fw.setStyleSheet("background: transparent; color: #333;")
        fl = QVBoxLayout(fw)
        fl.setContentsMargins(4, 4, 4, 4)
        fl.setSpacing(2)
        self._fmt_label = QLabel(self._build_formats_html())
        self._fmt_label.setFont(QFont("Consolas", 9))
        self._fmt_label.setWordWrap(True)
        self._fmt_label.setTextFormat(Qt.TextFormat.RichText)
        self._fmt_label.setStyleSheet("background: transparent; border: none; padding: 4px; color: #333;")
        fl.addWidget(self._fmt_label)
        fl.addStretch()
        scroll.setWidget(fw)
        cl.addWidget(scroll)
        root.addWidget(self.content)
        self.setFixedWidth(self._btn_width)

    def _get_format_color(self, name):
        red = {"A0x2", "A0x3", "A0x4", "A0x5", "A0x6", "A0x7", "A0x8", "A0x9"}
        if name in red:
            return "#c62828", "Нет возможности распечатать такой формат"
        if name in CUTTING_FORMATS:
            return "#1565c0", "Нужна резка"
        return "#2e7d32", "Без резки"

    def _fmt_span(self, name, size_str, bracket_str=None):
        color, tip = self._get_format_color(name)
        s = f'<span style="color:{color};" title="{tip}">{name} — {size_str}</span>'
        if bracket_str:
            s += (
                f' <span style="color:#2e7d32;font-weight:bold;" '
                f'title="Такой формат мы можем распечатать">({bracket_str})</span>'
            )
        return s

    def _build_formats_html(self):
        lines = []
        def table_start():
            lines.append('<table cellspacing="0" cellpadding="2" style="border:none;background:transparent;">')
        def table_end():
            lines.append('</table>')
        def hr():
            lines.append('<hr style="border:1px solid #ccc;">')
        a4 = [("A4","210×297 мм"),("A4x3","297×630 мм"),("A4x4","297×840 мм"),("A4x5","297×1050 мм"),
              ("A4x6","297×1260 мм"),("A4x7","297×1470 мм"),("A4x8","297×1680 мм"),("A4x9","297×1890 мм")]
        a3 = [("A3","297×420 мм"),("A3x3","420×891 мм"),("A3x4","420×1188 мм"),("A3x5","420×1485 мм"),
              ("A3x6","420×1782 мм"),("A3x7","420×2079 мм"),("A3x8","420×2376 мм"),("A3x9","420×2673 мм")]
        table_start()
        for i in range(max(len(a4),len(a3))):
            l = self._fmt_span(*a4[i]) if i<len(a4) else ""
            r = self._fmt_span(*a3[i]) if i<len(a3) else ""
            lines.append(f'<tr><td style="padding-right:20px;border:none;">{l}</td><td style="border:none;">{r}</td></tr>')
        table_end(); hr()
        a2 = [("A2","420×594 мм"),("A2x3","594×1260 мм"),("A2x4","594×1680 мм"),("A2x5","594×2100 мм"),
              ("A2x6","594×2520 мм"),("A2x7","594×2940 мм"),("A2x8","594×3360 мм"),("A2x9","594×3780 мм")]
        a1 = [("A1","594×841 мм"),("A1x3","841×1782 мм"),("A1x4","841×2376 мм"),("A1x5","841×2970 мм"),
              ("A1x6","841×3564 мм"),("A1x7","841×4158 мм"),("A1x8","841×4752 мм"),("A1x9","841×5346 мм")]
        table_start()
        for i in range(max(len(a2),len(a1))):
            l = self._fmt_span(*a2[i]) if i<len(a2) else ""
            r = self._fmt_span(*a1[i]) if i<len(a1) else ""
            lines.append(f'<tr><td style="padding-right:20px;border:none;">{l}</td><td style="border:none;">{r}</td></tr>')
        table_end(); hr()
        a0 = [("A0","841×1189 мм",None),("A0x2","1189×1682 мм","910×1287 мм"),("A0x3","1189×2523 мм","910×1930 мм"),
              ("A0x4","1189×3364 мм","910×2575 мм"),("A0x5","1189×4205 мм","910×3218 мм"),("A0x6","1189×5046 мм","910×3862 мм"),
              ("A0x7","1189×5887 мм","910×4505 мм"),("A0x8","1189×6728 мм","910×5150 мм"),("A0x9","1189×7569 мм","910×5793 мм")]
        table_start()
        for name,size,bracket in a0:
            c = self._fmt_span(name,size,bracket)
            lines.append(f'<tr><td colspan="2" style="border:none;">{c}</td></tr>')
        table_end()
        return "\n".join(lines)

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)

    def toggle(self):
        if self._expanded:
            self.content.setVisible(False)
            self.setFixedWidth(self._btn_width)
            self.btn_toggle.setText("◀\n📐\nФ\nо\nр\nм\nа\nт\nы")
        else:
            self.content.setVisible(True)
            self.setFixedWidth(self._panel_width)
            self.btn_toggle.setText("▶\n📐\nФ\nо\nр\nм\nа\nт\nы")
        self._expanded = not self._expanded
        p = self.parent()
        if p and hasattr(p, '_reposition_hint'):
            p._reposition_hint()


# ─────────────────────────────────────────────────────────────────────────────
# Диалог нестандартного формата
# ─────────────────────────────────────────────────────────────────────────────

class UnknownFormatDialog(QDialog):
    def __init__(self, w, h, color, pages, pdf_path, parent=None):
        super().__init__(parent)
        self.w, self.h, self.color = w, h, color
        self.pages, self.pdf_path = pages, pdf_path
        self.result_action = self.result_value = self._temp_file = None
        self._build_ui()

    def _build_ui(self):
        cs = "цвет" if self.color else "ч/б"
        rng = compact_page_list(self.pages)
        self.setWindowTitle("Нестандартный формат")
        self.setMinimumWidth(560)
        self.setModal(True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        mw = QWidget()
        root = QVBoxLayout(mw)
        root.setSpacing(12)
        root.setContentsMargins(20,20,20,20)
        ib = QGroupBox("Обнаружен неизвестный формат")
        ib.setFont(QFont("Arial",10,QFont.Weight.Bold))
        ib.setStyleSheet("QGroupBox{color:#333;background-color:white;}QGroupBox::title{color:#333;}")
        il = QVBoxLayout(ib)
        for t in [f"Файл: <b>{os.path.basename(self.pdf_path)}</b>",
                  f"Размер: <b>{self.w} × {self.h} мм</b>",
                  f"Цветность: <b>{cs}</b>",
                  f"Страниц: <b>{len(self.pages)}</b>  ({rng})"]:
            lb = QLabel(t); lb.setFont(QFont("Arial",10)); lb.setStyleSheet("color:#333;background:transparent;")
            il.addWidget(lb)
        bo = QPushButton("👁️ Открыть эти страницы для просмотра")
        bo.setFont(QFont("Arial",10))
        bo.setStyleSheet("QPushButton{background-color:#e67e22;color:white;padding:10px;}QPushButton:hover{background-color:#d35400;}")
        bo.clicked.connect(self._open_pages)
        il.addWidget(bo)
        root.addWidget(ib)
        fb = QGroupBox("Вариант 1 — подогнать к формату")
        fb.setStyleSheet("QGroupBox{color:#333;background-color:white;}QGroupBox::title{color:#333;}")
        fl = QHBoxLayout(fb)
        self.edit_format = QLineEdit()
        self.edit_format.setPlaceholderText("Например: A4, A3, A3x3, A2x4 …")
        self.edit_format.setFont(QFont("Arial",10))
        self.edit_format.setStyleSheet("QLineEdit{color:#333;background:white;border:1px solid #ccc;}")
        fl.addWidget(self.edit_format)
        bf = QPushButton("Применить формат"); bf.setFixedWidth(160); bf.clicked.connect(self._apply_format)
        fl.addWidget(bf)
        root.addWidget(fb)
        rb = QGroupBox("Вариант 2 — рулонная печать")
        rb.setStyleSheet("QGroupBox{color:#333;background-color:white;}QGroupBox::title{color:#333;}")
        rl = QVBoxLayout(rb)
        rr = QHBoxLayout()
        lbl_len = QLabel("Длина на страницу (мм или м):"); lbl_len.setStyleSheet("color:#333;background:transparent;")
        rr.addWidget(lbl_len)
        self.edit_roll = QLineEdit()
        self.edit_roll.setPlaceholderText("Например: 594 или 0.594")
        self.edit_roll.setFont(QFont("Arial",10))
        self.edit_roll.setStyleSheet("QLineEdit{color:#333;background:white;border:1px solid #ccc;}")
        rr.addWidget(self.edit_roll)
        br = QPushButton("Применить длину"); br.setFixedWidth(160); br.clicked.connect(self._apply_roll)
        rr.addWidget(br)
        rl.addLayout(rr)
        ba = QPushButton(f"По бо́льшей стороне  ({max(self.w,self.h):.0f} мм × {len(self.pages)} стр.)")
        ba.setFont(QFont("Arial",10)); ba.clicked.connect(self._apply_auto)
        rl.addWidget(ba)
        root.addWidget(rb)
        bs = QPushButton("Пропустить (не учитывать эти страницы)")
        bs.setStyleSheet("QPushButton{background-color:#888;color:white;}QPushButton:hover{background-color:#666;}")
        bs.clicked.connect(self._skip)
        root.addWidget(bs)
        outer.addWidget(mw, stretch=1)
        self.hint_panel = FormatHintPanel(self)
        outer.addWidget(self.hint_panel, stretch=0)

    def _reposition_hint(self):
        self.adjustSize()

    def closeEvent(self, event):
        if self.result_action is None:
            self.result_action = "skip"; self.result_value = None
        super().closeEvent(event)

    def _open_pages(self):
        try:
            src = fitz.open(self.pdf_path); dst = fitz.open()
            for pn in self.pages:
                sp = src[pn-1]
                np_ = dst.new_page(-1, width=sp.rect.width, height=sp.rect.height)
                np_.show_pdf_page(np_.rect, src, pn-1)
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

    def _apply_format(self):
        raw = self.edit_format.text().strip()
        if not raw:
            QMessageBox.warning(self,"Ошибка","Введите название формата."); return
        def norm(s): return s.upper().replace("А","A").replace("Х","X").replace(" ","")
        un = norm(raw); matched = None
        for k in list(ISO_A)+list(ISO_A_NONSTANDARD):
            if norm(k)==un: matched=k; break
        if matched is None:
            if QMessageBox.question(self,"Неизвестный формат",f'Формат "{raw}" не найден.\nВсё равно использовать?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.No: return
            matched = un
        self.result_action="format"; self.result_value=matched; self.accept()

    def _apply_roll(self):
        t = self.edit_roll.text().strip().replace(",",".")
        try: v=float(t)
        except ValueError: QMessageBox.warning(self,"Ошибка","Введите числовое значение."); return
        if v<=0: QMessageBox.warning(self,"Ошибка","Значение должно быть > 0."); return
        if v<100: v*=1000
        self.result_action="roll_mm"; self.result_value=v; self.accept()

    def _apply_auto(self):
        self.result_action="roll_auto"; self.result_value=max(self.w,self.h); self.accept()

    def _skip(self):
        self.result_action="skip"; self.result_value=None; self.accept()


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

    def __init__(self, pdfs, force_bw=False):
        super().__init__()
        self.pdfs = pdfs; self.force_bw = force_bw
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
                        ff=defaultdict(int); fp=defaultdict(list); frb=frc=0.0; frb_p,frc_p=[],[]; cg=defaultdict(list); file_roll_groups=[]
                        for i,p in enumerate(doc):
                            if self._stop_requested: break
                            pn=i+1; r=p.mediabox
                            w,h=sorted((round(r.width*25.4/72,1),round(r.height*25.4/72,1)))
                            col = False if self.force_bw else self.detect_page_color(p)
                            fA=self.match_format_with_tolerance(w,h,ISO_A)
                            fN=self.match_format_with_tolerance(w,h,ISO_A_NONSTANDARD)
                            if fA:
                                key=f"{fA} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            elif fN:
                                key=f"{fN} {'цвет' if col else 'ч/б'}"; grand[key]+=1; ff[key]+=1; fp[key].append(pn)
                            else: cg[(w,h,col)].append(pn)
                            prog=int(100*(file_idx+(i+1)/total)/total_files); self.progress.emit(prog); time.sleep(0.001)
                        if self._stop_requested:
                            file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups}); break
                        for (w,h,col),pages in cg.items():
                            if self._stop_requested: break
                            self.need_user_input.emit(w,h,col,pages,pdf_path); self._wait_for_user()
                            if self._stop_requested: break
                            action=self._user_action; value=self._user_value; kind="цвет" if col else "ч/б"
                            if action=="skip": pass
                            elif action=="format":
                                key=f"{value} {kind}"; grand[key]+=len(pages); ff[key]+=len(pages); fp[key].extend(pages)
                            elif action in ("roll_mm","roll_auto"):
                                ppm=float(value); mm=ppm*len(pages)
                                if col: grand["Рулон цвет мм"]+=mm; frc+=mm; frc_p.extend(pages)
                                else: grand["Рулон ч/б мм"]+=mm; frb+=mm; frb_p.extend(pages)
                                file_roll_groups.append({"w":w,"h":h,"color":col,"count":len(pages),"per_page_mm":ppm,"total_mm":mm,"pages":sorted(pages)})
                                sk=f"{w:.0f}×{h:.0f}"; rfk=f"_roll_fold_{sk}_{kind}"; grand[rfk]=grand.get(rfk,0)+len(pages)
                        file_details.append({"name":name,"total":total,"formats":dict(ff),"pages":{k:sorted(v) for k,v in fp.items()},"roll_bw":frb,"roll_color":frc,"roll_bw_pages":sorted(frb_p),"roll_color_pages":sorted(frc_p),"roll_groups":file_roll_groups})
                except Exception as e: self.error.emit(f"Ошибка при обработке {pdf_path}: {e}"); continue
            if self._stop_requested:
                self.finished.emit(dict(grand),total_source,file_page_counts,file_details); self.stopped.emit()
            else:
                self.progress.emit(100); self.finished.emit(dict(grand),total_source,file_page_counts,file_details)
        except Exception as e: self.error.emit(f"Критическая ошибка: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────

class PrintingCalculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Калькулятор расчёта проектной документации")
        self.setGeometry(100,100,1200,700)
        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.primary_color="#0066cc"; self.danger_color="#d33"; self.bg_color="#f5f6f7"
        self.card_color="#ffffff"; self.text_color="#333333"
        self.apply_style()
        self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
        self.selected_path=""; self.copies=1; self.force_bw=False
        self.need_folding_a4=self.need_folding_a3=False
        self.need_binding_a4=self.need_binding_a3=False
        self.thread=self.current_dialog=None; self._history_items=[]
        self.init_ui()
        QTimer.singleShot(100, self.refresh_history)

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
            QSpinBox{{background-color:{self.card_color};color:{self.text_color};border:1px solid #ccc;border-radius:4px;padding:2px 4px;}}
            QCheckBox{{color:{self.text_color};background:transparent;}}
            QRadioButton{{background-color:{self.card_color};color:{self.text_color};padding:4px 12px;font-weight:normal;}}
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
        WhatsNewDialog(APP_VERSION, parent=self).exec()

    def create_input_tab(self):
        w=QWidget(); lay=QVBoxLayout(w); lay.setSpacing(15); lay.setContentsMargins(20,20,20,20)
        ff=QFrame(); fl=QVBoxLayout(ff); fl.addWidget(self._bold_label("📁 Выберите папку:"))
        row=QHBoxLayout(); self.label_path=QLabel("Путь не выбран"); self.label_path.setStyleSheet("color:#666;padding:5px;background:transparent;"); row.addWidget(self.label_path)
        bb=QPushButton("📂 Обзор..."); bb.clicked.connect(self.browse_path); row.addWidget(bb); fl.addLayout(row); lay.addWidget(ff)
        cf=QFrame(); cl=QVBoxLayout(cf); cl.addWidget(self._bold_label("🎨 Цветность:"))
        cr=QHBoxLayout(); self.rb_color_auto=QRadioButton("По файлу"); self.rb_color_bw=QRadioButton("Ч/б"); self.rb_color_auto.setChecked(True)
        self.color_mode_group=QButtonGroup(self); self.color_mode_group.addButton(self.rb_color_auto); self.color_mode_group.addButton(self.rb_color_bw)
        cr.addWidget(self.rb_color_auto); cr.addWidget(self.rb_color_bw); cr.addStretch(); cl.addLayout(cr)
        h=QLabel("«По файлу» — анализ цвета каждой страницы.  «Ч/б» — всё считается чёрно-белым.")
        h.setStyleSheet("color:#666;font-size:10px;background:transparent;"); h.setWordWrap(True); cl.addWidget(h); lay.addWidget(cf)
        pf=QFrame(); pl=QVBoxLayout(pf); pl.addWidget(self._bold_label("⚙️ Параметры:"))
        r2=QHBoxLayout(); lbl_copies=QLabel("Количество экземпляров:"); lbl_copies.setStyleSheet(f"color:{self.text_color};background:transparent;"); r2.addWidget(lbl_copies)
        self.spinbox_copies=NoScrollSpinBox(); self.spinbox_copies.setMinimum(1); self.spinbox_copies.setMaximum(100); self.spinbox_copies.setValue(1); self.spinbox_copies.setFixedWidth(80)
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
        btn_whats_new=QPushButton(f"🎉 Что нового (v{APP_VERSION})"); btn_whats_new.setFont(QFont("Arial",9)); btn_whats_new.setCursor(Qt.CursorShape.PointingHandCursor)
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
        bc=QPushButton("📋 Копировать в буфер обмена"); bc.setMinimumHeight(40); bc.clicked.connect(self.copy_report); lay.addWidget(bc); return w

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
        p=QFileDialog.getExistingDirectory(self,"Выберите папку с PDF файлами")
        if p: self.selected_path=p; self.label_path.setText(f"✓ {p}")

    def on_params_changed(self):
        self.copies=self.spinbox_copies.value(); self.need_folding_a4=self.rb_folding_a4.isChecked(); self.need_folding_a3=self.rb_folding_a3.isChecked()
        self.need_binding_a4=self.rb_binding_a4.isChecked(); self.need_binding_a3=self.rb_binding_a3.isChecked(); self.calculate_and_display()

    def start_analysis(self):
        if not self.selected_path: self.label_status.setText("❌ Выберите папку или файл"); return
        if not os.path.exists(self.selected_path): self.label_status.setText("❌ Путь не существует"); return
        if self.selected_path.lower().endswith(".pdf"): pdfs=[self.selected_path]
        else: pdfs=[os.path.join(r,f) for r,_,fs in os.walk(self.selected_path) for f in fs if f.lower().endswith(".pdf")]
        if not pdfs: self.label_status.setText("❌ PDF файлы не найдены"); return
        self.force_bw=self.rb_color_bw.isChecked(); self.grand={}; self.total_source=0; self.file_page_counts=[]; self.file_details=[]
        self.label_status.setText("⏳ Идет анализ..."); self.progress_bar.setValue(0); self.btn_analyze.setEnabled(False); self.btn_stop.setEnabled(True)
        self.thread=AnalysisThread(pdfs,force_bw=self.force_bw)
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
            calc_data={'version':1,'app_version':APP_VERSION,'saved_at':datetime.now().isoformat(),'name':name,
                'source':{'path':self.selected_path,'files_count':len(self.file_page_counts),'total_pages':self.total_source},
                'params':{'copies':self.copies,'force_bw':self.force_bw,
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
            self.selected_path=data.get('source',{}).get('path','')
            if self.selected_path: self.label_path.setText(f"✓ {self.selected_path}")
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

    def _gfs(self, fmt): return ISO_A.get(fmt) or ISO_A_NONSTANDARD.get(fmt)

    def _autosize(self, te, minh=80, maxh=2000):
        d=te.document(); d.setTextWidth(te.viewport().width()); te.setFixedHeight(max(minh,min(int(d.size().height()+10),maxh)))

    def _build_print_summary(self):
        c=self.copies; st=defaultdict(int); di=defaultdict(list); erb=erc=0.0
        for fmt in ISO_A:
            for kind in KIND_ORDER:
                cnt=int(self.grand.get(f"{fmt} {kind}",0))
                if cnt>0: st[(fmt,kind)]+=cnt*c
        for src,(tgt,div) in CONVERSION_RULES.items():
            for kind in KIND_ORDER:
                cnt=int(self.grand.get(f"{src} {kind}",0))
                if cnt>0: sq=cnt*c; add=math.ceil(sq/div); st[(tgt,kind)]+=add; di[(tgt,kind)].append((src,sq,add))
        ps=set(CONVERSION_RULES)
        for fmt,(fw,fh) in ISO_A_NONSTANDARD.items():
            if fmt in ps: continue
            for kind in KIND_ORDER:
                cnt=int(self.grand.get(f"{fmt} {kind}",0))
                if cnt>0:
                    mm=max(fw,fh)*cnt*c
                    if kind=="цвет": erc+=mm
                    else: erb+=mm
        return st,di,erb,erc

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
        lines,total=[],0
        for fmt in ISO_A_NONSTANDARD:
            if fmt not in CUTTING_FORMATS: continue
            qty=(int(self.grand.get(f"{fmt} цвет",0))+int(self.grand.get(f"{fmt} ч/б",0)))*self.copies
            if qty>0: fw,fh=ISO_A_NONSTANDARD[fmt]; lines.append(f"{fmt} ({fw}×{fh} мм) — {qty} шт."); total+=qty
        return lines,total

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
        total=0.0
        for fmt in FMT_ORDER:
            sz=ISO_A.get(fmt)
            if not sz: continue
            wps=sz[0]*sz[1]*PAPER_DENSITY_G_PER_MM2; qty=sum(st.get((fmt,k),0) for k in KIND_ORDER)
            if qty>0: total+=wps*qty
        rm=rbm+rcm
        if rm>0: total+=rm*ROLL_WEIGHT_G_PER_MM
        if bt and tb>0:
            u=BINDING_WEIGHT_G.get(bt,0)
            if u>0: total+=u*tb
        return total

    def display_details(self):
        if not self.file_details: self.text_details.setText("Нет данных. Сначала проведите анализ."); return
        lines=[]
        for fd in self.file_details:
            lines.append(f"📄 {fd['name']}  ({fd['total']} стр.)")
            fmts=fd.get("formats",{}); pm=fd.get("pages",{})
            def sk(item):
                f,k=self._pfk(item[0])
                if f in FMT_ORDER: return (0,FMT_ORDER.index(f),k or "")
                if f in ISO_A_NONSTANDARD: return (1,list(ISO_A_NONSTANDARD).index(f),k or "")
                return (2,f or "",k or "")
            for k,cnt in sorted(fmts.items(),key=sk):
                f,kn=self._pfk(k)
                if not f: continue
                rng=compact_page_list(pm.get(k,[])); sz=self._gfs(f); ss=f" ({sz[0]}×{sz[1]} мм)" if sz else ""
                if rng: lines.append(f"    {f} {kn}{ss} — {cnt} стр. ({rng})")
                else: lines.append(f"    {f} {kn}{ss} — {cnt} стр.")
            for rg in fd.get("roll_groups",[]):
                kind_str="цвет" if rg["color"] else "ч/б"; rng=compact_page_list(rg["pages"])
                line=f"    Рулон {kind_str} ({rg['w']:.0f}×{rg['h']:.0f} мм) — {rg['count']} стр."
                if rng: line+=f" ({rng})"
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
        if not self.grand: return
        self.display_details(); st,di,erb,erc=self._build_print_summary()
        pl,tpp=[],0
        for fmt in FMT_ORDER:
            fw,fh=ISO_A[fmt]
            for kind in KIND_ORDER:
                t=st.get((fmt,kind),0)
                if t<=0: continue
                line=f"{fmt} {kind} ({fw}×{fh} мм) — {t} стр."
                if di.get((fmt,kind)): parts=[f"из {s}: {sq}→{a}" for s,sq,a in di[(fmt,kind)]]; line+="  ["+", ".join(parts)+"]"
                pl.append(line); tpp+=t
        self.text_printing.setText("\n".join(pl) if pl else "Нет данных для печати")
        rl=[]; rbt=self.grand.get("Рулон ч/б мм",0)*self.copies+erb; rct=self.grand.get("Рулон цвет мм",0)*self.copies+erc
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
        nb=[]
        for fmt,(fw,fh) in ISO_A_NONSTANDARD.items():
            for kind in KIND_ORDER:
                cnt=int(self.grand.get(f"{fmt} {kind}",0))
                if cnt>0: q=cnt*c; nb.append(f"{fmt} {kind} ({fw}×{fh} мм) — {q} стр."); tpr+=q
        cb=[]
        for k in self.grand:
            if k.startswith("Рулон") or k.startswith("_roll_fold_"): continue
            fmt,kind=self._pfk(k)
            if not fmt or not kind or fmt in ISO_A or fmt in ISO_A_NONSTANDARD: continue
            cnt=int(self.grand.get(k,0))
            if cnt>0: q=cnt*c; cb.append(f"{fmt} {kind} — {q} стр."); tpr+=q
        rb_lines=[]
        for fd in self.file_details:
            for rg in fd.get("roll_groups",[]):
                kind_str="цвет" if rg.get("color") else "ч/б"; w=rg.get("w",0); h=rg.get("h",0); count=rg.get("count",0)
                if count<=0: continue
                q=count*c; tpr+=q; rb_lines.append(f"{w:.0f}×{h:.0f} мм {kind_str} — {q} шт.")
        if rb_lines:
            agg=defaultdict(int)
            for line in rb_lines:
                m=re.match(r'(.+?) — (\d+) шт\.$',line)
                if m: agg[m.group(1)]+=int(m.group(2))
            rb_lines=[f"{k} — {v} шт." for k,v in agg.items()]
        rbr=self.grand.get("Рулон ч/б мм",0)*c; rcr=self.grand.get("Рулон цвет мм",0)*c
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
            if sb or nb or cb: lines.append("")
            lines.append("• Нестандартные/рулонные форматы:"); lines.extend(f"  {l}" for l in rb_lines)
        if not (sb or nb or cb or rb_lines): lines.append("Нет данных")
        lines.append(f"Итого страниц: {tpr}"); lines.append("")
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
        if rbr>0 or rcr>0:
            lines.append("РУЛОННАЯ ПЕЧАТЬ:")
            if rbr>0: lines.append(f"  Ч/б — {rbr:.0f} мм ({rbr/1000:.2f} м)")
            if rcr>0: lines.append(f"  Цвет — {rcr:.0f} мм ({rcr/1000:.2f} м)")
            lines.append("")
        lines.append("─"*60); lines.append(f"ВЕС: {self._fw(tw)}"); lines.append("="*60)
        self.text_report.setText("\n".join(lines))

    def copy_report(self):
        txt=self.text_report.toPlainText()
        try:
            import pyperclip; pyperclip.copy(txt)
        except:
            try: p=subprocess.Popen(['clip'],stdin=subprocess.PIPE,shell=True); p.communicate(txt.encode('utf-8'))
            except: pass
        self.label_status.setText("✅ Отчет скопирован в буфер обмена")

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

    # 1. Лицензия
    ok, msg = check_remote_license()
    if not ok:
        QMessageBox.critical(None, "Доступ запрещён", msg)
        sys.exit(1)

    # 2. Обновление (только в frozen / exe режиме)
    if getattr(sys, "frozen", False):
        has_update, latest_ver, dl_url, upd_err = check_for_update()
        if upd_err:
            QMessageBox.warning(
                None, "Проверка обновлений",
                f"Не удалось проверить наличие обновлений.\n\n{upd_err}"
            )
        elif has_update:
            ans = QMessageBox.question(
                None,
                "Доступно обновление",
                f"Доступна новая версия {latest_ver}.\n\nОбновить сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if ans == QMessageBox.StandardButton.Yes:
                UpdateDialog(latest_ver, dl_url).exec()

    # 3. Авторизация
    dlg = LoginDialog()
    if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.authenticated:
        sys.exit(0)

    # 4. Главное окно
    window = PrintingCalculator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()