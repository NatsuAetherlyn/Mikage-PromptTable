import json
import re
import os
import struct
from typing import Dict, Any, Optional
from PIL import Image

def extract_png_metadata(image_path: str) -> Dict[str, Any]:
    """
    Extract AI generation metadata from PNG/JPEG/WEBP image files.
    Supports:
    - Stable Diffusion WebUI (A1111 / Forge / SD.Next)
    - ComfyUI (prompt JSON / workflow JSON)
    - NovelAI
    - Generic text chunks
    """
    result = {
        "prompt": "",
        "negative_prompt": "",
        "character": "",
        "recommendation": "",
        "model": "",
        "width": 0,
        "height": 0,
        "raw_info": {}
    }

    if not os.path.exists(image_path):
        return result

    ext = os.path.splitext(image_path)[1].lower()
    if ext in ('.mp4', '.mov', '.m4v', '.webm'):
        return extract_video_metadata(image_path, result)

    try:
        with Image.open(image_path) as img:
            result["width"], result["height"] = img.size
            info = dict(img.info) if hasattr(img, 'info') else {}
            result["raw_info"] = {k: str(v)[:500] for k, v in info.items() if isinstance(v, (str, int, float, bool))}

            # 1. SD WebUI / Forge format ('parameters' chunk)
            if "parameters" in info and isinstance(info["parameters"], str):
                params_text = info["parameters"]
                parse_sd_parameters(params_text, result)

            # 2. ComfyUI format ('prompt' and/or 'workflow' chunks)
            elif "prompt" in info or "workflow" in info:
                parse_comfyui_metadata(info, result)

            # 3. NovelAI format ('Description' or 'Comment')
            elif "Description" in info or "Comment" in info:
                desc = info.get("Description") or info.get("Comment") or ""
                if isinstance(desc, str):
                    result["prompt"] = desc.strip()
                    if "Software" in info and "NovelAI" in str(info["Software"]):
                        result["recommendation"] = "NovelAI 生成"

            # 4. Fallback: check other text keys
            elif "prompt" in info and isinstance(info["prompt"], str):
                result["prompt"] = info["prompt"].strip()

    except Exception as e:
        print(f"[Metadata] Error reading {image_path}: {e}")

    # Fallback for character name if not detected
    if not result["character"]:
        result["character"] = infer_character_from_filename_or_prompt(image_path, result["prompt"])

    # Fallback for recommendation if not detected
    if not result["recommendation"]:
        # Check if LoRA exists in prompt
        loras = re.findall(r'<lora:([^:>]+):([^>]+)>', result["prompt"])
        if loras:
            rec_parts = [f"LoRA: {name} @ {weight}" for name, weight in loras]
            result["recommendation"] = "; ".join(rec_parts)
        else:
            result["recommendation"] = "标准采样参数"

    return result


def parse_sd_parameters(params_text: str, result: Dict[str, Any]):
    """Parse standard Automatic1111 / SD WebUI parameters text."""
    # Split into sections: prompt, negative prompt, steps/generation info
    # Format:
    # <Positive Prompt>
    # Negative prompt: <Negative Prompt>
    # Steps: 20, Sampler: ..., Size: ...
    lines = params_text.strip().split("\n")
    pos_lines = []
    neg_lines = []
    meta_line = ""

    current_section = "pos"
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("Negative prompt:"):
            current_section = "neg"
            neg_lines.append(line_strip[len("Negative prompt:"):].strip())
        elif line_strip.startswith("Steps:") or "Sampler:" in line_strip:
            current_section = "meta"
            meta_line = line_strip
        else:
            if current_section == "pos":
                pos_lines.append(line)
            elif current_section == "neg":
                neg_lines.append(line)

    result["prompt"] = "\n".join(pos_lines).strip()
    result["negative_prompt"] = "\n".join(neg_lines).strip()

    # Parse metadata line
    if meta_line:
        # Extract Model
        model_match = re.search(r'Model:\s*([^,]+)', meta_line)
        if model_match:
            result["model"] = model_match.group(1).strip()

        # Extract LoRA or weights
        lora_matches = re.findall(r'LoRA hashes:\s*\"([^\"]+)\"', meta_line)
        model_hash = re.search(r'Model hash:\s*([^,]+)', meta_line)

        # Check for LoRA inside prompt tags, e.g. <lora:CKXL_Phoebe:0.5>
        loras = re.findall(r'<lora:([^:>]+):([^>]+)>', result["prompt"])
        if loras:
            rec_list = [f"使用 {name} @ {weight}" for name, weight in loras]
            result["recommendation"] = " / ".join(rec_list)
        elif result["model"]:
            result["recommendation"] = f"模型: {result['model']}"


def parse_comfyui_metadata(info: Dict[str, Any], result: Dict[str, Any]):
    """Parse a ComfyUI API-format graph (from a PNG chunk or an mp4 atom).

    Node types vary wildly between model families (CLIPTextEncode for SD,
    MiniMaxH3ImageToVideo for Minimax H3, checkpoint/unet loaders, assorted LoRA
    loaders...), so instead of enumerating node classes this scans every node's
    inputs for text prompts, LoRA references and model file names.
    """
    prompt_json = None
    if "prompt" in info:
        try:
            val = info["prompt"]
            prompt_json = json.loads(val) if isinstance(val, str) else val
        except Exception:
            prompt_json = None

    if not isinstance(prompt_json, dict):
        return

    NEG_HINTS = ("bad hand", "lowres", "low quality", "worst quality", "watermark",
                 "nsfw", "blurry", "jpeg artifact", "extra digit", "text, error")

    pos_prompts = []
    neg_prompts = []
    loras = []
    model_names = []

    for _node_id, node in prompt_json.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        for key, value in inputs.items():
            k = str(key).lower()

            # ---- prompts: any sizeable text-ish input ----
            if isinstance(value, str) and len(value) >= 12 and (
                    k in ("text", "prompt", "positive", "positive_prompt",
                          "negative", "negative_prompt", "description")
                    or "prompt" in k or "text" in k):
                text_value = value.strip()
                if not text_value:
                    continue
                lowered = text_value.lower()
                looks_negative = (
                    k.startswith("neg") or "negative" in k
                    or (len(text_value) < 600
                        and sum(1 for h in NEG_HINTS if h in lowered) >= 2)
                )
                if looks_negative:
                    neg_prompts.append(text_value)
                else:
                    pos_prompts.append(text_value)

            # ---- LoRA references on any loader node ----
            if isinstance(value, str) and "lora" in k and k.endswith("name") and value.strip():
                strength = None
                for sk in ("strength", "strength_model", "weight", "lora_strength"):
                    if sk in inputs:
                        strength = inputs.get(sk)
                        break
                clean = os.path.splitext(os.path.basename(value.replace("\\", "/")))[0]
                loras.append((clean, strength))

            # ---- checkpoint / unet file names ----
            if isinstance(value, str) and k in ("ckpt_name", "unet_name",
                                                "model_name", "checkpoint"):
                if value.strip():
                    model_names.append(
                        os.path.splitext(os.path.basename(value.replace("\\", "/")))[0])

        # fallback: a video/image-to-video node may carry the prompt under its
        # own widget name; capture any long string input once per node
        if not any(isinstance(v, str) and len(v) >= 12 for v in inputs.values()):
            for value in inputs.values():
                if isinstance(value, str) and len(value) >= 24:
                    pos_prompts.append(value.strip())
                    break

    if pos_prompts:
        result["prompt"] = max(pos_prompts, key=len)
    if neg_prompts:
        result["negative_prompt"] = max(neg_prompts, key=len)
    if model_names:
        result["model"] = model_names[0]

    if loras:
        seen = set()
        parts = []
        for name, strength in loras:
            if name in seen:
                continue
            seen.add(name)
            parts.append(f"{name} @ {strength}" if strength is not None else name)
        result["recommendation"] = "使用 " + " / ".join(parts)
    elif model_names:
        result["recommendation"] = f"模型: {model_names[0]}"


def infer_character_from_filename_or_prompt(image_path: str, prompt: str) -> str:
    """Infer a display name for the item.

    Danbooru-style prompts lead with the character tag ("phoebe (wuthering
    waves), ..."), which is what we want. Video/natural-language workflows start
    with sentences, so matches must be short and near the start of the prompt to
    count; otherwise the file name is the better source.
    """
    KNOWN = {
        "phoebe": "菲比", "yvonne": "伊冯", "cantarella": "坎特雷拉",
        "changli": "长离", "jinshi": "今汐", "yinlin": "吟霖",
        "shorekeeper": "守岸人", "chixia": "炽霞", "baizhi": "白芷",
        "danjin": "丹瑾", "yangyang": "秧秧", "rover": "漂泊者",
        "amiya": "阿米娅", "texas": "德克萨斯", "lappland": "拉普兰德",
        "skadi": "斯卡蒂", "surtr": "史尔特尔", "kal'tsit": "凯尔希",
        "mudrock": "泥岩", "chen qianyu": "陈千语", "perlica": "佩丽卡",
    }

    filename_stem = os.path.splitext(os.path.basename(image_path))[0]

    def from_filename():
        cleaned = re.sub(r'^\d+[-_]?', '', filename_stem)
        cleaned = re.sub(r'^(preview|sample|output|frame)[-_]?', '', cleaned, flags=re.I)
        cleaned = cleaned.replace('_', ' ').replace('-', ' ')
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = re.sub(r'\s*\d+\s*$', '', cleaned).strip()      # trailing index
        cleaned = re.sub(r'[\s_\-]+$', '', cleaned).strip()
        if cleaned and len(cleaned) > 1 and not cleaned.isdigit():
            low = cleaned.lower()
            if low in KNOWN:
                return KNOWN[low]
            return cleaned
        return "未命名人物"

    # Danbooru tag at the start of the prompt: "name (series)"
    head = (prompt or "").strip()[:160]
    m = re.match(r'^([A-Za-z0-9_\-]+(?:\s[A-Za-z0-9_\-]+)?)\s*\(([^)]{2,40})\)', head)
    if m:
        name = m.group(1).strip()
        if len(name) <= 32 and len(name.split()) <= 3:
            known = KNOWN.get(name.lower())
            if known:
                return known
            return f"{name.title()} ({m.group(2).strip()})"

    # any known name mentioned near the start of the prompt
    low_head = head.lower()
    for key, cn in KNOWN.items():
        if re.search(r'\b' + re.escape(key) + r'\b', low_head):
            return cn

    return from_filename()


# ---------------- Video (mp4 / mov / m4v) metadata ----------------

VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm')


def _mp4_ilst_keys(data):
    """Parse the QuickTime `keys` atom -> ordered key names."""
    ki = data.find(b'keys')
    if ki < 0:
        return []
    pos = ki + 4
    if pos + 8 > len(data):
        return []
    try:
        count = struct.unpack('>I', data[pos + 4:pos + 8])[0]
    except struct.error:
        return []
    if count > 512:
        return []
    names = []
    p = pos + 8
    for _ in range(count):
        if p + 8 > len(data):
            break
        try:
            size = struct.unpack('>I', data[p:p + 4])[0]
        except struct.error:
            break
        if size < 8 or p + size > len(data):
            break
        names.append(data[p + 8:p + size].decode('utf-8', 'ignore'))
        p += size
    return names


def _mp4_ilst_values(data):
    """Parse the `ilst` atom -> list of UTF-8 payloads, ordered like `keys`."""
    ii = data.find(b'ilst')
    if ii < 0:
        return []
    try:
        end = ii - 4 + struct.unpack('>I', data[ii - 4:ii])[0]
    except struct.error:
        return []
    values = []
    p = ii + 4
    while p + 8 <= min(end, len(data)):
        try:
            entry_size = struct.unpack('>I', data[p:p + 4])[0]
        except struct.error:
            break
        if entry_size < 8 or p + entry_size > len(data):
            break
        entry = data[p:p + entry_size]
        di = entry.find(b'data')
        if di > 0 and di + 12 <= len(entry):
            values.append(entry[di + 12:].decode('utf-8', 'ignore'))
        else:
            values.append('')
        p += entry_size
    return values


def _mp4_dimensions(data):
    """Read width/height from the VisualSampleEntry inside the stsd atom.
    (Searching from offset 0 would match codec *brands* in the ftyp header.)"""
    stsd = data.find(b'stsd')
    search_from = stsd if stsd > 0 else 0
    for tag in (b'avc1', b'hvc1', b'hev1', b'av01', b'vp09', b'mp4v'):
        idx = data.find(tag, search_from)
        while idx > 0:
            if idx + 32 <= len(data):
                try:
                    # 4cc + 6 reserved + 2 dataref + 2+2+12 pre_defined = 28,
                    # then width(2), height(2)
                    w = struct.unpack('>H', data[idx + 28:idx + 30])[0]
                    h = struct.unpack('>H', data[idx + 30:idx + 32])[0]
                    if 0 < w <= 16384 and 0 < h <= 16384:
                        return w, h
                except struct.error:
                    pass
            idx = data.find(tag, idx + 1)
    return 0, 0


def extract_video_metadata(path: str, result: dict):
    """ComfyUI writes its graph JSON into the mp4 `udta/ilst` atom under the keys
    `prompt` / `workflow` — the same shapes parsed for PNG files."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"[Metadata] video read failed {path}: {e}")
        return result

    result["width"], result["height"] = _mp4_dimensions(data)

    blob = {}
    keys = _mp4_ilst_keys(data)
    values = _mp4_ilst_values(data)
    for i, name in enumerate(keys):
        if i < len(values):
            blob[name.lower()] = values[i]

    result["raw_info"] = {k: str(v)[:300] for k, v in blob.items()}

    if blob.get('prompt'):
        parse_comfyui_metadata({'prompt': blob['prompt']}, result)
    elif blob.get('workflow'):
        parse_comfyui_metadata({'workflow': blob['workflow']}, result)

    if not result.get("character"):
        result["character"] = infer_character_from_filename_or_prompt(path, result.get("prompt", ""))
    if not result.get("recommendation"):
        result["recommendation"] = "视频生成"
    return result

