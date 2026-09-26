import os
import json
import re
import sys
import subprocess
import webbrowser
from urllib.parse import quote
import webview
from typing import List, Dict, Any, Optional
from backend.storage import StorageManager
from backend.metadata import extract_png_metadata
from backend.excel_io import export_to_excel, import_from_excel
from backend.model_library import ModelLibrary
from backend import win32utils

IMAGE_FILTER = ('媒体文件 (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.apng;*.bmp;*.mp4;*.webm;*.mov;*.m4v)',
                '图片与动图 (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.apng;*.bmp)',
                '视频 (*.mp4;*.webm;*.mov;*.m4v)',
                '所有文件 (*.*)')
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.apng', '.bmp')
VIDEO_EXTS = ('.mp4', '.webm', '.mov', '.m4v')
MEDIA_EXTS = IMAGE_EXTS + VIDEO_EXTS
EXCEL_FILTER = ('Excel 表格 (*.xlsx)', '所有文件 (*.*)')


class JsApi:
    def __init__(self, storage: StorageManager, library: ModelLibrary, default_comfy_root: str = ""):
        self.storage = storage
        self.library = library
        self._window: Optional[webview.Window] = None
        self._default_root = default_comfy_root

    def set_window(self, window: webview.Window):
        self._window = window

    # ---------------- bootstrap ----------------

    def get_state(self) -> Dict[str, Any]:
        if not self.storage.file_existed and not self.storage.items:
            self._seed_samples()
        pruned = self.storage.prune_placeholders()
        return {
            "items": self.storage.items,
            "categories": self.storage.get_categories(),
            "data_dir": self.storage.data_dir,
            "pruned": pruned,
        }

    def _seed_samples(self):
        sample = (r"C:\Users\25677\.zcode\cli\image-cache"
                  r"\sess_ebd31b34-13e6-47bc-a480-21a2ea985eae"
                  r"\image-fb8c8f0cd1d33d5d2b28713f1d9f9e97.png")
        exists = os.path.exists(sample)
        thumb = self.storage.generate_thumbnail(sample) if exists else ""
        for item in (
            {"id": "sample_phoebe", "character": "菲比", "recommendation": "使用 CKXL @ 0.5",
             "annotation_tags": [], "scheme": "tags",
             "negative_prompt": "lowres, bad anatomy, bad hands, worst quality, watermark",
             "images": [{"path": sample if exists else "", "thumb_url": thumb,
                         "width": 883, "height": 858,
                         "full_prompt": "phoebe (wuthering waves), wuthering waves, 1girl, black gloves, blonde hair, blue eyes, gloves, hair ornament, hat, long hair, long sleeves, shirt, skirt, tacet mark (wuthering waves), thighs, very long hair, white hat, white pantyhose, white shirt, white skirt, x hair ornament",
                         "residual_prompt": "", "model": None, "style_prompt": "", "generic_prompt": ""}]},
            {"id": "sample_yvonne", "character": "伊冯", "recommendation": "使用 CKXL @ 0.55",
             "annotation_tags": [], "scheme": "tags",
             "negative_prompt": "lowres, bad anatomy, worst quality",
             "images": [{"path": sample if exists else "", "thumb_url": thumb,
                         "width": 883, "height": 858,
                         "full_prompt": "yvonne (arknights), black horns, blush, breasts, cone hair bun, cowboy shot, double bun, fingernails, hair bun, hair intakes, hair ornament, horns, long hair, multicolored hair, navel, pants, pink hair, pointy ears, ringed eyes, sidelocks, stomach, streaked hair, tail, thick eyebrows, very long hair, white pants",
                         "residual_prompt": "", "model": None, "style_prompt": "", "generic_prompt": ""}]},
        ):
            self.storage.add_item(item)

    # ---------------- items ----------------

    def save_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        item_id = item.get("id")
        if item_id:
            updated = self.storage.update_item(item_id, item)
            if updated:
                return {"success": True, "item": updated}
        return {"success": True, "item": self.storage.add_item(item)}

    def delete_item(self, item_id: str) -> Dict[str, Any]:
        return {"success": self.storage.delete_item(item_id)}

    def clear_items(self) -> Dict[str, Any]:
        return {"success": self.storage.clear_items()}

    def reorder_items(self, item_ids: List[str]) -> Dict[str, Any]:
        return {"success": self.storage.reorder_items(item_ids)}

    def add_blank_item(self, category_id: str = "") -> Dict[str, Any]:
        fallback = self.storage.categories[0]["id"] if self.storage.categories else ""
        item = self.storage.add_item({
            "character": "新条目",
            "category_id": category_id or fallback,
            "scheme": "tags",
            "family": "",
            "annotation_tags": [],
            "recommendation": "",
            "negative_prompt": "",
            "images": [{"path": "", "thumb_url": "", "width": 0, "height": 0,
                        "full_prompt": "1girl, solo, masterpiece, best quality",
                        "residual_prompt": "", "model": None,
                        "style_prompt": "", "generic_prompt": ""}],
        })
        return {"success": True, "item": item}

    # ---------------- images within entry ----------------

    def add_images_to_entry(self, item_id: str, paths: List[str]) -> Dict[str, Any]:
        added = 0
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            meta = extract_png_metadata(p)
            self.storage.add_image(item_id, {
                "path": p,
                "thumb_url": self.storage.generate_thumbnail(p),
                "width": meta["width"], "height": meta["height"],
                "full_prompt": meta.get("prompt", ""),
                "model": {"name": meta.get("model", ""), "type": "", "lib_id": ""}
                if meta.get("model") else None,
            })
            added += 1
        return {"success": added > 0, "added": added, "item": self.storage.get_item(item_id)}

    def remove_entry_image(self, item_id: str, image_id: str) -> Dict[str, Any]:
        return {"success": self.storage.remove_image(item_id, image_id) is not None,
                "item": self.storage.get_item(item_id)}

    def set_primary_image(self, item_id: str, image_id: str) -> Dict[str, Any]:
        item = self.storage.get_item(item_id)
        if not item:
            return {"success": False}
        imgs = item["images"]
        target = next((im for im in imgs if im.get("id") == image_id), None)
        if not target:
            return {"success": False}
        item["images"] = [target] + [im for im in imgs if im.get("id") != image_id]
        self.storage.save()
        return {"success": True, "item": item}

    def replace_entry_image(self, item_id: str, image_id: str, new_path: str = "") -> Dict[str, Any]:
        path = new_path or self._pick_single_image()
        if not path:
            return {"success": False, "message": "已取消选择"}
        if not os.path.exists(path):
            return {"success": False, "message": "所选文件不存在"}
        meta = extract_png_metadata(path)
        updates = {
            "path": path,
            "thumb_url": self.storage.generate_thumbnail(path),
            "width": meta["width"], "height": meta["height"],
        }
        if meta.get("prompt"):
            updates["full_prompt"] = meta["prompt"]
        item = self.storage.update_image(item_id, image_id, updates)
        return {"success": bool(item), "item": item, "meta": meta}

    def reparse_entry_image(self, item_id: str, image_id: str) -> Dict[str, Any]:
        item = self.storage.get_item(item_id)
        if not item:
            return {"success": False, "message": "条目不存在"}
        im = next((i for i in item["images"] if i.get("id") == image_id), None)
        if not im:
            return {"success": False, "message": "图片不存在"}
        path = im.get("path", "")
        if not path or not os.path.exists(path):
            return {"success": False, "message": "该图没有可解析的原图"}
        meta = extract_png_metadata(path)
        updates = {"width": meta["width"], "height": meta["height"]}
        if meta.get("prompt"):
            updates["full_prompt"] = meta["prompt"]
        if meta.get("recommendation"):
            item["recommendation"] = meta["recommendation"]
        if meta.get("negative_prompt"):
            item["negative_prompt"] = meta["negative_prompt"]
        if meta.get("model"):
            updates["model"] = {"name": meta["model"], "type": "", "lib_id": ""}
        self.storage.update_image(item_id, image_id, updates)
        self.storage.save()
        return {"success": True, "item": self.storage.get_item(item_id)}

    # ---------------- categories ----------------

    def get_categories(self) -> List[Dict[str, Any]]:
        return self.storage.get_categories()

    def add_category(self, name: str, color: str = "#6366f1") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"success": False, "message": "分区名称不能为空"}
        if any(c.get("name") == name for c in self.storage.get_categories()):
            return {"success": False, "message": f"分区「{name}」已存在"}
        cat = self.storage.add_category(name, color)
        return {"success": True, "category": cat, "categories": self.storage.get_categories()}

    def rename_category(self, cat_id: str, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"success": False, "message": "分区名称不能为空"}
        return {"success": self.storage.rename_category(cat_id, name),
                "categories": self.storage.get_categories()}

    def delete_category(self, cat_id: str) -> Dict[str, Any]:
        if len(self.storage.get_categories()) <= 1:
            return {"success": False, "message": "至少需要保留一个分区"}
        ok = self.storage.delete_category(cat_id)
        return {"success": ok, "categories": self.storage.get_categories(), "items": self.storage.items}

    # ---------------- model library ----------------

    def get_library(self) -> Dict[str, Any]:
        return self.library.state()

    def rescan_models(self) -> Dict[str, Any]:
        return self.library.rescan()

    def pick_folder(self) -> str:
        if not self._window:
            return ""
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return ""
        return result if isinstance(result, str) else result[0]

    def add_model_root(self, path: str = "") -> Dict[str, Any]:
        if not path:
            path = self.pick_folder()
        if not path:
            return {"success": False, "message": "已取消选择"}
        res = self.library.add_root(path)
        self.library.rescan()
        return {"success": True, **res}

    def remove_model_root(self, path: str) -> Dict[str, Any]:
        return {"success": True, **self.library.remove_root(path)}

    def hash_model(self, model_id: str) -> Dict[str, Any]:
        return self.library.start_hash(model_id)

    def hash_all_models(self) -> Dict[str, Any]:
        return self.library.hash_missing()

    def sync_all_models(self) -> Dict[str, Any]:
        return self.library.sync_all()

    def get_family_options(self) -> List[str]:
        """Live list of model families (folder-driven; renames show up at once)."""
        return self.library.family_options()

    def sync_model_civitai(self, model_id: str) -> Dict[str, Any]:
        return self.library.sync_civitai(model_id)

    def sync_or_hash(self, model_id: str) -> Dict[str, Any]:
        return self.library.sync_or_hash(model_id)

    def open_data_folder(self) -> Dict[str, Any]:
        try:
            os.startfile(self.storage.data_dir)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def open_model_page(self, model_id: str) -> Dict[str, Any]:
        return self.library.open_page(model_id)

    def open_civitai_search(self, name: str) -> Dict[str, Any]:
        return self.library.open_search(name)

    def add_manual_model(self, name: str, mtype: str, base_model: str, version: str) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {"success": False, "message": "模型名称不能为空"}
        rec = self.library.add_manual(name, mtype, base_model.strip(), version.strip())
        return {"success": True, "model": rec}

    def update_library_model(self, model_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        rec = self.library.update_model(model_id, updates)
        return {"success": bool(rec), "model": rec}

    def delete_library_model(self, model_id: str) -> Dict[str, Any]:
        return {"success": self.library.remove_model(model_id)}

    def open_in_explorer(self, path: str) -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {"success": False, "message": "文件不存在或已被移动"}
        try:
            subprocess.run(["explorer", f"/select,{os.path.normpath(path)}"], check=False)
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ---------------- image import ----------------

    def pick_images(self) -> List[str]:
        if not self._window:
            return []
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                                 file_types=IMAGE_FILTER)
        return list(result) if result else []

    def import_image_paths(self, paths: List[str], category_id: str = "") -> List[Dict[str, Any]]:
        added = []
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for fn in sorted(files):
                        if fn.lower().endswith(MEDIA_EXTS):
                            item = self._image_to_item(os.path.join(root, fn), category_id)
                            if item:
                                added.append(item)
            else:
                item = self._image_to_item(p, category_id)
                if item:
                    added.append(item)
        return added

    def _pick_single_image(self) -> str:
        if not self._window:
            return ""
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                                 file_types=IMAGE_FILTER)
        if not result:
            return ""
        return result if isinstance(result, str) else result[0]

    def _resolve_family(self, meta: Dict[str, Any]) -> str:
        """Best-effort: match the image's checkpoint or LoRA name against the
        model library and reuse that model's family folder as the item marker."""
        names = []
        if meta.get("model"):
            names.append(meta["model"])
        for lname in re.findall(r'<lora:([^:>]+)', meta.get("prompt") or ""):
            names.append(lname.strip())
        for name in names:
            if not name:
                continue
            rec = self.library.find_by_name(name)
            if rec and rec.get("family"):
                return rec["family"]
        return ""

    def _image_to_item(self, path: str, category_id: str) -> Optional[Dict[str, Any]]:
        try:
            meta = extract_png_metadata(path)
            return self.storage.add_item({
                "character": meta["character"],
                "category_id": category_id,
                "family": self._resolve_family(meta),
                "recommendation": meta.get("recommendation", ""),
                "negative_prompt": meta.get("negative_prompt", ""),
                "model": meta.get("model", ""),
                "scheme": "tags",
                "annotation_tags": [],
                "images": [{
                    "path": path,
                    "thumb_url": self.storage.generate_thumbnail(path),
                    "width": meta["width"], "height": meta["height"],
                    "full_prompt": meta.get("prompt", ""),
                    "residual_prompt": "",
                    "model": {"name": meta["model"], "type": "", "lib_id": ""} if meta.get("model") else None,
                    "style_prompt": "", "generic_prompt": "",
                }],
            })
        except Exception as e:
            print(f"[Import] error {path}: {e}")
            return None

    # ---------------- excel ----------------

    def export_excel(self, category_id: str = "") -> Dict[str, Any]:
        if not self._window:
            return {"success": False, "message": "窗口未就绪"}
        result = self._window.create_file_dialog(webview.SAVE_DIALOG,
                                                 save_filename="AI提示词注释表.xlsx",
                                                 file_types=EXCEL_FILTER)
        if not result:
            return {"success": False, "message": "已取消保存"}
        target = result if isinstance(result, str) else result[0]
        if not target.lower().endswith(".xlsx"):
            target += ".xlsx"

        items = self.storage.items
        if category_id:
            items = [it for it in items if it.get("category_id") == category_id]
        cat_names = {c["id"]: c["name"] for c in self.storage.get_categories()}
        payload = [dict(it, category_name=cat_names.get(it.get("category_id"), "")) for it in items]
        ok, msg = export_to_excel(payload, target)
        return {"success": ok, "message": msg, "path": target}

    def import_excel(self, category_id: str = "") -> Dict[str, Any]:
        if not self._window:
            return {"success": False, "message": "窗口未就绪"}
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=EXCEL_FILTER)
        if not result:
            return {"success": False, "message": "已取消选择"}
        path = result if isinstance(result, str) else result[0]

        ok, rows, msg = import_from_excel(path)
        if not ok:
            return {"success": False, "message": msg}

        name_to_id = {c["name"]: c["id"] for c in self.storage.get_categories()}
        for row in rows:
            cat_name = (row.pop("category_name", "") or "").strip()
            if cat_name:
                if cat_name not in name_to_id:
                    cat = self.storage.add_category(cat_name)
                    name_to_id[cat_name] = cat["id"]
                row["category_id"] = name_to_id[cat_name]
            else:
                row["category_id"] = category_id

            img_path = row.get("image_path", "")
            self.storage.add_item({
                "character": row.get("character", "未命名"),
                "category_id": row.get("category_id", ""),
                "recommendation": row.get("recommendation", ""),
                "annotation_tags": [],
                "scheme": "tags",
                "images": [{
                    "path": img_path,
                    "thumb_url": self.storage.generate_thumbnail(img_path) if img_path else "",
                    "full_prompt": row.get("prompt", ""),
                    "residual_prompt": "",
                    "model": None, "style_prompt": "", "generic_prompt": "",
                    "width": 0, "height": 0,
                }],
            })

        cats = self.storage.get_categories()
        return {"success": True, "message": msg,
                "items": self.storage.items, "categories": cats}

    # ---------------- window commands (custom titlebar) ----------------

    def win32(self, action: str, arg: str = "") -> Any:
        if not self._window:
            return False
        try:
            return win32utils.window_command(self._window, action, arg)
        except Exception as e:
            print(f"[Win32] command failed: {e}")
            return False

    # ---------------- persisted UI settings ----------------

    def _settings_path(self) -> str:
        return os.path.join(self.storage.data_dir, "settings.json")

    def get_settings(self) -> Dict[str, Any]:
        """Small key/value store for display preferences (survives restarts)."""
        path = self._settings_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                print(f"[Settings] load failed: {e}")
        return {}

    def save_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(updates, dict):
            return {"success": False, "message": "无效的设置数据"}
        merged = self.get_settings()
        merged.update(updates)
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            return {"success": True, "settings": merged}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ---------------- misc ----------------

    def copy_text(self, text: str) -> bool:
        try:
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            p.communicate((text or "").encode("utf-8"))
            return True
        except Exception:
            return False