import os, sys, time, io, math
import fitz
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
from collections import defaultdict


class TeeLog:
    def __init__(self):
        self.lines = []

    def write(self, msg):
        self.lines.append(msg)
        sys.__stdout__.write(msg)

    def flush(self):
        sys.__stdout__.flush()


# Константы
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

FMT_ORDER = ["A4", "A3", "A2", "A1", "A0"]
KIND_ORDER = ["ч/б", "цвет"]


def detect_page_color(page, tol=5, white_thr=245, min_colored_pixels=50, min_colored_ratio=0.002):
    try:
        scale = 200 / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
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

        if colored_count >= min_colored_pixels and (colored_count / ink_count) >= min_colored_ratio:
            return True
        return False

    except Exception:
        return False


def match_format_with_tolerance(w, h, table, tol=FORMAT_TOLERANCE_MM):
    for name, (fw, fh) in table.items():
        if (abs(w - fw) <= tol and abs(h - fh) <= tol) or (abs(h - fw) <= tol and abs(w - fh) <= tol):
            return name
    return None


def compact_page_list(pages):
    if not pages:
        return ""
    pages = sorted(pages)
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = p
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def print_progress(current, total, bar_len=30):
    percent = int(100 * current / total)
    filled = int(bar_len * current / total)
    bar = "█" * filled + "-" * (bar_len - filled)
    sys.stdout.write(f"\r  Обработка страниц: |{bar}| {percent}%")
    sys.stdout.flush()


def _size_key(w, h):
    return f"{w:g}×{h:g}"


def analyze_pdf(path, grand, log, check_color=True):
    if "_roll_detail" not in grand or not isinstance(grand.get("_roll_detail"), dict):
        grand["_roll_detail"] = defaultdict(lambda: {
            "color_pages": 0, "color_mm": 0.0,
            "bw_pages": 0, "bw_mm": 0.0
        })
    roll_detail = grand["_roll_detail"]

    doc = fitz.open(path)
    name = os.path.basename(path)
    total = len(doc)
    print(f"\n📄 {name} ({total} стр.):")
    log.append(f"{name} ({total} стр.)")

    std_A = defaultdict(lambda: {"color": [], "bw": []})
    std_N = defaultdict(lambda: {"color": [], "bw": []})
    custom = []

    for i, p in enumerate(doc, 1):
        r = p.mediabox
        w, h = sorted((round(r.width * 25.4 / 72, 1), round(r.height * 25.4 / 72, 1)))
        col = detect_page_color(p) if check_color else False

        fA = match_format_with_tolerance(w, h, ISO_A)
        fN = match_format_with_tolerance(w, h, ISO_A_NONSTANDARD)

        if fA:
            (std_A[fA]["color"] if col else std_A[fA]["bw"]).append(i)
        elif fN:
            (std_N[fN]["color"] if col else std_N[fN]["bw"]).append(i)
        else:
            custom.append((i, w, h, col))

        print_progress(i, total)
        time.sleep(0.002)

    sys.stdout.write("\n")

    roll = {"color": 0.0, "bw": 0.0}

    if custom:
        folder = os.path.join(os.path.dirname(path), "Нестандартные")
        os.makedirs(folder, exist_ok=True)
        out_path = os.path.join(folder, os.path.splitext(name)[0] + "__nonstandard.pdf")

        src = fitz.open(path)
        dst = fitz.open()
        new_map = []
        for n, (orig, w, h, c) in enumerate(custom, 1):
            sp = src[orig - 1]
            npg = dst.new_page(-1, width=sp.rect.width, height=sp.rect.height)
            npg.show_pdf_page(npg.rect, src, orig - 1)
            new_map.append((n, orig, w, h, c))
        src.close()

        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except:
                print(f"⚠️ Закрой {out_path}")
                sys.exit(1)

        dst.save(out_path)
        dst.close()

        print(f"  ⚠️ Нестандартные страницы сохранены: {os.path.basename(out_path)}")
        log.append(f"Создан {os.path.basename(out_path)}")

        grouped = defaultdict(list)
        for new, _, w, h, c in new_map:
            grouped[(w, h, c)].append(new)

        keys = list(grouped.keys())
        i = 0
        while i < len(keys):
            w, h, c = keys[i]
            pages = grouped[(w, h, c)]
            color_str = "цвет" if c else "ч/б"
            ranges = compact_page_list(pages)

            ans = input(
                f"    ▸ {w}×{h} мм ({color_str}) — {len(pages)} стр. ({ranges})\n"
                "       Введите формат (A4, A3x3) или длину (мм/м), Enter=бОльшая сторона, b=назад: "
            ).strip()

            log.append(f"{w}×{h} {color_str} -> {ans}")

            if ans.lower() in ("b", "назад"):
                i = max(0, i - 1)
                print("🔙 Назад")
                continue

            sizek = _size_key(w, h)
            page_cnt = len(pages)

            if not ans:
                mm_per_page = max(w, h)
                mm_sum = mm_per_page * page_cnt

                grand["Enter (по Enter) стр"] += page_cnt

                if c:
                    roll["color"] += mm_sum
                    roll_detail[sizek]["color_pages"] += page_cnt
                    roll_detail[sizek]["color_mm"] += mm_sum
                else:
                    roll["bw"] += mm_sum
                    roll_detail[sizek]["bw_pages"] += page_cnt
                    roll_detail[sizek]["bw_mm"] += mm_sum

                print(f"Добавлено: {mm_sum:.0f} мм (бОльшая сторона × {page_cnt} стр.)\n")
                i += 1
                continue

            try:
                val = float(ans.replace(",", "."))
                if val < 100:
                    val *= 1000
                mm_per_page = val
                mm_sum = mm_per_page * page_cnt

                if c:
                    roll["color"] += mm_sum
                    roll_detail[sizek]["color_pages"] += page_cnt
                    roll_detail[sizek]["color_mm"] += mm_sum
                else:
                    roll["bw"] += mm_sum
                    roll_detail[sizek]["bw_pages"] += page_cnt
                    roll_detail[sizek]["bw_mm"] += mm_sum

                print(f"Добавлено: {mm_sum:.0f} мм ({mm_per_page:.0f} мм × {page_cnt} стр.)\n")
                i += 1
                continue
            except ValueError:
                pass

            if ans.lower().startswith(("a", "а")):
                fmt = ans.upper().replace("А", "A")
                for (_, orig, ow, oh, cc) in new_map:
                    if abs(ow - w) <= FORMAT_TOLERANCE_MM and abs(oh - h) <= FORMAT_TOLERANCE_MM and cc == c:
                        (std_A if fmt in ISO_A else std_N)[fmt]["color" if c else "bw"].append(orig)
                print(f"Подогнано к {fmt}\n")
                i += 1
                continue

            print("⚠️ Неизвестный ввод, повторите.")

    print(f"\n📊 Форматы и количество страниц в файле {name}:")
    for grp, title in ((std_A, "Стандартные форматы"), (std_N, "Расширенные форматы")):
        if not grp:
            continue
        print(f"  🔹 {title}:")
        for fmt, d in grp.items():
            if d["bw"]:
                cnt = len(d["bw"])
                print(f"    {fmt} ч/б — {cnt} стр. ({compact_page_list(sorted(d['bw']))})")
                grand[f"{fmt} ч/б"] += cnt
            if d["color"]:
                cnt = len(d["color"])
                print(f"    {fmt} цвет — {cnt} стр. ({compact_page_list(sorted(d['color']))})")
                grand[f"{fmt} цвет"] += cnt

    if any(roll.values()):
        msg = f"  🌀 Рулонная печать — ч/б {roll['bw']:.0f} мм, цвет {roll['color']:.0f} мм"
        print(msg)
        log.append(msg)
        if roll["bw"]:
            grand["Рулон ч/б мм"] += roll["bw"]
        if roll["color"]:
            grand["Рулон цвет мм"] += roll["color"]

    doc.close()


def print_summary(grand, total_source, copies,
                  need_folding, need_binding, file_page_counts):
    print("\n" + "=" * 60)
    print("ИТОГОВАЯ СВОДКА")
    print("=" * 60)

    print(f"\nВсего страниц: {total_source * copies}")
    print(f"Кол-во экземпляров: {copies}")

    print("\nРазмеры и цветность страниц:")

    # Черно-белая печать
    print("Черно-белая печать:")
    bw_found = False
    for fmt in FMT_ORDER:
        bw_cnt = int(grand.get(f"{fmt} ч/б", 0))
        if bw_cnt > 0:
            print(f"  {fmt} - {bw_cnt * copies} стр.")
            bw_found = True

    for fmt in sorted(
            [k for k in grand.keys() if k.endswith("ч/б") and not any(f == k.replace(" ч/б", "") for f in FMT_ORDER)]):
        cnt = int(grand.get(fmt, 0))
        if cnt > 0:
            print(f"  {fmt} - {cnt * copies} стр.")
            bw_found = True

    if not bw_found:
        print("  Нет")

    # Цветная печать
    print("Цветная печать:")
    color_found = False
    for fmt in FMT_ORDER:
        color_cnt = int(grand.get(f"{fmt} цвет", 0))
        if color_cnt > 0:
            print(f"  {fmt} - {color_cnt * copies} стр.")
            color_found = True

    for fmt in sorted([k for k in grand.keys() if
                       k.endswith("цвет") and not any(f == k.replace(" цвет", "") for f in FMT_ORDER)]):
        cnt = int(grand.get(fmt, 0))
        if cnt > 0:
            print(f"  {fmt} - {cnt * copies} стр.")
            color_found = True

    if not color_found:
        print("  Нет")

    # РУЛОН
    roll_bw = int(round(grand.get("Рулон ч/б мм", 0)))
    roll_color = int(round(grand.get("Рулон цвет мм", 0)))

    if roll_bw or roll_color:
        print("\nРулонная печать:")
        if roll_bw:
            print(f"  ч/б — {math.ceil(roll_bw / 1000)} пог. м.")
        if roll_color:
            print(f"  цвет — {math.ceil(roll_color / 1000)} пог. м.")

    # РЕЗКА
    cut_pages = int(grand.get("Enter (по Enter) стр", 0))
    cut_pages *= copies

    if cut_pages:
        print("\nРезка нестандартных форматов:")
        print(f"  {cut_pages} шт.")

    # ФАЛЬЦОВКА
    if need_folding:
        print("\nФальцовка под A4:")

        for fmt in ("A3", "A2", "A1", "A0"):
            total_fmt = (
                    int(grand.get(f"{fmt} цвет", 0)) +
                    int(grand.get(f"{fmt} ч/б", 0))
            )
            if total_fmt > 0:
                print(f"  {fmt} — {total_fmt * copies} стр.")

    # БРОШЮРОВКА
    if need_binding:
        print("\nБрошюровка под A4:")

        thresholds = [30, 70, 110, 170, 220, 280, 400, 470]
        prev = 0
        for t in thresholds:
            cnt = sum(1 for n in file_page_counts if prev < n <= t)
            if cnt > 0:
                print(f"  До {t} стр — {cnt * copies} файл(ов)")
            prev = t

        over = sum(1 for n in file_page_counts if n > thresholds[-1])
        if over > 0:
            print(f"  Свыше {thresholds[-1]} стр — {over * copies} файл(ов)")


def main():
    tee_logger = TeeLog()
    sys.stdout = tee_logger

    path = input("Введите путь к PDF файлу или папке: ").strip()
    if not os.path.exists(path):
        print("Путь не найден.")
        return

    try:
        copies = int(input("Какое количество экземпляров? (число): ").strip())
        if copies < 1:
            copies = 1
    except ValueError:
        copies = 1

    check_color = input("Цветность по файлам? (+ или -): ").strip() == "+"
    need_binding = input("Нужна ли брошюровка? (+ или -): ").strip() == "+"

    # Если брошюровка не требуется, спрашиваем про фальцовку
    if need_binding:
        need_folding = True
    else:
        need_folding = input("Нужна ли фальцовка? (+ или -): ").strip() == "+"

    pdfs = [path] if path.lower().endswith(".pdf") else [
        os.path.join(r, f)
        for r, _, fs in os.walk(path)
        for f in fs
        if f.lower().endswith(".pdf")
    ]

    grand = defaultdict(float)
    total_source = 0
    file_page_counts = []

    for pdf in pdfs:
        try:
            with fitz.open(pdf) as d:
                n_pages = len(d)
            total_source += n_pages
            file_page_counts.append(n_pages)

            analyze_pdf(pdf, grand, [], check_color=check_color)

        except Exception as e:
            print(f"\n⚠️ Ошибка при обработке {pdf}:\n   {e}")
            continue

    print_summary(
        grand,
        total_source,
        copies,
        need_folding,
        need_binding,
        file_page_counts
    )


if __name__ == "__main__":
    main()
