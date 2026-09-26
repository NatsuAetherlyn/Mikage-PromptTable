import os
import json
import base64
import time
import io
from typing import List, Dict, Any, Optional
from PIL import Image

DEFAULT_CATEGORIES = [
    {"id": "cat_character", "name": "人物", "color": "#6366f1"},
    {"id": "cat_costume", "name": "服饰", "color": "#38bdf8"},
    {"id": "cat_style", "name": "画风", "color": "#a855f7"},
    {"id": "cat_scene", "name": "场景", "color": "#10b981"},
]

_img_seq = {"n": 0}


def new_image_id() -> str:
    _img_seq["n"] += 1
    return f"img_{int(time.time() * 1000)}_{_img_seq['n']}"


def migrate_item(item: Dict[str, Any], fallback_cat: str) -> Dict[str, Any]:
    """Upgrade a v1 item (single image_path/prompt) to the v2 multi-image model."""
    images = item.get("images")
    if not isinstance(images, list):
        images = []
        if item.get("image_path") or item.get("thumb_url"):
            images = [{
                "path": item.get("image_path", "") or "",
                "thumb_url": item.get("thumb_url", "") or "",
                "width": item.get("width", 0) or 0,
                "height": item.get("height", 0) or 0,
                "full_prompt": item.get("prompt", "") or "",
            }]
        item["images"] = images

    for im in images:
        im.setdefault("id", new_image_id())
        im.setdefault("path", "")
        im.setdefault("thumb_url", "")
        im.setdefault("width", 0)
        im.setdefault("height", 0)
        im.setdefault("full_prompt", im.get("prompt", "") or "")
        im.setdefault("residual_prompt", "")
        im.setdefault("model", None)          # {"name": str, "type": str, "lib_id": str}
        im.setdefault("style_prompt", "")
        im.setdefault("generic_prompt", "")
        im.pop("prompt", None)

    item.setdefault("annotation_tags", [])
    item.setdefault("scheme", "tags")          # 'tags' | 'model'
    item.setdefault("family", "")            # model family marker (Anima / Krea 2 / ...)
    item.setdefault("recommendation", "")
    item.setdefault("negative_prompt", "")
    item.setdefault("model", "")
    item.setdefault("notes", "")
    item.setdefault("category_id", fallback_cat)

    # ---- v3: shared-vs-per-image fields ----
    # Tag mode   : models live on the item (shared); prompts live on each image
    # Model mode : models live on each image; prompts live on the item (shared)
    item.setdefault("models", [])              # [{name, type, lib_id}]
    item.setdefault("shared_prompt", "")
    item.setdefault("shared_style", "")
    item.setdefault("shared_generic", "")
    item.setdefault("slideshow", {"mode": "off", "auto": False, "interval": 1500})

    if not isinstance(item.get("models"), list):
        item["models"] = []
    item["models"] = [c for c in (_clean_model(m) for m in item["models"]) if c]

    ss = item.get("slideshow")
    if not isinstance(ss, dict):
        ss = {"mode": "off", "auto": False, "interval": 1500}
    ss.setdefault("mode", "off")
    ss.setdefault("auto", False)
    try:
        ss["interval"] = max(300, int(ss.get("interval", 1500)))
    except (TypeError, ValueError):
        ss["interval"] = 1500
    item["slideshow"] = ss

    for im in images:
        # v2 kept a single `model` object; v3 uses a list so a checkpoint and
        # its LoRAs can coexist.
        legacy = im.pop("model", None)
        if not isinstance(im.get("models"), list):
            im["models"] = []
        if isinstance(legacy, dict) and legacy.get("name"):
            if not any((m or {}).get("name") == legacy["name"] for m in im["models"]):
                im["models"].append(legacy)
        im["models"] = [c for c in (_clean_model(m) for m in im["models"]) if c]

    for legacy in ("image_path", "prompt", "thumb_url"):
        item.pop(legacy, None)
    return item


def _clean_model(m):
    """Normalise a model reference; returns None when there is no name."""
    if not isinstance(m, dict):
        return None
    name = str(m.get("name") or "").strip()
    if not name:
        return None
    mtype = str(m.get("type") or "").strip().lower()
    if mtype not in ("checkpoint", "lora"):
        mtype = ""
    return {"name": name, "type": mtype, "lib_id": str(m.get("lib_id") or "")}


class StorageManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.data_file = os.path.join(data_dir, "gallery_data.json")
        self.file_existed = os.path.exists(self.data_file)
        self.items: List[Dict[str, Any]] = []
        self.categories: List[Dict[str, Any]] = []
        self.load()

    # ---------- load / save ----------

    def load(self, path: Optional[str] = None) -> List[Dict[str, Any]]:
        target = path or self.data_file
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.items, self.categories = data, list(DEFAULT_CATEGORIES)
                elif isinstance(data, dict):
                    self.items = data.get("items", [])
                    self.categories = data.get("categories") or list(DEFAULT_CATEGORIES)
            except Exception as e:
                print(f"[Storage] load failed {target}: {e}")
                self.items, self.categories = [], list(DEFAULT_CATEGORIES)
        else:
            self.items, self.categories = [], list(DEFAULT_CATEGORIES)

        fallback = self.categories[0]["id"] if self.categories else ""
        self.items = [migrate_item(it, fallback) for it in self.items]
        return self.items

    def save(self, path: Optional[str] = None) -> bool:
        target = path or self.data_file
        try:
            parent = os.path.dirname(os.path.abspath(target))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump({
                    "version": "3.0",
                    "updated_at": time.time(),
                    "categories": self.categories,
                    "items": self.items,
                }, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[Storage] save failed {target}: {e}")
            return False

    def prune_placeholders(self) -> Dict[str, int]:
        """Drop entries that only exist as placeholders.

        An entry with no image at all (or whose images never got a path) renders
        as a "未绑定图片" card forever, so it is removed automatically. Images
        whose file is merely *missing* are kept: a disconnected drive or a moved
        folder must not silently destroy the user's annotations.
        """
        kept, images_dropped, entries_dropped = [], 0, 0
        for it in self.items:
            imgs = list(it.get("images") or [])
            usable = [im for im in imgs if (im or {}).get("path")]
            images_dropped += len(imgs) - len(usable)
            if not usable:
                entries_dropped += 1
                continue
            it["images"] = usable
            kept.append(it)
        if entries_dropped or images_dropped:
            self.items = kept
            self.save()
        return {"entries": entries_dropped, "images": images_dropped}

    # ---------- items ----------

    def add_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        fallback = self.categories[0]["id"] if self.categories else ""
        if "id" not in item or not item["id"]:
            item["id"] = f"item_{int(time.time() * 1000)}_{len(self.items) + 1}"
        item.setdefault("created_at", time.time())
        item.setdefault("category_id", fallback)
        migrate_item(item, fallback)
        self.items.append(item)
        self.save()
        return item

    def update_item(self, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for it in self.items:
            if it.get("id") == item_id:
                it.update(updates)
                migrate_item(it, it.get("category_id", ""))
                it["updated_at"] = time.time()
                self.save()
                return it
        return None

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return next((it for it in self.items if it.get("id") == item_id), None)

    def delete_item(self, item_id: str) -> bool:
        n = len(self.items)
        self.items = [it for it in self.items if it.get("id") != item_id]
        if len(self.items) != n:
            self.save()
            return True
        return False

    def clear_items(self) -> bool:
        self.items = []
        self.save()
        return True

    def reorder_items(self, item_ids: List[str]) -> bool:
        id_map = {it.get("id"): it for it in self.items}
        ordered = [id_map[i] for i in item_ids if i in id_map]
        ordered += [it for it in self.items if it.get("id") not in item_ids]
        self.items = ordered
        self.save()
        return True

    # ---------- images within an item ----------

    def add_image(self, item_id: str, image: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        item = self.get_item(item_id)
        if not item:
            return None
        image.setdefault("id", new_image_id())
        for k in ("path", "thumb_url", "full_prompt", "residual_prompt", "style_prompt", "generic_prompt"):
            image.setdefault(k, "")
        for k in ("width", "height"):
            image.setdefault(k, 0)
        image.setdefault("model", None)
        item["images"].append(image)
        item["updated_at"] = time.time()
        self.save()
        return item

    def update_image(self, item_id: str, image_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        item = self.get_item(item_id)
        if not item:
            return None
        for im in item["images"]:
            if im.get("id") == image_id:
                im.update(updates)
                item["updated_at"] = time.time()
                self.save()
                return item
        return None

    def remove_image(self, item_id: str, image_id: str) -> Optional[Dict[str, Any]]:
        item = self.get_item(item_id)
        if not item:
            return None
        item["images"] = [im for im in item["images"] if im.get("id") != image_id]
        item["updated_at"] = time.time()
        self.save()
        return item

    # ---------- categories ----------

    def get_categories(self) -> List[Dict[str, Any]]:
        if not self.categories:
            self.categories = list(DEFAULT_CATEGORIES)
            self.save()
        return self.categories

    def add_category(self, name: str, color: str = "#6366f1") -> Dict[str, Any]:
        cat = {"id": f"cat_{int(time.time() * 1000)}", "name": name, "color": color}
        self.categories.append(cat)
        self.save()
        return cat

    def rename_category(self, cat_id: str, name: str) -> bool:
        for c in self.categories:
            if c.get("id") == cat_id:
                c["name"] = name
                self.save()
                return True
        return False

    def delete_category(self, cat_id: str) -> bool:
        before = len(self.categories)
        self.categories = [c for c in self.categories if c.get("id") != cat_id]
        fallback = self.categories[0]["id"] if self.categories else ""
        for it in self.items:
            if it.get("category_id") == cat_id:
                it["category_id"] = fallback
        if len(self.categories) != before:
            self.save()
            return True
        return False

    # ---------- thumbnails ----------

    VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm')

    @staticmethod
    def generate_thumbnail(image_path: str, max_size: int = 620) -> str:
        if not image_path or not os.path.exists(image_path):
            return ""
        # videos are rendered by the browser itself (first frame), no PIL involved
        if os.path.splitext(image_path)[1].lower() in StorageManager.VIDEO_EXTS:
            return ""
        try:
            with Image.open(image_path) as img:
                # animated GIF / WebP / APNG: grab a representative frame
                try:
                    if getattr(img, "is_animated", False):
                        total = getattr(img, "n_frames", 1) or 1
                        if total > 1:
                            img.seek(min(total - 1, max(1, total // 4)))
                except Exception:
                    pass

                if img.mode in ("P", "PA"):
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", img.size, (16, 20, 32))
                    bg.paste(img, mask=img.split()[-1])
                    img_to_save = bg
                elif img.mode != "RGB":
                    img_to_save = img.convert("RGB")
                else:
                    img_to_save = img

                w, h = img_to_save.size
                if w > max_size or h > max_size:
                    ratio = min(max_size / w, max_size / h)
                    thumb = img_to_save.resize(
                        (max(1, int(w * ratio)), max(1, int(h * ratio))),
                        Image.Resampling.LANCZOS)
                else:
                    thumb = img_to_save
                buf = io.BytesIO()
                thumb.save(buf, format="WEBP", quality=84, method=4)
                return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            print(f"[Thumbnail] failed {image_path}: {e}")
            return ""