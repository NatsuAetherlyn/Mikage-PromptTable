import os
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image as OpenpyxlImage
from typing import List, Dict, Any, Tuple
from PIL import Image
import tempfile

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


def export_to_excel(items: List[Dict[str, Any]], output_path: str) -> Tuple[bool, str]:
    """
    Export annotation items to an Excel (.xlsx) file matching the layout of Image 1.
    Columns: 序号, 分区, 人物, Prompt, 预览图, 使用推荐, 图片路径
    预览图 column embeds the thumbnail so exports are fully self-contained.
    """
    try:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Prompt注释与画廊"

        # Headers
        headers = ["序号", "分区", "人物", "Prompt", "预览图", "使用推荐", "图片路径"]
        ws.append(headers)

        # Header styles (Modern Slate Glass theme)
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = thin_border

        ws.row_dimensions[1].height = 28

        # Column widths
        col_widths = {
            "A": 7,   # 序号
            "B": 12,  # 分区
            "C": 18,  # 人物
            "D": 48,  # Prompt
            "E": 24,  # 预览图
            "F": 28,  # 使用推荐
            "G": 35   # 图片路径
        }
        for col_letter, width in col_widths.items():
            ws.column_dimensions[col_letter].width = width

        # Content styles
        cell_font = Font(name="Microsoft YaHei", size=10, color="0F172A")
        code_font = Font(name="Consolas", size=9.5, color="334155")
        text_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        temp_img_files = []

        for idx, item in enumerate(items, start=1):
            row_idx = idx + 1
            ws.row_dimensions[row_idx].height = 110  # generous height for image thumbnail

            char_name = item.get("character") or "未命名"
            prompt_text = item.get("prompt") or ""
            rec_text = item.get("recommendation") or ""
            img_path = item.get("image_path") or ""
            cat_name = item.get("category_name") or ""

            # Values
            ws.cell(row=row_idx, column=1, value=idx).alignment = center_align
            ws.cell(row=row_idx, column=2, value=cat_name).alignment = center_align
            ws.cell(row=row_idx, column=3, value=char_name).alignment = center_align
            ws.cell(row=row_idx, column=4, value=prompt_text).alignment = text_align
            ws.cell(row=row_idx, column=5, value="").alignment = center_align  # Image goes here
            ws.cell(row=row_idx, column=6, value=rec_text).alignment = text_align
            ws.cell(row=row_idx, column=7, value=img_path).alignment = text_align

            # Fonts and borders
            ws.cell(row=row_idx, column=1).font = cell_font
            ws.cell(row=row_idx, column=2).font = cell_font
            ws.cell(row=row_idx, column=3).font = Font(name="Microsoft YaHei", size=10, bold=True, color="0F172A")
            ws.cell(row=row_idx, column=4).font = code_font
            ws.cell(row=row_idx, column=6).font = cell_font
            ws.cell(row=row_idx, column=7).font = Font(name="Consolas", size=8.5, color="64748B")

            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).border = thin_border

            # Embed thumbnail image into cell D{row_idx}
            if img_path and os.path.exists(img_path):
                try:
                    with Image.open(img_path) as pil_img:
                        # Resize to fit within 150x130
                        w, h = pil_img.size
                        max_w, max_h = 150, 130
                        ratio = min(max_w / w, max_h / h)
                        target_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
                        thumb_pil = pil_img.resize(target_size, Image.Resampling.LANCZOS)
                        
                        # Save temp png
                        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                        thumb_pil.save(tmp.name, format="PNG")
                        temp_img_files.append(tmp.name)
                        
                        excel_img = OpenpyxlImage(tmp.name)
                        excel_img.width = target_size[0]
                        excel_img.height = target_size[1]

                        # Pin to the 预览图 column
                        ws.add_image(excel_img, f"E{row_idx}")
                except Exception as img_err:
                    print(f"[Excel Export] Failed to embed image for row {row_idx}: {img_err}")
                    ws.cell(row=row_idx, column=5, value="[无法嵌入图片]")

        wb.save(output_path)

        # Cleanup temp images
        for tmp_path in temp_img_files:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        return True, f"成功导出 {len(items)} 条注释到: {output_path}"
    except Exception as e:
        return False, f"导出失败: {str(e)}"


def import_from_excel(input_path: str) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Import annotation items from an Excel (.xlsx) file.
    Also recovers embedded preview images (e.g. ones exported by this app):
    each image anchored in the 预览图 column is decoded and re-saved next to
    the executable, then bound back to its row's entry.
    """
    if not os.path.exists(input_path):
        return False, [], "文件不存在"
    try:
        wb = openpyxl.load_workbook(input_path)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return False, [], "表格为空"

        header_row = rows[0]
        header_map = {}
        for idx, h in enumerate(header_row):
            if not h:
                continue
            h_str = str(h).strip().lower()
            if "人物" in h_str or "角色" in h_str or "name" in h_str:
                header_map["character"] = idx
            elif "prompt" in h_str or "提示词" in h_str:
                header_map["prompt"] = idx
            elif "推荐" in h_str or "备注" in h_str or "note" in h_str or "weight" in h_str:
                header_map["recommendation"] = idx
            elif "路径" in h_str or "path" in h_str or "file" in h_str:
                header_map["image_path"] = idx
            elif "分区" in h_str or "分类" in h_str or "category" in h_str:
                header_map["category_name"] = idx

        # ---- Recover embedded images: anchor row -> saved local file ----
        embedded_dir = os.path.join(
            os.path.dirname(os.path.abspath(input_path)),
            "embedded_images_" + os.path.splitext(os.path.basename(input_path))[0]
        )
        row_images = {}  # excel row number (1-based) -> saved image path
        recovered = 0
        try:
            for shape in getattr(ws, "_images", []):
                try:
                    anchor = shape.anchor
                    # OneCellAnchor/TwoCellAnchor expose _from (row is 0-based)
                    from_row = getattr(getattr(anchor, "_from", None), "row", None)
                    if from_row is None or from_row == 0:
                        continue  # skip anything riding on the header row
                    # openpyxl: shape._data() returns the true encoded image
                    # bytes (PNG/JPEG); shape.ref holds zlib-compressed raw
                    # pixels and is NOT a decodable image, so it is tried last
                    # only through PIL with explicit format hints.
                    img_bytes = None
                    data_fn = getattr(shape, "_data", None)
                    if callable(data_fn):
                        try:
                            img_bytes = data_fn()
                        except Exception:
                            img_bytes = None
                    if not img_bytes:
                        ref = getattr(shape, "ref", None)
                        if ref is not None and hasattr(ref, "read"):
                            raw = ref.read()
                            try:
                                pil = Image.open(io.BytesIO(raw))
                                pil.load()
                                buf = io.BytesIO()
                                pil.save(buf, format="PNG")
                                img_bytes = buf.getvalue()
                            except Exception:
                                img_bytes = None

                    if not img_bytes:
                        continue

                    os.makedirs(embedded_dir, exist_ok=True)
                    save_path = os.path.join(embedded_dir, f"row_{from_row + 1}.png")
                    with open(save_path, "wb") as fh:
                        fh.write(img_bytes)
                    # validate it is a real image
                    try:
                        with Image.open(save_path) as check:
                            check.verify()
                    except Exception:
                        os.remove(save_path)
                        continue
                    row_images[from_row + 1] = save_path
                    recovered += 1
                except Exception as shape_err:
                    print(f"[Excel Import] skipped a drawing shape: {shape_err}")
        except Exception as imgs_err:
            print(f"[Excel Import] no embedded images recovered: {imgs_err}")

        items = []
        for r_idx, row in enumerate(rows[1:], start=2):
            if not any(row):
                continue

            def cell(key: str, default: str = "") -> str:
                if key not in header_map:
                    return default
                col = header_map[key]
                if col >= len(row) or row[col] is None:
                    return default
                return str(row[col]).strip()

            img_path = cell("image_path")
            # Row without a usable path but with an embedded picture: adopt it
            if (not img_path or not os.path.exists(img_path)) and r_idx in row_images:
                img_path = row_images[r_idx]

            items.append({
                "character": cell("character", "未命名"),
                "prompt": cell("prompt"),
                "recommendation": cell("recommendation"),
                "image_path": img_path,
                "category_name": cell("category_name"),
            })

        note = f"成功从 Excel 导入 {len(items)} 条记录"
        if recovered:
            note += f"，恢复了 {recovered} 张内嵌图片"
        return True, items, note
    except Exception as e:
        return False, [], f"导入解析失败: {str(e)}"
