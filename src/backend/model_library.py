import os
import json
import time
import hashlib
import threading
import urllib.request
import urllib.error
import webbrowser
from typing import List, Dict, Any, Optional
from urllib.parse import quote

MODEL_EXTS = ('.safetensors', '.ckpt', '.pt', '.sft', '.gguf')
# only these three folders are part of the model library; everything else
# (controlnet / vae / embeddings / ...) is ignored
LIBRARY_FOLDERS = ("checkpoints", "diffusion_models", "loras")
CIVITAI_API = "https://civitai.com/api/v1/model-versions/by-hash/{sha}"
REQUEST_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MikagePromptTable/1.0"


class ModelLibrary:
    """Local model registry: scans ComfyUI-style model roots, computes SHA256,
    syncs metadata from Civitai, groups models by base-model family (大类)."""

    def __init__(self, data_dir: str, default_root: str = ""):
        self.library_file = os.path.join(data_dir, "model_library.json")
        self.models: List[Dict[str, Any]] = []
        self.roots: List[Dict[str, Any]] = []
        self.scanning = False
        self._load()
        if not self.roots and default_root and os.path.isdir(default_root):
            self.roots = [{"path": os.path.normpath(default_root), "label": "ComfyUI"}]
            self._save()
        self.enforce_scope()

    # ---------- persistence ----------

    def _load(self):
        if not os.path.exists(self.library_file):
            return
        try:
            with open(self.library_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.models = data.get("models", [])
            self.roots = data.get("roots", [])
        except Exception as e:
            print(f"[Library] load failed: {e}")
            self.models, self.roots = [], []

    def scope_of(self, path: str):
        """Resolve (top_folder, family) for a model path, relative to a scan root.
        Returns None when the file is not directly inside one of the three
        library folders of any registered root."""
        if not path:
            return None
        norm = os.path.normpath(path)
        for root in self.roots:
            base = os.path.normpath(root.get("path", "") or "")
            if not base:
                continue
            base_name = os.path.basename(base).lower()
            try:
                rel = os.path.relpath(norm, base)
            except ValueError:
                continue
            if rel == "." or rel.startswith(".."):
                continue
            parts = rel.replace("\\", "/").split("/")
            if base_name in LIBRARY_FOLDERS:
                # the root itself is a library folder
                top = base_name
                family = parts[0] if len(parts) > 1 else ""
                return top, family
            if len(parts) < 2:
                continue
            top = parts[0].lower()
            if top not in LIBRARY_FOLDERS:
                continue
            family = parts[1] if len(parts) > 2 else ""
            return top, family
        return None

    def enforce_scope(self) -> int:
        """Keep only records inside checkpoints/diffusion_models/loras and refresh
        the derived `top` / `family` fields. Returns how many were dropped."""
        before = len(self.models)
        kept = []
        for m in self.models:
            p = m.get("path")
            if not p:
                kept.append(m)              # manual entries carry no path
                continue
            scope = self.scope_of(p)
            if not scope:
                continue                    # outside the three folders
            top, family = scope
            m["top"] = top
            m["family"] = family
            m["type"] = "lora" if top == "loras" else "checkpoint"
            kept.append(m)
        self.models = kept
        removed = before - len(kept)
        if removed:
            self._save()
        return removed

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.library_file), exist_ok=True)
            with open(self.library_file, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "roots": self.roots, "models": self.models},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Library] save failed: {e}")

    # ---------- roots ----------

    def add_root(self, path: str, label: str = "") -> Dict[str, Any]:
        path = os.path.normpath(path)
        if not any(os.path.normpath(r["path"]).lower() == path.lower() for r in self.roots):
            self.roots.append({"path": path, "label": label or os.path.basename(path)})
            self._save()
        return {"roots": self.roots}

    def remove_root(self, path: str) -> Dict[str, Any]:
        target = os.path.normpath(path).lower()
        self.roots = [r for r in self.roots if os.path.normpath(r["path"]).lower() != target]
        self._save()
        return {"roots": self.roots}

    # ---------- scanning ----------

    def rescan(self) -> Dict[str, Any]:
        if self.scanning:
            return {"scanning": True}
        self.scanning = True
        threading.Thread(target=self._scan_worker, daemon=True).start()
        return {"scanning": True}

    def _scan_worker(self):
        try:
            known = {os.path.normpath(m["path"]).lower() for m in self.models if m.get("path")}
            for root in self.roots:
                base = os.path.normpath(root.get("path", ""))
                if not base or not os.path.isdir(base):
                    continue
                for scan_base, top_name in library_scan_targets(base):
                    for dirpath, dirnames, filenames in os.walk(scan_base):
                        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                        for fn in filenames:
                            if not fn.lower().endswith(MODEL_EXTS):
                                continue
                            full = os.path.normpath(os.path.join(dirpath, fn))
                            if full.lower() in known:
                                continue
                            rel_dir = os.path.relpath(dirpath, scan_base).replace("\\", "/")
                            family = "" if rel_dir in (".", "") else rel_dir.split("/")[0]
                            top, _ = (top_name, family)
                            rec = {
                                "id": f"mdl_{int(time.time() * 1000)}_{len(self.models)}",
                                "name": os.path.splitext(fn)[0],
                                "filename": fn,
                                "path": full,
                                "top": top or top_name,
                                "family": family,
                                "type": "lora" if (top or top_name) == "loras" else "checkpoint",
                                "base_model": "",
                                "version": "",
                                "sha256": None,
                                "hash_status": "none",
                                "civitai": None,
                                "preview_path": "",
                                "added_at": time.time(),
                            }
                            apply_lora_manager_sidecar(rec)
                            self.models.append(rec)
                            known.add(full.lower())
            # restrict to the three library folders and refresh family fields
            self.enforce_scope()
            # backfill sidecar metadata for records created before this scan
            for rec in self.models:
                if rec.get("path") and os.path.exists(rec["path"]):
                    apply_lora_manager_sidecar(rec, fill_only=True)
            # drop records whose file vanished (manual entries keep empty path)
            self.models = [m for m in self.models
                           if not m.get("path") or os.path.exists(m["path"])]
            self._save()
        except Exception as e:
            print(f"[Library] scan error: {e}")
        finally:
            self.scanning = False

    @staticmethod
    def _family_key(name: str) -> str:
        """Merge key: letters/digits only, lowercased — so 'Krea2' and 'Krea 2'
        collapse into one option."""
        return "".join(ch for ch in str(name).lower() if ch.isalnum())

    def family_options(self, require_files: bool = True) -> List[str]:
        """First-level folders under checkpoints/ and diffusion_models/ of every
        registered root. Same-named folders are merged; empty placeholder folders
        (e.g. 'put_models_here') are skipped. Read live from disk on every call so
        renames show up immediately. loras is intentionally excluded."""
        merged = {}
        for root in self.roots:
            base = os.path.normpath(root.get("path", "") or "")
            if not base or not os.path.isdir(base):
                continue
            targets = []
            if os.path.basename(base).lower() in ("checkpoints", "diffusion_models"):
                targets.append(base)
            else:
                for folder in ("checkpoints", "diffusion_models"):
                    cand = os.path.join(base, folder)
                    if os.path.isdir(cand):
                        targets.append(cand)

            for folder_path in targets:
                try:
                    entries = sorted(os.listdir(folder_path))
                except OSError:
                    continue
                for entry in entries:
                    if entry.startswith('.'):
                        continue
                    sub = os.path.join(folder_path, entry)
                    if not os.path.isdir(sub):
                        continue
                    if require_files and not folder_has_models(sub):
                        continue
                    key = self._family_key(entry)
                    if not key:
                        continue
                    prev = merged.get(key)
                    # prefer the more readable spelling (contains a space) over 'Krea2'
                    if prev is None or (' ' not in prev and ' ' in entry):
                        merged[key] = entry
        return sorted(merged.values(), key=lambda s: s.lower())

    def state(self) -> Dict[str, Any]:
        return {
            "roots": self.roots,
            "models": self.models,
            "scanning": self.scanning,
            "families": self.family_options(),
        }

    # ---------- hashing ----------

    def start_hash(self, model_id: str) -> Dict[str, Any]:
        rec = self._find(model_id)
        if not rec:
            return {"success": False, "message": "模型不存在"}
        if rec.get("hash_status") == "hashing":
            return {"success": True, "message": "正在计算中"}
        if rec.get("sha256"):
            return {"success": True, "message": "已有哈希"}

        path = rec.get("path")
        if not path or not os.path.exists(path):
            return {"success": False, "message": "模型文件不存在（可能是手动添加的条目）"}

        def worker():
            rec["hash_status"] = "hashing"
            self._save()
            try:
                rec["sha256"] = sha256_file(path)
                rec["hash_status"] = "done"
                rec.pop("hash_error", None)
            except Exception as e:
                rec["hash_status"] = "error"
                rec["hash_error"] = str(e)
            self._save()
            if rec.get("sha256") and rec.pop("auto_sync", False):
                try:
                    self.sync_civitai(rec["id"])
                except Exception as e:
                    print(f"[Library] auto-sync failed: {e}")

        threading.Thread(target=worker, daemon=True).start()
        return {"success": True}

    def sync_all(self) -> Dict[str, Any]:
        """One-click: hash everything missing (auto-sync afterwards), and
        directly sync records that already have a hash but no Civitai data."""
        hash_queued = 0
        to_sync_now = []
        for rec in self.models:
            if rec.get("civitai"):
                continue
            if rec.get("sha256"):
                to_sync_now.append(rec)
            elif rec.get("path") and os.path.exists(rec["path"])                     and rec.get("hash_status") in ("none", "error"):
                rec["auto_sync"] = True
                self.start_hash(rec["id"])
                hash_queued += 1
        if to_sync_now:
            threading.Thread(target=self._sync_sequential, daemon=True).start()
        return {"success": True, "hash_queued": hash_queued, "sync_queued": len(to_sync_now)}

    def _sync_sequential(self):
        time.sleep(0.8)
        for rec in list(self.models):
            if rec.get("civitai") or not rec.get("sha256"):
                continue
            self.sync_civitai(rec["id"])
            time.sleep(0.4)

    def hash_missing(self, limit: int = 3) -> Dict[str, Any]:
        hashing = sum(1 for m in self.models if m.get("hash_status") == "hashing")
        started = 0
        for rec in self.models:
            if hashing + started >= limit:
                break
            if rec.get("path") and not rec.get("sha256") and rec.get("hash_status") != "hashing":
                self.start_hash(rec["id"])
                started += 1
        return {"success": True, "started": started}

    # ---------- civitai ----------

    def sync_civitai(self, model_id: str) -> Dict[str, Any]:
        rec = self._find(model_id)
        if not rec:
            return {"success": False, "message": "模型不存在"}
        sha = rec.get("sha256")
        if not sha:
            return {"success": False, "message": "请先计算文件哈希"}

        url = CIVITAI_API.format(sha=sha)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": REQUEST_UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"success": False, "message": "Civitai 上未找到该哈希对应的模型"}
            return {"success": False, "message": f"Civitai 请求失败: HTTP {e.code}"}
        except Exception as e:
            return {"success": False, "message": f"网络错误: {e}"}

        model = payload.get("model") or {}
        civitai = {
            "version_id": payload.get("id"),
            "model_id": payload.get("modelId"),
            "version_name": payload.get("name", ""),
            "model_name": model.get("name", ""),
            "type": model.get("type", ""),
            "base_model": payload.get("baseModel", ""),
            "trained_words": ", ".join(payload.get("trainedWords") or []),
            "page": civitai_page_url(payload.get("modelId"), payload.get("id")),
        }
        images = payload.get("images") or []
        if images and isinstance(images[0], dict):
            civitai["cover"] = images[0].get("url", "")

        rec["civitai"] = civitai
        if civitai.get("base_model") and not rec.get("base_model"):
            rec["base_model"] = civitai["base_model"]
        if civitai.get("version_name") and not rec.get("version"):
            rec["version"] = civitai["version_name"]
        if civitai.get("type"):
            t = civitai["type"].lower()
            if "lora" in t or "locon" in t or "lycoris" in t:
                rec["type"] = "lora"
            elif "checkpoint" in t:
                rec["type"] = "checkpoint"
        self._save()
        return {"success": True, "model": rec}

    def sync_or_hash(self, model_id: str) -> Dict[str, Any]:
        """User-facing sync: if the hash is missing, compute it first and chain
        straight into the Civitai sync; otherwise sync immediately."""
        rec = self._find(model_id)
        if not rec:
            return {"success": False, "message": "模型不存在"}

        if rec.get("sha256"):
            return self.sync_civitai(model_id)

        path = rec.get("path")
        if not path or not os.path.exists(path):
            return {"success": False,
                    "message": "该条目没有本地文件也没有已知哈希，无法按哈希匹配 Civitai"}

        rec["auto_sync"] = True
        if rec.get("hash_status") == "hashing":
            return {"success": True, "queued": True}
        self.start_hash(model_id)
        return {"success": True, "queued": True}

    def open_page(self, model_id: str) -> Dict[str, Any]:
        rec = self._find(model_id)
        if not rec:
            return {"success": False, "message": "模型不存在"}
        page = (rec.get("civitai") or {}).get("page")
        if page:
            webbrowser.open(page)
            return {"success": True}
        if rec.get("sha256"):
            self.sync_civitai(model_id)
            page = (self._find(model_id).get("civitai") or {}).get("page")
            if page:
                webbrowser.open(page)
                return {"success": True, "synced": True}
            return {"success": False, "message": "同步失败，无法打开模型页"}
        webbrowser.open(civitai_search_url(rec.get("name", "")))
        return {"success": True, "search": True}

    def open_search(self, name: str) -> Dict[str, Any]:
        webbrowser.open(civitai_search_url(name))
        return {"success": True}

    # ---------- manual records ----------

    def add_manual(self, name: str, mtype: str, base_model: str, version: str) -> Dict[str, Any]:
        rec = {
            "id": f"mdl_{int(time.time() * 1000)}",
            "name": name,
            "filename": "",
            "path": "",
            "type": mtype if mtype in ("checkpoint", "lora") else "lora",
            "base_model": base_model,
            "version": version,
            "sha256": None,
            "hash_status": "none",
            "civitai": None,
            "added_at": time.time(),
        }
        self.models.append(rec)
        self._save()
        return rec

    def update_model(self, model_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rec = self._find(model_id)
        if not rec:
            return None
        for k in ("name", "version", "base_model", "type"):
            if k in updates:
                rec[k] = updates[k]
        self._save()
        return rec

    def remove_model(self, model_id: str) -> bool:
        before = len(self.models)
        self.models = [m for m in self.models if m.get("id") != model_id]
        if len(self.models) != before:
            self._save()
            return True
        return False

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        n = name.strip().lower()
        return next((m for m in self.models if m.get("name", "").strip().lower() == n), None)

    # ---------- internals ----------

    def _find(self, model_id: str) -> Optional[Dict[str, Any]]:
        return next((m for m in self.models if m.get("id") == model_id), None)


# ---------------- helpers ----------------

def folder_has_models(folder: str, max_depth: int = 4) -> bool:
    """True when the folder (recursively, bounded) contains at least one model file."""
    depth = folder.replace("\\", "/").rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        if dirpath.replace("\\", "/").rstrip("/").count("/") - depth > max_depth:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower().endswith(MODEL_EXTS):
                return True
    return False


def library_scan_targets(base: str):
    """Yield (folder_to_walk, top_name). If `base` is itself one of the three
    library folders it is scanned directly; otherwise only its three subfolders."""
    name = os.path.basename(os.path.normpath(base)).lower()
    if name in LIBRARY_FOLDERS:
        yield base, name
        return
    for folder in LIBRARY_FOLDERS:
        cand = os.path.join(base, folder)
        if os.path.isdir(cand):
            yield cand, folder


def derive_scope(path: str):
    """Map a model path onto (top_folder, family).
    Family is the first subfolder under the top folder, e.g.
      .../loras/Anima/风格/x.safetensors -> ("loras", "Anima")
      .../checkpoints/Krea 2/x.safetensors -> ("checkpoints", "Krea 2")
      .../loras/x.safetensors -> ("loras", "")
    Returns ("", "") when the path is outside the three library folders."""
    if not path:
        return "", ""
    parts = os.path.normpath(path).replace("\\", "/").split("/")
    lower = [p.lower() for p in parts]
    idx = -1
    for i, p in enumerate(lower):
        if p in LIBRARY_FOLDERS:
            idx = i
    if idx < 0:
        return "", ""
    rest = parts[idx + 1:-1]          # drop the file name
    return lower[idx], (rest[0] if rest else "")


def classify_path(rel_lower: str) -> str:
    if "lora" in rel_lower or "lycoris" in rel_lower:
        return "lora"
    if "checkpoint" in rel_lower or "diffusion_models" in rel_lower or "unet" in rel_lower:
        return "checkpoint"
    return "unsorted"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def civitai_page_url(model_id, version_id) -> str:
    if not model_id:
        return ""
    url = f"https://civitai.com/models/{model_id}"
    if version_id:
        url += f"?modelVersionId={version_id}"
    return url


def civitai_search_url(name: str) -> str:
    return "https://civitai.com/models?query=" + quote(str(name))


# ---------------- Lora-Manager sidecar compatibility ----------------

def _sidecar_preview(directory: str, stem: str) -> str:
    for name in (stem + ".jpeg", stem + ".jpg", stem + ".png", stem + ".webp",
                 stem + ".preview.jpeg", stem + ".preview.png"):
        cand = os.path.join(directory, name)
        if os.path.exists(cand):
            return cand
    return ""


def apply_lora_manager_sidecar(rec: Dict[str, Any], fill_only: bool = False):
    """Read ComfyUI-Lora-Manager sidecar files next to the model file:
      <model>.metadata.json  and  <model>.jpeg/.png (preview)
    Fills sha256 (skips hashing), base_model, version, trained words and the
    local preview path. fill_only=True never overwrites existing values."""
    path = rec.get("path")
    if not path or not os.path.exists(path):
        return
    directory, filename = os.path.split(path)
    stem = os.path.splitext(filename)[0]

    if not rec.get("preview_path"):
        rec["preview_path"] = _sidecar_preview(directory, stem)

    meta_path = os.path.join(directory, filename + ".metadata.json")
    if not os.path.exists(meta_path):
        return
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return
    civ = meta.get("civitai") if isinstance(meta.get("civitai"), dict) else {}

    def set_if(field, value):
        if value is None or value == "":
            return
        if not rec.get(field) or not fill_only:
            rec[field] = value

    if meta.get("sha256") and not rec.get("sha256"):
        rec["sha256"] = str(meta["sha256"])
        rec["hash_status"] = "done"

    set_if("base_model", meta.get("base_model") or civ.get("baseModel"))
    set_if("version", civ.get("name") or meta.get("version"))
    if not fill_only and meta.get("model_name"):
        rec["name"] = meta["model_name"]

    if not rec.get("civitai"):
        rec["civitai"] = {}
    words = civ.get("trainedWords") or meta.get("tags")
    if isinstance(words, list) and words:
        rec["civitai"].setdefault("trained_words", ", ".join(str(w) for w in words))
    if civ.get("modelId") and civ.get("id"):
        rec["civitai"].setdefault(
            "page",
            f"https://civitai.com/models/{civ['modelId']}?modelVersionId={civ['id']}")
    rec["civitai"].setdefault("model_name", meta.get("model_name", ""))

    # preview: prefer local file, fall back to the recorded preview_url
    if not rec.get("preview_path"):
        pv = meta.get("preview_url")
        if isinstance(pv, str) and os.path.exists(pv):
            rec["preview_path"] = pv
        elif isinstance(pv, str) and pv.startswith("http"):
            rec["civitai"].setdefault("cover", pv)
