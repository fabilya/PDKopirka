import os
import sys
import time
import io
import math
import hmac
import hashlib
import random
import tempfile
import subprocess
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timedelta

import pymupdf as fitz
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QFileDialog, QLabel, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QProgressBar, QFrame,
    QScrollArea, QDialog, QLineEdit, QMessageBox, QGroupBox,
    QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
import json
import shutil

# ─────────────────────────────────────────────────────────────────────────────
# Автообновление
# ─────────────────────────────────────────────────────────────────────────────

APP_VERSION = "1.0.0"  # ← текущая версия

UPDATE_REPO = "fabilya/PDKopirka"  # username/repo
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"

GITHUB_TOKEN = "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"


def _parse_version(v: str):
    """Преобразует '1.2.3' в (1, 2, 3)."""
    v = v.lstrip("v").strip()
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)


def check_for_update():
    """
    Проверяет наличие новой версии.
    Возвращает (has_update, latest_version, download_url) или (False, None, None).
    """
    try:
        req = urllib.request.Request(UPDATE_API_URL)
        req.add_header("User-Agent", "PDKopirka-Updater/1.0")
        req.add_header("Accept", "application/vnd.github.v3+json")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"token {GITHUB_TOKEN}")

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        latest_tag = data.get("tag_name", "")
        latest_version = _parse_version(latest_tag)
        current_version = _parse_version(APP_VERSION)

        if latest_version <= current_version:
            return False, None, None

        # Ищем .exe в assets
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"].lower().endswith(".exe"):
                download_url = asset["browser_download_url"]
                # Для приватных репо нужно использовать API URL
                if GITHUB_TOKEN:
                    download_url = asset["url"]
                break

        if not download_url:
            return False, None, None

        return True, latest_tag, download_url

    except Exception as e:
        print(f"[UPDATE] Ошибка проверки: {e}")
        return False, None, None


def download_update(url: str, target_path: str, progress_callback=None) -> bool:
    """Скачивает .exe с отображением прогресса."""
    try:
        # Удаляем старый скачанный файл, если есть
        for old_file in [target_path, target_path + ".part"]:
            if os.path.exists(old_file):
                try:
                    os.remove(old_file)
                except OSError:
                    pass

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "PDKopirka-Updater/1.0")
        if GITHUB_TOKEN:
            req.add_header("Authorization", f"token {GITHUB_TOKEN}")
            req.add_header("Accept", "application/octet-stream")

        with urllib.request.urlopen(req, timeout=120) as resp:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024  # 64 КБ

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

        # Проверки целостности файла
        if total_size > 0 and downloaded != total_size:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False

        file_size = os.path.getsize(temp_path)
        if file_size < 1024 * 100:  # меньше 100 КБ
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False

        # Проверка PE-сигнатуры (MZ)
        with open(temp_path, "rb") as f:
            magic = f.read(2)
        if magic != b"MZ":
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False

        # Переименуем в финальный
        if os.path.exists(target_path):
            os.remove(target_path)
        os.rename(temp_path, target_path)

        return True

    except urllib.error.HTTPError as e:
        print(f"[UPDATE] HTTP {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        print(f"[UPDATE] Ошибка сети: {e.reason}")
        return False
    except Exception as e:
        print(f"[UPDATE] Ошибка: {e}")
        return False


def apply_update_and_restart(new_exe_path: str):
    """
    Заменяет .exe на новый и закрывает программу.
    Новая версия НЕ запускается автоматически.
    """
    if not getattr(sys, "frozen", False):
        return

    current_exe = sys.executable
    current_pid = os.getpid()

    tmp_dir = tempfile.gettempdir()
    bat_path = os.path.join(tmp_dir, "pdkopirka_update.bat")
    vbs_path = os.path.join(tmp_dir, "pdkopirka_update.vbs")

    bat_content = f"""@echo off
chcp 65001 >nul 2>&1

REM ===== ШАГ 1: Ждём закрытия программы =====
set /a cnt=0
:wait_process
set /a cnt+=1
tasklist /FI "PID eq {current_pid}" /NH 2>nul | findstr /R "[0-9]" >nul 2>&1
if not errorlevel 1 (
    if %cnt% gtr 60 goto skip_wait
    ping -n 2 127.0.0.1 >nul 2>&1
    goto wait_process
)
:skip_wait

REM ===== ШАГ 2: Минимальная задержка для освобождения файла =====
ping -n 2 127.0.0.1 >nul 2>&1

REM ===== ШАГ 3: Чистим _MEI от старых запусков =====
for /d %%D in ("%TEMP%\\_MEI*") do rmdir /s /q "%%D" >nul 2>&1

REM ===== ШАГ 4: Заменяем exe (до 15 попыток) =====
set /a tries=0
:replace
set /a tries+=1
move /y "{new_exe_path}" "{current_exe}" >nul 2>&1
if errorlevel 1 (
    if %tries% lss 15 (
        ping -n 2 127.0.0.1 >nul 2>&1
        goto replace
    ) else (
        exit /b 1
    )
)

REM ===== ШАГ 5: Самоуничтожение =====
del "{vbs_path}" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""

    vbs_content = f'''Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c """"{bat_path}""""", 0, False
Set WshShell = Nothing
'''

    try:
        with open(bat_path, "w", encoding="cp866", errors="replace") as f:
            f.write(bat_content)
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)

        subprocess.Popen(
            ["wscript.exe", "//B", "//Nologo", vbs_path],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Сразу выходим — без задержки
        QApplication.quit()
        sys.exit(0)

    except Exception as e:
        print(f"[UPDATE] Ошибка подготовки обновления: {e}")
        sys.exit(1)


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

        # Запрещаем закрытие и изменение размера
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.CustomizeWindowHint |
            Qt.WindowType.WindowTitleHint
        )

        self._build_ui()
        # Автозапуск через 100мс после появления
        QTimer.singleShot(100, self._do_update)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(25, 25, 25, 25)

        title = QLabel(f"🔄 Обновление до версии {self.latest_version}")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #0066cc;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.status_lbl = QLabel("Подготовка...")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #555;")
        layout.addWidget(self.status_lbl)

    def closeEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()

    def _do_update(self):
        new_exe = os.path.join(tempfile.gettempdir(), "PDKopirka_new.exe")

        # Колбэк для прогресса
        def on_progress(downloaded, total):
            if total > 0:
                pct = min(100, int(downloaded * 100 / total))
                self.progress.setValue(pct)

                mb_d = downloaded / (1024 * 1024)
                mb_t = total / (1024 * 1024)
                self.status_lbl.setText(
                    f"Загрузка... {mb_d:.1f} / {mb_t:.1f} МБ ({pct}%)"
                )
            else:
                mb_d = downloaded / (1024 * 1024)
                self.status_lbl.setText(f"Загрузка... {mb_d:.1f} МБ")
            QApplication.processEvents()

        self.status_lbl.setText("Скачивание обновления...")
        QApplication.processEvents()

        success = download_update(self.download_url, new_exe, progress_callback=on_progress)

        if not success:
            self.status_lbl.setText("❌ Ошибка загрузки. Попробуйте позже.")
            self.progress.setValue(0)
            QApplication.processEvents()
            time.sleep(3)
            os._exit(1)
            return

        self.progress.setValue(100)
        self.status_lbl.setText("✅ Загружено! Программа закроется...")
        QApplication.processEvents()

        apply_update_and_restart(new_exe)


Image.MAX_IMAGE_PIXELS = None

FORMAT_TOLERANCE_MM = 5

ISO_A = {
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "A1": (594, 841),
    "A0": (841, 1189),
}

ISO_A_NONSTANDARD = {
    "A4x3": (297, 630),
    "A4x4": (297, 841),
    "A4x5": (297, 1051),
    "A4x6": (297, 1261),
    "A4x7": (297, 1471),
    "A4x8": (297, 1682),
    "A4x9": (297, 1892),
    "A3x3": (420, 891),
    "A3x4": (420, 1189),
    "A3x5": (420, 1486),
    "A3x6": (420, 1783),
    "A3x7": (420, 2080),
    "A2x3": (594, 1261),
    "A2x4": (594, 1682),
    "A2x5": (594, 2102),
    "A1x3": (841, 1783),
    "A1x4": (841, 2378),
}

CONVERSION_RULES = {
    "A4x3": ("A1", 2),
    "A4x4": ("A1", 2),
    "A3x3": ("A0", 2),
    "A3x4": ("A0", 2),
}

PAPER_DENSITY_G_PER_MM2 = 5.0 / (210 * 297)
ROLL_WEIGHT_G_PER_MM = 80.0 / 1000.0
BINDING_WEIGHT_G = {"A4": 60.0, "A3": 90.0}

FMT_ORDER = ["A4", "A3", "A2", "A1", "A0"]
KIND_ORDER = ["ч/б", "цвет"]


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


def _verify_token(token: str) -> tuple:
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


def check_remote_license() -> tuple:
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

        with urllib.request.urlopen(req, timeout=15) as resp:
            token = resp.read().decode("utf-8").strip()

        valid, status = _verify_token(token)

        if not valid:
            return False, (
                "Ошибка проверки лицензии.\n\n"
                f"Код: {status}\n\n"
                "Обратитесь к администратору."
            )

        if status == "ACTIVE":
            return True, ""

        return False, (
            "Доступ к программе заблокирован администратором.\n\n"
            "Обратитесь к администратору для восстановления доступа."
        )
    except urllib.error.URLError:
        return False, (
            "Не удалось проверить лицензию.\n\n"
            "Проверьте подключение к интернету\n"
            "или обратитесь к администратору."
        )
    except Exception as e:
        return False, f"Ошибка проверки лицензии:\n{str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# SpinBox без скролла
# ─────────────────────────────────────────────────────────────────────────────

class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


# ─────────────────────────────────────────────────────────────────────────────
# Диалог авторизации
# ─────────────────────────────────────────────────────────────────────────────

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
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("🔐 Вход в систему")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #0066cc;")
        layout.addWidget(title)

        subtitle = QLabel("Калькулятор расчёта проектной документации")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666;")
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        input_style = """
            QLineEdit {
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 6px;
                padding: 6px 12px;
                color: #333;
            }
            QLineEdit:focus { border: 2px solid #0066cc; }
        """

        self.edit_login = QLineEdit()
        self.edit_login.setPlaceholderText("Логин")
        self.edit_login.setFont(QFont("Arial", 11))
        self.edit_login.setMinimumHeight(36)
        self.edit_login.setStyleSheet(input_style)
        layout.addWidget(self.edit_login)

        self.edit_password = QLineEdit()
        self.edit_password.setPlaceholderText("Пароль")
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_password.setFont(QFont("Arial", 11))
        self.edit_password.setMinimumHeight(36)
        self.edit_password.setStyleSheet(input_style)
        self.edit_password.returnPressed.connect(self._try_login)
        layout.addWidget(self.edit_password)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: red; font-size: 11px;")
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_error)

        btn = QPushButton("Войти")
        btn.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        btn.setMinimumHeight(40)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #0066cc; color: white;
                border: none; border-radius: 6px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0052a3; }
            QPushButton:pressed { background-color: #003d7a; }
        """)
        btn.clicked.connect(self._try_login)
        layout.addWidget(btn)

        btn_exit = QPushButton("Выход")
        btn_exit.setFont(QFont("Arial", 10))
        btn_exit.setMinimumHeight(32)
        btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #999; color: white;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #777; }
        """)
        btn_exit.clicked.connect(self._exit_app)
        layout.addWidget(btn_exit)

        self.setStyleSheet("QDialog { background-color: #f5f6f7; }")

    def _try_login(self):
        login = self.edit_login.text().strip()
        password = self.edit_password.text().strip()

        if _h(login.lower()) == _VL and _h(password) == _VP:
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


# ─────────────────────────────────────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────────────────────────────────────

def compact_page_list(pages):
    if not pages:
        return ""
    pages = sorted(pages)
    ranges = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(str(start) if start == end else f"{start}-{end}")
            start = end = p
    ranges.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(ranges)


# ─────────────────────────────────────────────────────────────────────────────
# Диалог нестандартного формата
# ─────────────────────────────────────────────────────────────────────────────

class UnknownFormatDialog(QDialog):
    def __init__(self, w, h, color, pages, pdf_path, parent=None):
        super().__init__(parent)
        self.w = w
        self.h = h
        self.color = color
        self.pages = pages
        self.pdf_path = pdf_path
        self.result_action = None
        self.result_value = None
        self._temp_file = None
        self._build_ui()

    def _build_ui(self):
        color_str = "цвет" if self.color else "ч/б"
        ranges = compact_page_list(self.pages)

        self.setWindowTitle("Нестандартный формат")
        self.setMinimumWidth(520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 20)

        info_box = QGroupBox("Обнаружен неизвестный формат")
        info_box.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        info_layout = QVBoxLayout(info_box)

        for text in [
            f"Файл: <b>{os.path.basename(self.pdf_path)}</b>",
            f"Размер: <b>{self.w} × {self.h} мм</b>",
            f"Цветность: <b>{color_str}</b>",
            f"Страниц: <b>{len(self.pages)}</b>  ({ranges})",
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Arial", 10))
            info_layout.addWidget(lbl)

        btn_open = QPushButton("👁️ Открыть эти страницы для просмотра")
        btn_open.setFont(QFont("Arial", 10))
        btn_open.setStyleSheet(
            "background-color: #e67e22; color: white; padding: 10px;"
        )
        btn_open.clicked.connect(self._open_pages)
        info_layout.addWidget(btn_open)
        root.addWidget(info_box)

        fmt_box = QGroupBox("Вариант 1 — подогнать к формату")
        fmt_layout = QHBoxLayout(fmt_box)
        self.edit_format = QLineEdit()
        self.edit_format.setPlaceholderText("Например: A4, A3, A3x3, A2x4 …")
        self.edit_format.setFont(QFont("Arial", 10))
        fmt_layout.addWidget(self.edit_format)
        btn_fmt = QPushButton("Применить формат")
        btn_fmt.setFixedWidth(160)
        btn_fmt.clicked.connect(self._apply_format)
        fmt_layout.addWidget(btn_fmt)
        root.addWidget(fmt_box)

        roll_box = QGroupBox("Вариант 2 — рулонная печать")
        roll_layout = QVBoxLayout(roll_box)
        roll_row = QHBoxLayout()
        lbl_roll = QLabel("Длина на страницу (мм или м):")
        lbl_roll.setFont(QFont("Arial", 10))
        self.edit_roll = QLineEdit()
        self.edit_roll.setPlaceholderText("Например: 594 или 0.594")
        self.edit_roll.setFont(QFont("Arial", 10))
        btn_roll = QPushButton("Применить длину")
        btn_roll.setFixedWidth(160)
        btn_roll.clicked.connect(self._apply_roll)
        roll_row.addWidget(lbl_roll)
        roll_row.addWidget(self.edit_roll)
        roll_row.addWidget(btn_roll)
        roll_layout.addLayout(roll_row)

        btn_auto = QPushButton(
            f"По бо́льшей стороне  ({max(self.w, self.h):.0f} мм × "
            f"{len(self.pages)} стр.)"
        )
        btn_auto.setFont(QFont("Arial", 10))
        btn_auto.clicked.connect(self._apply_auto)
        roll_layout.addWidget(btn_auto)
        root.addWidget(roll_box)

        btn_skip = QPushButton("Пропустить (не учитывать эти страницы)")
        btn_skip.setStyleSheet("background-color: #888; color: white;")
        btn_skip.clicked.connect(self._skip)
        root.addWidget(btn_skip)

    def closeEvent(self, event):
        if self.result_action is None:
            self.result_action = "skip"
            self.result_value = None
        super().closeEvent(event)

    def _open_pages(self):
        try:
            src = fitz.open(self.pdf_path)
            dst = fitz.open()
            for pn in self.pages:
                sp = src[pn - 1]
                np_ = dst.new_page(-1, width=sp.rect.width, height=sp.rect.height)
                np_.show_pdf_page(np_.rect, src, pn - 1)

            base = os.path.splitext(os.path.basename(self.pdf_path))[0]
            rng = compact_page_list(self.pages).replace(", ", "_")
            tmp_name = f"{base}__стр_{rng}.pdf"
            tmp_dir = tempfile.gettempdir()
            tmp_path = os.path.join(tmp_dir, tmp_name)

            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    stamp = datetime.now().strftime("%H%M%S")
                    tmp_path = os.path.join(tmp_dir, f"{base}__стр_{rng}_{stamp}.pdf")

            dst.save(tmp_path)
            dst.close()
            src.close()
            self._temp_file = tmp_path

            if sys.platform == "win32":
                os.startfile(tmp_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", tmp_path])
            else:
                subprocess.Popen(["xdg-open", tmp_path])
        except Exception as e:
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось открыть страницы:\n{str(e)}")

    def _apply_format(self):
        raw = self.edit_format.text().strip()
        if not raw:
            QMessageBox.warning(self, "Ошибка", "Введите название формата.")
            return

        def normalize(s):
            return s.upper().replace("А", "A").replace("Х", "X").replace(" ", "")

        user_norm = normalize(raw)
        matched = None
        for key in list(ISO_A.keys()) + list(ISO_A_NONSTANDARD.keys()):
            if normalize(key) == user_norm:
                matched = key
                break

        if matched is None:
            reply = QMessageBox.question(
                self, "Неизвестный формат",
                f'Формат "{raw}" не найден.\nВсё равно использовать?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            matched = user_norm

        self.result_action = "format"
        self.result_value = matched
        self.accept()

    def _apply_roll(self):
        text = self.edit_roll.text().strip().replace(",", ".")
        try:
            val = float(text)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Введите числовое значение.")
            return
        if val <= 0:
            QMessageBox.warning(self, "Ошибка", "Значение должно быть > 0.")
            return
        if val < 100:
            val *= 1000
        self.result_action = "roll_mm"
        self.result_value = val
        self.accept()

    def _apply_auto(self):
        self.result_action = "roll_auto"
        self.result_value = max(self.w, self.h)
        self.accept()

    def _skip(self):
        self.result_action = "skip"
        self.result_value = None
        self.accept()


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
        self.pdfs = pdfs
        self.force_bw = force_bw
        self._user_action = None
        self._user_value = None
        self._stop_requested = False
        import threading
        self._wait_event = threading.Event()

    def request_stop(self):
        self._stop_requested = True
        self._user_action = "skip"
        self._user_value = None
        self._wait_event.set()

    def set_user_response(self, action, value):
        self._user_action = action
        self._user_value = value
        self._wait_event.set()

    def _wait_for_user(self):
        self._wait_event.clear()
        self._wait_event.wait()

    def detect_page_color(self, page, tol=15, white_thr=240,
                          min_colored_pixels=30, min_colored_ratio=0.00005):
        """
        Определяет, есть ли на странице цветные элементы.
        Параметры подобраны для распознавания мелких подписей и линий.
        """
        try:
            scale = 200 / 72
            pix = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB, alpha=False
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

            # Не белые пиксели (есть какое-то содержимое)
            ink = mx < white_thr
            ink_count = int(ink.sum())
            if ink_count == 0:
                return False

            # Цветные пиксели: разница между макс и мин каналом значительна
            diff = mx - mn
            colored = ink & (diff > tol)
            colored_count = int(colored.sum())

            # Проверка по абсолютному количеству ИЛИ по проценту
            if colored_count >= min_colored_pixels:
                return True
            if (colored_count / ink_count) >= min_colored_ratio:
                return True

            return False
        except Exception:
            return False

    def match_format_with_tolerance(self, w, h, table, tol=FORMAT_TOLERANCE_MM):
        for name, (fw, fh) in table.items():
            if ((abs(w - fw) <= tol and abs(h - fh) <= tol) or
                    (abs(h - fw) <= tol and abs(w - fh) <= tol)):
                return name
        return None

    def run(self):
        try:
            grand = defaultdict(float)
            total_source = 0
            file_page_counts = []
            file_details = []
            total_files = len(self.pdfs)

            for file_idx, pdf_path in enumerate(self.pdfs):
                if self._stop_requested:
                    break
                try:
                    with fitz.open(pdf_path) as doc:
                        total = len(doc)
                        total_source += total
                        file_page_counts.append(total)
                        name = os.path.basename(pdf_path)
                        self.status.emit(f"Анализ: {name} ({total} стр.)")

                        ff = defaultdict(int)
                        fp = defaultdict(list)
                        frb = 0.0
                        frc = 0.0
                        frb_p = []
                        frc_p = []
                        cg = defaultdict(list)

                        for i, p in enumerate(doc):
                            if self._stop_requested:
                                break
                            pn = i + 1
                            r = p.mediabox
                            w, h = sorted((round(r.width * 25.4 / 72, 1),
                                           round(r.height * 25.4 / 72, 1)))
                            col = False if self.force_bw else self.detect_page_color(p)

                            fA = self.match_format_with_tolerance(w, h, ISO_A)
                            fN = self.match_format_with_tolerance(w, h, ISO_A_NONSTANDARD)

                            if fA:
                                key = f"{fA} {'цвет' if col else 'ч/б'}"
                                grand[key] += 1; ff[key] += 1; fp[key].append(pn)
                            elif fN:
                                key = f"{fN} {'цвет' if col else 'ч/б'}"
                                grand[key] += 1; ff[key] += 1; fp[key].append(pn)
                            else:
                                cg[(w, h, col)].append(pn)

                            prog = int(100 * (file_idx + (i + 1) / total) / total_files)
                            self.progress.emit(prog)
                            time.sleep(0.001)

                        if self._stop_requested:
                            file_details.append({
                                "name": name, "total": total,
                                "formats": dict(ff),
                                "pages": {k: sorted(v) for k, v in fp.items()},
                                "roll_bw": frb, "roll_color": frc,
                                "roll_bw_pages": sorted(frb_p),
                                "roll_color_pages": sorted(frc_p),
                            })
                            break

                        for (w, h, col), pages in cg.items():
                            if self._stop_requested:
                                break
                            self.need_user_input.emit(w, h, col, pages, pdf_path)
                            self._wait_for_user()
                            if self._stop_requested:
                                break

                            action = self._user_action
                            value = self._user_value
                            kind = "цвет" if col else "ч/б"

                            if action == "skip":
                                pass
                            elif action == "format":
                                key = f"{value} {kind}"
                                grand[key] += len(pages)
                                ff[key] += len(pages)
                                fp[key].extend(pages)
                            elif action in ("roll_mm", "roll_auto"):
                                mm = float(value) * len(pages)
                                if col:
                                    grand["Рулон цвет мм"] += mm
                                    frc += mm; frc_p.extend(pages)
                                else:
                                    grand["Рулон ч/б мм"] += mm
                                    frb += mm; frb_p.extend(pages)

                        file_details.append({
                            "name": name, "total": total,
                            "formats": dict(ff),
                            "pages": {k: sorted(v) for k, v in fp.items()},
                            "roll_bw": frb, "roll_color": frc,
                            "roll_bw_pages": sorted(frb_p),
                            "roll_color_pages": sorted(frc_p),
                        })
                except Exception as e:
                    self.error.emit(f"Ошибка при обработке {pdf_path}: {str(e)}")
                    continue

            if self._stop_requested:
                self.finished.emit(dict(grand), total_source,
                                   file_page_counts, file_details)
                self.stopped.emit()
            else:
                self.progress.emit(100)
                self.finished.emit(dict(grand), total_source,
                                   file_page_counts, file_details)
        except Exception as e:
            self.error.emit(f"Критическая ошибка: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно
# ─────────────────────────────────────────────────────────────────────────────

class PrintingCalculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Калькулятор расчёта проектной документации")
        self.setGeometry(100, 100, 1200, 700)

        self.primary_color = "#0066cc"
        self.danger_color  = "#d33"
        self.bg_color      = "#f5f6f7"
        self.card_color    = "#ffffff"

        self.apply_style()

        self.grand = {}
        self.total_source = 0
        self.file_page_counts = []
        self.file_details = []
        self.selected_path = ""
        self.copies = 1
        self.force_bw = False

        self.need_folding_a4 = False
        self.need_folding_a3 = False
        self.need_binding_a4 = False
        self.need_binding_a3 = False

        self.thread = None
        self.current_dialog = None
        self.init_ui()

    def apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color: {self.bg_color}; }}
            QTabWidget::pane {{ border: 1px solid #ddd; background-color: {self.bg_color}; }}
            QTabBar::tab {{
                background-color: #e8e8e8; padding: 8px 20px;
                margin-right: 2px; border: 1px solid #ddd;
                color: #333; font-weight: bold;
            }}
            QTabBar::tab:selected {{ background-color: {self.primary_color}; color: white; }}
            QFrame {{
                background-color: {self.card_color};
                border-radius: 4px; border: 1px solid #e0e0e0;
            }}
            QGroupBox {{
                background-color: {self.card_color}; border: 1px solid #d0d0d0;
                border-radius: 6px; margin-top: 8px; padding-top: 4px;
                font-weight: bold; color: #333;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 6px; }}
            QPushButton {{
                background-color: {self.primary_color}; color: white;
                border: none; padding: 8px 16px; border-radius: 4px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #0052a3; }}
            QPushButton:pressed {{ background-color: #003d7a; }}
            QPushButton:disabled {{ background-color: #bbb; color: #eee; }}
            QLabel {{ color: #333; }}
            QLineEdit {{
                background-color: white; border: 1px solid #ccc;
                border-radius: 4px; padding: 4px 6px; color: #333;
            }}
            QTextEdit {{ background-color: {self.card_color}; border: 1px solid #e0e0e0; border-radius: 4px; }}
            QSpinBox {{ background-color: {self.card_color}; color: #333; }}
            QRadioButton {{
                background-color: {self.card_color}; color: #333;
                padding: 4px 12px; font-weight: normal;
            }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QRadioButton::indicator:unchecked {{ background-color: white; border: 2px solid #ccc; border-radius: 9px; }}
            QRadioButton::indicator:checked {{ background-color: {self.primary_color}; border: 2px solid {self.primary_color}; border-radius: 9px; }}
            QRadioButton:disabled {{ color: #aaa; }}
            QRadioButton::indicator:disabled {{ background-color: #eee; border: 2px solid #ddd; }}
        """)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(10, 10, 10, 10)
        ml.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_input_tab(),   "📁 ВВОД")
        self.tabs.addTab(self.create_details_tab(), "📊 2")
        self.tabs.addTab(self.create_manager_tab(), "👔 4")
        self.tabs.addTab(self.create_report_tab(),  "📄 3")
        ml.addWidget(self.tabs)

    def create_input_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Выбор пути
        file_frame = QFrame()
        fl = QVBoxLayout(file_frame)
        lbl = QLabel("📁 Выберите PDF файл или папку:")
        lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        fl.addWidget(lbl)
        row = QHBoxLayout()
        self.label_path = QLabel("Путь не выбран")
        self.label_path.setStyleSheet("color: #666; padding: 5px;")
        row.addWidget(self.label_path)
        btn_browse = QPushButton("📂 Обзор...")
        btn_browse.clicked.connect(self.browse_path)
        row.addWidget(btn_browse)
        fl.addLayout(row)
        layout.addWidget(file_frame)

        # Цветность
        color_frame = QFrame()
        cl = QVBoxLayout(color_frame)
        lbl_ct = QLabel("🎨 Цветность:")
        lbl_ct.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        cl.addWidget(lbl_ct)

        color_row = QHBoxLayout()
        self.rb_color_auto = QRadioButton("По файлу")
        self.rb_color_bw   = QRadioButton("Ч/б")
        self.rb_color_auto.setChecked(True)
        self.color_mode_group = QButtonGroup(self)
        self.color_mode_group.addButton(self.rb_color_auto)
        self.color_mode_group.addButton(self.rb_color_bw)
        color_row.addWidget(self.rb_color_auto)
        color_row.addWidget(self.rb_color_bw)
        color_row.addStretch()
        cl.addLayout(color_row)

        hint = QLabel("«По файлу» — анализ цвета каждой страницы.  "
                       "«Ч/б» — всё считается чёрно-белым.")
        hint.setStyleSheet("color: #666; font-size: 10px;")
        hint.setWordWrap(True)
        cl.addWidget(hint)
        layout.addWidget(color_frame)

        # Параметры
        params_frame = QFrame()
        pl = QVBoxLayout(params_frame)
        lbl2 = QLabel("⚙️ Параметры:")
        lbl2.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        pl.addWidget(lbl2)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Количество экземпляров:"))
        self.spinbox_copies = NoScrollSpinBox()
        self.spinbox_copies.setMinimum(1)
        self.spinbox_copies.setMaximum(100)
        self.spinbox_copies.setValue(1)
        self.spinbox_copies.setFixedWidth(80)
        self.spinbox_copies.valueChanged.connect(self.on_params_changed)
        row2.addWidget(self.spinbox_copies)
        row2.addStretch()
        pl.addLayout(row2)

        # Брошюровка
        bl = QLabel("📌 Брошюровка на пластиковую пружину:")
        bl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        pl.addWidget(bl)

        br = QHBoxLayout()
        self.rb_binding_none = QRadioButton("Не нужна")
        self.rb_binding_a4   = QRadioButton("A4")
        self.rb_binding_a3   = QRadioButton("A3")
        self.rb_binding_none.setChecked(True)
        self.binding_group = QButtonGroup(self)
        self.binding_group.addButton(self.rb_binding_none)
        self.binding_group.addButton(self.rb_binding_a4)
        self.binding_group.addButton(self.rb_binding_a3)
        br.addWidget(self.rb_binding_none)
        br.addWidget(self.rb_binding_a4)
        br.addWidget(self.rb_binding_a3)
        br.addStretch()
        pl.addLayout(br)

        # Фальцовка
        fll = QLabel("📋 Фальцовка:")
        fll.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        pl.addWidget(fll)

        fr = QHBoxLayout()
        self.rb_folding_none = QRadioButton("Не нужна")
        self.rb_folding_a4   = QRadioButton("Под A4")
        self.rb_folding_a3   = QRadioButton("Под A3")
        self.rb_folding_none.setChecked(True)
        self.folding_group = QButtonGroup(self)
        self.folding_group.addButton(self.rb_folding_none)
        self.folding_group.addButton(self.rb_folding_a4)
        self.folding_group.addButton(self.rb_folding_a3)
        fr.addWidget(self.rb_folding_none)
        fr.addWidget(self.rb_folding_a4)
        fr.addWidget(self.rb_folding_a3)
        fr.addStretch()
        pl.addLayout(fr)

        self.binding_group.buttonClicked.connect(self.on_binding_changed)
        self.folding_group.buttonClicked.connect(self.on_params_changed)
        layout.addWidget(params_frame)

        # Прогресс
        prog_frame = QFrame()
        prl = QVBoxLayout(prog_frame)
        lbl3 = QLabel("Статус анализа:")
        lbl3.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        prl.addWidget(lbl3)
        self.label_status = QLabel("Готово")
        prl.addWidget(self.label_status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{ border: 1px solid #ddd; border-radius: 4px; text-align: center; height: 25px; }}
            QProgressBar::chunk {{ background-color: {self.primary_color}; }}
        """)
        prl.addWidget(self.progress_bar)
        layout.addWidget(prog_frame)

        # Кнопки
        btn_row = QHBoxLayout()
        self.btn_analyze = QPushButton("▶️ НАЧАТЬ АНАЛИЗ")
        self.btn_analyze.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.btn_analyze.setMinimumHeight(50)
        self.btn_analyze.clicked.connect(self.start_analysis)
        btn_row.addWidget(self.btn_analyze, stretch=3)

        self.btn_stop = QPushButton("⏹ СТОП")
        self.btn_stop.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{ background-color: {self.danger_color}; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #a00; }}
            QPushButton:pressed {{ background-color: #800; }}
            QPushButton:disabled {{ background-color: #ddd; color: #999; }}
        """)
        self.btn_stop.clicked.connect(self.stop_analysis)
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_stop, stretch=1)
        layout.addLayout(btn_row)

        layout.addStretch()
        return widget

    def on_binding_changed(self):
        if self.rb_binding_a4.isChecked():
            self.rb_folding_a4.setChecked(True)
            for rb in (self.rb_folding_none, self.rb_folding_a3, self.rb_folding_a4):
                rb.setEnabled(False)
        elif self.rb_binding_a3.isChecked():
            self.rb_folding_a3.setChecked(True)
            for rb in (self.rb_folding_none, self.rb_folding_a4, self.rb_folding_a3):
                rb.setEnabled(False)
        else:
            for rb in (self.rb_folding_none, self.rb_folding_a4, self.rb_folding_a3):
                rb.setEnabled(True)
        self.on_params_changed()

    def create_details_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        lbl = QLabel("📊 Детализация по файлам (1 экз., с номерами страниц):")
        lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(lbl)
        self.text_details = QTextEdit()
        self.text_details.setReadOnly(True)
        self.text_details.setFont(QFont("Consolas", 9))
        layout.addWidget(self.text_details)
        return widget

    def create_manager_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sc = QWidget()
        sl = QVBoxLayout(sc)
        sl.setSpacing(15)

        def make_block(title, attr, min_h=80):
            frame = QFrame()
            fl_ = QVBoxLayout(frame)
            fl_.setContentsMargins(10, 10, 10, 10)
            lb = QLabel(title)
            lb.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            fl_.addWidget(lb)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setSizePolicy(te.sizePolicy().horizontalPolicy(),
                             te.sizePolicy().Policy.Fixed)
            te.setMinimumHeight(min_h)
            fl_.addWidget(te)
            setattr(self, attr, te)
            return frame

        sl.addWidget(make_block("🖨️ Печать (с конвертацией, с учётом экземпляров):", "text_printing", 120))
        sl.addWidget(make_block("🌀 Рулонная печать:", "text_roll", 80))
        sl.addWidget(make_block("📋 Фальцовка:", "text_folding", 120))
        sl.addWidget(make_block("📌 Брошюровка:", "text_binding", 80))

        total_frame = QFrame()
        tl = QVBoxLayout(total_frame)
        self.label_total = QLabel("⚖️ Вес: —")
        self.label_total.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.label_total.setStyleSheet(f"color: {self.primary_color};")
        tl.addWidget(self.label_total)
        sl.addWidget(total_frame)

        sl.addStretch()
        scroll.setWidget(sc)
        layout.addWidget(scroll)
        return widget

    def create_report_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        lbl = QLabel("📄 Полный отчет:")
        lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(lbl)
        self.text_report = QTextEdit()
        self.text_report.setReadOnly(True)
        self.text_report.setFont(QFont("Courier", 9))
        layout.addWidget(self.text_report)
        btn_copy = QPushButton("📋 Копировать в буфер обмена")
        btn_copy.setMinimumHeight(40)
        btn_copy.clicked.connect(self.copy_report)
        layout.addWidget(btn_copy)
        return widget

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку с PDF файлами")
        if path:
            self.selected_path = path
            self.label_path.setText(f"✓ {path}")

    def on_params_changed(self):
        self.copies = self.spinbox_copies.value()
        self.need_folding_a4 = self.rb_folding_a4.isChecked()
        self.need_folding_a3 = self.rb_folding_a3.isChecked()
        self.need_binding_a4 = self.rb_binding_a4.isChecked()
        self.need_binding_a3 = self.rb_binding_a3.isChecked()
        self.calculate_and_display()

    def start_analysis(self):
        if not self.selected_path:
            self.label_status.setText("❌ Выберите папку или файл")
            return
        if not os.path.exists(self.selected_path):
            self.label_status.setText("❌ Путь не существует")
            return

        if self.selected_path.lower().endswith(".pdf"):
            pdfs = [self.selected_path]
        else:
            pdfs = [os.path.join(r, f) for r, _, fs in os.walk(self.selected_path)
                    for f in fs if f.lower().endswith(".pdf")]

        if not pdfs:
            self.label_status.setText("❌ PDF файлы не найдены")
            return

        self.force_bw = self.rb_color_bw.isChecked()
        self.grand = {}
        self.total_source = 0
        self.file_page_counts = []
        self.file_details = []
        self.label_status.setText("⏳ Идет анализ...")
        self.progress_bar.setValue(0)
        self.btn_analyze.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.thread = AnalysisThread(pdfs, force_bw=self.force_bw)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.need_user_input.connect(self.show_unknown_format_dialog)
        self.thread.finished.connect(self.analysis_finished)
        self.thread.error.connect(self.analysis_error)
        self.thread.stopped.connect(self.analysis_stopped)
        self.thread.start()

    def stop_analysis(self):
        if self.thread is None or not self.thread.isRunning():
            return
        self.label_status.setText("⏹ Останавливаю анализ...")
        self.btn_stop.setEnabled(False)
        if self.current_dialog is not None:
            try:
                self.current_dialog.result_action = "skip"
                self.current_dialog.result_value = None
                self.current_dialog.reject()
            except Exception:
                pass
            self.current_dialog = None
        self.thread.request_stop()

    def show_unknown_format_dialog(self, w, h, color, pages, pdf_path):
        if self.thread is not None and self.thread._stop_requested:
            self.thread.set_user_response("skip", None)
            return
        dlg = UnknownFormatDialog(w, h, color, pages, pdf_path, parent=self)
        self.current_dialog = dlg
        dlg.exec()
        self.current_dialog = None
        self.thread.set_user_response(dlg.result_action, dlg.result_value)

    def update_progress(self, v):
        self.progress_bar.setValue(v)

    def update_status(self, s):
        self.label_status.setText(f"⏳ {s}")

    def analysis_finished(self, grand, total_source, fpc, fd):
        self.grand = grand
        self.total_source = total_source
        self.file_page_counts = fpc
        self.file_details = fd
        if self.thread is None or not self.thread._stop_requested:
            self.label_status.setText("✅ Анализ завершен")
            self.progress_bar.setValue(100)
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.display_details()
        self.calculate_and_display()

    def analysis_stopped(self):
        self.label_status.setText("⏹ Анализ остановлен пользователем")
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def analysis_error(self, error):
        self.label_status.setText(f"❌ {error}")
        self.btn_analyze.setEnabled(True)
        self.btn_stop.setEnabled(False)

    # ── Вспомогательные ───────────────────────────────────────────────────

    def _pfk(self, key):
        if key.endswith(" ч/б"):   return key[:-4], "ч/б"
        if key.endswith(" цвет"):  return key[:-5], "цвет"
        return None, None

    def _gfs(self, fmt):
        return ISO_A.get(fmt) or ISO_A_NONSTANDARD.get(fmt)

    def _autosize(self, te, minh=80, maxh=2000):
        d = te.document()
        d.setTextWidth(te.viewport().width())
        h = max(minh, min(int(d.size().height() + 10), maxh))
        te.setFixedHeight(h)

    def _build_print_summary(self):
        c = self.copies
        st = defaultdict(int)
        di = defaultdict(list)
        erb = 0.0
        erc = 0.0

        for fmt in ISO_A:
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    st[(fmt, kind)] += cnt * c

        for src, (tgt, div) in CONVERSION_RULES.items():
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{src} {kind}", 0))
                if cnt > 0:
                    sq = cnt * c
                    add = math.ceil(sq / div)
                    st[(tgt, kind)] += add
                    di[(tgt, kind)].append((src, sq, add))

        ps = set(CONVERSION_RULES.keys())
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

    def _calc_folding(self, target):
        sl, nl, tf = [], [], 0
        if target == "A4":
            sf = ["A3", "A2", "A1", "A0"]; ex = {"A4"}
        elif target == "A3":
            sf = ["A2", "A1", "A0"]; ex = {"A4", "A3"}
        else:
            return sl, nl, tf

        for fmt in sf:
            qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                   int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
            if qty > 0:
                sl.append(f"{fmt} → {target} — {qty} шт."); tf += qty

        for fmt in ISO_A_NONSTANDARD:
            qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                   int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
            if qty > 0:
                nl.append(f"{fmt} → {target} — {qty} шт."); tf += qty

        ct = defaultdict(int)
        for k in self.grand:
            if k.startswith("Рулон"): continue
            fmt, kind = self._pfk(k)
            if not fmt or fmt in ex or fmt in ISO_A or fmt in ISO_A_NONSTANDARD: continue
            ct[fmt] += int(self.grand.get(k, 0))
        for fmt in sorted(ct):
            qty = ct[fmt] * self.copies
            if qty > 0:
                nl.append(f"{fmt} → {target} — {qty} шт."); tf += qty

        return sl, nl, tf

    def _calc_binding(self):
        bl, tb = [], 0
        if not self.file_page_counts:
            return bl, tb
        thrs = [30, 70, 110, 170, 220, 280, 400, 470]
        bins = defaultdict(int)
        for pc in self.file_page_counts:
            for t in thrs:
                if pc <= t:
                    bins[t] += 1; break
            else:
                bins[thrs[-1]] += 1
        for t in thrs:
            if bins[t] > 0:
                q = bins[t] * self.copies
                bl.append(f"До {t} стр. — {q} шт."); tb += q
        return bl, tb

    def _fw(self, g):
        return f"{g / 1000:.2f} кг"

    def _calc_weight(self, st, rbm, rcm, bt, tb):
        total = 0.0
        for fmt in FMT_ORDER:
            sz = ISO_A.get(fmt)
            if not sz: continue
            wps = sz[0] * sz[1] * PAPER_DENSITY_G_PER_MM2
            qty = sum(st.get((fmt, k), 0) for k in KIND_ORDER)
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
        if not self.file_details:
            self.text_details.setText("Нет данных. Сначала проведите анализ.")
            return
        lines = []
        for fd in self.file_details:
            lines.append(f"📄 {fd['name']}  ({fd['total']} стр.)")
            fmts = fd.get("formats", {})
            pm = fd.get("pages", {})

            def sk(item):
                f, k = self._pfk(item[0])
                if f in FMT_ORDER: return (0, FMT_ORDER.index(f), k or "")
                if f in ISO_A_NONSTANDARD: return (1, list(ISO_A_NONSTANDARD).index(f), k or "")
                return (2, f or "", k or "")

            for k, cnt in sorted(fmts.items(), key=sk):
                f, kn = self._pfk(k)
                if not f: continue
                rng = compact_page_list(pm.get(k, []))
                sz = self._gfs(f)
                ss = f" ({sz[0]}×{sz[1]} мм)" if sz else ""
                if rng:
                    lines.append(f"    {f} {kn}{ss} — {cnt} стр. ({rng})")
                else:
                    lines.append(f"    {f} {kn}{ss} — {cnt} стр.")

            for label, pk, mk in [("Рулон ч/б", "roll_bw_pages", "roll_bw"),
                                   ("Рулон цвет", "roll_color_pages", "roll_color")]:
                rp = fd.get(pk, [])
                rm = fd.get(mk, 0)
                if rp or rm > 0:
                    rng = compact_page_list(rp)
                    line = f"    {label} — {rm:.0f} мм"
                    if rng: line += f" ({rng})"
                    lines.append(line)
            lines.append("")
        self.text_details.setText("\n".join(lines).rstrip())

    def calculate_and_display(self):
        if not self.grand:
            return
        self.display_details()
        st, di, erb, erc = self._build_print_summary()

        # Печать
        pl, tpp = [], 0
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                t = st.get((fmt, kind), 0)
                if t <= 0: continue
                line = f"{fmt} {kind} ({fw}×{fh} мм) — {t} стр."
                if di.get((fmt, kind)):
                    parts = [f"из {s}: {sq}→{a}" for s, sq, a in di[(fmt, kind)]]
                    line += "  [" + ", ".join(parts) + "]"
                pl.append(line); tpp += t
        self.text_printing.setText("\n".join(pl) if pl else "Нет данных для печати")

        # Рулон
        rl = []
        rbt = self.grand.get("Рулон ч/б мм", 0) * self.copies + erb
        rct = self.grand.get("Рулон цвет мм", 0) * self.copies + erc
        if rbt > 0: rl.append(f"Ч/б — {rbt:.0f} мм ({rbt / 1000:.2f} м)")
        if rct > 0: rl.append(f"Цвет — {rct:.0f} мм ({rct / 1000:.2f} м)")
        self.text_roll.setText("\n".join(rl) if rl else "Рулонная печать не требуется")

        # Фальцовка
        ftp, tf, ft = [], 0, None
        slr, nlr = [], []
        if self.need_folding_a4: ft = "A4"
        elif self.need_folding_a3: ft = "A3"
        if ft:
            slr, nlr, tf = self._calc_folding(ft)
            ftp.append(f"Фальцовка под {ft}"); ftp.append("")
            if slr: ftp.append("Стандартные форматы:"); ftp.extend(slr)
            if nlr:
                if slr: ftp.append("")
                ftp.append("Нестандартные форматы:"); ftp.extend(nlr)
        self.text_folding.setText("\n".join(ftp) if ftp else "Фальцовка не требуется")

        # Брошюровка
        blines, tb, bt = [], 0, None
        if self.need_binding_a4:
            bt = "A4"; blines, tb = self._calc_binding()
        elif self.need_binding_a3:
            bt = "A3"; blines, tb = self._calc_binding()
        if bt:
            bt_parts = [f"Брошюровка на пружину {bt}", ""]
            bt_parts.extend(blines if blines else ["Нет данных"])
            self.text_binding.setText("\n".join(bt_parts))
        else:
            self.text_binding.setText("Брошюровка не требуется")

        # Вес
        tw = self._calc_weight(st, rbt, rct, bt, tb)
        self.label_total.setText(f"⚖️ Вес: {self._fw(tw) if tw > 0 else '0.00 кг'}")

        QTimer.singleShot(0, lambda: self._autosize(self.text_printing, 120))
        QTimer.singleShot(0, lambda: self._autosize(self.text_roll, 80))
        QTimer.singleShot(0, lambda: self._autosize(self.text_folding, 120))
        QTimer.singleShot(0, lambda: self._autosize(self.text_binding, 80))

        self._build_report(ft, slr, nlr, tf, bt, blines, tb, tw)

    def _build_report(self, ft, fs, fn, tf, bt, bl, tb, tw):
        c = self.copies
        tpr = 0

        sb = []
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    q = cnt * c; sb.append(f"{fmt} {kind} ({fw}×{fh} мм) — {q} стр."); tpr += q

        nb = []
        for fmt, (fw, fh) in ISO_A_NONSTANDARD.items():
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    q = cnt * c; nb.append(f"{fmt} {kind} ({fw}×{fh} мм) — {q} стр."); tpr += q

        cb = []
        for k in self.grand:
            if k.startswith("Рулон"): continue
            fmt, kind = self._pfk(k)
            if not fmt or not kind or fmt in ISO_A or fmt in ISO_A_NONSTANDARD: continue
            cnt = int(self.grand.get(k, 0))
            if cnt > 0:
                q = cnt * c; cb.append(f"{fmt} {kind} — {q} стр."); tpr += q

        rbr = self.grand.get("Рулон ч/б мм", 0) * c
        rcr = self.grand.get("Рулон цвет мм", 0) * c
        cms = "Ч/б (принудительно)" if self.force_bw else "По файлу"

        lines = [
            "=" * 60, "АНАЛИЗ ПРОЕКТНОЙ ДОКУМЕНТАЦИИ", "=" * 60,
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Всего страниц в источнике: {self.total_source}",
            f"Количество экземпляров: {c}",
            f"Режим цветности: {cms}", "",
            "ПЕЧАТЬ (исходные форматы × экземпляры):",
        ]

        if sb: lines.append("• Стандартные форматы:"); lines.extend(f"  {l}" for l in sb)
        if nb:
            if sb: lines.append("")
            lines.append("• Расширенные форматы:"); lines.extend(f"  {l}" for l in nb)
        if cb:
            if sb or nb: lines.append("")
            lines.append("• Произвольные форматы:"); lines.extend(f"  {l}" for l in cb)
        if not (sb or nb or cb): lines.append("Нет данных")
        lines.append(f"Итого страниц: {tpr}"); lines.append("")

        if ft:
            lines.append(f"ФАЛЬЦОВКА ПОД {ft}:")
            if fs: lines.append("• Стандартные форматы:"); lines.extend(f"  {l}" for l in fs)
            if fn:
                if fs: lines.append("")
                lines.append("• Нестандартные форматы:"); lines.extend(f"  {l}" for l in fn)
            if not (fs or fn): lines.append("Не требуется")
            lines.append(f"Итого листов: {tf}"); lines.append("")

        if bt:
            lines.append(f"БРОШЮРОВКА НА ПРУЖИНУ {bt}:")
            if bl: lines.append("• По количеству страниц:"); lines.extend(f"  {l}" for l in bl)
            else: lines.append("Не требуется")
            lines.append(f"Итого брошюр: {tb}"); lines.append("")

        if rbr > 0 or rcr > 0:
            lines.append("РУЛОННАЯ ПЕЧАТЬ:")
            if rbr > 0: lines.append(f"  Ч/б — {rbr:.0f} мм ({rbr / 1000:.2f} м)")
            if rcr > 0: lines.append(f"  Цвет — {rcr:.0f} мм ({rcr / 1000:.2f} м)")
            lines.append("")

        lines.append("─" * 60)
        lines.append(f"ВЕС: {self._fw(tw)}")
        lines.append("=" * 60)
        self.text_report.setText("\n".join(lines))

    def copy_report(self):
        try:
            import pyperclip
            pyperclip.copy(self.text_report.toPlainText())
        except Exception:
            try:
                p = subprocess.Popen(['clip'], stdin=subprocess.PIPE, shell=True)
                p.communicate(self.text_report.toPlainText().encode('utf-8'))
            except Exception:
                pass
        self.label_status.setText("✅ Отчет скопирован в буфер обмена")

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            self.thread.request_stop()
            self.thread.wait(2000)
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)

    # 1. Лицензия
    ok, msg = check_remote_license()
    if not ok:
        QMessageBox.critical(None, "Доступ запрещён", msg)
        sys.exit(1)

    # 2. ОБНОВЛЕНИЕ (обязательное для .exe, автоматическое)
    if getattr(sys, "frozen", False):
        try:
            has_update, latest_ver, dl_url = check_for_update()
            if has_update:
                # Принудительное обновление — выбора нет
                upd_dlg = UpdateDialog(latest_ver, dl_url)
                upd_dlg.exec()
                # Сюда не придём, т.к. вызов sys.exit() внутри диалога
        except Exception as e:
            print(f"[UPDATE] Ошибка: {e}")
            QMessageBox.warning(None, "Обновление",
                "Не удалось проверить обновления.\n"
                "Программа продолжит работу со старой версией.")
            # Не выходим — работаем дальше

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