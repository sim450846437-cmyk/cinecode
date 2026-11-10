"""Structural checks for a model storyboard. This does not judge prose quality."""
import json
import re

SCALES = ("全景", "中景", "近景", "特写")
RESOURCE_KEYS = ("image", "video", "audio")


def extract_json(text):
    """Return the first JSON object in model text, or None."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def validate_story(data):
    """Character ids, scene ids, shot order, and missing media. Not a taste score."""
    errors = []
    if not isinstance(data, dict):
        return ["not_object"]
    plot = data.get("plot")
    if not isinstance(plot, str) or not plot.strip():
        errors.append("plot_missing")
    characters = data.get("characters")
    scenes = data.get("scenes")
    shots = data.get("shots")
    if not isinstance(characters, list) or not characters:
        errors.append("characters_missing")
        characters = []
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes_missing")
        scenes = []
    if not isinstance(shots, list) or len(shots) < 4:
        errors.append("shots_need_four")
        shots = shots if isinstance(shots, list) else []
    char_ids = []
    for item in characters:
        if not isinstance(item, dict):
            errors.append("character_not_object")
            continue
        cid = str(item.get("id") or "").strip()
        desc = str(item.get("description") or "").strip()
        if not cid or not desc:
            errors.append("character_incomplete")
            continue
        if cid in char_ids:
            errors.append("character_duplicate:" + cid)
        char_ids.append(cid)
    scene_ids = []
    for item in scenes:
        if not isinstance(item, dict):
            errors.append("scene_not_object")
            continue
        sid = str(item.get("id") or "").strip()
        desc = str(item.get("description") or "").strip()
        if not sid or not desc:
            errors.append("scene_incomplete")
            continue
        if sid in scene_ids:
            errors.append("scene_duplicate:" + sid)
        scene_ids.append(sid)
    last_start = None
    seen_index = []
    for item in shots:
        if not isinstance(item, dict):
            errors.append("shot_not_object")
            continue
        index = item.get("index")
        if not isinstance(index, int):
            errors.append("shot_index")
        else:
            seen_index.append(index)
        sid = str(item.get("scene_id") or "").strip()
        if sid not in scene_ids:
            errors.append("scene_ref:" + sid)
        refs = item.get("character_ids")
        if not isinstance(refs, list) or not refs:
            errors.append("character_refs_missing")
            refs = []
        for ref in refs:
            if str(ref) not in char_ids:
                errors.append("character_ref:" + str(ref))
        scale = str(item.get("scale") or "").strip()
        if scale not in SCALES:
            errors.append("scale:" + scale)
        if not str(item.get("action") or "").strip():
            errors.append("action_missing")
        if not str(item.get("dialogue") or "").strip():
            errors.append("dialogue_missing")
        start = item.get("start_s")
        if not isinstance(start, (int, float)):
            errors.append("start_missing")
        else:
            if last_start is not None and start < last_start:
                errors.append("timeline_backwards")
            last_start = start
        dialogue = str(item.get("dialogue") or "")
        for cid in char_ids:
            if cid and cid in dialogue and cid not in [str(x) for x in refs]:
                errors.append("dialogue_names_unlisted:" + cid)
        resources = item.get("resources") if isinstance(item.get("resources"), dict) else {}
        for key in RESOURCE_KEYS:
            if resources.get(key) not in (None, "", "not_generated"):
                errors.append("resource_claimed:" + key)
    if seen_index and seen_index != list(range(1, len(seen_index) + 1)):
        errors.append("index_not_sequential")
    return errors


def force_not_generated(data):
    """Media files are absent until an import supplies them."""
    if not isinstance(data, dict):
        return data
    for shot in data.get("shots") or []:
        if isinstance(shot, dict):
            shot["resources"] = {"image": "not_generated", "video": "not_generated", "audio": "not_generated"}
    return data


def strip_fence(text):
    return re.sub(r"^```(?:json)?|```$", "", text or "", flags=re.M)
