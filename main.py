import os
import sys
import time
import io
import math
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime

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
BINDING_WEIGHT_G = {
    "A4": 60.0,
    "A3": 90.0,
}

FMT_ORDER = ["A4", "A3", "A2", "A1", "A0"]
KIND_ORDER = ["ч/б", "цвет"]

# ─────────────────────────────────────────────────────────────────────────────
# Конфигурация авторизации и удалённого контроля
# ─────────────────────────────────────────────────────────────────────────────

# Хеши логина и пароля (SHA-256)
# login: Admin   password: 1qwer432
VALID_LOGIN_HASH = hashlib.sha256("admin".encode()).hexdigest()
VALID_PASSWORD_HASH = hashlib.sha256("1qwer432".encode()).hexdigest()

# URL для проверки лицензии (GitHub Gist raw-ссылка)
# Создайте Gist на https://gist.github.com с содержимым: ACTIVE
# Замените URL ниже на ваш raw-URL
LICENSE_CHECK_URL = "https://gist.githubusercontent.com/fabilya/d460ac938145cd8d99f261c250f90255/raw/gistfile1.txt"  # ← вставьте сюда ваш URL

# Ключ, который должен быть в ответе для разрешения работы
LICENSE_ACTIVE_KEY = "ACTIVE"


# ─────────────────────────────────────────────────────────────────────────────
# SpinBox без прокрутки колёсиком
# ─────────────────────────────────────────────────────────────────────────────

class NoScrollSpinBox(QSpinBox):
    """SpinBox, который игнорирует прокрутку колёсиком мыши."""

    def wheelEvent(self, event):
        event.ignore()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.setReadOnly(False)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Диалог авторизации
# ─────────────────────────────────────────────────────────────────────────────

class LoginDialog(QDialog):
    """Окно входа с логином и паролем."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Авторизация")
        self.setFixedSize(400, 280)
        self.setModal(True)
        self.authenticated = False

        # Запрещаем закрытие крестиком без авторизации
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint
        )

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        # Заголовок
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

        # Логин
        self.edit_login = QLineEdit()
        self.edit_login.setPlaceholderText("Логин")
        self.edit_login.setFont(QFont("Arial", 11))
        self.edit_login.setMinimumHeight(36)
        self.edit_login.setStyleSheet("""
            QLineEdit {
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 6px;
                padding: 6px 12px;
                color: #333;
            }
            QLineEdit:focus {
                border: 2px solid #0066cc;
            }
        """)
        layout.addWidget(self.edit_login)

        # Пароль
        self.edit_password = QLineEdit()
        self.edit_password.setPlaceholderText("Пароль")
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_password.setFont(QFont("Arial", 11))
        self.edit_password.setMinimumHeight(36)
        self.edit_password.setStyleSheet("""
            QLineEdit {
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 6px;
                padding: 6px 12px;
                color: #333;
            }
            QLineEdit:focus {
                border: 2px solid #0066cc;
            }
        """)
        self.edit_password.returnPressed.connect(self._try_login)
        layout.addWidget(self.edit_password)

        # Сообщение об ошибке
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: red; font-size: 11px;")
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_error)

        # Кнопка
        btn = QPushButton("Войти")
        btn.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        btn.setMinimumHeight(40)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #0066cc;
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0052a3; }
            QPushButton:pressed { background-color: #003d7a; }
        """)
        btn.clicked.connect(self._try_login)
        layout.addWidget(btn)

        # Кнопка «Выход»
        btn_exit = QPushButton("Выход")
        btn_exit.setFont(QFont("Arial", 10))
        btn_exit.setMinimumHeight(32)
        btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #999;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #777; }
        """)
        btn_exit.clicked.connect(self._exit_app)
        layout.addWidget(btn_exit)

        self.setStyleSheet("QDialog { background-color: #f5f6f7; }")

    # В методе LoginDialog._try_login:

    def _try_login(self):
        login = self.edit_login.text().strip()
        password = self.edit_password.text().strip()

        login_hash = hashlib.sha256(login.lower().encode()).hexdigest()  # ← .lower()
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        if login_hash == VALID_LOGIN_HASH and password_hash == VALID_PASSWORD_HASH:
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
            self.authenticated = False
            self.reject()
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Проверка удалённой лицензии
# ─────────────────────────────────────────────────────────────────────────────

def check_remote_license():
    """
    Проверяет удалённый файл лицензии.
    Возвращает (ok: bool, message: str).
    Если URL не задан — пропускает проверку (для отладки).
    """
    if not LICENSE_CHECK_URL:
        return True, ""

    try:
        # Добавляем метку времени, чтобы обойти кэширование GitHub
        separator = "&" if "?" in LICENSE_CHECK_URL else "?"
        url_no_cache = f"{LICENSE_CHECK_URL}{separator}nocache={int(time.time())}"

        req = urllib.request.Request(url_no_cache, method="GET")
        req.add_header("User-Agent", "PrintCalc/1.0")
        req.add_header("Cache-Control", "no-cache, no-store, must-revalidate")
        req.add_header("Pragma", "no-cache")
        req.add_header("Expires", "0")

        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8").strip()
            if LICENSE_ACTIVE_KEY in content:
                return True, ""
            else:
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
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def compact_page_list(pages):
    if not pages:
        return ""
    pages = sorted(pages)
    ranges = []
    start = pages[0]
    end = pages[0]
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
            for page_num in self.pages:
                src_page = src[page_num - 1]
                new_page = dst.new_page(
                    -1, width=src_page.rect.width, height=src_page.rect.height
                )
                new_page.show_pdf_page(new_page.rect, src, page_num - 1)

            base_name = os.path.splitext(os.path.basename(self.pdf_path))[0]
            ranges = compact_page_list(self.pages).replace(", ", "_")
            temp_name = f"{base_name}__стр_{ranges}.pdf"
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, temp_name)

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    stamp = datetime.now().strftime("%H%M%S")
                    temp_path = os.path.join(
                        temp_dir, f"{base_name}__стр_{ranges}_{stamp}.pdf"
                    )

            dst.save(temp_path)
            dst.close()
            src.close()
            self._temp_file = temp_path

            if sys.platform == "win32":
                os.startfile(temp_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", temp_path])
            else:
                subprocess.Popen(["xdg-open", temp_path])
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка", f"Не удалось открыть страницы:\n{str(e)}"
            )

    def _apply_format(self):
        raw = self.edit_format.text().strip()
        if not raw:
            QMessageBox.warning(self, "Ошибка", "Введите название формата.")
            return

        def normalize(s):
            return s.upper().replace("А", "A").replace("Х", "X").replace(" ", "")

        user_norm = normalize(raw)
        matched_key = None
        for key in list(ISO_A.keys()) + list(ISO_A_NONSTANDARD.keys()):
            if normalize(key) == user_norm:
                matched_key = key
                break

        if matched_key is None:
            reply = QMessageBox.question(
                self, "Неизвестный формат",
                f'Формат "{raw}" не найден в списке.\nВсё равно использовать?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            matched_key = user_norm

        self.result_action = "format"
        self.result_value = matched_key
        self.accept()

    def _apply_roll(self):
        text = self.edit_roll.text().strip().replace(",", ".")
        try:
            val = float(text)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Введите числовое значение.")
            return
        if val <= 0:
            QMessageBox.warning(self, "Ошибка", "Значение должно быть больше 0.")
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

    def detect_page_color(self, page, tol=5, white_thr=245,
                          min_colored_pixels=50, min_colored_ratio=0.002):
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
            ink = mx < white_thr
            ink_count = int(ink.sum())
            if ink_count == 0:
                return False
            colored = ink & ((mx - mn) > tol)
            colored_count = int(colored.sum())
            return (colored_count >= min_colored_pixels and
                    (colored_count / ink_count) >= min_colored_ratio)
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

                        file_formats = defaultdict(int)
                        file_pages = defaultdict(list)
                        file_roll_bw = 0.0
                        file_roll_color = 0.0
                        file_roll_bw_pages = []
                        file_roll_color_pages = []
                        custom_groups = defaultdict(list)

                        for i, p in enumerate(doc):
                            if self._stop_requested:
                                break
                            page_num = i + 1
                            r = p.mediabox
                            w, h = sorted((
                                round(r.width * 25.4 / 72, 1),
                                round(r.height * 25.4 / 72, 1)
                            ))

                            if self.force_bw:
                                col = False
                            else:
                                col = self.detect_page_color(p)

                            fA = self.match_format_with_tolerance(w, h, ISO_A)
                            fN = self.match_format_with_tolerance(w, h, ISO_A_NONSTANDARD)

                            if fA:
                                key = f"{fA} {'цвет' if col else 'ч/б'}"
                                grand[key] += 1
                                file_formats[key] += 1
                                file_pages[key].append(page_num)
                            elif fN:
                                key = f"{fN} {'цвет' if col else 'ч/б'}"
                                grand[key] += 1
                                file_formats[key] += 1
                                file_pages[key].append(page_num)
                            else:
                                custom_groups[(w, h, col)].append(page_num)

                            prog = int(
                                100 * (file_idx + (i + 1) / total) / total_files
                            )
                            self.progress.emit(prog)
                            time.sleep(0.001)

                        if self._stop_requested:
                            file_details.append({
                                "name": name, "total": total,
                                "formats": dict(file_formats),
                                "pages": {k: sorted(v) for k, v in file_pages.items()},
                                "roll_bw": file_roll_bw,
                                "roll_color": file_roll_color,
                                "roll_bw_pages": sorted(file_roll_bw_pages),
                                "roll_color_pages": sorted(file_roll_color_pages),
                            })
                            break

                        for (w, h, col), pages in custom_groups.items():
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
                                file_formats[key] += len(pages)
                                file_pages[key].extend(pages)
                            elif action in ("roll_mm", "roll_auto"):
                                mm_per_page = float(value)
                                mm_total = mm_per_page * len(pages)
                                if col:
                                    grand["Рулон цвет мм"] += mm_total
                                    file_roll_color += mm_total
                                    file_roll_color_pages.extend(pages)
                                else:
                                    grand["Рулон ч/б мм"] += mm_total
                                    file_roll_bw += mm_total
                                    file_roll_bw_pages.extend(pages)

                        file_details.append({
                            "name": name, "total": total,
                            "formats": dict(file_formats),
                            "pages": {k: sorted(v) for k, v in file_pages.items()},
                            "roll_bw": file_roll_bw,
                            "roll_color": file_roll_color,
                            "roll_bw_pages": sorted(file_roll_bw_pages),
                            "roll_color_pages": sorted(file_roll_color_pages),
                        })
                except Exception as e:
                    self.error.emit(f"Ошибка при обработке {pdf_path}: {str(e)}")
                    continue

            if self._stop_requested:
                self.finished.emit(
                    dict(grand), total_source, file_page_counts, file_details
                )
                self.stopped.emit()
            else:
                self.progress.emit(100)
                self.finished.emit(
                    dict(grand), total_source, file_page_counts, file_details
                )
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
            QTabWidget::pane {{
                border: 1px solid #ddd;
                background-color: {self.bg_color};
            }}
            QTabBar::tab {{
                background-color: #e8e8e8;
                padding: 8px 20px;
                margin-right: 2px;
                border: 1px solid #ddd;
                color: #333;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background-color: {self.primary_color};
                color: white;
            }}
            QFrame {{
                background-color: {self.card_color};
                border-radius: 4px;
                border: 1px solid #e0e0e0;
            }}
            QGroupBox {{
                background-color: {self.card_color};
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 4px;
                font-weight: bold;
                color: #333;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }}
            QPushButton {{
                background-color: {self.primary_color};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover   {{ background-color: #0052a3; }}
            QPushButton:pressed {{ background-color: #003d7a; }}
            QPushButton:disabled {{
                background-color: #bbb;
                color: #eee;
            }}
            QLabel    {{ color: #333; }}
            QLineEdit {{
                background-color: white;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 4px 6px;
                color: #333;
            }}
            QTableWidget {{
                background-color: {self.card_color};
                gridline-color: #e0e0e0;
                border: 1px solid #e0e0e0;
            }}
            QTableWidget::item {{ padding: 5px; }}
            QHeaderView::section {{
                background-color: #f0f0f0;
                color: #333;
                padding: 5px;
                border: none;
                font-weight: bold;
            }}
            QTextEdit {{
                background-color: {self.card_color};
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }}
            QSpinBox {{
                background-color: {self.card_color};
                color: #333;
            }}
            QRadioButton {{
                background-color: {self.card_color};
                color: #333;
                padding: 4px 12px;
                font-weight: normal;
            }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QRadioButton::indicator:unchecked {{
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 9px;
            }}
            QRadioButton::indicator:checked {{
                background-color: {self.primary_color};
                border: 2px solid {self.primary_color};
                border-radius: 9px;
            }}
            QRadioButton:disabled {{ color: #aaa; }}
            QRadioButton::indicator:disabled {{
                background-color: #eee;
                border: 2px solid #ddd;
            }}
        """)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_input_tab(),   "📁 Ввод данных")
        self.tabs.addTab(self.create_details_tab(), "📊 Детализация по файлам")
        self.tabs.addTab(self.create_manager_tab(), "👔 Для менеджера")
        self.tabs.addTab(self.create_report_tab(),  "📄 Отчет")
        main_layout.addWidget(self.tabs)

    # ── Вкладка «Ввод данных» ─────────────────────────────────────────────

    def create_input_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── Выбор папки/файла ────────────────────────────────────────────
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

        # ── Цветность ────────────────────────────────────────────────────
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

        lbl_hint = QLabel(
            "«По файлу» — анализ каждой страницы на цвет.  "
            "«Ч/б» — всё считается чёрно-белым без анализа цвета."
        )
        lbl_hint.setStyleSheet("color: #666; font-size: 10px;")
        lbl_hint.setWordWrap(True)
        cl.addWidget(lbl_hint)
        layout.addWidget(color_frame)

        # ── Параметры ────────────────────────────────────────────────────
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

        # ── Брошюровка ───────────────────────────────────────────────────
        binding_lbl = QLabel("📌 Брошюровка на пластиковую пружину:")
        binding_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        pl.addWidget(binding_lbl)

        binding_row = QHBoxLayout()
        self.rb_binding_none = QRadioButton("Не нужна")
        self.rb_binding_a4   = QRadioButton("A4")
        self.rb_binding_a3   = QRadioButton("A3")
        self.rb_binding_none.setChecked(True)

        self.binding_group = QButtonGroup(self)
        self.binding_group.addButton(self.rb_binding_none)
        self.binding_group.addButton(self.rb_binding_a4)
        self.binding_group.addButton(self.rb_binding_a3)

        binding_row.addWidget(self.rb_binding_none)
        binding_row.addWidget(self.rb_binding_a4)
        binding_row.addWidget(self.rb_binding_a3)
        binding_row.addStretch()
        pl.addLayout(binding_row)

        # ── Фальцовка ────────────────────────────────────────────────────
        folding_lbl = QLabel("📋 Фальцовка:")
        folding_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        pl.addWidget(folding_lbl)

        folding_row = QHBoxLayout()
        self.rb_folding_none = QRadioButton("Не нужна")
        self.rb_folding_a4   = QRadioButton("Под A4")
        self.rb_folding_a3   = QRadioButton("Под A3")
        self.rb_folding_none.setChecked(True)

        self.folding_group = QButtonGroup(self)
        self.folding_group.addButton(self.rb_folding_none)
        self.folding_group.addButton(self.rb_folding_a4)
        self.folding_group.addButton(self.rb_folding_a3)

        folding_row.addWidget(self.rb_folding_none)
        folding_row.addWidget(self.rb_folding_a4)
        folding_row.addWidget(self.rb_folding_a3)
        folding_row.addStretch()
        pl.addLayout(folding_row)

        self.binding_group.buttonClicked.connect(self.on_binding_changed)
        self.folding_group.buttonClicked.connect(self.on_params_changed)

        layout.addWidget(params_frame)

        # ── Прогресс ─────────────────────────────────────────────────────
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
            QProgressBar {{
                border: 1px solid #ddd; border-radius: 4px;
                text-align: center; height: 25px;
            }}
            QProgressBar::chunk {{ background-color: {self.primary_color}; }}
        """)
        prl.addWidget(self.progress_bar)
        layout.addWidget(prog_frame)

        # ── Кнопки ───────────────────────────────────────────────────────
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
            QPushButton {{
                background-color: {self.danger_color};
                color: white; border: none;
                padding: 8px 16px; border-radius: 4px; font-weight: bold;
            }}
            QPushButton:hover   {{ background-color: #a00; }}
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
            self.rb_folding_none.setEnabled(False)
            self.rb_folding_a3.setEnabled(False)
            self.rb_folding_a4.setEnabled(False)
        elif self.rb_binding_a3.isChecked():
            self.rb_folding_a3.setChecked(True)
            self.rb_folding_none.setEnabled(False)
            self.rb_folding_a4.setEnabled(False)
            self.rb_folding_a3.setEnabled(False)
        else:
            self.rb_folding_none.setEnabled(True)
            self.rb_folding_a4.setEnabled(True)
            self.rb_folding_a3.setEnabled(True)
        self.on_params_changed()

    # ── Вкладка «Детализация» ─────────────────────────────────────────────

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

    # ── Вкладка «Для менеджера» ───────────────────────────────────────────

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

        def make_block(title, attr, min_height=80):
            frame = QFrame()
            fl_inner = QVBoxLayout(frame)
            fl_inner.setContentsMargins(10, 10, 10, 10)
            lbl_inner = QLabel(title)
            lbl_inner.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            fl_inner.addWidget(lbl_inner)

            te = QTextEdit()
            te.setReadOnly(True)
            te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            te.setSizePolicy(
                te.sizePolicy().horizontalPolicy(),
                te.sizePolicy().Policy.Fixed
            )
            te.setMinimumHeight(min_height)
            fl_inner.addWidget(te)
            setattr(self, attr, te)
            return frame

        sl.addWidget(make_block(
            "🖨️ Печать (с конвертацией нестандартных, с учётом экземпляров):",
            "text_printing", 120
        ))
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

    # ── Вкладка «Отчет» ───────────────────────────────────────────────────

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

    # ── Навигация / параметры ─────────────────────────────────────────────

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку с PDF файлами"
        )
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

    # ── Запуск / остановка ────────────────────────────────────────────────

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
            pdfs = [
                os.path.join(r, f)
                for r, _, fs in os.walk(self.selected_path)
                for f in fs if f.lower().endswith(".pdf")
            ]

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

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, status):
        self.label_status.setText(f"⏳ {status}")

    def analysis_finished(self, grand, total_source, file_page_counts, file_details):
        self.grand = grand
        self.total_source = total_source
        self.file_page_counts = file_page_counts
        self.file_details = file_details

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

    # ── Вспомогательные методы ────────────────────────────────────────────

    def _parse_format_key(self, key):
        if key.endswith(" ч/б"):
            return key[:-4], "ч/б"
        if key.endswith(" цвет"):
            return key[:-5], "цвет"
        return None, None

    def _get_format_size(self, fmt):
        if fmt in ISO_A:
            return ISO_A[fmt]
        if fmt in ISO_A_NONSTANDARD:
            return ISO_A_NONSTANDARD[fmt]
        return None

    def _autosize_textedit(self, textedit, min_height=80, max_height=2000):
        doc = textedit.document()
        doc.setTextWidth(textedit.viewport().width())
        h = int(doc.size().height() + 10)
        h = max(min_height, min(h, max_height))
        textedit.setFixedHeight(h)

    def _build_print_summary_with_copies(self):
        copies = self.copies
        standard_totals   = defaultdict(int)
        derived_info      = defaultdict(list)
        extra_roll_bw_mm  = 0.0
        extra_roll_color_mm = 0.0

        for fmt in ISO_A.keys():
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    standard_totals[(fmt, kind)] += cnt * copies

        for src, (target, div) in CONVERSION_RULES.items():
            for kind in KIND_ORDER:
                src_cnt = int(self.grand.get(f"{src} {kind}", 0))
                if src_cnt > 0:
                    src_qty = src_cnt * copies
                    add = math.ceil(src_qty / div)
                    standard_totals[(target, kind)] += add
                    derived_info[(target, kind)].append((src, src_qty, add))

        processed_sources = set(CONVERSION_RULES.keys())
        for fmt, (fw, fh) in ISO_A_NONSTANDARD.items():
            if fmt in processed_sources:
                continue
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    add_mm = max(fw, fh) * cnt * copies
                    if kind == "цвет":
                        extra_roll_color_mm += add_mm
                    else:
                        extra_roll_bw_mm += add_mm

        return standard_totals, derived_info, extra_roll_bw_mm, extra_roll_color_mm

    def _calculate_folding(self, target_format):
        std_lines = []
        nonstd_lines = []
        total_fold = 0

        if target_format == "A4":
            std_fmts = ["A3", "A2", "A1", "A0"]
            exclude_iso = {"A4"}
        elif target_format == "A3":
            std_fmts = ["A2", "A1", "A0"]
            exclude_iso = {"A4", "A3"}
        else:
            return std_lines, nonstd_lines, total_fold

        for fmt in std_fmts:
            qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                   int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
            if qty > 0:
                std_lines.append(f"{fmt} → {target_format} — {qty} шт.")
                total_fold += qty

        for fmt in ISO_A_NONSTANDARD.keys():
            qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                   int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
            if qty > 0:
                nonstd_lines.append(f"{fmt} → {target_format} — {qty} шт.")
                total_fold += qty

        custom_totals = defaultdict(int)
        for k in self.grand.keys():
            if k.startswith("Рулон"):
                continue
            fmt, kind = self._parse_format_key(k)
            if not fmt:
                continue
            if fmt in exclude_iso or fmt in ISO_A or fmt in ISO_A_NONSTANDARD:
                continue
            custom_totals[fmt] += int(self.grand.get(k, 0))

        for fmt in sorted(custom_totals.keys()):
            qty = custom_totals[fmt] * self.copies
            if qty > 0:
                nonstd_lines.append(f"{fmt} → {target_format} — {qty} шт.")
                total_fold += qty

        return std_lines, nonstd_lines, total_fold

    def _calculate_binding(self):
        binding_lines = []
        total_books = 0
        if not self.file_page_counts:
            return binding_lines, total_books

        thresholds = [30, 70, 110, 170, 220, 280, 400, 470]
        bins = defaultdict(int)
        for pc in self.file_page_counts:
            for thr in thresholds:
                if pc <= thr:
                    bins[thr] += 1
                    break
            else:
                bins[thresholds[-1]] += 1

        for thr in thresholds:
            if bins[thr] > 0:
                qty = bins[thr] * self.copies
                binding_lines.append(f"До {thr} стр. — {qty} шт.")
                total_books += qty
        return binding_lines, total_books

    def _format_weight(self, grams):
        return f"{grams / 1000:.2f} кг"

    def _calculate_weight(self, std_totals, roll_bw_total_mm,
                          roll_color_total_mm, binding_target, total_books):
        total = 0.0
        for fmt in FMT_ORDER:
            size = ISO_A.get(fmt)
            if not size:
                continue
            fw, fh = size
            weight_per_sheet = fw * fh * PAPER_DENSITY_G_PER_MM2
            qty = sum(std_totals.get((fmt, kind), 0) for kind in KIND_ORDER)
            if qty > 0:
                total += weight_per_sheet * qty

        roll_total_mm = roll_bw_total_mm + roll_color_total_mm
        if roll_total_mm > 0:
            total += roll_total_mm * ROLL_WEIGHT_G_PER_MM

        if binding_target and total_books > 0:
            unit = BINDING_WEIGHT_G.get(binding_target, 0)
            if unit > 0:
                total += unit * total_books
        return total

    # ── Детализация ───────────────────────────────────────────────────────

    def display_details(self):
        if not self.file_details:
            self.text_details.setText("Нет данных. Сначала проведите анализ.")
            return

        lines = []
        for fd in self.file_details:
            lines.append(f"📄 {fd['name']}  ({fd['total']} стр.)")
            fmts = fd.get("formats", {})
            pages_map = fd.get("pages", {})

            def sort_key(item):
                fmt, kind = self._parse_format_key(item[0])
                if fmt in FMT_ORDER:
                    return (0, FMT_ORDER.index(fmt), kind or "")
                if fmt in ISO_A_NONSTANDARD:
                    return (1, list(ISO_A_NONSTANDARD.keys()).index(fmt), kind or "")
                return (2, fmt or "", kind or "")

            if fmts:
                for k, count in sorted(fmts.items(), key=sort_key):
                    fmt, kind = self._parse_format_key(k)
                    if not fmt:
                        continue
                    pages = pages_map.get(k, [])
                    ranges = compact_page_list(pages)
                    size = self._get_format_size(fmt)
                    size_str = f" ({size[0]}×{size[1]} мм)" if size else ""
                    if ranges:
                        lines.append(f"    {fmt} {kind}{size_str} — {count} стр. ({ranges})")
                    else:
                        lines.append(f"    {fmt} {kind}{size_str} — {count} стр.")

            for label, pages_key, mm_key in [
                ("Рулон ч/б",   "roll_bw_pages",    "roll_bw"),
                ("Рулон цвет",  "roll_color_pages", "roll_color"),
            ]:
                rp = fd.get(pages_key, [])
                rm = fd.get(mm_key, 0)
                if rp or rm > 0:
                    ranges = compact_page_list(rp)
                    line = f"    {label} — {rm:.0f} мм"
                    if ranges:
                        line += f" ({ranges})"
                    lines.append(line)
            lines.append("")

        self.text_details.setText("\n".join(lines).rstrip())

    # ── Основной расчёт ───────────────────────────────────────────────────

    def calculate_and_display(self):
        if not self.grand:
            return

        self.display_details()

        std_totals, derived_info, extra_roll_bw, extra_roll_color = \
            self._build_print_summary_with_copies()

        # ── Печать ───────────────────────────────────────────────────────
        printing_lines = []
        total_print_pages = 0
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                total = std_totals.get((fmt, kind), 0)
                if total <= 0:
                    continue
                line = f"{fmt} {kind} ({fw}×{fh} мм) — {total} стр."
                if derived_info.get((fmt, kind)):
                    parts = [f"из {src}: {sq}→{add}"
                             for src, sq, add in derived_info[(fmt, kind)]]
                    line += "  [" + ", ".join(parts) + "]"
                printing_lines.append(line)
                total_print_pages += total

        self.text_printing.setText(
            "\n".join(printing_lines) if printing_lines else "Нет данных для печати"
        )

        # ── Рулонная печать ──────────────────────────────────────────────
        roll_lines = []
        roll_bw_total = self.grand.get("Рулон ч/б мм", 0) * self.copies + extra_roll_bw
        roll_color_total = self.grand.get("Рулон цвет мм", 0) * self.copies + extra_roll_color

        if roll_bw_total > 0:
            roll_lines.append(f"Ч/б — {roll_bw_total:.0f} мм ({roll_bw_total / 1000:.2f} м)")
        if roll_color_total > 0:
            roll_lines.append(f"Цвет — {roll_color_total:.0f} мм ({roll_color_total / 1000:.2f} м)")

        self.text_roll.setText(
            "\n".join(roll_lines) if roll_lines else "Рулонная печать не требуется"
        )

        # ── Фальцовка ────────────────────────────────────────────────────
        folding_text_parts = []
        total_fold = 0
        folding_target = None
        std_lines_for_report = []
        nonstd_lines_for_report = []

        if self.need_folding_a4:
            folding_target = "A4"
        elif self.need_folding_a3:
            folding_target = "A3"

        if folding_target:
            std_lines, nonstd_lines, total_fold = self._calculate_folding(folding_target)
            std_lines_for_report = std_lines
            nonstd_lines_for_report = nonstd_lines
            folding_text_parts.append(f"Фальцовка под {folding_target}")
            folding_text_parts.append("")
            if std_lines:
                folding_text_parts.append("Стандартные форматы:")
                folding_text_parts.extend(std_lines)
            if nonstd_lines:
                if std_lines:
                    folding_text_parts.append("")
                folding_text_parts.append("Нестандартные форматы:")
                folding_text_parts.extend(nonstd_lines)

        self.text_folding.setText(
            "\n".join(folding_text_parts) if folding_text_parts else "Фальцовка не требуется"
        )

        # ── Брошюровка ───────────────────────────────────────────────────
        binding_lines = []
        total_books = 0
        binding_target = None

        if self.need_binding_a4:
            binding_target = "A4"
            binding_lines, total_books = self._calculate_binding()
        elif self.need_binding_a3:
            binding_target = "A3"
            binding_lines, total_books = self._calculate_binding()

        if binding_target:
            bt = [f"Брошюровка на пружину {binding_target}", ""]
            bt.extend(binding_lines if binding_lines else ["Нет данных"])
            self.text_binding.setText("\n".join(bt))
        else:
            self.text_binding.setText("Брошюровка не требуется")

        # ── Вес ──────────────────────────────────────────────────────────
        total_weight = self._calculate_weight(
            std_totals, roll_bw_total, roll_color_total, binding_target, total_books
        )
        weight_str = self._format_weight(total_weight) if total_weight > 0 else "0.00 кг"
        self.label_total.setText(f"⚖️ Вес: {weight_str}")

        # ── Автоподгон высоты ────────────────────────────────────────────
        QTimer.singleShot(0, lambda: self._autosize_textedit(self.text_printing, 120))
        QTimer.singleShot(0, lambda: self._autosize_textedit(self.text_roll, 80))
        QTimer.singleShot(0, lambda: self._autosize_textedit(self.text_folding, 120))
        QTimer.singleShot(0, lambda: self._autosize_textedit(self.text_binding, 80))

        self._build_report(
            folding_target, std_lines_for_report, nonstd_lines_for_report,
            total_fold, binding_target, binding_lines, total_books, total_weight
        )

    # ── Отчёт ─────────────────────────────────────────────────────────────

    def _build_report(self, folding_target, fold_std, fold_nonstd, total_fold,
                      binding_target, binding_lines, total_books, total_weight):
        copies = self.copies
        total_pages_report = 0

        std_block = []
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    qty = cnt * copies
                    std_block.append(f"{fmt} {kind} ({fw}×{fh} мм) — {qty} стр.")
                    total_pages_report += qty

        nonstd_block = []
        for fmt, (fw, fh) in ISO_A_NONSTANDARD.items():
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    qty = cnt * copies
                    nonstd_block.append(f"{fmt} {kind} ({fw}×{fh} мм) — {qty} стр.")
                    total_pages_report += qty

        custom_block = []
        for k in self.grand.keys():
            if k.startswith("Рулон"):
                continue
            fmt, kind = self._parse_format_key(k)
            if not fmt or not kind:
                continue
            if fmt in ISO_A or fmt in ISO_A_NONSTANDARD:
                continue
            cnt = int(self.grand.get(k, 0))
            if cnt > 0:
                qty = cnt * copies
                custom_block.append(f"{fmt} {kind} — {qty} стр.")
                total_pages_report += qty

        roll_bw_report = self.grand.get("Рулон ч/б мм", 0) * copies
        roll_color_report = self.grand.get("Рулон цвет мм", 0) * copies
        color_mode_str = "Ч/б (принудительно)" if self.force_bw else "По файлу"

        lines = [
            "=" * 60,
            "АНАЛИЗ ПРОЕКТНОЙ ДОКУМЕНТАЦИИ",
            "=" * 60,
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Всего страниц в источнике: {self.total_source}",
            f"Количество экземпляров: {copies}",
            f"Режим цветности: {color_mode_str}",
            "",
            "ПЕЧАТЬ (исходные форматы × экземпляры):",
        ]

        if std_block:
            lines.append("• Стандартные форматы:")
            lines.extend(f"  {l}" for l in std_block)
        if nonstd_block:
            if std_block:
                lines.append("")
            lines.append("• Расширенные форматы:")
            lines.extend(f"  {l}" for l in nonstd_block)
        if custom_block:
            if std_block or nonstd_block:
                lines.append("")
            lines.append("• Произвольные форматы:")
            lines.extend(f"  {l}" for l in custom_block)
        if not (std_block or nonstd_block or custom_block):
            lines.append("Нет данных")

        lines.append(f"Итого страниц: {total_pages_report}")
        lines.append("")

        if folding_target:
            lines.append(f"ФАЛЬЦОВКА ПОД {folding_target}:")
            if fold_std:
                lines.append("• Стандартные форматы:")
                lines.extend(f"  {l}" for l in fold_std)
            if fold_nonstd:
                if fold_std:
                    lines.append("")
                lines.append("• Нестандартные форматы:")
                lines.extend(f"  {l}" for l in fold_nonstd)
            if not (fold_std or fold_nonstd):
                lines.append("Не требуется")
            lines.append(f"Итого листов: {total_fold}")
            lines.append("")

        if binding_target:
            lines.append(f"БРОШЮРОВКА НА ПРУЖИНУ {binding_target}:")
            if binding_lines:
                lines.append("• По количеству страниц:")
                lines.extend(f"  {l}" for l in binding_lines)
            else:
                lines.append("Не требуется")
            lines.append(f"Итого брошюр: {total_books}")
            lines.append("")

        if roll_bw_report > 0 or roll_color_report > 0:
            lines.append("РУЛОННАЯ ПЕЧАТЬ:")
            if roll_bw_report > 0:
                lines.append(f"  Ч/б — {roll_bw_report:.0f} мм ({roll_bw_report / 1000:.2f} м)")
            if roll_color_report > 0:
                lines.append(f"  Цвет — {roll_color_report:.0f} мм ({roll_color_report / 1000:.2f} м)")
            lines.append("")

        lines.append("─" * 60)
        lines.append(f"ВЕС: {self._format_weight(total_weight)}")
        lines.append("=" * 60)

        self.text_report.setText("\n".join(lines))

    # ── Утилиты ───────────────────────────────────────────────────────────

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

    # 1. Проверка удалённой лицензии
    license_ok, license_msg = check_remote_license()
    if not license_ok:
        QMessageBox.critical(None, "Доступ запрещён", license_msg)
        sys.exit(1)

    # 2. Авторизация
    login_dlg = LoginDialog()
    result = login_dlg.exec()
    if result != QDialog.DialogCode.Accepted or not login_dlg.authenticated:
        sys.exit(0)

    # 3. Основное окно
    window = PrintingCalculator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()