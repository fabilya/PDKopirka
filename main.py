import os
import sys
import time
import io
import math
import tempfile
import subprocess
from collections import defaultdict
from datetime import datetime

import pymupdf as fitz
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QFileDialog, QLabel, QSpinBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QProgressBar, QFrame,
    QScrollArea, QDialog, QLineEdit, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
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

FMT_ORDER = ["A4", "A3", "A2", "A1", "A0"]
KIND_ORDER = ["ч/б", "цвет"]


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

        lbl_file = QLabel(f"Файл: <b>{os.path.basename(self.pdf_path)}</b>")
        lbl_file.setFont(QFont("Arial", 10))
        lbl_size = QLabel(f"Размер: <b>{self.w} × {self.h} мм</b>")
        lbl_size.setFont(QFont("Arial", 10))
        lbl_color = QLabel(f"Цветность: <b>{color_str}</b>")
        lbl_color.setFont(QFont("Arial", 10))
        lbl_pages = QLabel(f"Страниц: <b>{len(self.pages)}</b>  ({ranges})")
        lbl_pages.setFont(QFont("Arial", 10))

        info_layout.addWidget(lbl_file)
        info_layout.addWidget(lbl_size)
        info_layout.addWidget(lbl_color)
        info_layout.addWidget(lbl_pages)

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

    def _open_pages(self):
        try:
            src = fitz.open(self.pdf_path)
            dst = fitz.open()

            for page_num in self.pages:
                src_page = src[page_num - 1]
                new_page = dst.new_page(
                    -1,
                    width=src_page.rect.width,
                    height=src_page.rect.height
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
                        temp_dir,
                        f"{base_name}__стр_{ranges}_{stamp}.pdf"
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
                self, "Ошибка",
                f"Не удалось открыть страницы:\n{str(e)}"
            )

    def _apply_format(self):
        raw = self.edit_format.text().strip()
        if not raw:
            QMessageBox.warning(self, "Ошибка", "Введите название формата.")
            return

        def normalize(s):
            return (s.upper()
                    .replace("А", "A")
                    .replace("Х", "X")
                    .replace(" ", "")
                    )

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

    def __init__(self, pdfs):
        super().__init__()
        self.pdfs = pdfs
        self._user_action = None
        self._user_value = None

        import threading
        self._wait_event = threading.Event()

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
                try:
                    with fitz.open(pdf_path) as doc:
                        total = len(doc)
                        total_source += total
                        file_page_counts.append(total)

                        name = os.path.basename(pdf_path)
                        self.status.emit(f"Анализ: {name} ({total} стр.)")

                        # Накопители по файлу
                        file_formats = defaultdict(int)
                        file_pages = defaultdict(list)   # key -> [page_nums]
                        file_roll_bw = 0.0
                        file_roll_color = 0.0
                        file_roll_bw_pages = []          # номера страниц
                        file_roll_color_pages = []

                        custom_groups = defaultdict(list)

                        for i, p in enumerate(doc):
                            page_num = i + 1
                            r = p.mediabox
                            w, h = sorted((
                                round(r.width * 25.4 / 72, 1),
                                round(r.height * 25.4 / 72, 1)
                            ))
                            col = self.detect_page_color(p)

                            fA = self.match_format_with_tolerance(w, h, ISO_A)
                            fN = self.match_format_with_tolerance(
                                w, h, ISO_A_NONSTANDARD
                            )

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

                        for (w, h, col), pages in custom_groups.items():
                            self.need_user_input.emit(
                                w, h, col, pages, pdf_path
                            )
                            self._wait_for_user()

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
                            "name": name,
                            "total": total,
                            "formats": dict(file_formats),
                            "pages": {k: sorted(v) for k, v in file_pages.items()},
                            "roll_bw": file_roll_bw,
                            "roll_color": file_roll_color,
                            "roll_bw_pages": sorted(file_roll_bw_pages),
                            "roll_color_pages": sorted(file_roll_color_pages),
                        })

                except Exception as e:
                    self.error.emit(
                        f"Ошибка при обработке {pdf_path}: {str(e)}"
                    )
                    continue

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
        self.bg_color = "#f5f6f7"
        self.card_color = "#ffffff"

        self.apply_style()

        self.grand = {}
        self.total_source = 0
        self.file_page_counts = []
        self.file_details = []
        self.selected_path = ""
        self.copies = 1
        self.need_folding = False
        self.need_binding = False

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
            QPushButton:hover  {{ background-color: #0052a3; }}
            QPushButton:pressed {{ background-color: #003d7a; }}
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
            QSpinBox, QCheckBox {{
                background-color: {self.card_color};
                color: #333;
            }}
            QCheckBox::indicator {{ width: 18px; height: 18px; }}
            QCheckBox::indicator:unchecked {{
                background-color: white;
                border: 2px solid #ccc;
                border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {self.primary_color};
                border: 2px solid {self.primary_color};
                border-radius: 3px;
            }}
        """)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_input_tab(), "📁 Ввод данных")
        self.tabs.addTab(self.create_details_tab(), "📊 Детализация по файлам")
        self.tabs.addTab(self.create_manager_tab(), "👔 Для менеджера")
        self.tabs.addTab(self.create_report_tab(), "📄 Отчет")

        main_layout.addWidget(self.tabs)

    def create_input_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        file_frame = QFrame()
        fl = QVBoxLayout(file_frame)
        lbl = QLabel("📁 Выберите PDF файл или папку:")
        lbl.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        fl.addWidget(lbl)
        row = QHBoxLayout()
        self.label_path = QLabel("Путь не выбран")
        self.label_path.setStyleSheet("color: #666; padding: 5px;")
        row.addWidget(self.label_path)
        btn = QPushButton("📂 Обзор...")
        btn.clicked.connect(self.browse_path)
        row.addWidget(btn)
        fl.addLayout(row)
        layout.addWidget(file_frame)

        params_frame = QFrame()
        pl = QVBoxLayout(params_frame)
        lbl2 = QLabel("⚙️ Параметры:")
        lbl2.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        pl.addWidget(lbl2)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Количество экземпляров:"))
        self.spinbox_copies = QSpinBox()
        self.spinbox_copies.setMinimum(1)
        self.spinbox_copies.setMaximum(100)
        self.spinbox_copies.setValue(1)
        self.spinbox_copies.valueChanged.connect(self.on_params_changed)
        row2.addWidget(self.spinbox_copies)
        row2.addStretch()
        pl.addLayout(row2)

        self.checkbox_folding = QCheckBox("Требуется фальцовка под A4")
        self.checkbox_folding.stateChanged.connect(self.on_params_changed)
        pl.addWidget(self.checkbox_folding)

        self.checkbox_binding = QCheckBox(
            "Требуется брошюровка на пластиковую пружину A4"
        )
        self.checkbox_binding.stateChanged.connect(self.on_params_changed)
        pl.addWidget(self.checkbox_binding)

        layout.addWidget(params_frame)

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

        btn_analyze = QPushButton("▶️ НАЧАТЬ АНАЛИЗ")
        btn_analyze.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        btn_analyze.setMinimumHeight(50)
        btn_analyze.clicked.connect(self.start_analysis)
        layout.addWidget(btn_analyze)

        layout.addStretch()
        return widget

    def create_details_tab(self):
        """Вкладка «Детализация по файлам» — всегда в 1 экз., с номерами страниц."""
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
        """Вкладка «Для менеджера»: Печать → Рулон → Фальцовка → Брошюровка."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sc = QWidget()
        sl = QVBoxLayout(sc)
        sl.setSpacing(15)

        def make_block(title, attr, height=180):
            frame = QFrame()
            fl_inner = QVBoxLayout(frame)
            lbl_inner = QLabel(title)
            lbl_inner.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            fl_inner.addWidget(lbl_inner)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setMaximumHeight(height)
            fl_inner.addWidget(te)
            setattr(self, attr, te)
            return frame

        sl.addWidget(make_block(
            "🖨️ Печать (с конвертацией нестандартных, с учётом экземпляров):",
            "text_printing", 240
        ))
        sl.addWidget(make_block("🌀 Рулонная печать:", "text_roll", 100))
        sl.addWidget(make_block("📋 Фальцовка под A4:", "text_folding", 200))
        sl.addWidget(make_block("📌 Брошюровка на пружину A4:", "text_binding", 130))

        total_frame = QFrame()
        tl = QVBoxLayout(total_frame)
        self.label_total = QLabel("📄 Итого: 0")
        self.label_total.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.label_total.setStyleSheet(f"color: {self.primary_color};")
        tl.addWidget(self.label_total)
        sl.addWidget(total_frame)

        sl.addStretch()
        scroll.setWidget(sc)
        layout.addWidget(scroll)

        btn_save = QPushButton("💾 Сохранить отчет PDF")
        btn_save.setMinimumHeight(40)
        btn_save.clicked.connect(self.save_pdf_report)
        layout.addWidget(btn_save)

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
        path = QFileDialog.getExistingDirectory(
            self, "Выберите папку с PDF файлами"
        )
        if path:
            self.selected_path = path
            self.label_path.setText(f"✓ {path}")

    def on_params_changed(self):
        self.copies = self.spinbox_copies.value()
        self.need_folding = self.checkbox_folding.isChecked()
        self.need_binding = self.checkbox_binding.isChecked()
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
            pdfs = [
                os.path.join(r, f)
                for r, _, fs in os.walk(self.selected_path)
                for f in fs if f.lower().endswith(".pdf")
            ]

        if not pdfs:
            self.label_status.setText("❌ PDF файлы не найдены")
            return

        self.label_status.setText("⏳ Идет анализ...")
        self.progress_bar.setValue(0)

        self.thread = AnalysisThread(pdfs)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.need_user_input.connect(self.show_unknown_format_dialog)
        self.thread.finished.connect(self.analysis_finished)
        self.thread.error.connect(self.analysis_error)
        self.thread.start()

    def show_unknown_format_dialog(self, w, h, color, pages, pdf_path):
        dlg = UnknownFormatDialog(w, h, color, pages, pdf_path, parent=self)
        dlg.exec()
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

        self.label_status.setText("✅ Анализ завершен")
        self.progress_bar.setValue(100)

        self.display_details()
        self.calculate_and_display()

    def analysis_error(self, error):
        self.label_status.setText(f"❌ {error}")

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

    def _build_print_summary_with_copies(self):
        """
        Конвертация для блока «Печать» в «Для менеджера»:
          ШАГ 1: умножаем количество страниц на self.copies
          ШАГ 2: применяем правила (A4x3→A1, A4x4→A1, A3x3→A0, A3x4→A0)
          ШАГ 3: остальные ISO_A_NONSTANDARD → рулон (max(w,h) × кол-во × копии)
        """
        copies = self.copies

        standard_totals = defaultdict(int)
        derived_info = defaultdict(list)
        extra_roll_bw_mm = 0.0
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
                    derived_info[(target, kind)].append(
                        (src, src_qty, add)
                    )

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

        return (standard_totals, derived_info,
                extra_roll_bw_mm, extra_roll_color_mm)

    # ── Вкладка «Детализация по файлам» ───────────────────────────────────

    def display_details(self):
        """
        Показывает по каждому файлу: какие форматы и какие страницы.
        Всегда в 1 экземпляре. Не зависит от self.copies.
        """
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
                    return (
                        1,
                        list(ISO_A_NONSTANDARD.keys()).index(fmt),
                        kind or "",
                    )
                return (2, fmt or "", kind or "")

            if fmts:
                for k, count in sorted(fmts.items(), key=sort_key):
                    fmt, kind = self._parse_format_key(k)
                    if not fmt:
                        continue
                    pages = pages_map.get(k, [])
                    ranges = compact_page_list(pages)
                    if ranges:
                        lines.append(
                            f"    {fmt} {kind} — {count} стр. ({ranges})"
                        )
                    else:
                        lines.append(f"    {fmt} {kind} — {count} стр.")

            # Рулонная печать (пользовательская)
            rb_pages = fd.get("roll_bw_pages", [])
            rc_pages = fd.get("roll_color_pages", [])
            rb_mm = fd.get("roll_bw", 0)
            rc_mm = fd.get("roll_color", 0)

            if rb_pages or rb_mm > 0:
                ranges = compact_page_list(rb_pages)
                if ranges:
                    lines.append(
                        f"    Рулон ч/б — {rb_mm:.0f} мм ({ranges})"
                    )
                else:
                    lines.append(f"    Рулон ч/б — {rb_mm:.0f} мм")

            if rc_pages or rc_mm > 0:
                ranges = compact_page_list(rc_pages)
                if ranges:
                    lines.append(
                        f"    Рулон цвет — {rc_mm:.0f} мм ({ranges})"
                    )
                else:
                    lines.append(f"    Рулон цвет — {rc_mm:.0f} мм")

            lines.append("")  # пустая строка между файлами

        self.text_details.setText("\n".join(lines).rstrip())

    # ── Вкладка «Для менеджера» + Отчёт ───────────────────────────────────

    def calculate_and_display(self):
        if not self.grand:
            return

        # Обновляем также детализацию (она от копий не зависит, но при первом
        # запуске данные могут не отрисоваться)
        self.display_details()

        # ═══ «Для менеджера» (с конвертацией, × копии) ═══════════════════
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
                    parts = [
                        f"из {src}: {src_qty}→{add}"
                        for (src, src_qty, add) in derived_info[(fmt, kind)]
                    ]
                    line += "  [" + ", ".join(parts) + "]"
                printing_lines.append(line)
                total_print_pages += total

        self.text_printing.setText(
            "\n".join(printing_lines) if printing_lines
            else "Нет данных для печати"
        )

        # ── Рулонная печать ──────────────────────────────────────────────
        roll_lines = []
        roll_bw_total = (self.grand.get("Рулон ч/б мм", 0) * self.copies
                         + extra_roll_bw)
        roll_color_total = (self.grand.get("Рулон цвет мм", 0) * self.copies
                            + extra_roll_color)

        if roll_bw_total > 0:
            roll_lines.append(
                f"Ч/б — {roll_bw_total:.0f} мм ({roll_bw_total / 1000:.2f} м)"
            )
        if roll_color_total > 0:
            roll_lines.append(
                f"Цвет — {roll_color_total:.0f} мм ({roll_color_total / 1000:.2f} м)"
            )

        self.text_roll.setText(
            "\n".join(roll_lines) if roll_lines
            else "Рулонная печать не требуется"
        )

        # ── Фальцовка (по исходным форматам × копии) ─────────────────────
        folding_lines = []
        nonstd_folding_lines = []
        total_fold = 0

        if self.need_folding:
            for fmt in ["A3", "A2", "A1", "A0"]:
                qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                       int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
                if qty > 0:
                    folding_lines.append(f"{fmt} → A4 — {qty} шт.")
                    total_fold += qty

            for fmt in ISO_A_NONSTANDARD.keys():
                qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                       int(self.grand.get(f"{fmt} ч/б", 0))) * self.copies
                if qty > 0:
                    nonstd_folding_lines.append(f"{fmt} → A4 — {qty} шт.")
                    total_fold += qty

            custom_totals = defaultdict(int)
            for k in self.grand.keys():
                if k.startswith("Рулон"):
                    continue
                fmt, kind = self._parse_format_key(k)
                if not fmt:
                    continue
                if fmt == "A4":
                    continue
                if fmt in ISO_A:
                    continue
                if fmt in ISO_A_NONSTANDARD:
                    continue
                custom_totals[fmt] += int(self.grand.get(k, 0))

            for fmt in sorted(custom_totals.keys()):
                qty = custom_totals[fmt] * self.copies
                if qty > 0:
                    nonstd_folding_lines.append(f"{fmt} → A4 — {qty} шт.")
                    total_fold += qty

        all_folding_text_parts = []
        if folding_lines:
            all_folding_text_parts.append("Стандартные форматы:")
            all_folding_text_parts.extend(folding_lines)
        if nonstd_folding_lines:
            if all_folding_text_parts:
                all_folding_text_parts.append("")
            all_folding_text_parts.append("Нестандартные форматы:")
            all_folding_text_parts.extend(nonstd_folding_lines)

        self.text_folding.setText(
            "\n".join(all_folding_text_parts) if all_folding_text_parts
            else "Фальцовка не требуется"
        )

        # ── Брошюровка ───────────────────────────────────────────────────
        binding_lines = []
        total_books = 0

        if self.need_binding and self.file_page_counts:
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

        self.text_binding.setText(
            "\n".join(binding_lines) if binding_lines
            else "Брошюровка не требуется"
        )

        # ── Итого ────────────────────────────────────────────────────────
        parts = [f"Страниц к печати: {total_print_pages}"]
        if self.need_folding and total_fold > 0:
            parts.append(f"Листов к фальцовке: {total_fold}")
        if self.need_binding and total_books > 0:
            parts.append(f"Брошюр: {total_books}")
        if roll_bw_total + roll_color_total > 0:
            parts.append(
                f"Рулон: {(roll_bw_total + roll_color_total):.0f} мм"
            )

        self.label_total.setText("📄 " + "   |   ".join(parts))

        # ═══ ОТЧЁТ (как было: исходные форматы × копии, без конвертации) ══
        self._build_report(binding_lines, total_books)

    def _build_report(self, binding_lines, total_books):
        """
        Отчёт: исходные форматы × копии. Без конвертации.
        """
        copies = self.copies
        total_pages_report = 0

        std_block = []
        for fmt in FMT_ORDER:
            fw, fh = ISO_A[fmt]
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    qty = cnt * copies
                    std_block.append(
                        f"{fmt} {kind} ({fw}×{fh} мм) — {qty} стр."
                    )
                    total_pages_report += qty

        nonstd_block = []
        for fmt in ISO_A_NONSTANDARD.keys():
            fw, fh = ISO_A_NONSTANDARD[fmt]
            for kind in KIND_ORDER:
                cnt = int(self.grand.get(f"{fmt} {kind}", 0))
                if cnt > 0:
                    qty = cnt * copies
                    nonstd_block.append(
                        f"{fmt} {kind} ({fw}×{fh} мм) — {qty} стр."
                    )
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

        lines = [
            "=" * 60,
            "АНАЛИЗ ПРОЕКТНОЙ ДОКУМЕНТАЦИИ",
            "=" * 60,
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Всего страниц в источнике: {self.total_source}",
            f"Количество экземпляров: {copies}",
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

        if self.need_folding:
            lines.append("ФАЛЬЦОВКА ПОД A4:")
            std_fold_report = []
            std_fold_total = 0
            for fmt in ["A3", "A2", "A1", "A0"]:
                qty = (int(self.grand.get(f"{fmt} цвет", 0)) +
                       int(self.grand.get(f"{fmt} ч/б", 0))) * copies
                if qty > 0:
                    std_fold_report.append(f"{fmt} → A4 — {qty} шт.")
                    std_fold_total += qty

            nonstd_fold_report = defaultdict(int)
            for k in self.grand.keys():
                if k.startswith("Рулон"):
                    continue
                fmt, kind = self._parse_format_key(k)
                if not fmt:
                    continue
                if fmt == "A4":
                    continue
                if fmt in ISO_A:
                    continue
                nonstd_fold_report[fmt] += int(self.grand.get(k, 0))

            nonstd_fold_lines = []
            nonstd_fold_total = 0
            for fmt in sorted(nonstd_fold_report.keys()):
                qty = nonstd_fold_report[fmt] * copies
                if qty > 0:
                    nonstd_fold_lines.append(f"{fmt} → A4 — {qty} шт.")
                    nonstd_fold_total += qty

            fold_total_report = std_fold_total + nonstd_fold_total

            if std_fold_report:
                lines.append("Стандартные форматы:")
                lines.extend(std_fold_report)
            if nonstd_fold_lines:
                if std_fold_report:
                    lines.append("")
                lines.append("Нестандартные форматы:")
                lines.extend(nonstd_fold_lines)
            if not (std_fold_report or nonstd_fold_lines):
                lines.append("Не требуется")

            lines.append(f"Итого листов: {fold_total_report}")
            lines.append("")

        if self.need_binding:
            lines.append("БРОШЮРОВКА НА ПРУЖИНУ A4:")
            lines.extend(binding_lines if binding_lines else ["Не требуется"])
            lines.append(f"Итого брошюр: {total_books}")
            lines.append("")

        if roll_bw_report > 0 or roll_color_report > 0:
            lines.append("РУЛОННАЯ ПЕЧАТЬ:")
            if roll_bw_report > 0:
                lines.append(
                    f"Ч/б — {roll_bw_report:.0f} мм "
                    f"({roll_bw_report / 1000:.2f} м)"
                )
            if roll_color_report > 0:
                lines.append(
                    f"Цвет — {roll_color_report:.0f} мм "
                    f"({roll_color_report / 1000:.2f} м)"
                )
            lines.append("")

        lines.append("=" * 60)
        self.text_report.setText("\n".join(lines))

    # ── Утилиты ───────────────────────────────────────────────────────────

    def copy_report(self):
        try:
            import pyperclip
            pyperclip.copy(self.text_report.toPlainText())
        except Exception:
            try:
                p = subprocess.Popen(
                    ['clip'], stdin=subprocess.PIPE, shell=True
                )
                p.communicate(
                    self.text_report.toPlainText().encode('utf-8')
                )
            except Exception:
                pass
        self.label_status.setText("✅ Отчет скопирован в буфер обмена")

    def save_pdf_report(self):
        if not self.grand:
            self.label_status.setText("❌ Сначала проведите анализ")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчет", "", "PDF файлы (*.pdf)"
        )
        if not path:
            return
        try:
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text(
                (35, 35), self.text_report.toPlainText(), fontsize=10
            )
            doc.save(path)
            doc.close()
            self.label_status.setText(
                f"✅ Отчет сохранен: {os.path.basename(path)}"
            )
        except Exception as e:
            self.label_status.setText(f"❌ Ошибка сохранения: {str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PrintingCalculator()
    window.show()
    sys.exit(app.exec())