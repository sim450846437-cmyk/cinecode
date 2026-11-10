"""Structural checks for a model storyboard. This does not judge prose quality or pictures."""
import argparse
import json
import re
import sys
from pathlib import Path

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


OFFICIAL_MIN_SHOTS = 4


def named_shot_count(brief):
    """Return a count only when the brief itself names one."""
    match = re.search(r"([0-9]+|[一二两三四五六七八九十])\s*镜", brief or "")
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return max(1, int(token))
    table = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    return table.get(token)


def min_shots_for(brief):
    """Official boards stay at four distinct shots. A brief may only raise that floor."""
    named = named_shot_count(brief)
    if named is not None and named > OFFICIAL_MIN_SHOTS:
        return named, "brief_named_count"
    if named == OFFICIAL_MIN_SHOTS:
        return OFFICIAL_MIN_SHOTS, "brief_named_count"
    return OFFICIAL_MIN_SHOTS, "official_minimum_four"


def normalize_story(data):
    """Split a comma-joined id string. The words stay the model's."""
    notes = []
    if not isinstance(data, dict):
        return notes
    for shot in data.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        refs = shot.get("character_ids")
        if isinstance(refs, str):
            shot["character_ids"] = [part.strip() for part in re.split(r"[,，、\s]+", refs) if part.strip()]
            notes.append("split_character_ids")
    return notes


def validate_story(data, min_shots=4):
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
    if not isinstance(shots, list) or len(shots) < min_shots:
        errors.append("shots_need_" + str(min_shots))
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
    actions = []
    events = []
    dialogues = []
    for item in shots:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if action and action in actions:
            errors.append("shot_action_repeated")
        event = action_event(action, char_ids)
        if event and event in events:
            errors.append("shot_action_same_event")
        if action:
            actions.append(action)
        if event:
            events.append(event)
        line = str(item.get("dialogue") or "").strip()
        if line and line in dialogues:
            errors.append("dialogue_repeated")
        if line:
            dialogues.append(line)
    if seen_index and seen_index != list(range(1, len(seen_index) + 1)):
        errors.append("index_not_sequential")
    return errors


# Place words only. Removing them must not be described as narrative diversity.
_PLACE_WORDS = (
    "候车室门口", "站台中央", "站台东侧", "站台西侧", "站台一角", "候车室",
    "站台", "车厢", "月台", "门口", "角落", "中央", "一角", "旁边", "对面",
    "东侧", "西侧", "左侧", "右侧", "前方", "后方",
)


def action_event(text, names):
    """Exact core after names and place words. Not a semantic comparison."""
    core = str(text or "").strip()
    for name in sorted((str(name) for name in names if name), key=len, reverse=True):
        core = core.replace(name, "")
    for place in sorted(_PLACE_WORDS, key=len, reverse=True):
        core = core.replace(place, "")
    core = re.sub(r"(?:站在|坐在|走在|留在|等在)", "", core)
    core = re.sub(r"[，。；、：！？\s和与及的了着在]", "", core)
    return core


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


def board_from_json(data):
    """Accept a bare board or a storyboard_local payload. Do not call a model."""
    if isinstance(data, dict) and isinstance(data.get("story"), dict):
        return data["story"]
    return data


def validation_report(data, min_shots=OFFICIAL_MIN_SHOTS, floor_basis="official_minimum_four"):
    board = board_from_json(data)
    if isinstance(board, dict):
        normalize_story(board)
    errors = validate_story(board, min_shots=min_shots)
    shots = board.get("shots") if isinstance(board, dict) else None
    return {
        "structure_ok": not errors,
        "errors": errors,
        "shot_count": len(shots) if isinstance(shots, list) else 0,
        "shot_floor": {"min_shots": min_shots, "basis": floor_basis},
        "qualified": False,
        "chain_complete": False,
        "media_quality": "not_run",
        "adherence": {
            "checked": ["dialogue_exact", "action_event_after_names_and_places"],
            "semantic_similarity": False,
            "prompt_coverage": "not_this_command",
            "note": "Identical dialogue is dialogue_repeated. Actions that still match after character names and place words are removed are shot_action_same_event. A different action string is not narrative diversity. dfg coverage only checks whether prompt terms appear and does not read these shot lines. This is not a picture or sound pass.",
        },
    }


def main(argv):
    parser = argparse.ArgumentParser(
        description="Validate a storyboard file offline. No model and no media quality pass.",
        epilog=(
            "examples/storyboard-fewer-than-four.json exits 1 with shots_need_4. "
            "examples/storyboard-four-distinct.json exits 0; qualified stays false and media_quality is not_run. "
            "examples/storyboard-same-event.json exits 1 with dialogue_repeated and shot_action_same_event. "
            "No arguments exit 2 with need_story_json. Help is not a validation pass."
        ),
    )
    parser.add_argument("story", nargs="?", help="path to storyboard JSON")
    parser.add_argument("--brief", default="", help="optional brief; a named count can only raise the four-shot floor")
    if argv in (["-h"], ["--help"]):
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if not args.story:
        print(json.dumps({
            "error": "need_story_json",
            "structure_ok": False,
            "qualified": False,
            "chain_complete": False,
            "media_quality": "not_run",
        }, ensure_ascii=False))
        return 2
    path = Path(args.story)
    if not path.is_file():
        print(json.dumps({
            "error": "story_file_missing",
            "path": str(path),
            "structure_ok": False,
            "qualified": False,
            "media_quality": "not_run",
        }, ensure_ascii=False))
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(json.dumps({
            "error": "story_not_json",
            "structure_ok": False,
            "qualified": False,
            "media_quality": "not_run",
        }, ensure_ascii=False))
        return 2
    min_shots, floor_basis = min_shots_for(args.brief) if args.brief else (OFFICIAL_MIN_SHOTS, "official_minimum_four")
    report = validation_report(data, min_shots=min_shots, floor_basis=floor_basis)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["structure_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
